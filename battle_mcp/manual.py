"""Translate copy-and-paste replies using the options actually shown to one seat."""

import json
import re
import secrets
from dataclasses import dataclass

from . import declarations
from .decision_view import decision_view
from .room import RoomConflict


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("同一 JSON 对象中的字段不能重复。")
        result[key] = value
    return result


_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})([^\r\n]*)$", re.M)


def _parse_reply(reply):
    if not isinstance(reply, str) or len(reply.encode("utf-8")) > 65536:
        raise ValueError("请粘贴不超过 64 KiB 的模型回复。")
    body = reply.strip().replace("\r\n", "\n").replace("\r", "\n")
    fences = list(_FENCE.finditer(body))
    if fences:
        if len(fences) != 2:
            raise ValueError("请提供一个完整的 JSON 代码块。")
        start, end = fences
        if (start[2].strip().lower() not in ("", "json") or end[2].strip()
                or not end[1].startswith(start[1])):
            raise ValueError("请用一对 Markdown 围栏包住一条 JSON 指令。")
        if re.search(r'"reply_to"\s*:', body[:start.start()] + body[end.end():]):
            raise ValueError("代码块外还有一条回复，请只提交一个决定。")
        body = body[start.end():end.start()].strip()
    try:
        data = json.loads(body, object_pairs_hook=_unique_keys)
        _json(data).encode("utf-8")  # Reject non-finite numbers and unpaired Unicode surrogates.
    except (json.JSONDecodeError, RecursionError, UnicodeError):
        raise ValueError("无法解析这条 JSON 回复，请保留原请求编号并让模型重新输出。") from None
    if not isinstance(data, dict) or not isinstance(data.get("reply_to"), str):
        raise ValueError("回复需要包含原样复制的 reply_to。")
    keys = data.keys() - {"reply_to"}
    if len(keys) != 1 or not keys <= {"choice", "ready", "prepare", "wait", "rules"}:
        raise ValueError("一次回复只能指定 choice、ready、prepare、wait 或 rules 中的一项。")
    operation, = keys
    argument = data[operation]
    if operation in ("ready", "wait") and argument is not True:
        raise ValueError("ready 和 wait 的值必须是 true。")
    if operation == "prepare" and not isinstance(argument, dict):
        raise ValueError("prepare 需要一条提前声明或撤回指令。")
    if operation in ("choice", "rules") and not isinstance(argument, str):
        raise ValueError("choice 和 rules 需要字符串。")
    return data["reply_to"], operation, argument


def _letter(index):
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


@dataclass
class _Ticket:
    code: str
    revision: int
    choices: dict


_INSTRUCTIONS = (
    "由操作者转交你的回复，请根据本席可见的信息制定战术。"
    "每次只回复一个 json 代码块，将本次局面的 reply_to 原样写入，并搭配一个动作字段。\n"
    '选择当前选项用 "choice":"A"（字母见 options）；赛前用 "ready":true 预留常规决策并准备。'
    '用 "wait":true 表示继续观察，原有迎击与决策资格保留。'
    '用 "rules":"3.3" 等章节号查条文，也可查 index、full、catalog。\n'
    '在事件发生前用 "prepare":{"event":"scores_ready","mode":"reserve","when":{"score":"lt"},'
    '"match":{"kind":"special_replace"}} 等结构登记。mode 可为 reserve（到时询问）或 execute'
    '（唯一匹配自动执行，须指定 match.kind）。when、match 可以省略，repeat 默认为 false。'
    '用 "prepare":{"cancel":"p1"} 撤回自己的待触发声明。先登记再作当前决定，每次提交后接收下一份局面。'
    "计时按房间的实际时间进行，包含人工搬运用时。\n"
)


