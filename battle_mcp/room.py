"""A shared game clock, customizable house rules, and real-time seat state."""

import hashlib
import json
import random
import re
import threading
import time
from pathlib import Path

from loader import load_characters_from_packs
from . import declarations as plans
from .bot import choose_draw_bottom, choose_inturn_move, choose_move
from .engine import ArenaEngine, action_fields
from .ruleset import (
    ROOM_RULE_BOUNDS,
    build_opponent_presets,
    default_ruleset,
    generate_matched_team,
    normalize_ruleset,
    snake_turn_side,
    team_power,
    validate_match_teams,
    validate_single_team,
)


class RoomConflict(ValueError):
    """The seat acted on a superseded view or reused an action receipt."""


SEATS = (1, 2)
RULEBOOK = Path("docs") / "正式规则书.md"
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


def _coerce_team_list(roster):
    if isinstance(roster, (list, tuple)) and len(roster) == 2:
        if all(isinstance(c, str) for c in roster):
            return {1: [roster[0]], 2: [roster[1]]}
        if all(isinstance(team, (list, tuple)) and all(isinstance(c, str) for c in team) for team in roster):
            return {1: list(roster[0]), 2: list(roster[1])}
    raise ValueError("双方都需要有效的出战角色列表。")


class Room:
    def __init__(
        self,
        roster=None,
        seed=None,
        *,
        selectable=False,
        bot=False,
        hotseat=False,
        challenge=None,
        ruleset=None,
        room_code=None,
        start_immediately=None,
    ):
        self.challenge = challenge
        if challenge:
            bot = True
            if roster is None and not selectable:
                roster = challenge.validate_roster(None)
        self.bot_side = 2 if bot else None
        self.hotseat = bool(hotseat and not bot)
        self.host_side = 1
        self.room_code = room_code
        self._seed = seed
        self._rng = random.Random(seed)
        self.is_online = not bot and not self.hotseat and challenge is None

        base_rules = normalize_ruleset(ruleset, online=self.is_online)
        # Legacy unlimited rosters passed directly (e.g. solo duplicate characters) unlock free_duplicates automatically
        if roster is not None and ruleset is None and (bot or self.hotseat):
            coerced = _coerce_team_list(roster)
            if any(len(set(t)) < len(t) for t in coerced.values()):
                base_rules["duplicate_policy"] = "free_duplicates"
        self.ruleset = base_rules

        extra_packs = self.challenge.packs if self.challenge else ()
        self._pool = {c["id"]: c for c in load_characters_from_packs(extra_packs=extra_packs)}
        self._opponent_presets = build_opponent_presets(self._pool)

        if roster is not None:
            initial_picks = _coerce_team_list(roster)
        elif self.challenge:
            default_pair = self.challenge.validate_roster(None)
            initial_picks = {1: [] if selectable else list(default_pair[0]), 2: list(self.challenge.opponents)}
        elif selectable:
            default_ids = list(self._pool.keys())
            if self.bot_side:
                opp = generate_matched_team(self._pool, 3, ruleset=self.ruleset, rng=self._rng)
                initial_picks = {1: [], 2: opp}
            elif self.hotseat:
                initial_picks = {1: [], 2: []}
            else:
                p1 = [default_ids[0]] if default_ids else []
                p2 = [default_ids[1 if len(default_ids) > 1 else 0]] if default_ids else []
                initial_picks = {1: p1, 2: p2}
        else:
            default_ids = list(self._pool.keys())
            initial_picks = {
                1: [default_ids[0]],
                2: [default_ids[1 if len(default_ids) > 1 else 0]],
            }

        self._selectable = bool(selectable or bot or self.hotseat)
        self._lobby_picks = initial_picks

        should_auto_start = bool(start_immediately) and bool(initial_picks[1]) and bool(initial_picks[2])

        # Build an initial engine (uses safe fallback pair while lobby picks are still empty)
        if initial_picks[1] and initial_picks[2]:
            self.engine = self._build_engine(initial_picks)
            self._engine_dirty = False
        else:
            fallback_ids = list(self._pool.keys())
            f1 = fallback_ids[0]
            f2 = next((cid for cid in fallback_ids if cid != f1), f1)
            self.engine = ArenaEngine([f1, f2], seed=seed, bot_side=self.bot_side, open_rosters=True, extra_packs=extra_packs)
            self._engine_dirty = True

        self.cv = threading.Condition()
        self.seated = set()
        self.human_seats = set()
        self.canvas_seats = set()
        self._hotseat_side = 1
        self._hotseat_revealed = None
        self._next_votes = set()
        self._revision = dict.fromkeys((None, *SEATS), 0)
        self._journal = {s: [] for s in self._revision}
        self._wake = self._revision.copy()
        self._receipts = {s: {} for s in SEATS}
        self._match_number = 1
        self._match_revision_floor = dict.fromkeys((*SEATS, "hotseat"), 0)
        self._history_start = self._revision.copy()
        self._state_epoch = 0

        # Disconnect tracking (`60s` clock freeze + `120s` optional claim win)
        self.disconnect_warn_s = 60.0
        self.disconnect_claim_s = 120.0
        self._active_ws_counts = {1: 0, 2: 0}
        self._offline_since = {1: None, 2: None}
        self._disconnect_timers = {1: [], 2: []}
        self._disconnect_frozen_by = None

        self._beat_timer = self._timer = self._continuation = self._pause_timer = None
        self._beat_started_at = None
        self._beat_duration_s = 0.0
        self._bot_inturn_window = None
        self._closed = False
        self._reset_match_decisions()

        if should_auto_start:
            with self.cv:
                self.seated = {1, 2}
                if self.hotseat:
                    self.human_seats = {1, 2}
                    self.canvas_seats = {1, 2}
                elif self.bot_side:
                    self.human_seats = {1}
                    self.canvas_seats = {1}
                self._sync_engine_auto_claim()
                self._drive()

    @property
    def started(self):
        return len(self.seated) == 2

    @property
    def pause_bank_limit(self):
        limit = self.ruleset.get("pause_limit_s")
        return float(limit) if limit is not None else None

    @pause_bank_limit.setter
    def pause_bank_limit(self, value):
        self.ruleset["pause_limit_s"] = value
        val = float(value) if value is not None else None
        self._pause_bank = {s: val for s in SEATS}

    def _sync_engine_auto_claim(self):
        """Canvas human seats explicitly toggle `claim_pre_reveal`; bots & headless MCP seats auto-claim."""
        auto_sides = set(SEATS) - set(self.canvas_seats)
        if self.bot_side in SEATS:
            auto_sides.add(self.bot_side)
        self.engine.auto_claim_sides = auto_sides

    def _build_engine(self, picks):
        roster = [list(picks[1]), list(picks[2])]
        if self.challenge:
            self.challenge.validate_roster(roster)
        open_rosters = self.ruleset.get("duplicate_policy") != "strict_unique"
        eng = ArenaEngine(
            roster,
            seed=self._seed,
            bot_side=self.bot_side,
            open_rosters=open_rosters,
            extra_packs=self.challenge.packs if self.challenge else (),
            fixed_opponent=self.challenge is not None,
            ruleset=self.ruleset,
        )
        return eng

    def _seat_pick(self, picks, side, character_id):
        team = list(picks.get(side) or [])
        if self.ruleset.get("max_chars") == 1:
            replacement = [character_id]
        elif character_id in team and self.ruleset.get("duplicate_policy") != "free_duplicates":
            replacement = team
        else:
            replacement = [character_id] if len(team) <= 1 and not self.started else [*team, character_id]
        return {**picks, side: replacement}

    def _cancel_disconnect_timers(self, side=None):
        sides = (side,) if side in SEATS else SEATS
        for s in sides:
            for t in self._disconnect_timers.get(s, ()):
                t.cancel()
            self._disconnect_timers[s] = []

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
        limit = self.pause_bank_limit
        self._pause_bank = {s: limit for s in SEATS}
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
        self._bot_inturn_window = None
        self._hotseat_revealed = None

    def close(self):
        with self.cv:
            self._closed = True
            self._cancel_match_timers()
            self._cancel_disconnect_timers()
            self._state_epoch += 1
            self.cv.notify_all()

    def _bump(self):
        self._state_epoch += 1
        self.cv.notify_all()

    # ── WebSocket Presence & Gentle Disconnect Protection (60s freeze / 120s optional claim) ──

    def on_ws_connect(self, side, *, hotseat=False):
        with self.cv:
            sides = SEATS if hotseat else ((side,) if side in SEATS else ())
            resumed = False
            for s in sides:
                self._active_ws_counts[s] += 1
                self._offline_since[s] = None
                self._cancel_disconnect_timers(s)
                if self._disconnect_frozen_by == s:
                    self._disconnect_frozen_by = None
                    resumed = True
            if resumed and self.started and not self.engine.game_over:
                self._note("peer_reconnected", "对手已重新连接，牌局继续。", wake=SEATS)
                self._drive(process=False)
            else:
                self._bump()

    def on_ws_disconnect(self, side, *, hotseat=False):
        with self.cv:
            if self._closed or hotseat or side not in SEATS or side == self.bot_side:
                return
            self._active_ws_counts[side] = max(0, self._active_ws_counts[side] - 1)
            if self._active_ws_counts[side] > 0:
                return
            now = time.monotonic()
            self._offline_since[side] = now
            self._cancel_disconnect_timers(side)
            if self.is_online:
                t_warn = threading.Timer(self.disconnect_warn_s, self._on_disconnect_warn, args=(self._match_number, side, now))
                t_warn.daemon = True
                t_claim = threading.Timer(self.disconnect_claim_s, self._on_disconnect_claimable, args=(self._match_number, side, now))
                t_claim.daemon = True
                self._disconnect_timers[side] = [t_warn, t_claim]
                t_warn.start()
                t_claim.start()
            self._bump()

    def _on_disconnect_warn(self, match_number, side, since_mono):
        with self.cv:
            if self._closed or match_number != self._match_number or self._offline_since.get(side) != since_mono:
                return
            if self.started and not self.engine.game_over:
                self._disconnect_frozen_by = side
                self._cancel_beat()
                self._note("peer_offline", f"席位 {side} 连接中断超过 {int(self.disconnect_warn_s)} 秒，牌桌时钟已挂起保护。", wake=SEATS)
            else:
                self._bump()

    def _on_disconnect_claimable(self, match_number, side, since_mono):
        with self.cv:
            if self._closed or match_number != self._match_number or self._offline_since.get(side) != since_mono:
                return
            if self.started and not self.engine.game_over:
                self._note("peer_timeout_claimable", f"席位 {side} 已离线满 {int(self.disconnect_claim_s)} 秒，可继续等待重连或提前结算获胜。", wake=SEATS)
            else:
                self._bump()

    def _peer_connection_status(self, viewer_side):
        if not self.is_online or viewer_side not in SEATS:
            return {"peer_online": True, "peer_offline_ms": 0, "disconnect_frozen": False, "can_claim_disconnect_win": False}
        opp = 3 - viewer_side
        since = self._offline_since.get(opp)
        if since is None:
            return {
                "peer_online": self._active_ws_counts.get(opp, 0) > 0,
                "peer_offline_ms": 0,
                "disconnect_frozen": False,
                "can_claim_disconnect_win": False,
            }
        offline_s = max(0.0, time.monotonic() - since)
        warned = offline_s >= self.disconnect_warn_s - 0.005
        claimable = self.started and not self.engine.game_over and offline_s >= self.disconnect_claim_s - 0.005
        return {
            "peer_online": False,
            "peer_offline_ms": int(round(offline_s * 1000)) if warned else 0,
            "disconnect_frozen": bool(self._disconnect_frozen_by is not None),
            "can_claim_disconnect_win": bool(claimable),
        }

    # ── Pause Bank & Turn Helpers ──

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
        limit = self.pause_bank_limit
        if turn != self._pause_turn:
            self._pause_turn = turn
            self._pause_bank = {s: limit for s in SEATS}

    def _remaining_pause_s(self, side):
        self._sync_turn_bank()
        limit = self.pause_bank_limit
        if limit is None:
            return None
        if side not in SEATS:
            return 0.0
        bank = self._pause_bank.get(side)
        if bank is None:
            bank = limit
        if self.paused_by == side and self._pause_started_at is not None and not self._client_paced:
            bank = max(0.0, bank - (time.monotonic() - self._pause_started_at))
        return bank

    def _clear_pause(self, *, deduct=True):
        if self._pause_timer is not None:
            self._pause_timer.cancel()
            self._pause_timer = None
        if self.paused_by is not None:
            side = self.paused_by
            limit = self.pause_bank_limit
            if deduct and limit is not None and self._pause_started_at is not None and not self._client_paced:
                elapsed = max(0.0, time.monotonic() - self._pause_started_at)
                prev = self._pause_bank.get(side)
                if prev is None:
                    prev = limit
                self._pause_bank[side] = max(0.0, prev - elapsed)
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
        self._state_epoch += 1
        if kind in ("match_start", "reopen_lobby"):
            self._match_revision_floor = {s: self._revision[s] for s in SEATS}
            self._match_revision_floor["hotseat"] = max(self._revision[s] for s in SEATS) + self._state_epoch
        self.cv.notify_all()

    @staticmethod
    def _seat(side):
        if type(side) is not int or side not in SEATS:
            raise PermissionError("此操作需要玩家席位。")

    def _options(self, side):
        if side not in SEATS or not self.started or self.engine.game_over or self._continuation:
            return []
        if self.paused_by is not None and self.paused_by != side:
            return []
        required = side in self.engine.required_sides()
        live_canvas = (side in self.canvas_seats or self.hotseat) and self.engine._mode() != "draw_select"
        available = []
        for move in self.engine.options(side):
            key = move_id(side, move)
            offered = required and (side in self.human_seats or self.hotseat or move["kind"] in plans.ORDINARY)
            inline_special = live_canvas and move["kind"].startswith("special_")
            if self.paused_by == side or offered or inline_special or key in self._grants[side]:
                available.append(dict(move, id=key))
        if side in self._asked:
            available.append(dict(kind="decline", id="decline", label="让过本次预留时机"))
        return available

    # ── Pre-Match Lobby View & Snake Draft Helpers ──

    def _current_draft_turn(self):
        if self.ruleset.get("pick_mode") != "draft" or self.started:
            return None
        p1_done = 1 in self.seated
        p2_done = 2 in self.seated
        if p1_done and p2_done:
            return None
        if p1_done:
            return 2
        if p2_done:
            return 1
        total_picked = len(self._lobby_picks.get(1, ())) + len(self._lobby_picks.get(2, ()))
        return snake_turn_side(total_picked, self.ruleset.get("draft_first_side", 1))

    def _lobby_snapshot(self, viewer_side, *, hotseat=False):
        picks_raw = {1: list(self._lobby_picks.get(1, ())), 2: list(self._lobby_picks.get(2, ()))}
        blind = (
            self.ruleset.get("pick_mode") == "blind"
            and not self.started
            and not hotseat
            and self.bot_side is None
        )
        visible_picks = {}
        pick_meta = {}
        for s in SEATS:
            raw_team = picks_raw[s]
            pwr = team_power(raw_team, self._pool)
            hide = blind and viewer_side != s
            visible_picks[s] = [] if hide else raw_team
            pick_meta[s] = {
                "count": len(raw_team),
                "power": pwr,
                "masked": hide,
                "ready": s in self.seated,
            }
        return {
            "room_code": self.room_code,
            "ruleset": dict(self.ruleset),
            "host_side": self.host_side,
            "is_host": bool(hotseat or viewer_side == self.host_side),
            "picks": visible_picks,
            "rule_bounds": dict(ROOM_RULE_BOUNDS),
            "pick_meta": pick_meta,
            "ready_sides": sorted(self.seated),
            "draft_turn_side": self._current_draft_turn(),
            "opponent_presets": list(self._opponent_presets) if self.bot_side and not self.challenge else [],
        }

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
            frame = short_frame(self.engine.state(side if self.started else None))
            view = dict(
                side=side,
                started=self.started,
                ready_sides=sorted(self.seated),
                paused_by=self.paused_by,
                can_pause=self._can_pause(side),
                finished=self.engine.game_over if self.started else False,
                winner_side=frame.get("winner_side") if self.started else None,
                revision=self._revision[side],
                cursor=len(log),
                events=log[cursor:],
                server_time_ms=time.time_ns() // 1_000_000,
                ruleset=dict(self.ruleset),
                room_code=self.room_code,
                frame=frame,
                event=dict(self.engine.event),
                options=self._options(side),
                declarations=[dict(p, id=key) for key, p in self._plans.get(side, {}).items()],
            )
            if self._selectable and self._lobby_picks is not None and not view["started"]:
                lob = self._lobby_snapshot(side)
                view["lobby"] = {
                    "characters": [dict(c) for c in self.engine.choices],
                    "picks": {
                        s: (team[0] if len(team) == 1 else list(team))
                        for s, team in lob["picks"].items()
                    },
                    "teams": lob["picks"],
                    "pick_meta": lob["pick_meta"],
                    "ruleset": lob["ruleset"],
                }
            if self.bot_side is not None:
                view["bot_side"] = self.bot_side
            if self.challenge:
                view["challenge"] = self.challenge.name
            return view

    # ── Canvas / WebSocket Unified Snapshot ──

    def _resolve_hotseat_view(self):
        """Determine `(effective_side, handoff_side, eligible_sides)` for a hotseat screen."""
        if not self.started or self.engine.game_over:
            return 1, None, []
        curtain = bool(self.ruleset.get("hotseat_curtain", True))
        if self.paused_by in SEATS:
            eligible = [s for s in SEATS if self._has_seat_special_options(s)]
            if curtain and self._hotseat_revealed != self.paused_by:
                return None, self.paused_by, eligible
            return self.paused_by, None, eligible
        req = self.engine.required_sides()
        if req:
            target = self._hotseat_side if self._hotseat_side in req else req[0]
            if curtain and self._hotseat_revealed != target:
                return None, target, list(req)
            self._hotseat_side = target
            return target, None, list(req)
        # Public resolution phase (`reveal` / `combat` / `timing` / `turn_end`)
        elig_special = [s for s in SEATS if self._has_seat_special_options(s)]
        if curtain:
            self._hotseat_revealed = None
            return None, None, elig_special
        return self._hotseat_side, None, elig_special

    def ws_position(self, side, *, hotseat=False):
        rev = max(self._revision[1], self._revision[2]) if hotseat else self._revision[side]
        return f"{rev}:{self.engine.revision}:{self._state_epoch}"

    def _canvas_snapshot_locked(self, side, *, hotseat=False):
        handoff_side = None
        hotseat_eligible = []
        eff_side = side
        rev_side = side
        if hotseat:
            eff_side, handoff_side, hotseat_eligible = self._resolve_hotseat_view()
            rev_side = eff_side if eff_side in SEATS else 1

        if eff_side in SEATS:
            self._record_revision_window(eff_side)
        self._sync_turn_bank()

        view_for_engine = eff_side if self.started else None
        frame = self.engine.state(view_for_engine)
        options = self._options(eff_side) if eff_side in SEATS else []
        journal = self._journal[eff_side]
        history_start = max(self._history_start[eff_side], len(journal) - 100)

        default_targets = {}
        if self.started:
            for s in (SEATS if hotseat else ((eff_side,) if eff_side in SEATS else ())):
                pl = next((p for p in self.engine.game.players if p.side == s), None)
                tgt = pl.default_target_character if pl else None
                if tgt and tgt.is_alive:
                    default_targets[s] = tgt.id

        beat_duration_ms = 0
        beat_remaining_ms = 0
        if self._beat_timer is not None and self._beat_started_at is not None:
            elapsed = max(0.0, time.monotonic() - self._beat_started_at)
            beat_duration_ms = int(round(self._beat_duration_s * 1000))
            beat_remaining_ms = max(0, int(round((self._beat_duration_s - elapsed) * 1000)))

        rem_pause_me = self._remaining_pause_s(eff_side) if eff_side in SEATS else None
        pause_bank_ms = int(round(rem_pause_me * 1000)) if rem_pause_me is not None else None
        rem_pause_active = (
            self._remaining_pause_s(self.paused_by)
            if self.paused_by in SEATS and not self._client_paced else None
        )
        pause_remaining_ms = int(round(rem_pause_active * 1000)) if rem_pause_active is not None else None

        extras = self.engine.canvas_extras(eff_side) if self.started else {
            "card_owners": {"duels": {}, "duels_rear": {}, "pre_reveal": {}},
            "speed_rolls": [],
            "pre_reveal_claimed": False,
            "pre_reveal_plan": [],
            "pre_reveal_eligible_cards": [],
            "pre_reveal_stage_targets": {},
        }
        conn_info = self._peer_connection_status(rev_side if not hotseat else None)
        lobby_info = self._lobby_snapshot(rev_side, hotseat=hotseat)
        has_special = (
            any(self._has_seat_special_options(s) for s in SEATS)
            if hotseat else self._has_human_special_options(eff_side)
        )
        ctrl_side = rev_side if hotseat else side

        return {
            "position": self.ws_position(side, hotseat=hotseat),
            "revision": (max(self._revision[1], self._revision[2]) + self._state_epoch) if hotseat else self._revision[rev_side],
            "engine_revision": self.engine.revision,
            "side": eff_side if not hotseat else (eff_side or self._hotseat_side),
            "seat_role": "hotseat" if hotseat else ("player" if side in SEATS else "spectator"),
            "hotseat": hotseat,
            "hotseat_handoff_side": handoff_side,
            "eligible_sides": hotseat_eligible,
            "match_number": self._match_number,
            "can_rematch": self._can_rematch(ctrl_side),
            "can_reopen_lobby": self._can_reopen_lobby(ctrl_side),
            "can_concede": bool(self.started and not self.engine.game_over and (hotseat or side in SEATS)),
            "can_restart": self._can_restart(ctrl_side),
            "client_paced": self._client_paced,
            "can_advance": self._can_advance_beat(ctrl_side),
            "next_voted": ctrl_side in self._next_votes,
            "has_special_actions": has_special,
            "beat_duration_ms": beat_duration_ms,
            "beat_remaining_ms": beat_remaining_ms,
            "pause_bank_ms": pause_bank_ms,
            "pause_remaining_ms": pause_remaining_ms,
            "declarations": [dict(p, id=key) for key, p in self._plans.get(eff_side, {}).items()] if eff_side in SEATS else [],
            "frame": frame,
            "options": options,
            "started": self.started,
            "ready": (len(self.seated) == 2) if hotseat else (side in self.seated),
            "bot_side": self.bot_side,
            "challenge": self.challenge.name if self.challenge else None,
            "selectable": self._selectable,
            "lobby_state": lobby_info,
            "ruleset": lobby_info["ruleset"],
            "room_code": self.room_code,
            "is_host": lobby_info["is_host"],
            **conn_info,
            **extras,
            "paused_by": self.paused_by,
            "can_pause": self._can_pause(ctrl_side),
            "window_remaining": self.engine._window_size - self.engine.game.placed_this_window
            if any(move["kind"] == "end" for move in options) else 0,
            "catalog": self._catalog(eff_side, hotseat=hotseat),
            "default_targets": default_targets,
            "history": [entry["text"] for entry in journal[history_start:]],
            "fx_events": list(self.engine.presentation.events) if self.started else [],
        }

    def canvas_state(self, side, after=None, *, hotseat=False):
        """Return current canvas snapshot, optionally long-polling until `after` changes."""
        if side is not None and not hotseat:
            self._seat(side)
        with self.cv:
            if after is not None:
                changed = self.cv.wait_for(
                    lambda: self._closed or self.ws_position(side, hotseat=hotseat) != after,
                    timeout=8,
                )
                if not changed:
                    return {"timeout": True}
            if self._closed:
                raise ValueError("对战房间已关闭。")
            return self._canvas_snapshot_locked(side, hotseat=hotseat)

    def canvas_assets(self):
        with self.cv:
            return self.engine.table_assets()

    def battle_record(self):
        with self.cv:
            if not self.started:
                raise ValueError("开战后可导出战报。")
            game = self.engine.game
            frame = self.engine.state(None)
            journal = self._journal[None]
            history_start = self._history_start[None]
            return {
                "match_number": self._match_number,
                "history": [e["text"] for e in journal[history_start:] if e["kind"] not in ("ready", "unready", "select_character")],
                "challenge": self.challenge.name if self.challenge else None,
                "bot_side": self.bot_side,
                "finished": game.is_over,
                "winner_side": frame.get("winner_side"),
                "frame": {
                    "turn": frame["turn"],
                    "players": [
                        {"side": p.side, "characters": [{"name": c.name} for c in p.characters]}
                        for p in game.players
                    ],
                },
            }

    # ── Command Serialization & Tolerance ──

    _REVISION_TOLERANT_OPS = frozenset({
        "pause", "resume", "set_default_target", "prepare",
        "update_rules", "update_team", "randomize_bot_team", "pass_first_pick",
        "ready", "unready", "concede", "reopen_lobby", "claim_disconnect_win",
        "hotseat_ready", "switch_side",
        "claim_pre_reveal", "stage_pre_reveal", "unstage_pre_reveal", "commit_pre_reveal_plan",
    })

    def _command(self, side, revision, request_id, operation, argument, run, *, allow_finished=False, hotseat=False):
        if not hotseat:
            self._seat(side)
            if side == self.bot_side:
                raise PermissionError("此席位由电脑控制。")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("请为每个命令提供唯一的 request_id。")
        with self.cv:
            rec_side = side if side in SEATS else 1
            signature = json.dumps([operation, argument], sort_keys=True, ensure_ascii=False)
            receipts = self._receipts[rec_side]
            if request_id in receipts:
                if signature != receipts[request_id]:
                    raise RoomConflict("此 request_id 已用于另一个操作。")
                return self._canvas_snapshot_locked(side, hotseat=True) if hotseat else self.observe(rec_side)
            while self._timer and not self._closed and self.started and not self.engine.game_over:
                due = min(self._timers(), default=None)
                if due is None or due[0] > time.monotonic():
                    break
                self._on_timer()
            current = (max(self._revision[1], self._revision[2]) + self._state_epoch) if hotseat else self._revision[rec_side]
            if revision is not None:
                if type(revision) is not int or revision < 0 or (operation not in self._REVISION_TOLERANT_OPS and revision > current):
                    raise RoomConflict("局面已更新，请重新观察后行动。")
                if revision != current and operation not in self._REVISION_TOLERANT_OPS:
                    same_window_special = (
                        not hotseat
                        and operation == "act"
                        and side in self.canvas_seats
                        and self._revision_windows[side].get(revision) == self._window()
                        and any(m["id"] == argument and m["kind"].startswith("special_") for m in self._options(side))
                    )
                    if not same_window_special:
                        raise RoomConflict("局面已更新，请重新观察后行动。")
            if self._closed or (self.started and self.engine.game_over and not allow_finished):
                raise ValueError("本局已经结束。")
            cursor = len(self._journal[rec_side])
            run()
            receipts[request_id] = signature
            return self._canvas_snapshot_locked(side, hotseat=True) if hotseat else self.observe(rec_side, cursor)

    # ── Room Lobby, Ruleset, Ready / Unready & Rematch / Reopen ──

    def update_rules(self, side, patch, revision, request_id, *, hotseat=False):
        def commit():
            if self.started:
                raise ValueError("对局进行中无法直接修改房规，请先返回选人台。")
            if not hotseat and side != self.host_side:
                raise PermissionError("只有房主可以调整房间规则。")
            next_rules = normalize_ruleset(patch, base=self.ruleset, online=self.is_online)
            self.ruleset = next_rules
            self._engine_dirty = True
            # Re-check any already-ready seat against new constraints
            invalidated = False
            for s in list(self.seated):
                if s == self.bot_side and self.challenge:
                    continue
                try:
                    validate_single_team(self._lobby_picks.get(s, ()), self._pool, self.ruleset, allow_empty=False)
                except ValueError:
                    invalidated = True
            if invalidated:
                self.seated.clear()
                self._note("rules_updated", "房主更新了房间规则，原准备状态已重置，请核对阵容。", wake=SEATS)
            else:
                self._note("rules_updated", "房主更新了房间规则。", wake=SEATS)
        return self._command(side, revision, request_id, "update_rules", patch, commit, allow_finished=True, hotseat=hotseat)

    def pass_first_pick(self, side, revision, request_id, *, hotseat=False):
        def commit():
            if self.started:
                raise ValueError("对局已开始。")
            if not hotseat and side != self.host_side:
                raise PermissionError("只有房主可以切换轮选先手。")
            self.ruleset["draft_first_side"] = 3 - self.ruleset.get("draft_first_side", 1)
            first_s = self.ruleset["draft_first_side"]
            self._note("draft_order", f"轮选先手已切换为席位 {first_s}。", wake=SEATS)
        return self._command(side, revision, request_id, "pass_first_pick", None, commit, allow_finished=True, hotseat=hotseat)

    def update_team(self, side, team, revision, request_id, *, target_side=None, hotseat=False):
        target = side if target_side is None else target_side

        def commit():
            self._seat(target)
            if not hotseat and target != side and target != self.bot_side:
                raise PermissionError("只能调整本席或电脑对手的阵容。")
            if self.challenge and target == self.bot_side:
                raise ValueError("挑战首领的阵容固定，不可修改。")
            if self.started or target in self.seated:
                raise ValueError("本席已准备或对局已开始，请先取消准备。")
            if not isinstance(team, (list, tuple)):
                raise ValueError("队伍参数须为角色 ID 列表。")
            clean_team = list(team)
            if self.challenge and target == 1 and any(c in self.challenge.opponents for c in clean_team):
                raise ValueError("挑战对手固定，请从其余角色中选择自己的阵容。")

            # Snake draft turn check when adding characters in online PvP
            if (self.ruleset.get("pick_mode") == "draft" and self.is_online
                    and len(clean_team) > len(self._lobby_picks.get(target, ()))):
                turn_side = self._current_draft_turn()
                if turn_side is not None and turn_side != target:
                    raise ValueError(f"当前轮到席位 {turn_side} 选人。")
                if len(clean_team) - len(self._lobby_picks.get(target, ())) > 1:
                    raise ValueError("明牌轮选每次只能锁定 1 名角色。")

            validate_single_team(clean_team, self._pool, self.ruleset, allow_empty=True)
            if (self.ruleset.get("duplicate_policy") == "strict_unique"
                    and self.ruleset.get("pick_mode") in ("open", "draft")):
                other = self._lobby_picks.get(3 - target, ())
                overlap = [c for c in clean_team if c in set(other) and not self._pool[c].get("mirror_allowed")]
                if overlap:
                    raise ValueError(f"「{self._pool[overlap[0]]['name']}」已被另一方选入。")

            self._lobby_picks = {**self._lobby_picks, target: clean_team}
            self._engine_dirty = True
            self._bump()
        return self._command(side, revision, request_id, "update_team", [target, list(team) if isinstance(team, (list, tuple)) else team], commit, allow_finished=True, hotseat=hotseat)

    def randomize_bot_team(self, side, revision, request_id, *, preset_id=None):
        def commit():
            if self.bot_side is None or self.challenge:
                raise ValueError("当前模式不支持随机生成电脑阵容。")
            if self.started:
                raise ValueError("对局进行中无法更换电脑阵容。")
            if preset_id:
                preset = next((p for p in self._opponent_presets if p["id"] == preset_id), None)
                if preset is None:
                    raise ValueError("未找到该预设对手阵容。")
                bot_team = list(preset["characters"])
                validate_single_team(bot_team, self._pool, self.ruleset, allow_empty=False)
            else:
                p1_power = team_power(self._lobby_picks.get(1, ()), self._pool) or 3
                bot_team = generate_matched_team(
                    self._pool,
                    p1_power,
                    ruleset=self.ruleset,
                    exclude_ids=self._lobby_picks.get(1, ()),
                    rng=self._rng,
                )
            self._lobby_picks = {**self._lobby_picks, self.bot_side: bot_team}
            self._engine_dirty = True
            self._bump()
        return self._command(side, revision, request_id, "randomize_bot_team", preset_id, commit, allow_finished=True)

    def select_character(self, side, character_id, revision, request_id, *, target_side=None):
        target = side if target_side is None else target_side

        def commit():
            self._seat(target)
            if target != side and target != self.bot_side:
                raise PermissionError("只能选择本席或电脑对手的角色。")
            if self._lobby_picks is None or self.started or target in self.seated:
                raise ValueError("本席当前无法更换出战角色。")
            if character_id not in self._pool:
                raise ValueError("出战角色不在本房间的卡包中。")
            picks = {**self._lobby_picks, target: [character_id]}
            validate_single_team(picks[target], self._pool, self.ruleset, allow_empty=False)
            self._lobby_picks = picks
            self._engine_dirty = True
            label = "电脑对手" if target == self.bot_side else f"席位 {target}"
            if self.ruleset.get("pick_mode") == "blind" and self.is_online:
                self._note("select_character", f"{label} 更新了出战编队。", audiences=(target,), wake=(target,))
            else:
                self._note("select_character", f"{label} 选择了{self._pool[character_id]['name']}。", wake=SEATS)
        return self._command(side, revision, request_id, "select_character", [target, character_id], commit)

    def unready(self, side, revision, request_id, *, hotseat=False):
        def commit():
            if self.started:
                raise ValueError("双方均已准备开战，可使用局内菜单重返选人台。")
            if hotseat:
                self.seated.clear()
                self._note("unready", "已取消准备。", wake=SEATS)
                return
            if side not in self.seated:
                return
            self.seated.discard(side)
            self._note("unready", f"席位 {side} 取消了准备。", wake=SEATS)
        return self._command(side, revision, request_id, "unready", None, commit, hotseat=hotseat)

    def ready(self, side, revision, request_id, *, human=False, canvas=False, character_id=None, roster=None, team=None, hotseat=False):
        def commit():
            if self.started:
                raise ValueError("对局已经开始。")
            if not hotseat and side in self.seated:
                raise ValueError("本席已准备。")
            picks = dict(self._lobby_picks or {1: [], 2: []})
            if roster is not None:
                if not (self.bot_side is not None or self.hotseat) or character_id is not None:
                    raise ValueError("只有单人或同屏模式可以同时提交双方阵容。")
                coerced = _coerce_team_list(roster)
                picks = coerced
            elif team is not None:
                if not isinstance(team, (list, tuple)):
                    raise ValueError("队伍列表格式无效。")
                picks[side] = list(team)
            elif character_id is not None:
                picks[side] = [character_id]

            if self.challenge:
                if roster is None:
                    picks[2] = list(self.challenge.opponents)
                self.challenge.validate_roster([picks[1], picks[2]])

            if hotseat or self.bot_side is not None:
                if self.bot_side is not None and not picks.get(self.bot_side):
                    p1_p = team_power(picks.get(1, ()), self._pool) or 3
                    picks[self.bot_side] = generate_matched_team(self._pool, p1_p, ruleset=self.ruleset, exclude_ids=picks.get(1, ()), rng=self._rng)
                validate_single_team(picks[1], self._pool, self.ruleset, allow_empty=False)
                if not self.challenge:
                    validate_single_team(picks[2], self._pool, self.ruleset, allow_empty=False)
            else:
                validate_single_team(picks[side], self._pool, self.ruleset, allow_empty=False)

            starting = hotseat or self.bot_side is not None or (3 - side) in self.seated
            rebuild = self._engine_dirty or picks != self._lobby_picks
            if starting and not self.challenge:
                try:
                    validate_match_teams([picks[1], picks[2]], self._pool, self.ruleset)
                except ValueError as exc:
                    self.seated.clear()
                    self.human_seats.clear()
                    self.canvas_seats.clear()
                    self._lobby_picks = picks
                    self._engine_dirty = rebuild
                    self._note("collision", f"{exc} 请双方调整阵容后重新准备。", wake=SEATS)
                    return
            engine = self._build_engine(picks) if starting and rebuild else None
            self._lobby_picks = picks
            self._engine_dirty = rebuild

            if hotseat:
                self.seated = {1, 2}
                self.human_seats = {1, 2}
                self.canvas_seats = {1, 2}
            else:
                self.seated.add(side)
                if human or self.bot_side is not None:
                    self.human_seats.add(side)
                if canvas:
                    self.canvas_seats.add(side)
                if self.bot_side is not None:
                    self.seated.add(self.bot_side)

            if len(self.seated) == 2:
                if engine is not None:
                    self.engine = engine
                    self._engine_dirty = False
                    self._history_start = {s: len(events) for s, events in self._journal.items()}
                self._sync_engine_auto_claim()
                self._note("ready", f"席位 {side} 已准备。", wake=SEATS)
                self._drive()
            else:
                self._note("ready", f"席位 {side} 已准备。", wake=SEATS)
        return self._command(side, revision, request_id, "ready", [human, canvas, character_id, roster, team], commit, hotseat=hotseat)

    def hotseat_ready(self, side, revision, request_id):
        def commit():
            if not self.hotseat:
                raise ValueError("仅同屏双人模式使用接手确认。")
            self._seat(side)
            _, handoff, eligible = self._resolve_hotseat_view()
            if handoff is None or side not in eligible:
                raise ValueError("请由当前待行动的席位接手。")
            if self.paused_by is not None:
                self.paused_by = side
            self._hotseat_side = side
            self._hotseat_revealed = side
            self._bump()
        return self._command(side, revision, request_id, "hotseat_ready", side, commit, hotseat=True)

    def switch_hotseat_side(self, side, revision, request_id):
        def commit():
            if not self.hotseat:
                raise ValueError("仅同屏双人模式支持切换席位视角。")
            next_s = 3 - self._hotseat_side
            if self.paused_by in SEATS:
                if not self._has_seat_special_options(next_s):
                    raise ValueError("该席位当前没有场内行动。")
                self.paused_by = next_s
            self._hotseat_side = next_s
            if not self.ruleset.get("hotseat_curtain", True):
                self._hotseat_revealed = next_s
            else:
                self._hotseat_revealed = None
            self._bump()
        return self._command(side, revision, request_id, "switch_side", None, commit, hotseat=True)

    def concede(self, side, revision, request_id, *, hotseat=False, match_number=None):
        def commit():
            if match_number is None:
                if revision is None or revision < self._match_revision_floor["hotseat" if hotseat else side]:
                    raise RoomConflict("请核对当前对局后再认输。")
            elif type(match_number) is not int or match_number != self._match_number:
                raise RoomConflict("这次认输不属于当前对局。")
            if not self.started or self.engine.game_over:
                raise ValueError("当前没有正在进行的对局。")
            loser = self._hotseat_side if hotseat else side
            self._seat(loser)
            self._cancel_match_timers()
            self.engine.forfeit_match(loser, reason="宣布认输")
            self._note("concede", self.engine.event["text"], wake=SEATS)
        return self._command(side, revision, request_id, "concede", match_number, commit, hotseat=hotseat)

    def claim_disconnect_win(self, side, revision, request_id):
        def commit():
            if not self.started or self.engine.game_over:
                raise ValueError("当前对局已结束。")
            status = self._peer_connection_status(side)
            if not status.get("can_claim_disconnect_win"):
                raise ValueError("对手尚未达到离线超时结算条件。")
            opp = 3 - side
            self._cancel_match_timers()
            self._disconnect_frozen_by = None
            self.engine.forfeit_match(opp, reason="离线超时，提前结算")
            self._note("disconnect_forfeit", self.engine.event["text"], wake=SEATS)
        return self._command(side, revision, request_id, "claim_disconnect_win", None, commit)

    def reopen_lobby(self, side, revision, request_id, *, hotseat=False):
        def commit():
            if not self.started:
                return
            if not self.engine.game_over and not hotseat and side != self.host_side:
                raise PermissionError("对局进行中只有房主可以发起重返选人台。")
            self._cancel_match_timers()
            self._disconnect_frozen_by = None
            self.seated.clear()
            self._engine_dirty = True
            self._reset_match_decisions()
            self._match_number += 1
            self._note("reopen_lobby", "已返回房间选人台，可调整阵容或房间规则后再战。", wake=SEATS)
        return self._command(side, revision, request_id, "reopen_lobby", None, commit, allow_finished=True, hotseat=hotseat)

    def pre_reveal_stage(self, side, action, revision, request_id, *, card_id=None, target=None, hotseat=False):
        def commit():
            if not self.started or self.engine.game_over:
                raise ValueError("对局尚未开始或已结束。")
            actor_side = self._hotseat_side if hotseat else side
            self.engine.pre_reveal_plan_command(actor_side, action, card_id=card_id, target=target)
            if action == "commit_pre_reveal_plan":
                self._drive()
            else:
                self._bump()
        return self._command(side, revision, request_id, action, [card_id, target], commit, hotseat=hotseat)

    # ── Pacing, Rematch & Match Loop ──

    @property
    def _client_paced(self):
        """Local solo vs bot or local hotseat: client drives combat/reveal beats smoothly."""
        if self.hotseat:
            return True
        return (self.bot_side is not None and bool(self.canvas_seats)
                and self.human_seats == self.canvas_seats)

    def _has_seat_special_options(self, side):
        if side not in SEATS or not self.started or self.engine.game_over:
            return False
        return bool(self.engine._special_options(side))

    def _has_human_special_options(self, side):
        if side not in self.human_seats or not self.started or self.engine.game_over:
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
            check_seats = SEATS if self.hotseat else self.human_seats
            if event["kind"] == "scores_ready" or event.get("timing") == "技能使用前，可换卡":
                return any(self._has_seat_special_options(s) for s in check_seats)
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
        return (
            (self.hotseat or side in self.human_seats)
            and self.started
            and not self.engine.game_over
            and self.paused_by is None
            and self._disconnect_frozen_by is None
            and not self._continuation
            and not self.engine.required_sides()
            and not self._asked
            and self._should_stop_human_beat()
        )

    def _can_rematch(self, side):
        if not self.started or not self.engine.game_over:
            return False
        if self.hotseat:
            return True
        if side not in self.human_seats:
            return False
        return self.bot_side is not None or len(self.human_seats) == 2

    def _can_reopen_lobby(self, side):
        if not self.started:
            return False
        if self.hotseat or side == self.host_side:
            return True
        return bool(self.engine.game_over and side in self.human_seats)

    def _can_restart(self, side):
        return (self.hotseat or (self.bot_side is not None and side in self.human_seats)) and self.started

    def rematch(self, side, revision, request_id, *, roster=None, hotseat=False):
        def commit():
            ctrl_side = 1 if hotseat else side
            if not (self._can_rematch(ctrl_side) or self._can_restart(ctrl_side)):
                raise ValueError("当前对局尚未开战或不支持再战。")
            if roster is not None:
                if not (self.bot_side is not None or self.hotseat):
                    raise ValueError("联机换人请点击「重返选人」返回选人台。")
                picks = _coerce_team_list(roster)
                if self.challenge:
                    self.challenge.validate_roster([picks[1], picks[2]])
            elif self._lobby_picks and self._lobby_picks.get(1) and self._lobby_picks.get(2):
                picks = dict(self._lobby_picks)
            else:
                picks = {p.side: [c.printed_id or c.id for c in p.characters] for p in self.engine.game.players}
            engine = self._build_engine(picks)
            self._reset_match_decisions()
            self.engine = engine
            if hotseat:
                self._hotseat_side = 1
                self._hotseat_revealed = None if self.ruleset.get("hotseat_curtain", True) else 1
            self._sync_engine_auto_claim()
            self._lobby_picks = picks
            self._match_number += 1
            self._history_start = {s: len(events) for s, events in self._journal.items()}
            self._note("match_start", f"第 {self._match_number} 局开始。", wake=SEATS)
            self._drive()

        return self._command(side, revision, request_id, "rematch", roster, commit, allow_finished=True, hotseat=hotseat)

    def next_beat(self, side, revision, request_id, *, hotseat=False):
        def commit():
            ctrl_side = 1 if hotseat else side
            if not self._can_advance_beat(ctrl_side):
                raise ValueError("当前不在可推进的结算节拍。")
            if self._client_paced or hotseat:
                self._step_beat()
                return
            self._next_votes.add(side)
            if self.human_seats <= self._next_votes:
                self._step_beat()
            else:
                self._note("next_vote", f"席位 {side} 已确认继续。", wake=SEATS)
        return self._command(side, revision, request_id, "next_beat", None, commit, hotseat=hotseat)

    def draw_bottom(self, side, card_ids, revision, request_id, *, hotseat=False):
        def commit():
            eff = self._hotseat_side if hotseat else side
            self.engine.draw_bottom(eff, card_ids)
            self._drive()
        return self._command(side, revision, request_id, "draw_bottom", card_ids, commit, hotseat=hotseat)

    def set_default_target(self, side, character_id, revision, request_id, *, hotseat=False):
        def commit():
            if not self.started or self.engine.game_over:
                raise ValueError("对局尚未开始或已结束。")
            actor_side = self._hotseat_side if hotseat else side
            self.engine.act("set_default_target", self.engine.revision, side=actor_side, character_id=character_id)
            self._note("default_target", "已更新默认集火目标。", audiences=(actor_side,))
        return self._command(side, revision, request_id, "set_default_target", character_id, commit, hotseat=hotseat)

    def _can_pause(self, side):
        if not self.hotseat and side not in SEATS:
            return False
        if not self.started or self.engine.game_over or self.paused_by is not None or self._continuation:
            return False
        if self.engine.required_sides() or self._asked:
            return False
        limit = self.pause_bank_limit
        if not self._client_paced and limit is not None and side in SEATS and (self._remaining_pause_s(side) or 0.0) <= 0.05:
            return False
        return True

    def _on_pause_timeout(self, match_number, side):
        with self.cv:
            if match_number != self._match_number or self._closed or not self.started or self.engine.game_over:
                return
            if self.paused_by != side:
                return
            self._pause_timer = None
            self._pause_bank[side] = 0.0
            self.paused_by = None
            self._pause_started_at = None
            self._note("pause_expired", f"席位 {side} 本回合思考时间已用尽，自动继续对局。", wake=SEATS)
            self._drive(process=False)

    def pause(self, side, revision, request_id, *, hotseat=False):
        def commit():
            p_side = side if side in SEATS else self._hotseat_side
            if hotseat:
                eligible = [s for s in SEATS if self._has_seat_special_options(s)]
                if not eligible:
                    raise ValueError("当前没有席位可以进行场内行动。")
                p_side = self._hotseat_side if self._hotseat_side in eligible else eligible[0]
            if not self._can_pause(p_side):
                limit = self.pause_bank_limit
                if not self._client_paced and limit is not None and (self._remaining_pause_s(p_side) or 0.0) <= 0.05:
                    raise ValueError("本回合思考时间已用尽。")
                raise ValueError("当前已有席位在决策，或尚未进入对局。")
            self._cancel_beat()
            self.paused_by = p_side
            if hotseat:
                self._hotseat_side = p_side
                self._hotseat_revealed = None if self.ruleset["hotseat_curtain"] else p_side
            self._pause_started_at = time.monotonic()
            if self._pause_timer is not None:
                self._pause_timer.cancel()
                self._pause_timer = None
            limit = self.pause_bank_limit
            if not self._client_paced and limit is not None:
                remaining = max(0.05, self._remaining_pause_s(p_side))
                self._pause_timer = threading.Timer(remaining, self._on_pause_timeout, args=(self._match_number, p_side))
                self._pause_timer.daemon = True
                self._pause_timer.start()
            self._schedule()
            self._note("pause", f"席位 {p_side} 暂停对局。", wake=SEATS)
        return self._command(side, revision, request_id, "pause", None, commit, hotseat=hotseat)

    def resume(self, side, revision, request_id, *, hotseat=False):
        def commit():
            if self.paused_by is None or (not hotseat and self.paused_by != side):
                raise ValueError("请由发起暂停的席位继续。")
            p_side = self.paused_by
            self._clear_pause(deduct=True)
            if hotseat and self.ruleset.get("hotseat_curtain", True):
                self._hotseat_revealed = None
            self._note("resume", f"席位 {p_side} 继续对局。", wake=SEATS)
            self._drive(process=False)
        return self._command(side, revision, request_id, "resume", None, commit, hotseat=hotseat)

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
                    if start is not None and time.monotonic() >= start + plan["when"]["after_ms"] / 1000:
                        raise ValueError("这个计时时点已经过去。")
                self._serial[side] += 1
                key = f"p{self._serial[side]}"
                entries[key] = plan
                if self.started:
                    self._bind_or_expire(side, key, plan, self.engine.state(side), self.engine.event)
            self._note("prepare", "已更新自己的提前声明。", audiences=(side,))
            self._schedule()
        return self._command(side, revision, request_id, "prepare", declaration, commit)

    def act(self, side, option_id, revision, request_id, *, hotseat=False):
        def commit():
            actor_side = self._hotseat_side if hotseat and side not in SEATS else side
            if hotseat and self.paused_by in SEATS:
                actor_side = self.paused_by
            elif hotseat:
                req = self.engine.required_sides()
                if req and actor_side not in req:
                    actor_side = req[0]
            choice = next((m for m in self._options(actor_side) if m["id"] == option_id), None)
            if choice is None:
                raise ValueError("当前无法执行此动作。")
            if choice["kind"] == "decline":
                self._release(actor_side)
                self._note("decline", "已让过本次预留时机。", audiences=(actor_side,))
                self._drive(process=False)
            else:
                was_paused_by_me = (self.paused_by == actor_side)
                self.engine.apply(actor_side, {k: v for k, v in choice.items() if k != "id"})
                self._release(actor_side)
                if was_paused_by_me:
                    required = self.engine.required_sides()
                    still_has_special = bool(self.engine._special_options(actor_side))
                    if (self.engine.game_over
                            or (required and required != [actor_side])
                            or not still_has_special):
                        self._clear_pause(deduct=True)
                self._drive()
        return self._command(side, revision, request_id, "act", option_id, commit, hotseat=hotseat)

    def _record(self, event):
        kind = event["kind"]
        if kind == "setup":
            return
        if kind == "action" and event.get("action_kind") == "attack":
            key = (event["turn"], len(self.engine.game.pre_reveal.space.space))
            self._since.setdefault(key, time.monotonic())
        if text := event.get("text"):
            wake = SEATS if kind == "finished" else ()
            self._note(kind, text, wake=wake)
        elif kind in ("roll", "scores_ready"):
            label = "原始骰点 " + " : ".join(map(str, event["rolls"]))
            if "scores" in event:
                label += "，拼点点数 " + " : ".join(map(str, event["scores"]))
            self._note(kind, label)
        for side in SEATS:
            frame = self.engine.state(side)
            for key, plan in list(self._plans[side].items()):
                self._bind_or_expire(side, key, plan, frame, event)

    def _bind_or_expire(self, side, key, plan, frame, event):
        when = plan["when"]
        turn = frame["turn"]
        binding = self._bindings[side].setdefault(key, {})
        if "turn" in when and turn > when["turn"]:
            self._expire_plan(side, key)
            return
        if "pending_number" in when:
            if "turn" not in when and turn > 0:
                binding.setdefault("turn", turn)
                if turn > binding["turn"]:
                    self._expire_plan(side, key)
                    return
            duels = frame["pre_reveal"]["duels"]
            number = when["pending_number"]
            if len(duels) >= number and duels[number - 1]["ready"]:
                self._expire_plan(side, key)
                return
        if "duel_number" in when and when.get("duel_kind", "regular") == "regular":
            combat = frame.get("combat")
            if frame["phase"] == "turn_end" or (
                combat and combat["kind"] == "regular"
                and (
                    combat["duel_number"] > when["duel_number"]
                    or (combat["duel_number"] == when["duel_number"]
                        and "round_id" in when and combat["round_id"] > when["round_id"])
                )
            ):
                self._expire_plan(side, key)
                return
        if "own_card_id" in when and turn > 0 and ("turn" not in when or turn == when["turn"]):
            wanted = when["own_card_id"]
            series = when.get("duel_kind")
            slots = []
            if series in (None, "regular"):
                slots.extend(frame["duels"])
            if series in (None, "pre_reveal"):
                slots.extend(frame["pre_reveal"]["duels"])
            if series in (None, "instant"):
                slots.extend(frame["special_duels"])
            if series in ("regular", "pre_reveal", "instant") and "duel_number" in when:
                number = when["duel_number"]
                slots = [s for s in slots if s["number"] == number]
            found = False
            for slot in slots:
                mine = next(member for member in slot["sides"] if member["side"] == side)
                for card in (*mine["cards"], *mine.get("rear_cards", ())):
                    if card.get("id") == wanted and not card.get("used") and card.get("state") != "negated":
                        found = True
            if found:
                binding["seen_card"] = True
            elif binding.get("seen_card") or frame["phase"] in ("combat", "turn_end"):
                self._expire_plan(side, key)

    def _expire_plan(self, side, key):
        if key in self._plans[side]:
            del self._plans[side][key]
            self._bindings[side].pop(key, None)
            self._note("plan_expired", f"声明 {key} 的目标窗口已过，不再触发。", audiences=(side,))

    def _consider(self, event, edges, *, timer_plan=None):
        automatic = []
        for side in SEATS:
            if side == self.bot_side:
                continue
            frame = None
            options = None
            for key, plan in list(self._plans[side].items()):
                if (timer_plan is None) != (plan["event"] != "timer"):
                    continue
                if timer_plan is not None and timer_plan != (side, key):
                    continue
                if frame is None:
                    frame = self.engine.state(side)
                trigger = plan["event"]
                edge = edges.get(side)
                actual = event
                if trigger in ("decision", "placement", "pre_reveal"):
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
            if side in required and self.engine._mode() == "draw_select":
                key = ("draw_select", self.engine.revision)
            if key and key != self._previous_choices[side]:
                mode = self.engine.state(side)["mode"]
                edges[side] = mode if mode != "instant_response" else "decision"
            self._previous_choices[side] = key
        return edges

    def _drive(self, *, process=True, initial_auto=()):
        if not self.started:
            return
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
                # Smart Mid-Turn Bot Play (`reveal` / `combat` / `timing` beats when no seat is required)
                if (self.bot_side is not None and not self.challenge
                        and not required and self.paused_by is None and not self._asked):
                    cur_win = (self._window(), self.engine.event.get("kind"), self.engine.event.get("timing"))
                    if self._bot_inturn_window != cur_win:
                        self._bot_inturn_window = cur_win
                        bot_state = self.engine.state(self.bot_side)
                        bot_opts = self.engine.options(self.bot_side)
                        inturn_move = choose_inturn_move(bot_state, bot_opts)
                        if inturn_move is not None:
                            self.engine.apply(self.bot_side, inturn_move)
                            self._record(self.engine.event)
                            if self.engine.game_over:
                                break
                            # Pause cleanly on this beat so the human player sees the AI's mid-turn play!
                            if self.human_seats:
                                break
                            continue
                if self.paused_by is not None or self._disconnect_frozen_by is not None or required or self._asked:
                    for side in edges:
                        self._note("decision", "请选择当前行动。", audiences=(side,), wake=(side,))
                    break
                if (self.human_seats or self.hotseat) and self._should_stop_human_beat():
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
        self._bump()

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
        self._bump()

    def _advance_beat(self):
        with self.cv:
            if self._beat_timer is not threading.current_thread():
                return
            self._beat_timer = None
            if self._disconnect_frozen_by is not None:
                return
            self._step_beat()

    def _resume(self, remaining):
        with self.cv:
            if self._continuation is not threading.current_thread():
                return
            self._continuation = None
            if not self._closed and self.started and not self.engine.game_over:
                self._drive(process=False, initial_auto=remaining)
                self._bump()

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
        if self._closed or not self.started or self.engine.game_over or self.paused_by is not None or self._disconnect_frozen_by is not None:
            return
        next_timer = min(self._timers(), default=None)
        if next_timer is not None:
            deadline, _ = next_timer
            self._timer = threading.Timer(max(0, deadline - time.monotonic()), self._on_timer,
                                          args=(self._match_number,))
            self._timer.daemon = True
            self._timer.start()

    def _on_timer(self, match_number=None):
        with self.cv:
            if match_number is not None and match_number != self._match_number:
                return
            if self._closed or not self.started or self.engine.game_over or self.paused_by is not None or self._disconnect_frozen_by is not None:
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
                return latest > cursor or (self.started and self.engine.game_over) or self._closed

            changed = self.cv.wait_for(changed_since_cursor, timeout=timeout)
            if not changed:
                return dict(side=side, cursor=cursor, timeout=True)
            return self.observe(side, cursor)

    def _catalog(self, side, *, hotseat=False):
        if self.started or (not self._selectable and not self._engine_dirty):
            return self.engine.catalog()
        visible = self._lobby_snapshot(side, hotseat=hotseat)["picks"]
        return self.engine.catalog({s: [self._pool[cid] for cid in team] for s, team in visible.items()})

    def rules(self, topic=None, *, viewer_side=None):
        if topic == "catalog":
            with self.cv:
                return {"catalog": self._catalog(viewer_side)}
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
            end = next((m.start() for m in headings[i + 1:] if len(m[1]) <= len(level)), len(book))
            sections[key] = (title, book[match.start():end].strip())
        if topic == "briefing":
            articles = []
            for key in BRIEFING_ARTICLES:
                title, section = sections[key]
                body = section.partition("\n")[2].strip()
                paragraphs = [p for p in body.split("\n\n")
                              if not p.startswith(('<a id=', '*例。', '*计数例。', '*桌面裁例。', '**算例**'))]
                articles.append(dict(id=key, title=title, text="\n\n".join(paragraphs)))
            with self.cv:
                catalog = self._catalog(viewer_side)
            return dict(source, sections=articles, catalog=catalog, guide=GUIDE)
        if topic in (None, "", "index"):
            return dict(source, reading="首次参赛先读 briefing；完整阅读可用 full 和 catalog。",
                        guide=GUIDE, events=list(plans.EVENTS), action_kinds=sorted(plans.KINDS),
                        examples=[{"event": "scores_ready", "mode": "reserve", "when": {"score": "lt"},
                                   "match": {"kind": "special_replace"}},
                                  {"event": "timer", "mode": "reserve", "when": {"pending_number": 1, "after_ms": 3000}}],
                        topics=[dict(id=k, title=v[0]) for k, v in sections.items()])
        if not isinstance(topic, str) or topic not in sections:
            raise ValueError("未知章节。可查目录、briefing（赛前读本）、full（完整规则书）或 catalog（印刷牌面）。")
        title, content = sections[topic]
        return dict(id=topic, title=title, text=content)
