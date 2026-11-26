"""Dedicated tests for hit causal event ordering, mid-duel cut-in placement/replacement, and PvP/VS-AI live actions."""

from itertools import count
import time
import unittest

from battle_mcp.room import Room
from battle_ui.match import BattleMatch
from models.card import Card


class HitCausalOrderAndMidDuelCutInTests(unittest.TestCase):
    def test_combat_strike_precedes_damage_and_ignite_while_following_pre_hit_events(self):
        match = BattleMatch(["cang_feng_he_lian", "plan_b_annolin"], seed=7, viewer_side=1)
        p1, _ = match.game.players
        atk = Card(p1, {
            "id": "test_triple_slash",
            "name": "试作三连斩",
            "cost": 1,
            "entries": [
                {
                    "trigger": "on_skill_use",
                    "description": "使用时自身获得2护盾",
                    "operation": {"op": "program", "code": ["$self", "normal", 2, "SHIELD"]},
                }
            ],
            "dice": [
                {
                    "type": "slash",
                    "level": 4,
                    "entries": [
                        {
                            "trigger": "on_dice_hit",
                            "description": "2物理",
                            "operation": {"op": "program", "code": ["$event.target", 2, "normal", "attack", "DAMAGE"]},
                        },
                        {
                            "trigger": "on_dice_hit",
                            "description": "命中时施加8烧伤",
                            "operation": {"op": "program", "code": ["$event.target", "烧伤", 8, "STATUS"]},
                        },
                        {
                            "trigger": "on_dice_hit",
                            "description": "命中时引燃目标",
                            "operation": {"keyword": "ignite"},
                        },
                    ],
                },
            ],
        }, p1.characters[0])
        p1.characters[0].skills.append(atk)
        p1.cardspace.hand.add_card(atk)

        snap = match.snapshot()
        placed = False
        for _ in range(20):
            if snap["mode"] == "handoff":
                snap = match.act("ready", snap["revision"])
            elif snap["mode"] == "draw_select":
                ids = [c["action_key"] for c in snap["draw_select"]["candidates"][:snap["draw_select"]["discard_count"]]]
                snap = match.act("draw_bottom", snap["revision"], card_ids=ids)
            elif snap["mode"] == "timing" and not snap["frame"]["cards_revealed"]:
                snap = match.act("next", snap["revision"])
            elif snap["mode"] == "placement":
                if snap["active_side"] == 1 and not placed:
                    snap = match.act("place", snap["revision"], card_id="test_triple_slash")
                    placed = True
                else:
                    snap = match.act("end", snap["revision"])
            elif snap["mode"] == "pre_attack":
                snap = match.act("end_attack", snap["revision"])
            else:
                break

        saw_skill_entrance_before_roll = False
        for _ in range(30):
            if snap["mode"] == "handoff":
                snap = match.act("ready", snap["revision"])
                continue
            events = snap["fx_events"]
            has_pay = any(e["kind"] == "cost_pay" for e in events)
            has_roll = any(e["kind"] == "dice_roll" for e in events)
            if has_pay and not has_roll and snap["mode"] == "combat":
                saw_skill_entrance_before_roll = True
            if any(e["kind"] == "combat_strike" for e in events):
                break
            snap = match.act("next", snap["revision"])

        self.assertTrue(saw_skill_entrance_before_roll, "Unopposed skill entrance must pause before rolling Die 1!")
        events = snap["fx_events"]
        seqs = [e["seq"] for e in events]
        self.assertEqual(seqs, sorted(seqs), "fx_events seq must remain strictly monotonic!")
        self.assertEqual(len(seqs), len(set(seqs)), "fx_events seq must have zero duplicates!")

        pay_idx = next(i for i, e in enumerate(events) if e["kind"] == "cost_pay")
        shield_idx = next(i for i, e in enumerate(events) if e["kind"] == "shield_gain" and i > pay_idx)
        roll_idx = next(i for i, e in enumerate(events) if e["kind"] == "dice_roll")
        strike_idx = next(i for i, e in enumerate(events) if e["kind"] == "combat_strike")
        dmg_indices = [i for i, e in enumerate(events) if e["kind"] == "damage"]

        self.assertLess(pay_idx, roll_idx)
        self.assertLess(shield_idx, strike_idx, "on_skill_use shield gain must precede combat_strike!")
        self.assertLess(roll_idx, strike_idx, "dice_roll must precede combat_strike!")
        self.assertGreaterEqual(len(dmg_indices), 2, "Expected direct hit damage + ignite burn damage!")
        for d_idx in dmg_indices:
            self.assertLess(strike_idx, d_idx, "combat_strike must strictly precede every hit/ignite damage event!")

    def test_vs_ai_room_keeps_live_hand_and_mid_duel_place_clashes_third_die_inline(self):
        room = Room(["cang_feng_ji_lan", "plan_b_heck"], seed=15, bot=True, start_immediately=True)
        match = room.engine
        human, bot = match.game.players

        for slot in match.game.duelspace.space:
            slot.content[1] = []
            slot.content[2] = []
        for ch in bot.characters:
            ch.used_duels = 0
        bot.cardspace.hand.content.clear()
        triple = Card(bot, {
            "id": "bot_three_hits",
            "name": "三段连击",
            "cost": 0,
            "dice": [
                {
                    "type": "slash",
                    "level": 2,
                    "entries": [{"trigger": "on_dice_hit", "operation": {"op": "program", "code": ["$event.target", 1, "normal", "attack", "DAMAGE"]}}],
                }
                for _ in range(3)
            ],
        }, bot.characters[0])
        bot.characters[0].skills.append(triple)
        bot.cardspace.hand.add_card(triple)
        match.game.auto_place_in_duel(2, triple)

        cut_in = Card(human, {
            "id": "ji_lan_test_cutin",
            "name": "测试插队盾",
            "cost": 0,
            "anytime_play": ["place"],
            "dice": [{"type": "block", "level": 5, "entries": []}],
        }, human.characters[0])
        human.characters[0].skills.append(cut_in)
        human.cardspace.hand.add_card(cut_in)

        for idx in range(25):
            state = room.canvas_state(1)
            if state["frame"]["cards_revealed"]:
                break
            opts = state["options"]
            end_m = next((m for m in opts if m["kind"] in ("end", "end_attack", "let_through")), None)
            if end_m:
                room.act(1, end_m["id"], state["revision"], f"pre-{idx}")
            elif state["can_advance"]:
                room.next_beat(1, state["revision"], f"prenx-{idx}")
            else:
                break

        for idx in range(30):
            state = room.canvas_state(1)
            strikes = [e for e in state["fx_events"] if e["kind"] == "combat_strike"]
            if len(strikes) == 2 and not state["frame"].get("effect_choice"):
                break
            opts = state["options"]
            dec = next((m for m in opts if m["kind"].startswith("special_decline_")), None)
            if dec:
                room.act(1, dec["id"], state["revision"], f"dec-{idx}")
            else:
                room.next_beat(1, state["revision"], f"s1-{idx}")

        state = room.canvas_state(1)
        strikes = [e for e in state["fx_events"] if e["kind"] == "combat_strike"]
        self.assertEqual(len(strikes), 2, "Opponent should have completed exactly 2 solo strikes!")
        human_view = next(p for p in state["frame"]["players"] if p["side"] == 1)
        self.assertIsNotNone(human_view["hand"], "VS-AI Room must keep human hand visible during combat!")
        place_move = next(
            opt for opt in state["options"]
            if opt["kind"] == "special_place" and opt.get("card_id") == "ji_lan_test_cutin" and opt.get("duel_number") == 1
        )

        room.act(1, place_move["id"], state["revision"], "cutin-act")

        for idx in range(15):
            state = room.canvas_state(1)
            clashes = [e for e in state["fx_events"] if e["kind"] == "dice_clash"]
            if clashes:
                break
            dec = next((m for m in state["options"] if m["kind"].startswith("special_decline_")), None)
            if dec:
                room.act(1, dec["id"], state["revision"], f"dec2-{idx}")
            elif state["can_advance"]:
                room.next_beat(1, state["revision"], f"s2-{idx}")
            else:
                break

        state = room.canvas_state(1)
        clashes = [e for e in state["fx_events"] if e["kind"] == "dice_clash"]
        self.assertEqual(len(clashes), 1, "Newly placed card's Die 1 must clash with Opponent's Die 3!")
        clash = clashes[0]
        self.assertEqual(clash["duel_number"], 1)
        by_side = {sd["side"]: sd for sd in clash["sides"]}
        self.assertEqual(by_side[1]["card_id"], "ji_lan_test_cutin")
        self.assertEqual(by_side[1]["die_number"], 1)
        self.assertEqual(by_side[2]["card_id"], "bot_three_hits")
        self.assertEqual(by_side[2]["die_number"], 3)


