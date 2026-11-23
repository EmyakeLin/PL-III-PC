"""Verify room pacing, client-driven PVE, PVP fast-forward/rematch, and dice-roll event alignment."""

import unittest
from itertools import count

from battle_mcp.room import Room
from battle_ui.match import BattleMatch


class _RoomHelper:
    def next_id(self):
        return f"req-{next(self.reqs)}"

    def canvas(self, side=1):
        return self.room.canvas_state(side)


class CanvasPvePacingTests(_RoomHelper, unittest.TestCase):
    def setUp(self):
        self.room = Room(["plan_b_annolin", "plan_b_heck"], seed=42, bot=True)
        self.addCleanup(self.room.close)
        self.reqs = count(1)

    def test_pve_is_client_paced_skips_empty_timings_and_supports_mid_match_restart(self):
        lobby = self.canvas(1)
        self.assertFalse(lobby["started"])
        self.assertFalse(lobby["can_restart"])
        # Rematch still rejected before starting the first game.
        with self.assertRaises(ValueError):
            self.room.rematch(1, lobby["revision"], self.next_id())

        # Start PVE via Canvas ready -> immediately lands on placement (or draw_select) with no beat timer.
        self.room.ready(
            1, lobby["revision"], self.next_id(),
            human=True, canvas=True, roster=[["plan_b_annolin"], ["plan_b_heck"]],
        )
        state = self.canvas(1)
        self.assertTrue(state["started"])
        self.assertTrue(state["client_paced"])
        self.assertTrue(state["can_restart"])
        self.assertIsNone(self.room._beat_timer)
        self.assertIn(state["frame"]["mode"], ("placement", "draw_select"))
        self.assertFalse(state["has_special_actions"])

        # End placement immediately -> skips all empty pre-reveal timing nodes and lands straight on reveal.
        while state["frame"]["mode"] == "placement":
            end_move = next(m for m in state["options"] if m["kind"] == "end")
            self.room.act(1, end_move["id"], state["revision"], self.next_id())
            state = self.canvas(1)

        self.assertEqual(state["frame"]["mode"], "reveal")
        self.assertTrue(state["can_advance"])
        self.assertIsNone(self.room._beat_timer)

        # Stepping via next_beat visits only meaningful beats (never empty timing / advance nodes).
        visited_modes = [state["frame"]["mode"]]
        for _ in range(40):
            if state["frame"]["mode"] in ("placement", "finished"):
                break
            self.assertTrue(state["can_advance"], state["frame"]["mode"])
            self.assertIsNone(self.room._beat_timer)
            self.room.next_beat(1, state["revision"], self.next_id())
            state = self.canvas(1)
            visited_modes.append(state["frame"]["mode"])

        self.assertNotIn("timing", visited_modes)
        self.assertNotIn("advance", visited_modes)
        self.assertIn("turn_end", visited_modes)
        self.assertIn(state["frame"]["mode"], ("placement", "finished"))

        # Mid-match restart / roster change works immediately without finishing the match.
        self.assertFalse(state["frame"]["is_over"])
        self.room.rematch(
            1, state["revision"], self.next_id(),
            roster=[["plan_b_heris", "plan_b_li_ling"], ["nova_lin_qiu", "plan_b_heck"]],
        )
        restarted = self.canvas(1)
        self.assertEqual(restarted["match_number"], 2)
        self.assertEqual(len(restarted["frame"]["players"][0]["characters"]), 2)
        self.assertEqual(len(restarted["frame"]["players"][1]["characters"]), 2)
        self.assertIsNone(self.room._beat_timer)

        # Stale-revision set_default_target still succeeds cleanly without throwing RoomConflict.
        target_id = restarted["frame"]["players"][1]["characters"][1]["id"]
        self.room.set_default_target(1, target_id, max(0, restarted["revision"] - 1), self.next_id())
        after_target = self.canvas(1)
        self.assertEqual(after_target["default_targets"].get(1), target_id)


