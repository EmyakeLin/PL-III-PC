import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from battle_mcp.room import Room
from bots.lan_qing import DANCE, FAMILIES, LEAF, LIGHT, SPIKE, _Turn, _use_face, choose_move, play_seat


class LanQingDecisions(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        room = Room(("plan_b_annolin", "lan_qing"), seed=4)
        self.addCleanup(room.close)
        for seat in (1, 2):
            room.ready(seat, room.observe(seat)["revision"], f"ready-{seat}")
        self.frame = room.observe(2)["frame"]
        self.other, self.own = self.frame["players"]
        self.actor, = self.own["characters"]
        pack = Path(__file__).resolve().parents[1] / "_packs" / "jingzhi_lan_qing.json"
        skills = json.loads(pack.read_text(encoding="utf-8"))["characters"][0]["skills"]
        self.cards = {c["id"]: {"id": c["id"], "instance_id": i, "cost": c["cost"],
                                "character_id": self.actor["id"]} for i, c in enumerate(skills)}

    def place(self, *keys):
        self.own["hand"] = [self.cards[k] for k in keys]
        moves = [{"kind": "place", "card_id": k} for k in keys] + [{"kind": "end"}]
        return choose_move(self.frame, moves).get("card_id")

    def test_six_cost_can_prime_ultimate_and_five_cost_cannot(self):
        self.assertEqual(self.place("lan_light", "lan_end"), "lan_end")
        self.own["cost"]["available"] -= 1
        self.assertEqual(self.place("lan_light", "lan_end"), "lan_light")

    def test_starters_precede_their_payoffs_in_either_hand_order(self):
        for starter, finisher in (("lan_open", "lan_dance_3"), ("lan_turn", "lan_spike_3"),
                                  ("lan_close", "lan_leaf_3")):
            self.assertEqual(self.place(finisher, starter), starter)
            self.assertEqual(self.place(starter, finisher), starter)

    def test_shared_charge_and_both_ultimate_branches_in_the_projection(self):
        active = set()
        for key in ("lan_open", "lan_open", "lan_turn"):
            _use_face(key, active)
        self.assertEqual(active, {DANCE, SPIKE})
        self.assertTrue(_use_face("lan_light", active))
        self.assertEqual(active, set())
        _use_face("lan_end", active)
        self.assertEqual(active, {LIGHT})
        self.assertTrue(_use_face("lan_light", active))
        self.assertEqual(active, FAMILIES)
        self.assertTrue(_use_face("lan_spike_2", active))
        self.assertFalse(_use_face("lan_spike_3", active))
        self.assertEqual(active, {DANCE, LEAF})
        active = {LEAF}
        self.assertFalse(_use_face("lan_light", active))
        self.assertEqual(active, FAMILIES)

    def test_score_reads_the_public_infusion_bonus(self):
        turn = _Turn(self.frame)
        play = [self.cards["lan_end"]]
        base = turn.score(play)
        self.actor["passive_values"]["涌流灌注"] = 2
        self.assertAlmostEqual(turn.score(play) - base, 0.7)

    def test_skips_lethal_self_payment_even_when_a_third_hand_play_would_heal_next_turn(self):
        self.frame["duels"] = [self.slot(1, "lan_end"), self.slot(2, "lan_dance_2")]
        self.actor["duels"]["used"] = 2
        self.actor["hp"] = 2
        self.assertEqual(self.place("lan_open"), "lan_open")
        self.actor["hp"] = 1
        self.assertIsNone(self.place("lan_open"))

    def test_shock_favors_three_hits_over_the_single_high_power_die(self):
        self.actor["duels"]["max"] = 1
        self.actor["statuses"] = {DANCE: 1, SPIKE: 1}
        self.assertEqual(self.place("lan_dance_3", "lan_spike_3"), "lan_spike_3")
        self.other["characters"][0]["statuses"]["电击"] = 4
        self.assertEqual(self.place("lan_dance_3", "lan_spike_3"), "lan_dance_3")

    def slot(self, number, key):
        return {"number": number, "sides": [{"side": 1, "cards": [{"hidden": True}]},
                                            {"side": 2, "cards": [self.cards[key]]}]}

    def test_intercept_only_if_it_preserves_a_more_valuable_committed_ultimate(self):
        self.own["hand"] = [self.cards["lan_turn"]]
        self.frame["duels"] = [self.slot(1, "lan_light")]
        self.frame["pre_reveal"]["duels"] = [{
            "number": 1, "attacking_side": 1, "target": {"kind": "character", "name": "澜清"},
            "sides": [{"side": 1, "cards": [{"id": "attack", "cost": 3}]}, {"side": 2, "cards": []}],
        }]
        moves = [{"kind": "intercept", "card_id": "lan_turn", "response_number": 1},
                 {"kind": "let_through", "response_number": 1}]
        self.assertEqual(choose_move(self.frame, moves)["kind"], "let_through")
        self.own["cost"]["available"] += 1
        self.assertEqual(choose_move(self.frame, moves)["kind"], "intercept")

    def test_discard_protects_a_primed_ultimate_and_uses_the_offered_entity(self):
        self.actor["statuses"] = {LIGHT: 1}
        self.own["hand"] = [self.cards["lan_light"], dict(self.cards["lan_open"], action_key="instance:42")]
        moves = [{"kind": "special_choose_card", "target_card_id": key} for key in ("lan_light", "instance:42")]
        self.assertIs(choose_move(self.frame, moves), moves[1])


class LanQingRoomTests(unittest.TestCase):
    def test_scripted_seat_waits_for_human_and_plays_to_result(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        room = Room(("plan_b_annolin", "lan_qing"), seed=8)
        self.addCleanup(room.close)
        priority = ("place", "attack", "intercept", "let_through", "end_attack", "end")
        wait = room.wait
        actions = []

        def opponent_acts(side, cursor, timeout):
            self.assertLess(len(actions), 500)
            view = room.observe(1)
            self.assertIn(2, view["ready_sides"])
            self.assertIsNone(view["frame"]["players"][1]["hand"])
            if 1 not in view["ready_sides"]:
                room.ready(1, view["revision"], "human")
                actions.append("ready")
            else:
                move = min(view["options"], key=lambda m: priority.index(m["kind"]) if m["kind"] in priority else 99)
                room.act(1, move["id"], view["revision"], f"human-{len(actions)}")
                actions.append(move["kind"])
            return wait(side, cursor, 0)

        with patch.object(room, "wait", side_effect=opponent_acts):
            winner = play_seat(room, 2)
        view = room.observe(1)
        self.assertTrue(view["finished"])
        self.assertIn("place", actions)
        self.assertEqual(winner, view["winner_side"])
