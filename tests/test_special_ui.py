import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from battle_ui.match import BattleMatch, StaleActionError
from models.card import Card
from special_actions_cli import offer_actions


class SpecialTableTests(unittest.TestCase):
    def setUp(self):
        self.output = self.enterContext(redirect_stdout(io.StringIO()))
        self.table = BattleMatch(("ember_wen_sheng", "plan_b_annolin"), seed=37)
        self.state = self.table.snapshot()
        self.until(lambda: self.state["mode"] == "placement")
        self.assertEqual(self.state["active_side"], 1)

    def play(self, action, **fields):
        self.state = self.table.act(action, self.state["revision"], **fields)

    def until(self, predicate):
        for _ in range(400):
            if predicate():
                return
            mode = self.state["mode"]
            if mode == "placement":
                self.play("end")
            elif mode == "handoff":
                self.play("ready")
            elif mode in ("pre_attack", "intercept"):
                self.play("end_attack" if self.state["can_end_attack"] else "let_through")
            else:
                self.play("next")
        self.fail("未到达指定时点")

    def private(self, side):
        if self.state["mode"] != "special_handoff":
            self.play("open_special")
        self.assertEqual(self.state["special_options"], [])
        self.assertTrue(all(p["hand"] is None for p in self.state["frame"]["players"]))
        self.play("ready", side=side)
        self.assertEqual(self.state["frame"]["viewer_side"], side)

    def use(self, kind, card_id=None):
        index = next(n for n, a in enumerate(self.state["special_options"])
                     if a["kind"] == kind and a["card_id"] == card_id)
        self.play("use_special", option=index)

    def interceptable_attack(self, name):
        player = self.table.game.players[0]
        owner = player.characters[0]
        card = Card(player, dict(id=name, name=name, cost=1, dice=[],
                                 anytime_play=["attack"], interceptable=True), owner)
        owner.skills.append(card)
        player.cardspace.hand.add_card(card)
        return card

    def test_explicitly_interceptable_attack_resumes_placement_and_rejects_stale_response(self):
        probe = self.interceptable_attack("可迎击的场内技能")
        self.private(1)
        self.use("attack", probe.id)
        self.assertTrue(self.state["special_pending"])
        self.assertEqual(self.state["eligible_sides"], [2, 1])
        with self.assertRaises(ValueError):
            self.play("leave_special")
        self.play("ready", side=1)
        self.assertFalse(any(a["kind"] == "pass_intercept" for a in self.state["special_options"]))
        self.play("switch_side")
        self.private(2)
        revision = self.state["revision"]
        self.use("pass_intercept")
        with self.assertRaises(StaleActionError):
            self.table.act("use_special", revision, option=0)
        self.assertEqual(self.state["frame"]["combat"]["kind"], "instant")
        self.assertEqual(len(self.state["frame"]["special_duels"]), 1)
        self.until(lambda: self.state["mode"] == "handoff")
        self.assertTrue(all(p["hand"] is None for p in self.state["frame"]["players"]))
        self.play("ready")
        self.assertEqual((self.state["mode"], self.state["active_side"], self.state["window_remaining"]),
                         ("placement", 1, 1))
        self.assertNotIn(probe.id, self.state["legal_cards"])

    def test_flying_entrance_resolves_without_interception_and_resumes_suspended_skill(self):
        self.play("place", card_id="wen_sheng_call")
        self.until(lambda: self.state["special_timing"] == "技能使用前，可换卡")
        before = self.state["frame"]["combat"]
        self.assertEqual(before["kind"], "regular")
        self.private(1)
        printed = next(c for c in self.state["frame"]["players"][0]["hand"] if c["id"] == "wen_sheng_entrance")
        self.assertTrue(printed["interceptable"])
        self.assertFalse(printed["instant_interceptable"])
        self.use("attack", "wen_sheng_entrance")
        self.assertFalse(self.state["special_pending"])
        public_slot = self.state["frame"]["special_duels"][0]
        self.assertTrue(public_slot["ready"])
        self.assertFalse(public_slot["interceptable"])
        self.assertEqual(self.state["frame"]["combat"]["kind"], "instant")
        self.private(2)
        self.assertFalse(any(a["kind"] in ("intercept", "pass_intercept") for a in self.state["special_options"]))
        self.play("leave_special")
        self.until(lambda: self.state["frame"]["combat"] and self.state["frame"]["combat"]["kind"] == "regular")
        self.assertEqual(self.state["frame"]["combat"], before)
        self.assertEqual(self.state["special_timing"], "技能使用前，可换卡")
        self.assertTrue(any("使用 飞场" in line for line in self.state["history"]))

    def test_pre_use_opportunity_is_selectable_and_the_underlying_phase_resumes(self):
        self.play("place", card_id="wen_sheng_call")
        self.until(lambda: self.state["special_timing"] == "技能使用前，可换卡")
        self.private(1)
        self.use("replace", "wen_sheng_duet")
        player = self.table.game.players[0]
        self.assertIn("点名上场", [card.name for card in player.cardspace.hand.content])
        self.assertEqual(player.characters[0].statuses.get("换卡机会", 0), 0)
        self.assertEqual(self.state["mode"], "timing")
        self.assertFalse(self.state["special_options"])
        self.until(lambda: any("使用 对手戏" in event for event in self.state["history"]))

    def test_cli_chooses_an_action_privately_and_preserves_placement(self):
        game = self.table.game
        actor = game.players[0]
        options = game.special.options(actor)
        index = next(n for n, a in enumerate(options, 1) if a.kind == "place")
        with patch("builtins.input", side_effect=["1", str(index), ""]):
            offer_actions(game)
        self.assertEqual(game.duelspace.space[0].get_content(1)[0].name, "飞场")
        self.assertEqual(actor.characters[0].used_duels, 1)
        self.assertIs(game.placing, actor)
        self.assertIsNone(game._private_player)

    def test_cli_default_field_attack_enters_combat_without_a_response_prompt(self):
        game = self.table.game
        actor = game.players[0]
        index = next(n for n, a in enumerate(game.special.options(actor), 1)
                     if a.kind == "attack" and a.card.id == "wen_sheng_entrance" and a.character)
        with patch("builtins.input", side_effect=["1", str(index)]):
            offer_actions(game)
        self.assertIsNotNone(game.pipeline.interrupt_space)
        self.assertFalse(game.special.pending_attacks)
        self.assertIs(game.placing, actor)

    def test_two_pending_attacks_can_be_answered_in_reverse_before_advancing(self):
        first = self.interceptable_attack("可迎击之一")
        second = self.interceptable_attack("可迎击之二")
        self.private(1)
        self.use("attack", first.id)
        self.private(1)
        self.use("attack", second.id)
        self.private(2)
        moves = self.state["special_options"]
        self.assertEqual([a["response_number"] for a in moves if a["kind"] == "pass_intercept"], [1, 2])
        index = next(n for n, a in enumerate(moves) if a["kind"] == "intercept" and a["response_number"] == 2)
        self.play("use_special", option=index)
        self.assertEqual([s["ready"] for s in self.state["frame"]["special_duels"]], [False, True])
        self.assertIsNone(self.state["frame"]["combat"])
        self.private(2)
        self.use("pass_intercept")
        self.assertEqual(self.state["frame"]["combat"]["duel_number"], 1)

    def test_full_regular_quota_hides_special_slot_placement_even_with_permission(self):
        owner = self.table.game.players[0].characters[0]
        owner.add_status("置卡机会", 1)
        owner.used_duels = owner.max_duels
        self.private(1)
        self.assertFalse(any(a["kind"] == "place" for a in self.state["special_options"]))
        self.assertTrue(any(a["kind"] == "attack" and a["card_id"] == "wen_sheng_entrance"
                            for a in self.state["special_options"]))