class MultiplayerPvpRoomTests(_RoomHelper, unittest.TestCase):
    def setUp(self):
        self.room = Room(["plan_b_annolin", "plan_b_heck"], seed=19, selectable=True)
        self.addCleanup(self.room.close)
        self.reqs = count(1)

    def test_pvp_skips_empty_timings_votes_next_and_supports_pause_resume(self):
        self.room.ready(1, self.canvas(1)["revision"], self.next_id(), human=True, canvas=True)
        self.room.ready(2, self.canvas(2)["revision"], self.next_id(), human=True, canvas=True)

        # Immediately reaches placement without sitting on empty turn_start timing nodes.
        s1 = self.canvas(1)
        self.assertFalse(s1["client_paced"])
        self.assertEqual(s1["frame"]["mode"], "placement")

        # Both sides end placement -> skips empty pre-reveal timing nodes -> lands straight on reveal.
        for _ in range(6):
            s1, s2 = self.canvas(1), self.canvas(2)
            if s1["frame"]["mode"] != "placement":
                break
            for side, st in ((1, s1), (2, s2)):
                end = next((m for m in st["options"] if m["kind"] == "end"), None)
                if end:
                    self.room.act(side, end["id"], st["revision"], self.next_id())

        s1, s2 = self.canvas(1), self.canvas(2)
        self.assertEqual(s1["frame"]["mode"], "reveal")
        self.assertTrue(s1["can_advance"])
        self.assertTrue(s2["can_advance"])
        self.assertIsNotNone(self.room._beat_timer)

        # Pause freezes the shared beat timer; resume restarts it cleanly.
        self.room.pause(2, s2["revision"], self.next_id())
        self.assertIsNone(self.room._beat_timer)
        self.assertEqual(self.canvas(1)["paused_by"], 2)
        self.room.resume(2, self.canvas(2)["revision"], self.next_id())
        self.assertIsNotNone(self.room._beat_timer)
        self.assertIsNone(self.canvas(1)["paused_by"])

        # Single seat voting next registers vote without jumping ahead of the other human.
        s1 = self.canvas(1)
        self.room.next_beat(1, s1["revision"], self.next_id())
        s1_after = self.canvas(1)
        self.assertTrue(s1_after["next_voted"])
        self.assertEqual(s1_after["frame"]["mode"], "reveal")

        # Second seat voting next advances the beat immediately!
        s2 = self.canvas(2)
        self.room.next_beat(2, s2["revision"], self.next_id())
        s1_next = self.canvas(1)
        self.assertFalse(s1_next["next_voted"])
        self.assertNotEqual(s1_next["frame"]["mode"], "reveal")
        self.assertNotEqual(s1_next["frame"]["mode"], "timing")

    def test_pvp_allows_post_match_rematch(self):
        self.room.ready(1, self.canvas(1)["revision"], self.next_id(), human=True, canvas=True)
        self.room.ready(2, self.canvas(2)["revision"], self.next_id(), human=True, canvas=True)
        with self.room.cv:
            self.room._cancel_beat()
            target = self.room.engine.game.players[1].characters[0]
            target.lose_hp(target.hp)
            self.room.engine.game.check_game_over()
            self.room.engine._finish()
            self.room._note("finished", "玩家一获胜。", wake=(1, 2))

        finished = self.canvas(1)
        self.assertTrue(finished["frame"]["is_over"])
        self.assertTrue(finished["can_rematch"])
        # Custom roster is rejected in PVP rematch, same-roster rematch succeeds.
        with self.assertRaises(ValueError):
            self.room.rematch(1, finished["revision"], self.next_id(), roster=["plan_b_heck", "plan_b_heris"])
        self.room.rematch(1, finished["revision"], self.next_id())
        rematched = self.canvas(1)
        self.assertEqual(rematched["match_number"], 2)
        self.assertFalse(rematched["frame"]["is_over"])
        self.assertEqual(rematched["frame"]["mode"], "placement")

    def test_human_vs_mcp_fast_forwards_immediately_while_preserving_agent_declarations(self):
        room = Room(["plan_b_annolin", "plan_b_heck"], seed=7)
        self.addCleanup(room.close)
        # Seat 2 is an MCP agent subscribing to micro-timing "roll"; Seat 1 is a Canvas human.
        room.prepare(2, {"mode": "reserve", "event": "roll"}, room.observe(2)["revision"], "mcp-roll")
        room.ready(1, room.observe(1)["revision"], "h1", human=True, canvas=True)
        room.ready(2, room.observe(2)["revision"], "a2", human=False)

        # Both place 1 card and end placement.
        placed = set()
        for step in range(12):
            s1, obs2 = room.canvas_state(1), room.observe(2)
            if s1["frame"]["mode"] != "placement":
                break
            for side, st in ((1, s1), (2, obs2)):
                if not st["options"]:
                    continue
                place = next((m for m in st["options"] if m["kind"] == "place"), None)
                end = next((m for m in st["options"] if m["kind"] == "end"), None)
                choice = place if (place and side not in placed) else end
                if choice:
                    if choice["kind"] == "place":
                        placed.add(side)
                    room.act(side, choice["id"], st["revision"], f"hm-{side}-{step}")

        s1 = room.canvas_state(1)
        self.assertEqual(s1["frame"]["mode"], "reveal")
        # Single human in Human-vs-MCP can advance immediately with next_beat,
        # and MCP agent's micro-timing "roll" declaration STILL fires during the skipped nodes!
        for idx in range(5):
            obs2 = room.observe(2)
            if obs2["event"]["kind"] == "roll":
                break
            s1 = room.canvas_state(1)
            self.assertTrue(s1["can_advance"], s1["frame"]["mode"])
            room.next_beat(1, s1["revision"], f"hm-next-{idx}")
        obs2 = room.observe(2)
        self.assertEqual(obs2["event"]["kind"], "roll")
        self.assertTrue(any(m["kind"] == "decline" for m in obs2["options"]))


