"""A shared game clock. All reads, trigger registration and moves are serialized per room."""

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from . import declarations as plans
from .engine import ArenaEngine


class RoomConflict(ValueError):
    """The seat acted on a superseded view or reused an action receipt."""


SEATS = (1, 2)
RULEBOOK = Path("docs") / "正式规则书.md"
# The briefing quotes numbered articles from the same edition as full and chapter lookup.
BRIEFING_ARTICLES = (
    "1.1", "1.3", "1.6", "2.1", "2.2", "2.3", "2.4", "2.5", "2.7", "2.9",
    "3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "4.2", "4.3", "4.4", "4.5", "4.6",
    "5.2", "5.3", "6.1", "6.3", "6.5", "7.2", "7.3",
)
GUIDE = (
    "双方按需 prepare，再 ready。ready 持续预留普通置卡、开牌前攻防、必须回应的迎击及词条要求的选牌或选交锋。"
    "临场特殊操作须额外提前准备。reserve 到点询问。execute 唯一匹配时执行，多项匹配时由本席选择。"
    "声明默认一次，repeat:true 可重复。一席多条自动声明按登记次序；双方同时命中优先本回合先手。"
    "roll 是原始骰面，scores_ready 是拼点点数就绪、胜负未定。timer 根据公开声明时间触发。"
    "先 prepare 后 act，可在当前抉择前准备下一个时机。等待及超时均保留待迎击的牌。"
)


def short_frame(frame):
    """Discard printed descriptions from frequent observations. The catalog carries them once."""
    def compact(value):
        if isinstance(value, list):
            return [compact(item) for item in value]
        if isinstance(value, dict):
            if "dice" in value and "cost" in value and "id" in value:
                return {key: value[key] for key in ("id", "action_key", "instance_id", "name", "cost", "character_id",
                                                   "borrowed", "use_restricted", "state", "play_mode")
                        if key in value}
            return {key: compact(item) for key, item in value.items()}
        return value
    return compact(frame)


def move_id(side, move):
    identity = [side, {k: v for k, v in move.items() if k != "label"}]
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()[:20]


