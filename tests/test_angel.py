import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game import Game
from entry.commands import expand_command
from loader import load_characters_from_packs
from models.card import Card
from models.opcode import OpCode
from player.player import Player


class PrintedDeckSizeTests(unittest.TestCase):
    def test_explicit_regular_size_excludes_out_of_combat_cards(self):
        character = dict(id="example", name="样例牌组", rank="EMPOWERED_BOSS", max_hp=15,
                         skills=[dict(id=str(i), name=str(i), cost=1, dice=[], out_of_combat=i >= 7)
                                 for i in range(9)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.json"
            for count, valid in [(None, False), (7, True), (8, False), (True, False)]:
                with self.subTest(count=count):
                    if count is not None:
                        character["regular_skill_count"] = count
                    path.write_text(json.dumps(dict(characters=[character])), encoding="utf-8")
                    if valid:
                        self.assertEqual(len(load_characters_from_packs(directory)[0]["skills"]), 9)
                    else:
                        with self.assertRaises(ValueError):
                            load_characters_from_packs(directory)


class AngelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = next(spec for spec in load_characters_from_packs() if spec["id"] == "angel")

    def setUp(self):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right])
        self.game.first_player = self.left
        dummy = dict(id="dummy", name="陪练", rank="NORMAL", max_hp=15, skills=[])
        self.game.deploy_rosters([[self.spec], [dummy]])
        self.actor, self.enemy = self.left.characters[0], self.right.characters[0]
        self.ctx = self.game.context
        self.cards = {card.name: card for card in self.actor.skills}

    def distribute(self, mark, amount):
        self.actor.rule_state["光暗转移中"] = True
        try:
            self.actor.add_status(mark, -amount)
            self.enemy.add_status(mark, amount)
        finally:
            self.actor.rule_state["光暗转移中"] = False

    def play(self, card, choose=None, opponent=None):
        self.game.start_turn()
        self.left.turn_cost_adjustment += 12
        self.game.place_in_duel(1, self.cards[card], 0)
        if opponent:
            self.game.place_in_duel(2, opponent, 0)
        self.game.pipeline.start_duel_combat()
        for _ in range(800):
            player = self.game.special.decision_owner
            if player:
                options = self.game.special.options(player)
                answer = choose(options) if choose else next(
                    (opt for opt in options if opt.kind == "decline_option"), options[0])
                self.game.special.apply(player, answer)
            elif self.game.pipeline.in_duel_phase and not self.game.is_over:
                self.game.pipeline.step_duel_combat()
            else:
                return
        self.fail("交锋没有结束")

    def test_distribution_transfer_bonus_and_physical_fallback(self):
        self.distribute("暗涌", 3)
        die = self.cards["光影乱流"].get_current_die(self.game)
        for n, expected in enumerate((6, 5, 4, 0)):
            before = self.enemy.lightcore_hp
            self.ctx.resolve_hit(die, self.enemy)
            self.assertEqual(before - self.enemy.lightcore_hp, expected)
            self.assertEqual(self.actor.statuses.get("光涌", 0), max(2 - n, 0))
        # Three quarters of 24 have not been lost; 15 actual loss crosses two.
        self.assertEqual(self.enemy.exact_hp, 11)
        self.enemy.add_status("光涌", -2)
        self.assertEqual(self.actor.statuses["光涌"], 2)

    def test_collapse_triggers_separate_fractional_packets_and_resets(self):
        with self.ctx.collect_facts() as facts:
            self.ctx.eval_block([self.enemy, 24, OpCode.LIGHTCORE_DAMAGE])
        self.assertEqual([v["amount"] for k, v in facts if k == "direct_damage"], [1.5] * 3)
        self.assertEqual(self.enemy.max_lightcore_hp, 20)
        self.ctx.eval_block([self.enemy, 5, OpCode.LIGHTCORE_DAMAGE])
        self.assertEqual(self.enemy.rule_state["光点解构次数"], 1)

    def test_reveal_overflow_and_dance_exit(self):
        self.actor.add_status("灰界", 8)
        self.actor.hp = 6
        for expected in (5, 7, 8, 8):
            self.ctx.dispatch_pipeline("on_reveal")
            self.assertEqual(self.actor.rule_state["光暗上限"], expected)
            self.assertEqual(self.actor.statuses["光涌"], expected)
            self.assertEqual(self.actor.statuses["暗涌"], expected)
        self.assertEqual((self.actor.hp, self.actor.statuses["灰界"]), (9, 8))
        self.actor.add_status("灰界", -2)
        self.game.start_turn()
        self.ctx.dispatch_pipeline("on_turn_start")
        self.assertEqual({c.name for c in self.left.cardspace.hand.content}, {"黑暗笼中", "烁光幻灭"})
        self.ctx.dispatch_pipeline("on_turn_end")
        self.assertEqual(self.actor.statuses["灰界"], 4)
        self.ctx.dispatch_pipeline("on_turn_prepared")
        self.assertFalse(self.actor.statuses.get("黑白共舞"))

    def test_cage_cancels_even_an_empty_hit_and_refunds_reserved_dark(self):
        cage = self.cards["黑暗笼中"]
        self.ctx.dispatch_pipeline("on_skill_use", source=self.actor, target=self.enemy, card=cage)
        self.assertEqual(self.actor.statuses.get("暗涌", 0), 0)
        empty = Card(self.right, dict(id="empty", name="空击", cost=0, dice=[dict(type="slash", level=1)]))
        empty.character = self.enemy
        die = empty.get_current_die(self.game)
        for expected in (2, 1, 0):
            self.assertFalse(self.ctx.resolve_hit(die, self.actor))
            self.assertEqual(self.actor.statuses.get("暗笼", 0), expected)
        self.assertEqual(self.actor.statuses["暗涌"], 3)
        self.assertTrue(self.ctx.resolve_hit(die, self.actor))

    def test_cage_precedes_external_before_hit_passives(self):
        self.enemy.add_status("暗笼", 1)
        self.ctx.register_entries(self.actor, [dict(trigger="before_dice_hit", operation={
            "op": "program", "code": ["$self", "探针", 1, "STATUS"]})])
        with self.ctx.collect_facts() as facts:
            self.play("光影乱流")
        self.assertEqual(len([v for k, v in facts if k == "hit"]), 3)
        self.assertEqual(self.actor.statuses.get("探针"), 3)

    def test_integer_damage_default_and_fractional_shield(self):
        for fractional, expected in ((False, 1), (True, 1.5)):
            self.enemy.concept_shield = 1
            with self.ctx.collect_facts() as facts:
                self.ctx.deal_damage(self.actor, self.enemy, 1.5, "concept", "none", keep_fraction=fractional)
            damage, = [v for k, v in facts if k == "direct_damage"]
            self.assertEqual((damage["amount"], damage["lost"]), (expected, expected - 1))

    def test_blocked_mark_receipt_falls_back_without_surge_bonus(self):
        self.ctx.register_entries(self.enemy, [dict(trigger="BEFORE STATUS", subject="target",
            when=[dict(left="$pending.status", op="eq", right="光涌"),
                  dict(left="$pending.amount", op="gt", right=0)], operation={"op": "cancel"})])
        before = self.enemy.lightcore_hp
        self.ctx.resolve_hit(self.cards["光影乱流"].get_current_die(self.game), self.enemy)
        self.assertEqual((self.enemy.lightcore_hp, self.enemy.hp, self.actor.statuses["光涌"]), (before, 14, 3))

    def test_transformation_removes_multiplier_and_activates_damage_in_order(self):
        card = self.cards["耀光周身"]
        self.distribute("光涌", 2)
        self.ctx.dispatch_pipeline("on_skill_use", card=card, source=self.actor, target=self.enemy)
        self.assertEqual([(d["type"], d["level"], d.get("multiplier", 1)) for d in card.dice],
                         [("slash", 6, 1), ("slash", 6, 1), ("evade", 4, 2), ("evade", 4, 3)])
        self.assertNotIn("2光点", card.dice[0]["entries"])
        self.assertIn("2光点", card.dice[1]["entries"])
        card.reset_for_draw()
        self.assertEqual([d["type"] for d in card.dice], ["evade"] * 4)

    def test_all_nine_cards_pay_and_resolve_from_a_duel(self):
        for name, cost, hits in (("灰界覆盖", 1, 1), ("光华幻形", 2, 1), ("取暗弃光", 2, 2),
                                 ("暗影凝集", 2, 1), ("耀光周身", 3, 0), ("光影乱流", 3, 4),
                                 ("至暗冬韵", 4, 4), ("黑暗笼中", 2, 1), ("烁光幻灭", 6, 2)):
            with self.subTest(name=name):
                self.setUp()
                with self.ctx.collect_facts() as facts:
                    self.play(name)
                payment, = [v for k, v in facts if k == "skill_payment"]
                self.assertEqual((payment["paid"], payment["cost"]), (True, cost))
                self.assertEqual(sum(k == "hit" for k, _ in facts), hits)

    def test_dance_winter_extra_hits_count_only_four_dice(self):
        self.actor.add_status("灰界", 6)
        with self.ctx.collect_facts() as facts:
            self.play("至暗冬韵")
        self.assertEqual([v["mode"] for k, v in facts if k == "hit"],
                         ["full", "full", "full", "damage_only", "damage_only", "damage_only", "full"])
        self.assertEqual(self.actor.statuses["灰界"], 2)
        self.assertEqual(len(self.ctx.scheduled_effects), 2)

    def test_solo_reroll_twice_on_one_die(self):
        def choose(options):
            return next(opt for opt in options if opt.option_id == "reroll")

        with patch.object(self.game.rng, "randint", return_value=2), self.ctx.collect_facts() as facts:
            self.play("光影乱流", choose)
        attacks = [event for kind, event in facts if kind == "solo_attack"]
        self.assertEqual([e["final_score"] for e in attacks], [4, 2, 2, 2])
        self.assertEqual(self.actor.turn_state["与暗争变已用"], 2)

    def training_card(self, dice, **extra):
        return Card(self.right, dict(id="training", name="对照", cost=0, dice=dice, **extra), self.enemy)

    def test_global_cap_counts_sealed_dark_and_rejects_external_gains(self):
        self.enemy.add_status("光涌", 1)
        self.assertEqual(self.enemy.statuses.get("光涌", 0), 0)
        self.distribute("光涌", 2)
        self.enemy.add_status("光涌", 4)
        self.assertEqual(self.enemy.statuses["光涌"], 2)
        self.ctx.eval_block([self.enemy, "光涌", 9, OpCode.RESTORE_STATUS_STACKS])
        self.assertEqual(self.enemy.statuses["光涌"], 2)
        self.ctx.eval_block([self.enemy, "光涌", 0, OpCode.RESTORE_STATUS_STACKS])
        self.assertEqual(self.actor.statuses["光涌"], 3)
        self.ctx.dispatch_pipeline("on_skill_use", source=self.actor, target=self.enemy, card=self.cards["黑暗笼中"])
        self.enemy.add_status("暗涌", 1)
        self.assertEqual(self.enemy.statuses.get("暗涌", 0), 0)
        self.actor.clear_status("暗笼")
        self.assertEqual(self.actor.statuses["暗涌"], 3)

    def test_speed_difference_applies_to_borrowed_card_and_caps_at_three(self):
        borrowed = Card(self.left, dict(id="borrowed", name="借牌", cost=0, dice=[dict(type="slash", level=1)]), self.actor)
        foe = self.training_card([dict(type="pierce", level=1)], range_level=3)
        die = borrowed.get_current_die(self.game)
        self.enemy.speed = 5
        for active in (False, True):
            self.actor.add_status("黑白共舞", int(active))
            for difference in (-3, 0, 1, 2, 4, 6, 8):
                with self.subTest(active=active, difference=difference):
                    self.actor.speed = self.enemy.speed + difference
                    total = min(3, int(active) + max(0, difference // 2))
                    self.assertEqual(borrowed.range_ignored(borrowed.data, foe), total)
                    self.assertEqual(die.resolve_value(OpCode.RESOLVE_FINAL_SCORE, 4, target=self.enemy), 4 + total)

    def test_current_ranged_disadvantage_samples_only_this_roll(self):
        card = self.cards["光影乱流"]
        die = card.get_current_die(self.game)
        rival = self.training_card([dict(type="slash", level=1)], range_level=3)
        enemy_die = rival.get_current_die(self.game)
        self.ctx.active_cards[self.left.side] = card
        self.ctx.dispatch_pipeline("before_dice_clash", source=self.actor, target=self.enemy,
                                   card=card, die=die, opponent_die=enemy_die)
        self.assertEqual(die.final_bonus, 3)
        with patch.object(self.game.rng, "randint", side_effect=[4, 1, 3]) as sample:
            self.assertEqual(enemy_die.roll(clash=True), 1)
            following = self.training_card([dict(type="slash", level=1)]).get_current_die(self.game)
            self.assertEqual(following.roll(clash=True), 3)
            self.assertEqual(sample.call_count, 3)
        self.assertFalse(self.enemy.ability_effects)

    def test_immediate_disadvantage_offsets_advantage_and_preserves_disadvantage(self):
        die = self.training_card([dict(type="slash", level=1)]).get_current_die(self.game)
        die.use_state["本次劣势"] = True
        for ability, rolls, expected, remaining in (("优势次数", [4], 4, 1), ("劣势次数", [4, 2], 2, 2)):
            with self.subTest(ability=ability):
                self.enemy.ability_effects.clear()
                self.ctx.eval_block([self.enemy, ability, 2, OpCode.ABILITY_EFFECT])
                with patch.object(self.game.rng, "randint", side_effect=rolls) as sample:
                    self.assertEqual(die.roll(clash=True), expected)
                    self.assertEqual(sample.call_count, len(rolls))
                self.assertEqual(self.enemy.ability_effects[ability], remaining)

    def test_cardwide_choice_and_shadow_independent_rewards(self):
        self.distribute("暗涌", 1)
        def swap(options):
            return next((o for o in options if o.option_id == "swap"),
                        next((o for o in options if o.kind == "decline_option"), options[0]))
        self.play("灰界覆盖", swap)
        self.assertEqual(self.actor.statuses["暗涌"], 3)
        self.assertEqual(self.enemy.statuses["光涌"], 2)
        self.setUp()
        self.distribute("光涌", 2)
        self.play("暗影凝集")
        self.assertEqual(self.left.next_turn_common_cost, 2)
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual((self.left.max_cost, self.actor.ability_effects["置卡机会"]), (7, 1))
        self.game.finish_turn()
        self.game.start_turn()
        die = self.cards["取暗弃光"].get_current_die(self.game)
        with patch.object(self.game.rng, "randint", return_value=1):
            die.roll()
        self.assertEqual(die.value, 3)

    def test_cage_opportunity_remains_flexible_and_dark_is_reserved(self):
        self.distribute("暗涌", 2)
        self.play("黑暗笼中")
        self.assertEqual(self.actor.ability_permission("place"), "置卡或换卡机会")
        self.assertEqual(self.actor.ability_permission("replace"), "置卡或换卡机会")
        self.assertEqual(self.actor.ability_effects["置卡或换卡机会"], 1)
        self.assertEqual(self.actor.rule_state["暗笼封存"], 1)
        self.assertEqual(self.actor.statuses["暗涌"], 2)
        self.assertIn(self.cards["黑暗笼中"], self.left.cardspace.hand.content)

    def test_finisher_discount_protection_and_extra_collapse(self):
        card = self.cards["烁光幻灭"]
        self.actor.add_status("灰界", 8)
        for _ in range(3):
            self.ctx.dispatch_pipeline("on_reveal")
        self.distribute("暗涌", 4)
        self.enemy.lightcore_hp = 8
        self.enemy.hp = 15
        with self.ctx.collect_facts() as facts:
            self.play(card.name)
        payment, = [v for k, v in facts if k == "skill_payment"]
        self.assertEqual(payment["cost"], 5)
        self.assertEqual(self.enemy.max_lightcore_hp, 16)
        light, = [v for k, v in facts if k == "lightcore_damage" and v.get("lightcore_type") == "光破"]
        self.assertEqual(light["attribute"], "光")
        self.assertTrue(card.instantiated_dice[-1].use_state["幻灭最高权"])
        self.assertEqual(self.actor.statuses["灰界"], 2)

    def test_first_finisher_die_only_protects_the_selected_next_die(self):
        card = self.cards["烁光幻灭"]
        foe = self.training_card([dict(type="slash", level=1)], range_level=3)
        self.ctx.active_cards[self.left.side] = card
        first = card.get_current_die(self.game)
        self.assertEqual(card.paired_ranges(foe), (0, 3))
        self.ctx.dispatch_pipeline("on_dice_hit", source=self.actor, target=self.enemy, card=card, die=first)
        protected = card.use_state["幻灭下骰"]
        self.assertFalse(self.ctx.eval_block([protected, OpCode.DESTROY]))
        card.advance_die()
        self.assertEqual(card.paired_ranges(foe), (0, 0))
        self.assertTrue(self.ctx.eval_block([foe.get_current_die(self.game), OpCode.DESTROY]))

    def test_finisher_checks_six_light_on_use_then_keeps_authority(self):
        for light in (5, 6):
            with self.subTest(light=light):
                self.setUp()
                self.actor.add_status("灰界", 8)
                self.ctx.dispatch_pipeline("on_reveal")
                self.ctx.dispatch_pipeline("on_reveal")
                self.distribute("光涌", 7 - light)
                card = self.cards["烁光幻灭"]
                foe = self.training_card([dict(type="slash", level=1)])
                first = card.get_current_die(self.game)
                self.ctx.dispatch_pipeline("on_dice_hit", source=self.actor, target=self.enemy, card=card, die=first)
                card.advance_die()
                last = card.get_current_die(self.game)
                self.ctx.dispatch_pipeline("before_dice_use", source=self.actor, target=self.enemy, side=1, card=card, die=last)
                self.ctx.register_entries(self.enemy, [dict(trigger="BEFORE DESTROY", subject="any",
                    authority="较高话语权", operation={"op": "cancel"})])
                self.ctx.dispatch_pipeline("on_dice_hit", source=self.actor, target=self.enemy,
                                           card=card, die=last, opponent_card=foe)
                self.assertEqual(foe.destroyed, light == 6)
                self.assertEqual(self.actor.statuses.get("光涌", 0), 0)

    def test_dance_third_reroll_reuses_the_opposing_score(self):
        self.actor.add_status("灰界", 6)
        face = dict(type="slash", level=4)
        own = Card(self.left, dict(id="test", name="测试", cost=0, dice=[face]), self.actor)
        self.cards["测试"] = own
        opponent = self.training_card([face])
        choose = lambda choices: next(o for o in choices if o.option_id == "reroll")
        with patch.object(self.game.rng, "randint", side_effect=[1, 9, 2, 3, 8]) as rolls:
            self.play("测试", choose, opponent)
        self.assertEqual(rolls.call_count, 5)
        self.assertEqual(opponent.instantiated_dice[0].clash_score, 9)
        self.assertEqual(own.instantiated_dice[0].final_score, 12)
        self.assertEqual(self.actor.turn_state["与暗争变已用"], 3)

    def test_collapse_count_stays_used_when_the_current_maximum_increases(self):
        for amount, increase in ((6, 40), (8, 0), (50, 0)):
            self.ctx.eval_block([self.enemy, amount, OpCode.LIGHTCORE_DAMAGE])
            self.ctx.eval_block([self.enemy, increase, OpCode.CHANGE_LIGHTCORE_MAX])
            if increase:
                self.ctx.eval_block([self.enemy, increase, OpCode.HEAL_LIGHTCORE])
        # This bar lost 64 overall, so it collapsed. The three triggers cost 4.5 HP.
        self.assertEqual(self.enemy.exact_hp, 2.5)

    def test_surge_transfer_builtin_matches_expansion_and_returns_accepted_amount(self):
        command = "TRANSFER_STATUS $self $event.target 外部标记 7"
        for code in ([command], expand_command(command)):
            self.actor.add_status("外部标记", 2)
            entry, = self.ctx.register_entries(self.actor, [dict(trigger="试转移", operation={
                "op": "program", "code": ["$self", "实收", *code, "SET_CHARACTER_STATE"]})])
            with self.ctx.collect_facts() as facts:
                self.ctx.dispatch_pipeline("试转移", source=self.actor, target=self.enemy)
            self.assertEqual(self.actor.rule_state["实收"], 2)
            self.assertEqual(self.actor.statuses.get("外部标记", 0), 0)
            self.assertFalse(any(k == "status_spent" for k, _ in facts))
            self.assertEqual(self.enemy.statuses["外部标记"], 2)
            self.ctx.entries.remove(entry)
            self.enemy.clear_status("外部标记")

    def test_equilibrium_damages_before_returning_paired_marks(self):
        self.distribute("光涌", 3)
        self.distribute("暗涌", 1)
        self.ctx.dispatch_pipeline("on_turn_end")
        self.assertEqual((self.actor.hp, self.enemy.hp), (15, 14))
        self.assertEqual((self.actor.statuses["光涌"], self.actor.statuses["暗涌"]), (1, 3))
        self.assertEqual((self.enemy.statuses["光涌"], self.enemy.statuses.get("暗涌", 0)), (2, 0))

    def test_dance_resets_threshold_and_returns_finishers_only_once(self):
        self.actor.add_status("灰界", 6)
        self.game.start_turn()
        self.assertEqual((self.left.max_cost, self.actor.max_duels), (7, 5))
        hand = self.left.cardspace.hand
        self.assertEqual({c.name for c in hand.content}, {"黑暗笼中", "烁光幻灭"})
        decisive = self.cards["黑暗笼中"]
        self.ctx.eval_block([decisive, "draw", OpCode.MOVE_CARD])
        self.ctx.dispatch_pipeline("on_turn_end")
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual((self.left.max_cost, self.actor.max_duels), (5, 4))
        self.actor.add_status("灰界", 2)
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual((self.left.max_cost, self.actor.max_duels), (7, 5))
        self.assertNotIn(decisive, hand.content)
