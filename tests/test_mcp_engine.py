import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from battle_mcp.engine import ArenaEngine
from models.duel import ClashPair


class FixedSeatTableTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))

    def at_placement(self, left, seed):
        self.table = ArenaEngine((left, "plan_b_annolin"), seed)
        self.assertEqual(self.table.event["kind"], "setup")
        self.assertTrue(all(p["hand_count"] == 0 for p in self.table.state()["players"]))
        self.until(lambda: bool(self.table.required_sides()))

    def until(self, ready):
        for _ in range(600):
            if ready():
                return
            self.table.advance()
        self.fail("没有到达预期时点")

    def play(self, side, kind, **fields):
        move = next(a for a in self.table.options(side)
                    if a["kind"] == kind and all(a.get(k) == v for k, v in fields.items()))
        return self.table.apply(side, move)

    def test_attack_right_and_multiple_defence_choices_are_independent(self):
        self.at_placement("mistport_cen_yao", 37)
        public = self.play(1, "place", card_id="cen_yao_fold_rule")
        self.assertNotIn("card_id", public)
        self.assertNotIn("折尺", public["text"])
        with self.assertRaises(ValueError):
            self.table.advance()
        with self.assertRaises(ValueError):
            self.table.apply(1, next(a for a in self.table.options(2) if a["kind"] == "place"))
        reserved = self.table.state(2)["players"][1]["hand"][0]["id"]
        self.play(2, "place", card_id=reserved)
        self.play(2, "end")
        self.play(1, "end")
        self.until(lambda: self.table.event["kind"] == "pre_reveal")
        for skill in ("cen_yao_sounding", "cen_yao_transit"):
            self.play(1, "attack", card_id=skill, duel_number=1)
        self.assertEqual(self.table.required_sides(), [1, 2])
        self.assertEqual([a["response_number"] for a in self.table.options(2)
                          if a["kind"] == "let_through"], [1, 2])
        self.play(2, "intercept", response_number=2)
        self.play(1, "end_attack")
        view = self.table.state()
        self.assertEqual(view["duels"][0]["sides"][1]["cards"], [{"hidden": True}])
        self.assertEqual([d["ready"] for d in view["pre_reveal"]["duels"]], [False, True])
        self.assertIsNone(view["response_times"][0]["answered_at_ms"])
        self.assertTrue(all(p["hand"] is None for p in view["players"]))
        self.assertEqual(self.table.options(None), [])
        self.assertIsNone(self.table.state(1)["players"][1]["hand"])
        self.assertIsNone(self.table.state(2)["players"][0]["hand"])

    def test_settled_scores_allow_a_blank_round_without_repeating_score_effects(self):
        self.at_placement("ember_wen_sheng", 1125)
        self.play(1, "place", card_id="wen_sheng_duet")
        self.play(2, "place", card_id="annolin_drifting_sword")
        self.play(2, "end")
        self.play(1, "end")
        original = ClashPair.clash_check
        with patch.object(ClashPair, "clash_check", autospec=True, side_effect=original) as resolutions:
            self.until(lambda: self.table.event["kind"] == "roll")
            self.assertEqual(len(self.table.event["rolls"]), 2)
            self.assertNotIn("scores", self.table.event)
            self.assertEqual(resolutions.call_count, 0)
            self.until(lambda: self.table.event["kind"] == "scores_ready")
            self.assertTrue(all(isinstance(s, int) for s in self.table.event["scores"]))
            self.assertFalse(self.table.game.pipeline.current_clash_results)
            self.play(1, "special_replace", card_id="wen_sheng_understudy", target_card_id="wen_sheng_duet")
            self.assertEqual(self.table.event["kind"], "action")
            self.until(lambda: bool(self.table.game.pipeline.current_clash_results))
            self.assertEqual(self.table.game.pipeline.current_clash_results, {2: "win"})
            self.assertEqual(resolutions.call_count, 1)
