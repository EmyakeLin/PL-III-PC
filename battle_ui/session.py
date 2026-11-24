"""The hot-seat / VS-AI table and its revision-checked commands."""

import random
import secrets
from http import HTTPStatus
from threading import Lock

from .match import BattleMatch


class BattleSession:
    """A single table shared by the browsers connected to this local process."""

    def __init__(self, seed=None, *, roster=None, ai_side=None, challenge=None, open_rosters=False):
        self.seed = seed
        self.ai_side = ai_side
        self.challenge = challenge
        self.open_rosters = open_rosters
        self._rng = random.Random(seed)
        self.match = self._new_match(roster, initial_handoff=roster is not None and ai_side is None)
        if self.ai_side is not None:
            self._drive_ai()
        self.revision = secrets.randbits(40)
        self.match_number = 1
        self.lock = Lock()

    def _new_match(self, roster, *, initial_handoff):
        if self.challenge:
            roster = self.challenge.validate_roster(roster)
        match = BattleMatch(roster, seed=self.seed, initial_handoff=initial_handoff, open_rosters=self.open_rosters,
                            extra_packs=self.challenge.packs if self.challenge else (), full_history=True)
        if self.challenge:
            match.game.players[self.ai_side - 1].target_priority = (("hp", 1), ("lightcore_hp", 1))
        return match

    def _remaining_budget(self, snap):
        """Compute AI's exact remaining shared & per-character cost budget after already-placed cards."""
        frame = snap.get("frame") or {}
        players = frame.get("players") or []
        me = next((p for p in players if p.get("side") == self.ai_side), None)
        if not me:
            return 0, {}, {}
        shared = int(((me.get("cost") or {}).get("available")) or 0)
        char_budget = {}
        char_statuses = {}
        for ch in me.get("characters") or []:
            cid = ch.get("id")
            if not cid:
                continue
            char_budget[cid] = int(((ch.get("cost") or {}).get("available")) or 0)
            char_statuses[cid] = dict(ch.get("statuses") or {})

        # Deduct cost of all cards AI has already committed to board slots this turn (not yet paid until combat)
        all_slots = (
            list(frame.get("duels") or [])
            + list(((frame.get("pre_reveal") or {}).get("duels")) or [])
            + list(frame.get("special_duels") or [])
        )
        for slot in all_slots:
            se = next((s for s in (slot.get("sides") or []) if s.get("side") == self.ai_side), None)
            all_side_cards = [*((se or {}).get("cards") or []), *((se or {}).get("rear_cards") or [])]
            for card in all_side_cards:
                if not card or card.get("used") or card.get("destroyed") or card.get("skipped"):
                    continue
                c_cost = max(0, int(card.get("cost") or 0))
                cid = card.get("character_id")
                personal = min(c_cost, char_budget.get(cid, 0))
                if cid in char_budget:
                    char_budget[cid] -= personal
                shared = max(0, shared - (c_cost - personal))
        return shared, char_budget, char_statuses

    def _is_card_affordable(self, card, shared, char_budget, char_statuses):
        if not card:
            return False
        cid = card.get("character_id")
        c_cost = max(0, int(card.get("cost") or 0))
        if c_cost > shared + char_budget.get(cid, 0):
            return False
        res = card.get("resource_cost")
        if isinstance(res, dict) and res.get("status"):
            have = int((char_statuses.get(cid) or {}).get(res["status"], 0))
            if have < int(res.get("amount") or 0):
                return False
        return True

    def _ai_step(self, snap):
        """Execute one legal action on behalf of `self.ai_side` (or auto-clear hotseat handoff)."""
        mode = snap.get("mode")
        active = snap.get("active_side")
        rev = self.match.revision

        # In VS-AI mode, never show hotseat handoff curtains — auto-ready into the active seat.
        if mode in ("handoff", "special_handoff"):
            if active is not None:
                self.match.act("ready", rev, side=active)
                return True
            return False

        if active != self.ai_side:
            return False

        if self.challenge and (decision := self.challenge.table_action(snap)):
            action, arguments = decision
            self.match.act(action, rev, **arguments)
            return True

        if mode == "draw_select":
            prompt = snap.get("draw_select") or {}
            discard_count = int(prompt.get("discard_count") or 0)
            candidates = list(prompt.get("candidates") or [])
            if len(candidates) >= discard_count:
                # Prefer putting higher-cost cards to the bottom (with slight random tie-break)
                ranked = sorted(
                    candidates,
                    key=lambda c: (int(c.get("cost") or 0), self._rng.random()),
                    reverse=True,
                )
                chosen = [c["action_key"] for c in ranked[:discard_count]]
                self.match.act("draw_bottom", rev, card_ids=chosen)
                return True
            return False

        if mode == "placement":
            legal = list(snap.get("legal_cards") or [])
            players = (snap.get("frame") or {}).get("players") or []
            me = next((p for p in players if p.get("side") == self.ai_side), None)
            hand = (me or {}).get("hand") or []
            hand_by_key = {(c.get("action_key") or c.get("id")): c for c in hand}
            shared, char_budget, char_statuses = self._remaining_budget(snap)

            affordable = [
                k for k in legal
                if self._is_card_affordable(hand_by_key.get(k), shared, char_budget, char_statuses)
            ]
            if affordable:
                chosen = self._rng.choice(affordable)
                self.match.act("place", rev, card_id=chosen)
                return True
            rear_legal = [
                k for k in (snap.get("legal_rear_cards") or [])
                if self._is_card_affordable(hand_by_key.get(k), shared, char_budget, char_statuses)
                and (snap.get("rear_targets") or {}).get(k)
            ]
            if rear_legal:
                chosen = self._rng.choice(rear_legal)
                duel_num = self._rng.choice(snap["rear_targets"][chosen])
                self.match.act("place_rear", rev, card_id=chosen, duel_number=duel_num)
                return True
            # If AI still holds an affordable pre-reveal card, optionally claim pre-reveal before ending placement!
            if not snap.get("pre_reveal_claimed"):
                pre_elig = [
                    k for k in (snap.get("pre_reveal_eligible_cards") or [])
                    if self._is_card_affordable(hand_by_key.get(k), shared, char_budget, char_statuses)
                ]
                if pre_elig and self._rng.random() < 0.45:
                    self.match.act("claim_pre_reveal", rev)
                    return True
            # Never play over-cost cards: end placement once remaining budget cannot afford any legal card!
            self.match.act("end", rev)
            return True

        if mode == "pre_attack":
            legal_atk = list(snap.get("legal_attack_cards") or [])
            targets_map = snap.get("attack_targets") or {}
            players = (snap.get("frame") or {}).get("players") or []
            me = next((p for p in players if p.get("side") == self.ai_side), None)
            hand_by_key = {(c.get("action_key") or c.get("id")): c for c in ((me or {}).get("hand") or [])}
            shared, char_budget, char_statuses = self._remaining_budget(snap)
            affordable_atk = [
                cid for cid in legal_atk
                if self._is_card_affordable(hand_by_key.get(cid), shared, char_budget, char_statuses)
            ]
            if affordable_atk and self._rng.random() < 0.45:
                for cid in affordable_atk:
                    tlist = targets_map.get(cid) or []
                    if tlist:
                        self.match.act("attack", rev, card_id=cid, target=self._rng.choice(tlist))
                        return True
            self.match.act("end_attack", rev)
            return True

        if mode == "intercept":
            pending = list(snap.get("pending_responses") or [])
            legal_int = snap["intercepts_by_number"].get(pending[0], []) if pending else []
            players = (snap.get("frame") or {}).get("players") or []
            me = next((p for p in players if p.get("side") == self.ai_side), None)
            hand_by_key = {(c.get("action_key") or c.get("id")): c for c in ((me or {}).get("hand") or [])}
            shared, char_budget, char_statuses = self._remaining_budget(snap)
            affordable_int = [
                cid for cid in legal_int
                if self._is_card_affordable(hand_by_key.get(cid), shared, char_budget, char_statuses)
            ]
            if pending:
                duel_num = pending[0]
                if affordable_int and self._rng.random() < 0.7:
                    self.match.act("intercept", rev, card_id=self._rng.choice(affordable_int), duel_number=duel_num)
                else:
                    self.match.act("let_through", rev, duel_number=duel_num)
                return True
            return False

        if mode == "special" or snap.get("effect_choice"):
            options = snap.get("special_options") or []
            if snap.get("special_pending") and not snap.get("effect_choice") and options:
                idx = next((i for i, option in enumerate(options) if option["kind"] == "pass_intercept"), 0)
                self.match.act("use_special", rev, option=idx)
                return True
            if snap.get("effect_choice") and options:
                non_decline = [i for i, o in enumerate(options) if o.get("kind") not in ("decline_card", "decline_option", "decline_character")]
                idx = self._rng.choice(non_decline) if non_decline else 0
                self.match.act("use_special", rev, option=idx)
                return True
            self.match.act("leave_special", rev)
            return True

        return False

    def _drive_ai(self):
        if self.ai_side is None:
            return
        for _ in range(48):
            snap = self.match.snapshot()
            if snap.get("mode") == "finished":
                break
            try:
                acted = self._ai_step(snap)
            except ValueError:
                break
            if not acted:
                break

    def _state(self):
        return {**self.match.snapshot(), "revision": self.revision, "match_number": self.match_number,
                "ai_side": self.ai_side, "challenge": self.challenge.name if self.challenge else None,
                "open_rosters": self.open_rosters}

    def state(self):
        with self.lock:
            return self._state()

    def battle_record(self):
        with self.lock:
            game = self.match.game
            frame = self.match._views[None].snapshot()
            return {"match_number": self.match_number, "history": list(self.match._history),
                    "challenge": self.challenge.name if self.challenge else None, "bot_side": self.ai_side,
                    "finished": game.is_over, "winner_side": frame["winner_side"],
                    "frame": {"turn": frame["turn"], "players": [
                        {"side": p.side, "characters": [{"name": c.name} for c in p.characters]} for p in game.players]}}

    def command(self, request):
        if not isinstance(request, dict) or type(request.get("revision")) is not int:
            raise ValueError("操作缺少有效的对局版本。")
        with self.lock:
            if request["revision"] != self.revision:
                return HTTPStatus.CONFLICT, self._state()
            action = request.get("action")
            if action == "new":
                roster = request.get("roster")
                self.match = self._new_match(roster, initial_handoff=self.ai_side is None)
                self.match_number += 1
            else:
                if action not in ("place", "place_rear", "end", "pass", "ready", "next",
                                  "attack", "end_attack", "intercept", "let_through", "switch_side",
                                  "claim_pre_reveal", "stage_pre_reveal", "unstage_pre_reveal", "commit_pre_reveal_plan",
                                  "trigger_table_action",
                                  "open_special", "leave_special", "use_special",
                                  "draw_bottom", "set_default_target"):
                    raise ValueError("未知的对战操作。")
                self.match.act(
                    action,
                    self.match.revision,
                    card_id=request.get("card_id"),
                    card_ids=request.get("card_ids"),
                    target=request.get("target"),
                    side=request.get("side"),
                    duel_number=request.get("duel_number"),
                    option=request.get("option"),
                    character_id=request.get("character_id"),
                )
            self._drive_ai()
            self.revision += 1
            return HTTPStatus.OK, self._state()