class ManualDesk:
    def __init__(self, room):
        self.room = room
        self._open = {}
        self._used = {1: {}, 2: {}}

    def status(self, sides):
        """Return only public timing and the authorized seats' readiness indicators."""
        with self.room.cv:
            for side in sides:
                self.room._seat(side)
            if len(set(sides)) != len(sides):
                raise ValueError("席位重复。")
            public = self.room.observe(None)
            frame = public["frame"]
            declared = {item["number"]: item["declared_at_ms"] for item in frame["response_times"]}
            pending = [{"number": duel["number"], "attacking_side": duel["attacking_side"],
                        "declared_at_ms": declared.get(duel["number"])}
                       for duel in frame["pre_reveal"]["duels"] if not duel["ready"]]
            seats = []
            for side in sides:
                own = self.room.observe(side)
                player = next(p for p in frame["players"] if p["side"] == side)
                seats.append(dict(side=side, name="、".join(c["name"] for c in player["characters"]),
                                  ready=side in public["ready_sides"], has_decision=bool(own["options"]),
                                  revision=own["revision"]))
            return dict(turn=frame["turn"], started=public["started"], finished=public["finished"],
                        winner_side=public["winner_side"], pending=pending, seats=seats)

    def export(self, side, *, briefing=False, cursor=None):
        self.room._seat(side)
        if type(briefing) is not bool:
            raise ValueError("briefing 必须是布尔值。")
        with self.room.cv:
            observed = self.room.observe(side, cursor)
            view = decision_view(observed)
            choices = {}
            for index, option in enumerate(view["options"], 1):
                letter = _letter(index)
                choices[letter] = option["id"]
                view["options"][index - 1] = {k: v for k, v in option.items() if k != "id"}
                view["options"][index - 1]["choice"] = letter
            ticket = self._open.get(side)
            if not ticket or ticket.revision != view["revision"] or ticket.choices != choices:
                ticket = _Ticket(f"S{side}-{secrets.token_urlsafe(9)}", view["revision"], choices)
                self._open[side] = ticket
            view["reply_to"] = ticket.code
            text = f"你是《光点计划 III》的席位 {side}。\n"
            if not view["finished"]:
                example = {"reply_to": ticket.code}
                if choices:
                    example["choice"] = next(iter(choices))
                elif side not in observed["ready_sides"]:
                    example["ready"] = True
                else:
                    example["wait"] = True
                text += _INSTRUCTIONS + "以下示例演示回复格式，请自行选择行动。\n```json\n" + _json(example) + "\n```\n"
            if briefing:
                text += "赛前读本及双方公开印刷牌面\n" + _json(self.room.rules("briefing")) + "\n"
                text += ("可订阅事件 " + "、".join(declarations.EVENTS)
                         + "\n可匹配的动作 " + "、".join(sorted(declarations.KINDS))
                         + "\nwhen 可筛选 " + "、".join(sorted(declarations.CONDITIONS))
                         + "\nmatch 可筛选 " + "、".join(sorted(declarations.MOVE_KEYS)) + "\n")
            if view["finished"]:
                text += "对局已结束，请用自然语言报告胜负和终局生命。\n"
            text += "本次局面\n" + _json(view)
            return dict(side=side, reply_to=ticket.code, revision=ticket.revision, cursor=view["cursor"],
                        text=text, finished=view["finished"], option_count=len(choices))

    def import_reply(self, side, reply):
        self.room._seat(side)
        code, operation, argument = _parse_reply(reply)
        signature = json.dumps([operation, argument], sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.room.cv:
            used = self._used[side].get(code)
            if used:
                previous, receipt = used
                if signature != previous:
                    raise RoomConflict("该请求已有另一份回复。请复制新的本席局面。")
                return dict(receipt, duplicate=True)
            ticket = self._open.get(side)
            if not ticket or ticket.code != code:
                raise RoomConflict("请求编号与本席当前请求不符。请重新复制本席局面。")
            view = self.room.observe(side)
            if view["revision"] != ticket.revision:
                raise RoomConflict("局面已更新。请复制最新局面给模型重新决定。")
            args = dict(revision=ticket.revision, request_id="manual-" + code)
            if operation == "choice":
                if argument not in ticket.choices:
                    raise ValueError("本次局面没有这个选项字母。")
                view = self.room.act(side, ticket.choices[argument], **args)
                message = f"已提交选项 {argument}。"
            elif operation == "ready":
                view = self.room.ready(side, **args)
                message = "已预留常规决策并准备。"
            elif operation == "prepare":
                view = self.room.prepare(side, argument, **args)
                message = "已更新本席的提前声明。"
            elif operation == "rules":
                reading = self.room.rules(argument)
                message = "已取回指定规则，可送回模型。"
            else:
                message = "本席选择继续观察；房间保留当前决定。"
            del self._open[side]
            receipt = dict(side=side, reply_to=code, revision=view["revision"], cursor=view["cursor"],
                           duplicate=False, operation=operation, message=message)
            if operation == "rules":
                packet = self.export(side, cursor=view["cursor"])
                receipt["text"] = "你查询的规则\n" + _json(reading) + "\n" + packet["text"]
            self._used[side][code] = (signature, receipt)
            return dict(receipt)