class PureMcpRoomPreservationTests(unittest.TestCase):
    def test_dual_mcp_agents_still_trigger_micro_timing_declarations(self):
        room = Room(["plan_b_annolin", "plan_b_heck"], seed=7)
        self.addCleanup(room.close)
        obs1 = room.observe(1)
        room.prepare(1, {"mode": "reserve", "event": "roll"}, obs1["revision"], "prep-roll")
        room.ready(1, room.observe(1)["revision"], "r1", human=False)
        room.ready(2, room.observe(2)["revision"], "r2", human=False)
        self.assertEqual(room.human_seats, set())
        self.assertIsNone(room._beat_timer)

        saw_roll_reservation = False
        for step in range(40):
            if room.engine.game_over:
                break
            acted = False
            for side in (1, 2):
                obs = room.observe(side)
                if obs["event"]["kind"] == "roll" and any(m["kind"] == "decline" for m in obs["options"]):
                    saw_roll_reservation = True
                    break
                if obs["options"]:
                    place = next((m for m in obs["options"] if m["kind"] == "place"), None)
                    end = next((m for m in obs["options"] if m["kind"] == "end"), None)
                    choice = place if (place and step < 2) else (end or obs["options"][0])
                    room.act(side, choice["id"], obs["revision"], f"act-{side}-{step}")
                    acted = True
                    break
            if saw_roll_reservation or not acted:
                break
        self.assertTrue(saw_roll_reservation)


class DiceRollEventAlignmentTests(unittest.TestCase):
    def _advance_until(self, match, predicate, limit=100):
        for _ in range(limit):
            snap = match.snapshot()
            if predicate(snap):
                return snap
            mode = snap["mode"]
            if mode == "handoff":
                match.act("ready", snap["revision"])
            elif mode in ("reveal", "combat", "turn_end", "timing"):
                match.act("next", snap["revision"])
            else:
                break
        return match.snapshot()

    def test_solo_attack_emits_dice_roll_strictly_before_combat_strike(self):
        match = BattleMatch(["plan_b_annolin", "plan_b_heck"], seed=11)
        snap = match.snapshot()
        first_side = snap["active_side"]
        first_player = next(p for p in snap["frame"]["players"] if p["side"] == first_side)
        attack_card = next(
            c for c in first_player["hand"]
            if (c.get("action_key") or c["id"]) in snap["legal_cards"]
            and any(d["type"] in ("slash", "pierce", "blunt") for d in c["dice"])
        )
        placed_first = False
        for _ in range(10):
            if snap["mode"] == "handoff":
                snap = match.act("ready", snap["revision"])
            elif snap["mode"] == "placement":
                if snap["active_side"] == first_side and not placed_first:
                    snap = match.act("place", snap["revision"], card_id=attack_card.get("action_key") or attack_card["id"])
                    placed_first = True
                else:
                    snap = match.act("end", snap["revision"])
            else:
                break

        snap = self._advance_until(
            match,
            lambda s: any(e["kind"] == "combat_strike" and e.get("one_sided") for e in s["fx_events"]),
        )
        events = snap["fx_events"]
        strike_idx = next(i for i, e in enumerate(events) if e["kind"] == "combat_strike" and e.get("one_sided"))
        roll_indices = [
            i for i, e in enumerate(events)
            if e["kind"] == "dice_roll" and e.get("one_sided") and e["sides"][0]["rolled_value"] is not None
        ]
        self.assertTrue(roll_indices, "Solo attack must emit a dice_roll event!")
        self.assertLess(roll_indices[0], strike_idx, "dice_roll must precede combat_strike!")

    def test_clash_emits_dice_clash_and_does_not_duplicate_roll_on_hit(self):
        match = BattleMatch(["plan_b_annolin", "plan_b_heck"], seed=12)
        snap = match.snapshot()
        placed = set()
        for _ in range(12):
            if snap["mode"] == "handoff":
                snap = match.act("ready", snap["revision"])
            elif snap["mode"] == "placement":
                side = snap["active_side"]
                if side not in placed and snap["legal_cards"]:
                    snap = match.act("place", snap["revision"], card_id=snap["legal_cards"][0])
                    placed.add(side)
                else:
                    snap = match.act("end", snap["revision"])
            else:
                break

        snap = self._advance_until(
            match,
            lambda s: s["mode"] == "turn_end",
            limit=120,
        )
        events = snap["fx_events"]
        clashes = [e for e in events if e["kind"] == "dice_clash"]
        self.assertTrue(clashes, "Expected at least one dice_clash event")
        for clash in clashes:
            for sd in clash["sides"]:
                self.assertIn("die_number", sd)
                if not sd.get("skipped"):
                    self.assertIsNotNone(sd.get("rolled_value"))
        clash_keys = {
            (e["turn"], e["duel_kind"], e["duel_number"], e["round_id"], sd["side"], sd["die_number"])
            for e in clashes for sd in e["sides"] if not sd.get("skipped")
        }
        dup_rolls = [
            e for e in events if e["kind"] == "dice_roll"
            for sd in e["sides"]
            if (e["turn"], e["duel_kind"], e["duel_number"], e["round_id"], sd["side"], sd["die_number"]) in clash_keys
        ]
        self.assertEqual(dup_rolls, [])


if __name__ == "__main__":
    unittest.main()