class OnlinePvpRoomInTurnTests(unittest.TestCase):
    def setUp(self):
        self.room = Room(["plan_b_annolin", "plan_b_heck"], seed=29)
        self.addCleanup(self.room.close)
        self.reqs = count(1)

    def next_id(self):
        return f"pvp-{next(self.reqs)}"

    def _setup_pvp_3die_duel(self):
        p1, p2 = self.room.engine.game.players
        cut_in = Card(p1, {
            "id": "p1_instant_guard",
            "name": "即时切入盾",
            "cost": 0,
            "anytime_play": ["place"],
            "dice": [{"type": "block", "level": 5, "entries": []}],
        }, p1.characters[0])
        p1.characters[0].skills.append(cut_in)
        p1.cardspace.hand.add_card(cut_in)

        swap_in = Card(p1, {
            "id": "p1_instant_swap",
            "name": "即时替换刃",
            "cost": 0,
            "anytime_replace": True,
            "dice": [{"type": "slash", "level": 5, "entries": []}],
        }, p1.characters[0])
        p1.characters[0].skills.append(swap_in)
        p1.cardspace.hand.add_card(swap_in)

        triple = Card(p2, {
            "id": "p2_triple_strike",
            "name": "敌方三连击",
            "cost": 0,
            "dice": [
                {
                    "type": "slash",
                    "level": 2,
                    "entries": [{"trigger": "on_dice_hit", "operation": {"op": "program", "code": ["$event.target", 1, "normal", "attack", "DAMAGE"]}}],
                }
                for _ in range(3)
            ],
        }, p2.characters[0])
        p2.characters[0].skills.append(triple)
        p2.cardspace.hand.add_card(triple)

        self.room.ready(1, self.room.canvas_state(1)["revision"], self.next_id(), human=True, canvas=True)
        self.room.ready(2, self.room.canvas_state(2)["revision"], self.next_id(), human=True, canvas=True)

        placed_p2 = False
        for _ in range(8):
            s1, s2 = self.room.canvas_state(1), self.room.canvas_state(2)
            if s1["frame"]["mode"] != "placement":
                break
            for side, st in ((1, s1), (2, s2)):
                if not st["options"]:
                    continue
                if side == 2 and not placed_p2:
                    move = next(m for m in st["options"] if m["kind"] == "place" and m["card_id"] == "p2_triple_strike")
                    placed_p2 = True
                else:
                    move = next((m for m in st["options"] if m["kind"] == "end"), None)
                if move:
                    self.room.act(side, move["id"], st["revision"], self.next_id())

    def _both_next(self):
        s1, s2 = self.room.canvas_state(1), self.room.canvas_state(2)
        if s1["can_advance"]:
            self.room.next_beat(1, s1["revision"], self.next_id())
        s2 = self.room.canvas_state(2)
        if s2["can_advance"]:
            self.room.next_beat(2, s2["revision"], self.next_id())

    def test_pvp_direct_play_without_pause_and_window_tolerant_commit_clashes_third_die(self):
        self._setup_pvp_3die_duel()

        # Advance until P2's 2nd solo hit lands
        for _ in range(20):
            s1 = self.room.canvas_state(1)
            if len([e for e in s1["fx_events"] if e["kind"] == "combat_strike"]) == 2:
                break
            self._both_next()

        s1_before_vote = self.room.canvas_state(1)
        s2_view = self.room.canvas_state(2)
        # 1. Zero pause required: Seat 1 sees its own special_place option privately; Seat 2 does NOT see Seat 1's options!
        self.assertIsNone(s1_before_vote["paused_by"])
        place_move = next(
            m for m in s1_before_vote["options"]
            if m["kind"] == "special_place" and m.get("card_id") == "p1_instant_guard"
        )
        self.assertFalse(any(m.get("card_id") == "p1_instant_guard" for m in s2_view["options"]))
        # Symmetric public beat duration on both seats (zero read-timer leak!)
        self.assertEqual(s1_before_vote["beat_duration_ms"], s2_view["beat_duration_ms"])
        self.assertGreater(s1_before_vote["beat_duration_ms"], 0)

        # 2. Even if Seat 2 votes next_beat or sets default target right before Seat 1's click arrives,
        #    Seat 1's inline special_place in the exact same window still commits without 409 RoomConflict!
        self.room.set_default_target(1, s1_before_vote["frame"]["players"][1]["characters"][0]["id"],
                                     s1_before_vote["revision"], self.next_id())
        self.assertGreater(self.room.canvas_state(1)["revision"], s1_before_vote["revision"])
        self.room.act(1, place_move["id"], s1_before_vote["revision"], self.next_id())

        # 3. Advance into Round 3 -> Seat 1's Die 1 clashes directly with Seat 2's Die 3!
        for _ in range(10):
            s1 = self.room.canvas_state(1)
            if any(e["kind"] == "dice_clash" for e in s1["fx_events"]):
                break
            self._both_next()

        clashes = [e for e in self.room.canvas_state(1)["fx_events"] if e["kind"] == "dice_clash"]
        self.assertEqual(len(clashes), 1)
        by_side = {sd["side"]: sd for sd in clashes[0]["sides"]}
        self.assertEqual((by_side[1]["card_id"], by_side[1]["die_number"]), ("p1_instant_guard", 1))
        self.assertEqual((by_side[2]["card_id"], by_side[2]["die_number"]), ("p2_triple_strike", 3))

    def test_pvp_prequeue_prepare_during_round_one_auto_places_after_second_die_with_zero_leak(self):
        self._setup_pvp_3die_duel()

        # Advance out of reveal onto the very first combat beat (unopposed skill entrance / Round 1)
        self._both_next()
        s1 = self.room.canvas_state(1)
        # Queue pre-declaration: execute special_place right at Round 2's after_dice_use!
        self.room.prepare(
            1,
            {
                "event": "timing",
                "mode": "execute",
                "when": {
                    "turn": 1,
                    "duel_kind": "regular",
                    "duel_number": 1,
                    "round_id": 2,
                    "timing": "after_dice_use",
                },
                "match": {"kind": "special_place", "card_id": "p1_instant_guard"},
            },
            max(0, s1["revision"] - 1),  # Stale-tolerant prepare submission!
            self.next_id(),
        )
        s1_after = self.room.canvas_state(1)
        s2_after = self.room.canvas_state(2)
        self.assertEqual(len(s1_after["declarations"]), 1)
        self.assertEqual(s2_after["declarations"], [], "Opponent must NEVER see Seat 1's queued pre-declaration!")

        # Simply step beats normally — Room automatically executes P1's placement right after Die 2 finishes!
        for _ in range(15):
            cur = self.room.canvas_state(1)
            if any(e["kind"] == "dice_clash" for e in cur["fx_events"]):
                break
            self._both_next()

        final_s1 = self.room.canvas_state(1)
        self.assertEqual(final_s1["declarations"], [], "Consumed one-shot pre-declaration must clear!")
        clashes = [e for e in final_s1["fx_events"] if e["kind"] == "dice_clash"]
        self.assertEqual(len(clashes), 1)
        by_side = {sd["side"]: sd for sd in clashes[0]["sides"]}
        self.assertEqual((by_side[1]["card_id"], by_side[1]["die_number"]), ("p1_instant_guard", 1))
        self.assertEqual((by_side[2]["card_id"], by_side[2]["die_number"]), ("p2_triple_strike", 3))

    def test_pvp_time_bank_preserves_multistep_combo_and_auto_resumes_on_timeout(self):
        self.room.pause_bank_limit = 0.12
        self._setup_pvp_3die_duel()
        self.room._pause_bank = {1: 0.12, 2: 0.12}

        s1 = self.room.canvas_state(1)
        self.room.pause(1, s1["revision"], self.next_id())
        paused = self.room.canvas_state(1)
        self.assertEqual(paused["paused_by"], 1)
        self.assertIsNotNone(paused["pause_remaining_ms"])

        # Step 1 while paused: place `p1_instant_guard` -> Seat 1 STILL has `p1_instant_swap` (replace) available,
        # so `paused_by` MUST remain 1 for combo follow-up!
        place_move = next(m for m in paused["options"] if m["kind"] == "special_place" and m["card_id"] == "p1_instant_guard")
        self.room.act(1, place_move["id"], paused["revision"], self.next_id())
        after_step1 = self.room.canvas_state(1)
        self.assertEqual(after_step1["paused_by"], 1, "Pause must hold when follow-up special action (replace) remains!")
        self.assertTrue(any(m["kind"] == "special_replace" and m["card_id"] == "p1_instant_swap" for m in after_step1["options"]))

        # Wait for the 0.12s Time Bank to expire -> Room auto-resumes and exhausts Seat 1's pause bank for this turn!
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and self.room.canvas_state(1)["paused_by"] is not None:
            time.sleep(0.02)
        resumed = self.room.canvas_state(1)
        self.assertIsNone(resumed["paused_by"], "Time bank expiry must automatically resume the PvP room!")
        self.assertFalse(resumed["can_pause"], "Exhausted turn time bank must prevent pause spam until next turn!")


if __name__ == "__main__":
    unittest.main()
