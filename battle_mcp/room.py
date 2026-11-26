"""A shared game clock. All reads, trigger registration and moves are serialized per room."""

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from . import declarations as plans
from .bot import choose_draw_bottom, choose_move
from .engine import ArenaEngine, action_fields


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
    identity = [side, action_fields(move)]
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()[:20]


def bot_roster(roster):
    if isinstance(roster, (list, tuple)) and len(roster) == 2:
        if all(isinstance(c, str) for c in roster):
            return dict(zip(SEATS, roster))
        if all(isinstance(team, (list, tuple)) and team and all(isinstance(c, str) for c in team) for team in roster):
            return {side: list(team) for side, team in zip(SEATS, roster)}
    raise ValueError("双方都需要至少一名有效的出战角色。")


class Room:
    def __init__(self, roster=None, seed=None, *, selectable=False, bot=False, challenge=None):
        self.challenge = challenge
        if challenge:
            bot = True
            if roster is None:
                roster = challenge.validate_roster(None)
        self.bot_side = 2 if bot else None
        self._seed = seed
        self._lobby_picks = bot_roster(roster) if bot and roster is not None else None
        self.engine = self._build_engine(self._lobby_picks) if self._lobby_picks else ArenaEngine(roster, seed=seed, bot_side=self.bot_side)
        if (selectable or bot) and self._lobby_picks is None:
            self._lobby_picks = {p.side: p.characters[0].id for p in self.engine.game.players}
        self.cv = threading.Condition()
        self.seated = set()
        self.human_seats = set()
        self.canvas_seats = set()
        self._next_votes = set()
        self._revision = dict.fromkeys((None, *SEATS), 0)
        self._journal = {s: [] for s in self._revision}
        self._wake = self._revision.copy()
        self._receipts = {s: {} for s in SEATS}
        self._match_number = 1
        self._history_start = self._revision.copy()
        self.pause_bank_limit = 20.0
        self._beat_timer = self._timer = self._continuation = self._pause_timer = None
        self._beat_started_at = None
        self._beat_duration_s = 0.0
        self._closed = False
        self._reset_match_decisions()

    def _build_engine(self, picks):
        roster = [picks[side] for side in SEATS]
        if self.challenge:
            self.challenge.validate_roster(roster)
        open_rosters = self.bot_side is not None and all(isinstance(team, list) for team in roster)
        return ArenaEngine(roster, seed=self._seed, bot_side=self.bot_side, open_rosters=open_rosters,
                           extra_packs=self.challenge.packs if self.challenge else ())

    def _seat_pick(self, picks, side, character_id):
        team = picks[side]
        replacement = [character_id, *team[1:]] if isinstance(team, list) else character_id
        return {**picks, side: replacement}

    def _cancel_match_timers(self):
        self._cancel_beat()
        for timer in (self._timer, self._continuation, self._pause_timer):
            if timer is not None:
                timer.cancel()
        self._timer = self._continuation = self._pause_timer = None

    def _reset_match_decisions(self):
        self._cancel_match_timers()
        self.paused_by = None
        self._pause_started_at = None
        self._pause_turn = 0
        self._pause_bank = {s: self.pause_bank_limit for s in SEATS}
        self._revision_windows = {s: {} for s in SEATS}
        self._next_votes.clear()
        self._plans = {s: {} for s in SEATS}
        self._serial = {s: 0 for s in SEATS}
        self._grants = {s: {} for s in SEATS}
        self._asked = set()
        self._anchors = {}
        self._bindings = {s: {} for s in SEATS}
        self._previous_choices = dict.fromkeys(SEATS)
        self._since = {}
        self._timer_seen = set()

    def close(self):
        with self.cv:
            self._closed = True
            self._cancel_match_timers()
            self.cv.notify_all()

    def _record_revision_window(self, side):
        if side not in SEATS:
            return
        win_map = self._revision_windows[side]
        win_map[self._revision[side]] = self._window()
        if len(win_map) > 24:
            for stale_rev in sorted(win_map)[:-24]:
                win_map.pop(stale_rev, None)

    def _sync_turn_bank(self):
        turn = self.engine.game.turn_number
        if turn != self._pause_turn:
            self._pause_turn = turn
            self._pause_bank = {s: self.pause_bank_limit for s in SEATS}

    def _remaining_pause_s(self, side):
        self._sync_turn_bank()
        if side not in SEATS:
            return 0.0
        bank = self._pause_bank.get(side, self.pause_bank_limit)
        if self.paused_by == side and self._pause_started_at is not None and not self._client_paced:
            bank = max(0.0, bank - (time.monotonic() - self._pause_started_at))
        return bank

    def _clear_pause(self, *, deduct=True):
        if self._pause_timer is not None:
            self._pause_timer.cancel()
            self._pause_timer = None
        if self.paused_by is not None:
            side = self.paused_by
            if deduct and self._pause_started_at is not None and not self._client_paced:
                elapsed = max(0.0, time.monotonic() - self._pause_started_at)
                self._pause_bank[side] = max(0.0, self._pause_bank.get(side, self.pause_bank_limit) - elapsed)
            self.paused_by = None
            self._pause_started_at = None

    def _note(self, kind, text, *, audiences=(None, 1, 2), wake=()):
        for side in audiences:
            journal = self._journal[side]
            cursor = len(journal) + 1
            journal.append(dict(id=cursor, kind=kind, text=text))
            self._revision[side] += 1
            self._record_revision_window(side)
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
        if self.paused_by is not None and self.paused_by != side:
            return []
        required = side in self.engine.required_sides()
        live_canvas = side in self.canvas_seats and self.engine._mode() != "draw_select"
        available = []
        for move in self.engine.options(side):
            key = move_id(side, move)
            offered = required and (side in self.human_seats or move["kind"] in plans.ORDINARY)
            inline_special = live_canvas and move["kind"].startswith("special_")
            if self.paused_by == side or offered or inline_special or key in self._grants[side]:
                available.append(dict(move, id=key))
        if side in self._asked:
            available.append(dict(kind="decline", id="decline", label="让过本次预留时机"))
        return available

    def observe(self, side, cursor=None):
        with self.cv:
            if side is not None:
                self._seat(side)
                self._record_revision_window(side)
            log = self._journal[side]
            if cursor is None:
                cursor = max(0, len(log) - 12)
            if type(cursor) is not int or not 0 <= cursor <= len(log):
                raise ValueError("cursor 不在本席位的事件范围内。")
            frame = short_frame(self.engine.state(side))
            view = dict(side=side, started=len(self.seated) == 2, ready_sides=sorted(self.seated),
                        paused_by=self.paused_by, can_pause=self._can_pause(side),
                        finished=self.engine.game_over, winner_side=frame.get("winner_side"),
                        revision=self._revision[side], cursor=len(log), events=log[cursor:],
                        server_time_ms=time.time_ns() // 1_000_000,
                        frame=frame, event=dict(self.engine.event), options=self._options(side),
                        declarations=[dict(p, id=key) for key, p in self._plans.get(side, {}).items()])
            if self._lobby_picks is not None and not view["started"]:
                view["lobby"] = {"characters": [dict(c) for c in self.engine.choices],
                                 "picks": {s: team[0] if isinstance(team, list) else team
                                           for s, team in self._lobby_picks.items()}}
            if self.bot_side is not None:
                view["bot_side"] = self.bot_side
            if self.challenge:
                view["challenge"] = self.challenge.name
            return view

    def canvas_state(self, side, after=None):
        """Wait for the next visible change, including animation beats between decisions."""
        if side is not None:
            self._seat(side)
        with self.cv:
            def position():
                return f"{self._revision[side]}:{self.engine.revision}"

            if after is not None:
                changed = self.cv.wait_for(lambda: self._closed or position() != after, timeout=8)
                if not changed:
                    return {"timeout": True}
            if self._closed:
                raise ValueError("对战房间已关闭。")
            if side is not None:
                self._record_revision_window(side)
            self._sync_turn_bank()
            frame = self.engine.state(side)
            options = self._options(side)
            journal = self._journal[side]
            history_start = max(self._history_start[side], len(journal) - 100)
            player = next((p for p in self.engine.game.players if p.side == side), None)
            target = player.default_target_character if player else None
            beat_duration_ms = 0
            beat_remaining_ms = 0
            if self._beat_timer is not None and self._beat_started_at is not None:
                elapsed = max(0.0, time.monotonic() - self._beat_started_at)
                beat_duration_ms = int(round(self._beat_duration_s * 1000))
                beat_remaining_ms = max(0, int(round((self._beat_duration_s - elapsed) * 1000)))
            pause_bank_ms = int(round(self._remaining_pause_s(side) * 1000)) if side in SEATS else 0
            pause_remaining_ms = (
                int(round(self._remaining_pause_s(self.paused_by) * 1000))
                if self.paused_by in SEATS and not self._client_paced else None
            )
            return {
                "position": position(), "revision": self._revision[side],
                "engine_revision": self.engine.revision, "side": side,
                "match_number": self._match_number, "can_rematch": self._can_rematch(side),
                "can_restart": self._can_restart(side),
                "client_paced": self._client_paced,
                "can_advance": self._can_advance_beat(side),
                "next_voted": side in self._next_votes,
                "has_special_actions": self._has_human_special_options(side),
                "beat_duration_ms": beat_duration_ms,
                "beat_remaining_ms": beat_remaining_ms,
                "pause_bank_ms": pause_bank_ms,
                "pause_remaining_ms": pause_remaining_ms,
                "declarations": [dict(p, id=key) for key, p in self._plans.get(side, {}).items()] if side in SEATS else [],
                "frame": frame, "options": options, "started": len(self.seated) == 2,
                "ready": side in self.seated, "bot_side": self.bot_side,
                "challenge": self.challenge.name if self.challenge else None,
                "selectable": self._lobby_picks is not None,
                "paused_by": self.paused_by, "can_pause": self._can_pause(side),
                "window_remaining": self.engine._window_size - self.engine.game.placed_this_window
                if any(move["kind"] == "end" for move in options) else 0,
                "catalog": self.engine.catalog(),
                "default_targets": {side: target.id} if target and target.is_alive else {},
                "history": [entry["text"] for entry in journal[history_start:]],
                "fx_events": list(self.engine.presentation.events),
            }

    def canvas_assets(self):
        with self.cv:
            return self.engine.table_assets()

    def _command(self, side, revision, request_id, operation, argument, run, *, allow_finished=False):
        self._seat(side)
        if side == self.bot_side:
            raise PermissionError("此席位由电脑控制。")
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
            # Pause, prepare, and default-target updates apply cleanly even if a beat just ticked.
            # Inline special moves from a Canvas seat also commit cleanly while the exact combat/phase window holds.
            current = self._revision[side]
            if type(revision) is not int or not 0 <= revision <= current:
                raise RoomConflict("局面已更新，请重新观察后行动。")
            if revision != current and operation not in ("pause", "set_default_target", "prepare"):
                same_window_special = (
                    operation == "act"
                    and side in self.canvas_seats
                    and self._revision_windows[side].get(revision) == self._window()
                    and any(m["id"] == argument and m["kind"].startswith("special_") for m in self._options(side))
                )
                if not same_window_special:
                    raise RoomConflict("局面已更新，请重新观察后行动。")
            if self._closed or (self.engine.game_over and not allow_finished):
                raise ValueError("本局已经结束。")
            cursor = len(self._journal[side])
            run()
            receipts[request_id] = signature
            return self.observe(side, cursor)

    def select_character(self, side, character_id, revision, request_id, *, target_side=None):
        target = side if target_side is None else target_side

        def commit():
            self._seat(target)
            if target != side and target != self.bot_side:
                raise PermissionError("只能选择本席或电脑对手的角色。")
            if self._lobby_picks is None or target in self.seated:
                raise ValueError("本席当前无法更换出战角色。")
            picked = self._lobby_picks
            character = next((c for c in self.engine.choices if c["id"] == character_id), None)
            if character is None:
                raise ValueError("出战角色不在本房间的卡包中。")
            roster = self._seat_pick(picked, target, character_id)
            if roster != picked:
                self.engine = self._build_engine(roster)
                self._lobby_picks = roster
                label = "电脑对手" if target == self.bot_side else f"席位 {target}"
                self._note("select_character", f"{label} 选择了{character['name']}。", wake=SEATS)
        return self._command(side, revision, request_id, "select_character", [target, character_id], commit)

    def ready(self, side, revision, request_id, *, human=False, canvas=False, character_id=None, roster=None):
        def commit():
            if side in self.seated:
                raise ValueError("本席已准备。")
            picks = self._lobby_picks
            if roster is not None:
                if self.bot_side is None or character_id is not None:
                    raise ValueError("只有人机房间可以同时选择双方角色。")
                picks = bot_roster(roster)
            elif character_id is not None:
                if picks is None:
                    raise ValueError("本房间使用预设阵容。")
                picks = self._seat_pick(picks, side, character_id)
            if picks != self._lobby_picks:
                self.engine = self._build_engine(picks)
                self._lobby_picks = picks
            self.seated.add(side)
            if human or self.bot_side is not None:
                self.human_seats.add(side)
            if canvas:
                self.canvas_seats.add(side)
            self._note("ready", f"席位 {side} 已准备。", wake=SEATS)
            if self.bot_side is not None:
                self.seated.add(self.bot_side)
            if len(self.seated) == 2:
                self._drive()
        return self._command(side, revision, request_id, "ready", [human, canvas, character_id, roster], commit)

    @property
    def _client_paced(self):
        """Single local Canvas human vs bot: client drives combat/reveal beats like hotseat."""
        return (self.bot_side is not None and bool(self.canvas_seats)
                and self.human_seats == self.canvas_seats)

    def _has_human_special_options(self, side):
        if side not in self.human_seats or len(self.seated) != 2 or self.engine.game_over:
            return False
        return bool(self.engine._special_options(side))

    def _should_stop_human_beat(self):
        mode = self.engine._mode()
        event = self.engine.event
        if mode == "advance" or event["kind"] == "setup":
            return False
        if mode in ("reveal", "combat", "turn_end"):
            return True
        if mode == "timing":
            if event["kind"] == "scores_ready" or event.get("timing") == "技能使用前，可换卡":
                return any(self._has_human_special_options(s) for s in self.human_seats)
            if event.get("timing") == "交锋开始前":
                return any(
                    ch.is_alive and any(spec.get("window") == "before_duel" for spec in ch.action_specs())
                    for p in self.engine.game.players for ch in p.characters
                )
            return False
        return False

    def _beat_delay(self):
        mode = self.engine._mode()
        ev_kind = self.engine.event["kind"]
        if ev_kind in ("roll", "scores_ready"):
            return 2.6
        if mode == "combat":
            last_fx = self.engine.presentation.events[-1]["kind"] if self.engine.presentation.events else None
            if last_fx in ("dice_roll", "dice_clash"):
                return 2.4
            if last_fx == "combat_strike":
                return 2.0
            return 1.75
        return 1.25

    def _can_advance_beat(self, side):
        return (side in self.human_seats and len(self.seated) == 2 and not self.engine.game_over
                and self.paused_by is None and not self._continuation
                and not self.engine.required_sides() and not self._asked
                and self._should_stop_human_beat())

    def _can_rematch(self, side):
        if not self.engine.game_over or side not in self.human_seats:
            return False
        return self.bot_side is not None or len(self.human_seats) == 2

    def _can_restart(self, side):
        return self.bot_side is not None and side in self.human_seats and len(self.seated) == 2

    def rematch(self, side, revision, request_id, *, roster=None):
        def commit():
            if not (self._can_rematch(side) or self._can_restart(side)):
                raise ValueError("当前对局尚未开战或不支持再战。")
            if roster is not None and self.bot_side is None:
                raise ValueError("联机再战沿用当前双方阵容。")
            if roster is not None:
                picks = bot_roster(roster)
            elif self._lobby_picks is not None:
                picks = self._lobby_picks
            else:
                picks = {p.side: [c.printed_id or c.id for c in p.characters] for p in self.engine.game.players}
            engine = self._build_engine(picks)
            self._reset_match_decisions()
            self.engine = engine
            if self._lobby_picks is not None or self.bot_side is not None:
                self._lobby_picks = picks
            self._match_number += 1
            self._history_start = {s: len(events) for s, events in self._journal.items()}
            self._note("match_start", f"第 {self._match_number} 局开始。", wake=SEATS)
            self._drive()

        return self._command(side, revision, request_id, "rematch", roster, commit, allow_finished=True)

    def next_beat(self, side, revision, request_id):
        def commit():
            if not self._can_advance_beat(side):
                raise ValueError("当前不在可推进的结算节拍。")
            if self._client_paced:
                self._step_beat()
                return
            self._next_votes.add(side)
            if self.human_seats <= self._next_votes:
                self._step_beat()
            else:
                self._note("next_vote", f"席位 {side} 已准备好进入下一拍。", audiences=(side,), wake=(side,))
        return self._command(side, revision, request_id, "next_beat", None, commit)

    def _can_pause(self, side):
        self._sync_turn_bank()
        has_bank = self._client_paced or self._remaining_pause_s(side) > 0.05
        return (side in self.human_seats and len(self.seated) == 2 and not self.engine.game_over
                and has_bank
                and self.paused_by is None and not self._continuation
                and self.engine._mode() != "draw_select"
                and self.engine.game.special.decision_owner is None
                and self.engine.game.special.pending_attack is None)

    def _on_pause_timeout(self, match_number, side):
        with self.cv:
            if match_number != self._match_number or self._closed or self.engine.game_over:
                return
            if self.paused_by != side:
                return
            self._pause_timer = None
            self._pause_bank[side] = 0.0
            self.paused_by = None
            self._pause_started_at = None
            self._note("pause_expired", f"席位 {side} 本回合思考时间已用尽，自动继续对局。", wake=SEATS)
            self._drive(process=False)

    def pause(self, side, revision, request_id):
        def commit():
            if not self._can_pause(side):
                if not self._client_paced and self._remaining_pause_s(side) <= 0.05:
                    raise ValueError("本回合思考时间已用尽。")
                raise ValueError("当前已有席位在决策，或尚未进入对局。")
            self._cancel_beat()
            self.paused_by = side
            self._pause_started_at = time.monotonic()
            if self._pause_timer is not None:
                self._pause_timer.cancel()
                self._pause_timer = None
            if not self._client_paced:
                remaining = max(0.05, self._remaining_pause_s(side))
                self._pause_timer = threading.Timer(remaining, self._on_pause_timeout, args=(self._match_number, side))
                self._pause_timer.daemon = True
                self._pause_timer.start()
            self._schedule()
            self._note("pause", f"席位 {side} 暂停对局。", wake=SEATS)
        return self._command(side, revision, request_id, "pause", None, commit)

    def resume(self, side, revision, request_id):
        def commit():
            if self.paused_by != side:
                raise ValueError("请由发起暂停的席位继续。")
            self._clear_pause(deduct=True)
            self._note("resume", f"席位 {side} 继续对局。", wake=SEATS)
            self._drive(process=False)
        return self._command(side, revision, request_id, "resume", None, commit)

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
                raise ValueError("当前无法执行此动作。")
            if choice["kind"] == "decline":
                self._release(side)
                self._note("decline", "已让过本次预留时机。", audiences=(side,))
                self._drive(process=False)
            else:
                was_paused_by_me = (self.paused_by == side)
                self.engine.apply(side, {k: v for k, v in choice.items() if k != "id"})
                self._release(side)
                if was_paused_by_me:
                    required = self.engine.required_sides()
                    still_has_special = bool(self.engine._special_options(side))
                    if (self.engine.game_over
                            or (required and required != [side])
                            or not still_has_special):
                        self._clear_pause(deduct=True)
                self._drive()
        return self._command(side, revision, request_id, "act", option_id, commit)

    def draw_bottom(self, side, card_ids, revision, request_id):
        def commit():
            self.engine.draw_bottom(side, card_ids)
            self._drive()
        return self._command(side, revision, request_id, "draw_bottom", card_ids, commit)

    def set_default_target(self, side, character_id, revision, request_id):
        def commit():
            if len(self.seated) != 2:
                raise ValueError("对局开始后才能指定集火目标。")
            player = self.engine._choose_seat(side, self.engine.game.players)
            enemy = self.engine._choose_seat(3 - side, self.engine.game.players)
            target = next((c for c in enemy.characters if c.id == character_id and c.is_alive), None)
            if target is None:
                raise ValueError("请选择存活的敌方角色。")
            player.set_default_target(target)
            self._note("default_target", f"默认目标设为{target.name}。", audiences=(side,), wake=(side,))
        return self._command(side, revision, request_id, "set_default_target", character_id, commit)

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
                ended |= bool(when.get("round_id") and (combat.get("round_id") or 0) > when["round_id"])
                ended |= "after_duel_end" in event.get("nodes", ())
            elif kind == scope[1] and scope[2] is not None:
                ended |= scope[2] > number
        elif not plan["repeat"] and when.get("turn", turn) == turn:
            number = when.get("pending_number")
            if number and (turn, number) in self._since:
                bound[key] = (turn, "pending", number)
            elif (combat and (when.get("own_card_id") or when.get("duel_number") or when.get("round_id"))
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
        self._cancel_beat()
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
                if original_window != self._window() or self.engine.current_move(side, move) is None:
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
                if self.bot_side in required and self.paused_by is None and not self._asked:
                    state = self.engine.state(self.bot_side)
                    if draw := state.get("draw_select"):
                        self.engine.draw_bottom(self.bot_side, choose_draw_bottom(draw))
                        continue
                    moves = [move for move in self.engine.options(self.bot_side) if move["kind"] in plans.ORDINARY]
                    move = (self.challenge.choose_move if self.challenge else choose_move)(state, moves)
                    if move is not None:
                        for side in edges.keys() - {self.bot_side}:
                            self._note("decision", "请选择当前行动。", audiences=(side,), wake=(side,))
                        automatic.append((self.bot_side, move, self._window()))
                        process = False
                        continue
                if self.paused_by is not None or required or self._asked:
                    for side in edges:
                        self._note("decision", "请选择当前行动。", audiences=(side,), wake=(side,))
                    break
                if self.human_seats and self._should_stop_human_beat():
                    self._sync_turn_bank()
                    self._next_votes.clear()
                    if not self._client_paced:
                        delay = self._beat_delay()
                        self._beat_started_at = time.monotonic()
                        self._beat_duration_s = delay
                        self._beat_timer = threading.Timer(delay, self._advance_beat)
                        self._beat_timer.daemon = True
                        self._beat_timer.start()
                    break
                self.engine.advance()
        self._schedule()

    def _cancel_beat(self):
        if self._beat_timer:
            self._beat_timer.cancel()
            self._beat_timer = None
        self._beat_started_at = None
        self._beat_duration_s = 0.0

    def _step_beat(self):
        self._cancel_beat()
        self._next_votes.clear()
        self.engine.advance()
        event = self.engine.event
        if event["kind"] == "timing" and not event.get("text"):
            self._note("timing", event["timing"])
        self._drive()
        self.cv.notify_all()

    def _advance_beat(self):
        with self.cv:
            if self._beat_timer is not threading.current_thread():
                return
            self._beat_timer = None
            self._step_beat()

    def _resume(self, remaining):
        with self.cv:
            if self._continuation is not threading.current_thread():
                return
            self._continuation = None
            if not self._closed and not self.engine.game_over:
                self._drive(process=False, initial_auto=remaining)
                self.cv.notify_all()

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
        if self._closed or self.engine.game_over or self.paused_by is not None:
            return
        next_timer = min(self._timers(), default=None)
        if next_timer is not None:
            deadline, _ = next_timer
            self._timer = threading.Timer(max(0, deadline-time.monotonic()), self._on_timer,
                                          args=(self._match_number,))
            self._timer.daemon = True
            self._timer.start()

    def _on_timer(self, match_number=None):
        with self.cv:
            if match_number is not None and match_number != self._match_number:
                return
            if self._closed or self.engine.game_over or self.paused_by is not None:
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