class Room:
    def __init__(self, roster=None, seed=None, *, selectable=False):
        self.engine = ArenaEngine(roster, seed=seed)
        self._seed = seed
        self._lobby_picks = ({p.side: p.characters[0].id for p in self.engine.game.players}
                             if selectable else None)
        self.cv = threading.Condition()
        self.seated = set()
        self._plans = {s: {} for s in SEATS}
        self._serial = {s: 0 for s in SEATS}
        self._grants = {s: {} for s in SEATS}
        self._asked = set()
        self._anchors = {}
        self._bindings = {s: {} for s in SEATS}
        self._previous_choices = dict.fromkeys(SEATS)
        self._revision = dict.fromkeys((None, *SEATS), 0)
        self._journal = {s: [] for s in self._revision}
        self._wake = self._revision.copy()
        self._receipts = {s: {} for s in SEATS}
        self._since = {}
        self._timer_seen = set()
        self._timer = None
        self._continuation = None
        self._closed = False

    def close(self):
        with self.cv:
            self._closed = True
            if self._timer:
                self._timer.cancel()
            if self._continuation:
                self._continuation.cancel()
            self.cv.notify_all()

    def _note(self, kind, text, *, audiences=(None, 1, 2), wake=()):
        for side in audiences:
            journal = self._journal[side]
            cursor = len(journal) + 1
            journal.append(dict(id=cursor, kind=kind, text=text))
            self._revision[side] += 1
            if side in wake or side is None:
                self._wake[side] = cursor
        self.cv.notify_all()

    @staticmethod
    def _seat(side):
        if type(side) is not int or side not in SEATS:
            raise PermissionError("此操作需要玩家席位。")

    def _options(self, side):
        if side not in self.seated or len(self.seated) != 2 or self.engine.game_over or self._continuation:
            return []
        required = side in self.engine.required_sides()
        available = []
        for move in self.engine.options(side):
            key = move_id(side, move)
            if (required and move["kind"] in plans.ORDINARY) or key in self._grants[side]:
                available.append(dict(move, id=key))
        if side in self._asked:
            available.append(dict(kind="decline", id="decline", label="让过本次预留时机"))
        return available

    def observe(self, side, cursor=None):
        with self.cv:
            if side is not None:
                self._seat(side)
            log = self._journal[side]
            if cursor is None:
                cursor = max(0, len(log) - 12)
            if type(cursor) is not int or not 0 <= cursor <= len(log):
                raise ValueError("cursor 不在本席位的事件范围内。")
            frame = short_frame(self.engine.state(side))
            view = dict(side=side, started=len(self.seated) == 2, ready_sides=sorted(self.seated),
                        finished=self.engine.game_over, winner_side=frame.get("winner_side"),
                        revision=self._revision[side], cursor=len(log), events=log[cursor:],
                        server_time_ms=time.time_ns() // 1_000_000,
                        frame=frame, event=dict(self.engine.event), options=self._options(side),
                        declarations=[dict(p, id=key) for key, p in self._plans.get(side, {}).items()])
            if self._lobby_picks is not None and not view["started"]:
                view["lobby"] = {"characters": [dict(c) for c in self.engine.choices],
                                 "picks": self._lobby_picks.copy()}
            return view

    def _command(self, side, revision, request_id, operation, argument, run):
        self._seat(side)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("请为每个命令提供唯一的 request_id。")
        with self.cv:
            signature = json.dumps([operation, argument], sort_keys=True, ensure_ascii=False)
            receipts = self._receipts[side]
            if request_id in receipts:
                if signature != receipts[request_id]:
                    raise RoomConflict("此 request_id 已用于另一个操作。")
                return self.observe(side)
            # A command arriving just after a public deadline must not beat
            # an already due declaration just because the timer thread is late.
            while self._timer and not self._closed and not self.engine.game_over:
                due = min(self._timers(), default=None)
                if due is None or due[0] > time.monotonic():
                    break
                self._on_timer()
            if type(revision) is not int or revision != self._revision[side]:
                raise RoomConflict("局面已更新，请重新观察后行动。")
            if self.engine.game_over or self._closed:
                raise ValueError("本局已经结束。")
            cursor = len(self._journal[side])
            run()
            receipts[request_id] = signature
            return self.observe(side, cursor)

    def select_character(self, side, character_id, revision, request_id):
        def commit():
            if self._lobby_picks is None or side in self.seated:
                raise ValueError("本席当前无法更换出战角色。")
            picked = self._lobby_picks
            character = next((c for c in self.engine.choices if c["id"] == character_id), None)
            if character is None:
                raise ValueError("出战角色不在本房间的卡包中。")
            if character_id != picked[side]:
                roster = {**picked, side: character_id}
                self.engine = ArenaEngine([roster[s] for s in SEATS], seed=self._seed)
                self._lobby_picks = roster
                self._note("select_character", f"席位 {side} 选择了{character['name']}。", wake=SEATS)
        return self._command(side, revision, request_id, "select_character", character_id, commit)

    def ready(self, side, revision, request_id):
        def commit():
            if side in self.seated:
                raise ValueError("本席已准备。")
            self.seated.add(side)
            self._note("ready", f"席位 {side} 已准备。", wake=SEATS)
            if len(self.seated) == 2:
                self._drive()
        return self._command(side, revision, request_id, "ready", None, commit)

    def prepare(self, side, declaration, revision, request_id):
        def commit():
            entries = self._plans[side]
            if isinstance(declaration, dict) and set(declaration) == {"cancel"}:
                key = declaration["cancel"]
                if not isinstance(key, str) or key not in entries:
                    raise ValueError("没有这条待触发的声明。")
                del entries[key]
                self._bindings[side].pop(key, None)
            else:
                plan = plans.validate(declaration)
                if plan["event"] == "timer":
                    turn = self.engine.event.get("turn", 0)
                    start = self._since.get((turn, plan["when"]["pending_number"]))
                    if start is not None and time.monotonic() >= start + plan["when"]["after_ms"]/1000:
                        raise ValueError("这个计时时点已经过去。")
                self._serial[side] += 1
                key = f"p{self._serial[side]}"
                entries[key] = plan
                self._bind_or_expire(side, key, plan, self.engine.state(side), self.engine.event)
            self._note("prepare", "已更新自己的提前声明。", audiences=(side,))
            self._schedule()
        return self._command(side, revision, request_id, "prepare", declaration, commit)

    def act(self, side, option_id, revision, request_id):
        def commit():
            choice = next((m for m in self._options(side) if m["id"] == option_id), None)
            if choice is None:
                raise ValueError("此动作没有事先预留，或当前已不合法。")
            if choice["kind"] == "decline":
                self._release(side)
                self._note("decline", "已让过本次预留时机。", audiences=(side,))
                self._drive(process=False)
            else:
                self.engine.apply(side, {k: v for k, v in choice.items() if k != "id"})
                self._release(side)
                self._drive()
        return self._command(side, revision, request_id, "act", option_id, commit)

    def _record(self, event):
        kind = event["kind"]
        if kind in ("action", "finished", "reveal", "turn_end", "roll", "scores_ready") or event.get("text"):
            text = event.get("text") or event.get("timing") or kind
            for field, label in (("rolls", "骰面"), ("scores", "拼点点数")):
                if field in event:
                    text += f"　{label} {event[field][0]} 对 {event[field][1]}"
            self._note(kind, text, wake=SEATS if self.engine.game_over else ())
        if kind in ("action", "finished", "pre_reveal", "turn_end"):
            self._sync_pending()

    def _sync_pending(self):
        frame = self.engine.state(None)
        turn = frame["turn"]
        now = time.monotonic()
        self._since = {(turn, d["number"]): self._since.get((turn, d["number"]), now)
                       for d in frame["pre_reveal"]["duels"] if not d["ready"]}

    def _bind_or_expire(self, side, key, plan, frame, event):
        """A paused parent duel can resume. Expire it only on positive evidence."""
        when = plan["when"]
        combat = frame.get("combat") or {}
        actor = next((p for p in combat.get("sides", []) if p["side"] == side), {})
        turn = frame["turn"]
        bound = self._bindings[side]
        scope = (turn, combat.get("kind"), combat.get("duel_number"))
        ended = when.get("turn", turn) < turn
        if key in bound:
            old_turn, kind, number = bound[key]
            ended |= old_turn < turn
            if kind == "pending":
                ended |= (old_turn, number) not in self._since
            elif scope == bound[key]:
                ended |= bool(when.get("own_card_id") and actor.get("card_id") not in (None, when["own_card_id"]))
                ended |= bool(when.get("die_number") and (actor.get("die_number") or 0) > when["die_number"])
                ended |= "after_duel_end" in event.get("nodes", ())
            elif kind == scope[1] and scope[2] is not None:
                ended |= scope[2] > number
        elif not plan["repeat"] and when.get("turn", turn) == turn:
            number = when.get("pending_number")
            if number and (turn, number) in self._since:
                bound[key] = (turn, "pending", number)
            elif (combat and (when.get("own_card_id") or when.get("duel_number"))
                  and when.get("own_card_id", actor.get("card_id")) == actor.get("card_id")
                  and when.get("duel_number", scope[2]) == scope[2]
                  and when.get("duel_kind", scope[1]) == scope[1] and scope[2] is not None):
                bound[key] = scope
        if ended:
            self._plans[side].pop(key, None)
            bound.pop(key, None)
            self._note("expired", f"声明 {key} 的目标或回合已结束。", audiences=(side,), wake=(side,))
        return ended

    def _consider(self, event, edges, *, timer_plan=None):
        automatic = []
        for side in SEATS:
            if not self._plans[side]:
                continue
            frame = None
            options = None
            for key, plan in list(self._plans[side].items()):
                if timer_plan is not None and (side, key) != timer_plan:
                    continue
                if frame is None:
                    frame = self.engine.state(side)
                if self._bind_or_expire(side, key, plan, frame, event):
                    continue
                trigger = plan["event"]
                edge = edges.get(side)
                actual = event
                if trigger in ("placement", "pre_reveal", "decision"):
                    if not edge or (trigger != "decision" and trigger != edge):
                        continue
                    actual = dict(event, kind=trigger)
                elif trigger == "timing" and event.get("timing") and event.get("nodes"):
                    actual = dict(event, kind="timing")
                if not plans.matches(plan, actual, frame, side, bool(edge)):
                    continue
                if options is None:
                    options = self.engine.options(side)
                moves = plans.select_moves(options, plan["match"])
                if not moves and plan["match"]:
                    continue
                if not plan["repeat"]:
                    del self._plans[side][key]
                    self._bindings[side].pop(key, None)
                if plan["mode"] == "execute" and len(moves) == 1:
                    automatic.append((side, moves[0]))
                else:
                    self._reserve(side, moves, "预留时机已到。" if plan["mode"] == "reserve"
                                  else "多个合法动作符合条件，请选择。")
        return automatic

    def _reserve(self, side, moves, text):
        self._asked.add(side)
        self._anchors[side] = self._window()
        self._grants[side].update((move_id(side, m), m) for m in moves)
        self._note("decision", text, audiences=(side,), wake=(side,))

    def _window(self):
        frame = self.engine.state(None)
        combat = frame.get("combat") or {}
        return (frame["turn"], combat.get("kind"), combat.get("duel_number"), combat.get("round_id"),
                tuple((s["card_id"], s["die_number"]) for s in combat.get("sides", [])),
                frame["phase"] if not combat else None)

    def _release(self, side):
        self._grants[side].clear()
        self._asked.discard(side)
        self._anchors.pop(side, None)

    def _revalidate(self):
        if not self._asked:
            return
        position = self._window()
        for side in list(self._asked):
            granted = self._grants[side]
            legal = {move_id(side, move) for move in self.engine.options(side)}
            if self._anchors[side] != position or (granted and not (granted.keys() & legal)):
                self._release(side)
                self._note("expired", "预留的行动窗口已结束。", audiences=(side,), wake=(side,))
            else:
                for key in granted.keys() - legal:
                    del granted[key]

    def _edges(self, required):
        edges = {}
        for side in SEATS:
            ordinary = [m for m in self.engine.options(side) if m["kind"] in plans.ORDINARY] if side in required else []
            key = tuple(move_id(side, m) for m in ordinary)
            if key and key != self._previous_choices[side]:
                mode = self.engine.state(side)["mode"]
                edges[side] = mode if mode != "instant_response" else "decision"
            self._previous_choices[side] = key
        return edges

    def _drive(self, *, process=True, initial_auto=()):
        auto_count = 0
        automatic = list(initial_auto)
        while True:
            required = self.engine.required_sides()
            edges = {}
            if process:
                event = self.engine.event
                self._record(event)
                if not self.engine.game_over:
                    self._revalidate()
                    edges = self._edges(required)
                    triggered = self._consider(event, edges)
                    if len(triggered) > 1:
                        first = self.engine.state(None).get("first_side")
                        triggered.sort(key=lambda entry: entry[0] != first)
                    if triggered:
                        scope = self._window()
                        automatic.extend((s, m, scope) for s, m in triggered)
            process = True
            if self.engine.game_over:
                break
            while automatic:
                side, move, original_window = automatic.pop(0)
                if original_window != self._window() or move not in self.engine.options(side):
                    self._note("expired", "预定动作已因先结算的行动失效。", audiences=(side,), wake=(side,))
                    continue
                if auto_count >= 32:
                    # Long automatic exchanges yield the room lock between
                    # batches, so either seat can still observe and edit plans.
                    remaining = [(side, move, original_window), *automatic]
                    self._continuation = threading.Timer(0.01, self._resume, args=(remaining,))
                    self._continuation.daemon = True
                    self._continuation.start()
                    return
                self.engine.apply(side, move)
                self._release(side)
                auto_count += 1
                break
            else:
                if required or self._asked:
                    for side in edges:
                        self._note("decision", "可处理已预留的对局决定。", audiences=(side,), wake=(side,))
                    break
                self.engine.advance()
        self._schedule()

    def _resume(self, remaining):
        with self.cv:
            self._continuation = None
            if not self._closed and not self.engine.game_over:
                self._drive(process=False, initial_auto=remaining)

    def _timers(self):
        for side in SEATS:
            for key, plan in self._plans[side].items():
                if plan["event"] != "timer":
                    continue
                when = plan["when"]
                for (turn, number), start in self._since.items():
                    marker = (side, key, turn, number)
                    if number == when["pending_number"] and turn == when.get("turn", turn) and marker not in self._timer_seen:
                        yield start + when["after_ms"] / 1000, marker

    def _schedule(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._closed or self.engine.game_over:
            return
        next_timer = min(self._timers(), default=None)
        if next_timer is not None:
            deadline, _ = next_timer
            self._timer = threading.Timer(max(0, deadline-time.monotonic()), self._on_timer)
            self._timer.daemon = True
            self._timer.start()

    def _on_timer(self):
        with self.cv:
            if self._closed or self.engine.game_over:
                return
            expired = sorted(self._timers())
            if not expired or expired[0][0] > time.monotonic():
                self._schedule()
                return
            _, marker = expired[0]
            self._timer_seen.add(marker)
            side, key, turn, number = marker
            self._note("timer", f"开牌前交锋 {number} 仍待迎击。", audiences=(side,), wake=(side,))
            automatic = self._consider({"kind": "timer", "turn": turn}, {}, timer_plan=(side, key))
            self._drive(process=False, initial_auto=[(s, m, self._window()) for s, m in automatic])

    def wait(self, side, cursor, timeout=None, *, visible_updates=False):
        with self.cv:
            if side is not None:
                self._seat(side)
            if type(cursor) is not int or not 0 <= cursor <= len(self._journal[side]):
                raise ValueError("无效的事件游标。")
            if timeout is not None and (type(timeout) not in (int, float) or not 0 <= timeout <= 60):
                raise ValueError("timeout 应为 0 至 60 秒。")
            def changed_since_cursor():
                latest = len(self._journal[side]) if visible_updates else self._wake[side]
                return latest > cursor or self.engine.game_over or self._closed

            changed = self.cv.wait_for(changed_since_cursor, timeout=timeout)
            if not changed:
                return dict(side=side, cursor=cursor, timeout=True)
            return self.observe(side, cursor)

    def rules(self, topic=None):
        if topic == "catalog":
            with self.cv:
                return {"catalog": self.engine.catalog()}
        book = (Path(__file__).resolve().parents[1] / RULEBOOK).read_text(encoding="utf-8")
        edition = book.split("\n\n", 2)[1].strip("*")
        source = dict(source=RULEBOOK.as_posix(), version=edition)
        if topic == "full":
            return dict(source, text=book)
        headings = list(re.finditer(r"^(##|###) (.+)$", book, re.M))
        sections = {}
        chapter = 0
        for i, match in enumerate(headings):
            level, title = match.groups()
            if level == "##":
                chapter += 1
            key = str(chapter) if level == "##" else title.split()[0]
            end = next((m.start() for m in headings[i+1:] if len(m[1]) <= len(level)), len(book))
            sections[key] = (title, book[match.start():end].strip())
        if topic == "briefing":
            articles = []
            for key in BRIEFING_ARTICLES:
                title, section = sections[key]
                # Omit the heading (returned separately), link anchors and standalone worked examples.
                body = section.partition("\n")[2].strip()
                paragraphs = [p for p in body.split("\n\n")
                              if not p.startswith(('<a id=', '*例。', '*计数例。', '*桌面裁例。', '**算例**'))]
                articles.append(dict(id=key, title=title, text="\n\n".join(paragraphs)))
            with self.cv:
                catalog = self.engine.catalog()
            return dict(source, sections=articles, catalog=catalog, guide=GUIDE)
        if topic in (None, "", "index"):
            return dict(source, reading="首次参赛先读 briefing；完整阅读可用 full 和 catalog。",
                        guide=GUIDE, events=list(plans.EVENTS), action_kinds=sorted(plans.KINDS),
                        examples=[{"event":"scores_ready", "mode":"reserve", "when":{"score":"lt"},
                                   "match":{"kind":"special_replace"}},
                                  {"event":"timer", "mode":"reserve", "when":{"pending_number":1, "after_ms":3000}}],
                        topics=[dict(id=k, title=v[0]) for k, v in sections.items()])
        if not isinstance(topic, str) or topic not in sections:
            raise ValueError("未知章节。可查目录、briefing（赛前读本）、full（完整规则书）或 catalog（印刷牌面）。")
        title, content = sections[topic]
        return dict(id=topic, title=title, text=content)
