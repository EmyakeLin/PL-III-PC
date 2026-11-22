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

    def test_private_response_stays_with_current_seat_and_rejects_other_seat(self):
        revision = self.state["revision"]
        with self.assertRaises(ValueError):
            self.table.act("open_special", revision, side=2)
        self.play("open_special", side=1)
        self.assertEqual((self.state["mode"], self.state["frame"]["viewer_side"]), ("special", 1))
        self.play("leave_special")
        self.assertEqual((self.state["mode"], self.state["active_side"]), ("placement", 1))

    def test_automatic_pursuit_names_the_parent_and_returns_before_the_original_hit(self):
        self.table = BattleMatch(("iron_qi_zheng", "plan_b_sa"), seed=2)
        self.state = self.table.snapshot()
        self.play("place", card_id="sa_disintegrate")
        self.play("ready", side=1)
        self.play("place", card_id="qi_zheng_hook")
        self.until(lambda: bool((self.state["frame"]["combat"] or {}).get("suspended")))
        pursuit = self.state["frame"]["combat"]
        self.assertEqual(pursuit["kind"], "instant")
        self.assertEqual(pursuit["suspended"], [{
            "kind": "regular", "duel_number": 1, "side": 1, "card_id": "qi_zheng_hook",
            "card_name": "勾带", "die_position": 2, "source_name": "过身取背",
        }])
        self.assertEqual(pursuit["sides"][0]["card_id"], "qi_zheng_pass")
        self.until(lambda: self.state["special_timing"] == "返回原交锋")
        resumed = self.state["frame"]["combat"]
        self.assertEqual((resumed["kind"], resumed["suspended"]), ("regular", []))
        self.assertEqual((resumed["sides"][0]["node"], resumed["sides"][0]["die"]["position"]),
                         ("before_dice_hit", 2))

    def test_nested_instant_returns_to_the_same_reserved_die_and_then_original_skill(self):
        opponent = self.table.game.players[1]
        extra = Card(opponent, dict(id="应时出击", name="应时出击", cost=0, dice=[],
                                    anytime_play=["attack"]), opponent.characters[0])
        opponent.characters[0].skills.append(extra)
        opponent.cardspace.hand.add_card(extra)
        self.play("place", card_id="wen_sheng_call")
        self.until(lambda: self.state["special_timing"] == "技能使用前，可换卡")
        original = self.state["frame"]["combat"]
        self.private(1)
        self.use("attack", "wen_sheng_entrance")
        self.until(lambda: self.state["special_timing"] == "命中前")
        paused = self.state["frame"]["combat"]
        self.assertEqual((paused["kind"], paused["duel_number"]), ("instant", 1))
        self.private(2)
        self.use("attack", extra.id)
        nested = self.state["frame"]["combat"]
        self.assertEqual((nested["duel_number"], len(nested["suspended"])), (2, 2))
        self.assertEqual(nested["suspended"][-1]["card_name"], "飞场")
        self.until(lambda: self.state["frame"]["combat"]["duel_number"] == 1)
        self.assertEqual(self.state["frame"]["combat"], paused)
        self.assertEqual(self.state["special_timing"], "命中前")
        self.until(lambda: self.state["frame"]["combat"]["kind"] == "regular")
        self.assertEqual(self.state["frame"]["combat"], original)

    def test_pre_use_opportunity_is_selectable_and_the_underlying_phase_resumes(self):
        self.play("place", card_id="wen_sheng_call")
        self.until(lambda: self.state["special_timing"] == "技能使用前，可换卡")
        self.private(1)
        self.use("replace", "wen_sheng_duet")
        player = self.table.game.players[0]
        self.assertIn("点名上场", [card.name for card in player.cardspace.hand.content])
        self.assertEqual(player.characters[0].ability_effects.get("换卡机会", 0), 0)
        self.assertEqual(self.state["mode"], "timing")
        self.assertFalse(self.state["special_options"])
        self.until(lambda: any("使用 对手戏" in event for event in self.state["history"]))

    def test_surprise_stops_on_the_chosen_skills_payment_before_its_first_die(self):
        for seed, card_id, extra_tunnel, paid, required, feedback in (
            (4, "lin_qiu_void_cut", 0, False, 2, "隧道不足（需 2，现有 1）"),
            (8, "lin_qiu_void_cut", 1, True, 2, "实付 2 费、2 隧道"),
            (8, "lin_qiu_draw_blade", 0, True, 0, "实付 0 费"),
        ):
            with self.subTest(card=card_id, extra_tunnel=extra_tunnel):
                self.table = BattleMatch(("nova_lin_qiu", "waa_lake"), seed=seed)
                self.state = self.table.snapshot()
                self.until(lambda: self.state["mode"] == "placement" and self.state["active_side"] == 1)
                self.play("place", card_id="lin_qiu_surprise")
                self.until(lambda: self.state["card_choice"])
                self.assertIs(self.table.game.special.decision_owner, self.table.game.players[0])
                if self.state["mode"] == "special_handoff":
                    self.play("ready", side=1)
                option = next(i for i, move in enumerate(self.state["special_options"])
                              if move.get("target_card_id") == card_id)
                if extra_tunnel:
                    self.table.game.players[0].characters[0].add_status("隧道", extra_tunnel)
                self.play("use_special", option=option)
                self.assertIsNone(self.table.game.special.decision_owner)
                self.until(lambda: any(e["kind"] == "cost_pay" and e["card_id"] == card_id
                                       for e in self.state["fx_events"]))
                payments = [e for e in self.state["fx_events"] if e["kind"] == "cost_pay" and e["card_id"] == card_id]
                self.assertEqual(len(payments), 1)
                payment = payments[0]
                actual = required if paid else 0
                self.assertEqual((payment["paid"], payment["required_cost"], payment["cost"]), (paid, required, actual))
                self.assertEqual((payment["personal_paid"], payment["common_paid"]), (0, actual))
                self.assertEqual(payment["resource_paid"], {"status": "隧道", "amount": 2} if extra_tunnel else None)
                self.assertEqual(payment["failure_reason"], None if paid else feedback)
                self.assertIn(feedback, self.state["history"][-1])
                self.assertEqual(self.state["mode"], "combat")
                combat = self.state["frame"]["combat"]
                self.assertEqual(combat["suspended"][-1]["card_id"], "lin_qiu_surprise")
                side = combat["sides"][0]
                self.assertEqual((side["card_id"], side["node"], side["die"]), (card_id, "logic_skill_use", None))

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
        owner.add_ability_effect("置卡机会", 1)
        owner.used_duels = owner.max_duels
        self.private(1)
        self.assertFalse(any(a["kind"] == "place" for a in self.state["special_options"]))
        self.assertTrue(any(a["kind"] == "attack" and a["card_id"] == "wen_sheng_entrance"
                            for a in self.state["special_options"]))
