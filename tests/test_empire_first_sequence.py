import random
import unittest
from copy import deepcopy
from unittest.mock import patch

from displayer import _card_choice_view
from game import Game
from loader import load_characters_from_packs
from models.card import Card, CardState
from models.opcode import OpCode
from player.player import Player


class FirstSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = next(c for c in load_characters_from_packs() if c["id"] == "empire_first_sequence")

    def deploy(self, enemies=1, spec=None):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(41))
        self.game.first_player = self.left
        dummies = [dict(id=f"dummy_{i}", name=f"陪练{i}", rank="NORMAL", max_hp=17, skills=[])
                   for i in range(enemies)]
        self.game.deploy_rosters([[self.spec if spec is None else spec], dummies])
        self.actor, self.enemy = self.left.characters[0], self.right.characters[0]
        self.ctx = self.game.context
        self.game.start_turn()
        self.cards = {c.name: c for c in self.actor.skills}

    def fire(self, event, card):
        self.ctx.dispatch_pipeline(event, source=self.actor, target=self.enemy, side=1, card=card)

    def end(self):
        self.game.finish_turn()
        self.ctx.dispatch_pipeline("on_turn_end")

    def test_resident_zero_score_draw_and_refill(self):
        for stacks in range(6):
            for enemies in (1, 2):
                with self.subTest(stacks=stacks, enemies=enemies):
                    self.deploy(enemies)
                    self.actor.add_status("崩解", stacks)
                    self.assertIn("崩解", self.actor.statuses)
                    self.game.start_turn()
                    self.assertEqual(self.left.available_cost, 5 + 2 * (enemies == 2) - 2 * (stacks == 4))
                    self.ctx.dispatch_pipeline("on_turn_start")
                    self.assertEqual(len(self.left.cardspace.hand.content), int(stacks < 2))
                    die = self.cards["惩戒"].get_current_die(self.game)
                    self.assertEqual(die.resolve_value(OpCode.RESOLVE_FINAL_SCORE, 3), 3 + max(0, 3 - stacks))
                    self.actor.clear_status("崩解")
                    self.assertEqual(self.actor.statuses["崩解"], 0)
                    self.assertEqual(die.resolve_value(OpCode.RESOLVE_FINAL_SCORE, 3), 6)

    def test_revive_reads_before_healing_and_halves_again(self):
        self.deploy()
        for maximum in (9, 4, 2, 1, 0):
            self.actor.add_status("崩解", 3)
            self.actor.lose_hp(18)
            self.assertTrue(self.actor.is_alive)
            self.assertEqual(self.actor.hp, 0)
            self.ctx.eval_block([self.actor, OpCode.INSTANT_DEATH])
            self.assertTrue(self.actor.is_alive)
            self.end()
            self.assertEqual((self.actor.max_hp, self.actor.hp), (maximum, min(3, maximum)))
            self.assertEqual(self.actor.is_alive, maximum > 0)
            if maximum:
                self.assertEqual(self.actor.statuses["崩解"], 0)
                self.game.start_turn()

    def test_changed_printed_fee_threshold_and_damage_fraction(self):
        variant = deepcopy(self.spec)
        purge = next(c for c in variant["skills"] if c["name"] == "肃清")
        purge["cost"] = 5
        part = purge["dice"][0]["entries"][0]["operation"]["code"]
        part[part.index("DIVIDE") - 1] = 4
        will = next(c for c in variant["skills"] if c["name"] == "贯彻他的意志")
        will["use_when"][0]["right"] = 6
        self.deploy(spec=variant)
        self.actor.hp = 6
        self.assertFalse(self.cards["贯彻他的意志"].meets_use_requirements())
        self.actor.hp = 5
        self.assertTrue(self.cards["贯彻他的意志"].meets_use_requirements())
        self.game.place_in_duel(1, self.cards["肃清"], 0)
        with self.ctx.collect_facts() as facts:
            self.combat()
        self.assertEqual([e["amount"] for k, e in facts if k == "direct_damage"], [5, 1, 2])
        self.assertEqual([e["cost"] for k, e in facts if k == "skill_payment"], [5])

    def test_turn_end_at_zero_one_four_and_five(self):
        for stacks, lost, expected in ((0, True, (False, 0)), (1, True, (True, 1)),
                                      (4, False, (True, 18)), (5, False, (False, 0)),
                                      (5, True, (False, 0))):
            with self.subTest(stacks=stacks, lost=lost):
                self.deploy()
                self.actor.add_status("崩解", stacks)
                if lost:
                    self.actor.lose_hp(18)
                self.end()
                self.assertEqual((self.actor.is_alive, self.actor.hp), expected)
                if stacks == 4:
                    self.assertEqual(self.actor.statuses["崩解"], 3)

    def test_mode_gate_fixed_and_printed_percentages(self):
        self.deploy()
        will, ruin = self.cards["贯彻他的意志"], self.cards["毁灭"]
        for hp, allowed in ((9, False), (8, True)):
            self.actor.hp = hp
            self.assertEqual(will.meets_use_requirements(), allowed)
        self.assertFalse(ruin.meets_use_requirements())
        self.fire("on_skill_use", will)
        self.assertTrue(ruin.meets_use_requirements())
        self.assertEqual(self.actor.statuses["崩解"], 0)
        self.ctx.dispatch_pipeline("on_turn_start")
        self.assertEqual(self.actor.statuses["崩解"], 1)
        for name, expected in (("贯彻他的意志", 6), ("肃清", 6), ("制裁", 4), ("灭杀", 2)):
            self.enemy.hp = 17
            die = self.cards[name].get_current_die(self.game)
            with self.ctx.collect_facts() as facts:
                self.ctx.resolve_hit(die, self.enemy)
            segments = [(e["amount"], e["grade"]) for k, e in facts if k == "direct_damage"]
            self.assertEqual(segments, [(expected, "concept")], name)
        self.end()
        self.assertEqual(self.actor.statuses["崩解"], 1)
        self.fire("after_skill_use", ruin)
        self.assertFalse(ruin.meets_use_requirements())
        self.assertEqual(self.actor.statuses["崩解"], 3)

    def test_ranked_reductions_bonuses_and_shield(self):
        for first in (1, 2):
            for rank in ("常规", "最高话语权"):
                with self.subTest(first=first, rank=rank):
                    self.deploy()
                    self.game.first_player = self.game.players[first - 1]
                    self.enemy.concept_shield = 1
                    self.ctx.register_entries(self.enemy, [dict(trigger="BEFORE DAMAGE", subject="target",
                        authority=rank, operation={"op":"program","code":[
                            "$self", "$event.incoming_modifiers", "damage_add", 2, "normal", "ADD_DAMAGE_MODIFIER",
                            "$self", "$event.incoming_modifiers", "armor", 1, "concept", "ADD_DAMAGE_MODIFIER"]})])
                    die = self.cards["灭杀"].get_current_die(self.game)
                    self.ctx.resolve_hit(die, self.enemy)
                    reduced = first == 2 and rank == "最高话语权"
                    self.assertEqual(self.enemy.hp, 17 - (2 + 2 - int(reduced) - 1))
                    self.assertEqual(self.enemy.concept_shield, 0)

    def test_damage_protection_is_local_to_one_percentage_segment(self):
        self.deploy()
        self.ctx.register_entries(self.enemy, [dict(trigger="BEFORE RESOLVE_DAMAGE", subject="target",
            operation={"op":"program","code":[1,"SUB"]})])
        for percent, expected in ((False, 1), (True, 3), (False, 1)):
            with self.ctx.collect_facts() as facts:
                self.ctx.deal_damage(self.actor, self.enemy, 2.5, "normal", "none", percentage_damage=percent)
            self.assertEqual([(e["amount"], e["grade"]) for k, e in facts if k == "direct_damage"],
                             [(expected, "concept" if percent else "normal")])

    def test_guard_rewards_only_when_the_guard_wins(self):
        for wins in (True, False):
            self.deploy()
            self.actor.hp = 6
            guard = self.cards["瓦解"]
            self.game.place_in_duel(1, guard, 0)
            face = dict(type="slash", level=1, base_value=0 if wins else 30)
            self.game.place_in_duel(2, self.training(self.enemy, [face, face]), 0)
            self.combat(lambda p: self.game.special.apply(p, next(o for o in self.game.special.options(p)
                                                                  if o.kind == "decline_option")))
            self.assertEqual(self.actor.hp, 7 if wins else 6)
            self.assertEqual(self.enemy.hp, 14 if wins else 15)
            self.end()
            self.game.start_turn()
            self.assertEqual(self.enemy.statuses["虚弱"], 4 if wins else 2)

    def combat(self, choose=None):
        if not self.game.pipeline.in_duel_phase:
            self.game.pipeline.start_duel_combat()
        for _ in range(600):
            if not self.game.pipeline.in_duel_phase or self.game.is_over:
                return
            owner = self.game.special.decision_owner
            if owner is not None:
                self.assertIsNotNone(choose)
                choose(owner)
            else:
                self.game.next_step()
        self.fail("交锋未结束")

    def training(self, actor, dice):
        return Card(actor.player, dict(id="training", name="陪练牌", cost=0, dice=dice), actor)

    def test_optional_reroll_uses_same_die_and_compares_actual_scores(self):
        for rolls, accepts, result, count in (
                ([1, 9], [False], "lose", 0), ([6, 9], [], "draw", 0),
                ([1, 9, 2, 10], [True, True], "win", 2),
                ([1, 9, 1, 1, 1], [True] * 3, "lose", 3)):
            with self.subTest(rolls=rolls):
                self.deploy()
                face = dict(type="slash", level=4)
                own, foe = self.training(self.actor, [face]), self.training(self.enemy, [face])
                self.game.place_in_duel(1, own, 0)
                self.game.place_in_duel(2, foe, 0)
                prompts = []

                def choose(owner):
                    self.assertIs(owner, self.left)
                    options = self.game.special.options(owner)
                    prompts.append(self.game.special.option_decision.event["die"])
                    accept = accepts[len(prompts) - 1]
                    self.game.special.apply(owner, next(o for o in options if o.kind ==
                                                        ("choose_option" if accept else "decline_option")))

                with patch.object(self.game.rng, "randint", side_effect=rolls) as rng:
                    self.combat(choose)
                die, = own.instantiated_dice
                self.assertEqual(prompts, [die] * len(accepts))
                self.assertEqual(rng.call_count, len(rolls))
                self.assertEqual(foe.instantiated_dice[0].clash_score, 9)
                self.assertEqual((die.clash_result, self.actor.turn_state.get("阴黑无明", 0)), (result, count))

    def test_despair_only_negates_cards_that_start_unopposed(self):
        self.deploy()
        despair = self.cards["绝望"]
        own = self.training(self.actor, [dict(type="evade", level=1)])
        face = dict(type="block", level=1)
        opposed = self.training(self.enemy, [face, dict(type="slash", level=1, entries=["1物理"])])
        solo = self.training(self.enemy, [dict(type="slash", level=1, entries=["1物理"])])
        self.fire("on_skill_use", despair)
        self.game.place_in_duel(1, own, 0)
        self.game.place_in_duel(2, opposed, 0)
        self.game.place_in_duel(2, solo, 1)
        self.combat()
        self.assertEqual(self.actor.hp, 17)
        self.assertNotEqual(opposed.state, CardState.NEGATED)
        self.assertEqual(solo.state, CardState.NEGATED)

    def test_reroll_at_reversed_clash_and_turn_limit_reset(self):
        self.deploy()
        for round_number in range(2):
            own = self.training(self.actor, [dict(type="slash", level=4, clash_order="lower")])
            foe = self.training(self.enemy, [dict(type="slash", level=4)])
            self.game.place_in_duel(1, own, 0)
            self.game.place_in_duel(2, foe, 0)
            if round_number == 0:
                self.actor.turn_state["阴黑无明"] = 2
            else:
                self.assertNotIn("阴黑无明", self.actor.turn_state)
            with patch.object(self.game.rng, "randint", side_effect=[1, 9, 10]):
                self.combat(lambda p: self.game.special.apply(p, next(o for o in self.game.special.options(p)
                                                                      if o.kind == "choose_option")))
            self.assertEqual(own.instantiated_dice[0].clash_result, "lose")
            self.assertEqual(self.actor.turn_state["阴黑无明"], 3 if round_number == 0 else 1)
            self.end()
            self.game.start_turn()

    def test_reroll_does_not_spend_a_second_clash_advantage(self):
        self.deploy()
        self.ctx.eval_block([self.actor, "优势次数", 2, OpCode.ABILITY_EFFECT])
        face = dict(type="slash", level=4)
        own, foe = self.training(self.actor, [face]), self.training(self.enemy, [face])
        self.game.place_in_duel(1, own, 0)
        self.game.place_in_duel(2, foe, 0)
        with patch.object(self.game.rng, "randint", side_effect=[1, 2, 9, 10]) as rng:
            self.combat(lambda p: self.game.special.apply(p, next(o for o in self.game.special.options(p)
                                                                  if o.kind == "choose_option")))
        self.assertEqual(rng.call_count, 4)
        self.assertEqual(own.instantiated_dice[0].clash_score, 13)
        self.assertEqual(self.actor.ability_effects["优势次数"], 1)

    def test_printed_attack_dice_apply_each_hit_in_order(self):
        for name, initial, remaining, pressure, disintegration, drew in (
                ("灭杀", 17, 13, 1, 1, 0), ("挫败", 17, 15, 2, 0, 0),
                ("瓦解", 17, 15, 0, 0, 0), ("绝望", 17, 17, 0, 1, 0),
                ("肃清", 17, 8, 3, 2, 0), ("惩戒", 17, 13, 1, 0, 1),
                ("抹除", 17, 10, 1, 1, 1), ("制裁", 17, 12, 1, 1, 0)):
            with self.subTest(skill=name):
                self.deploy()
                card = self.cards[name]
                self.enemy.hp = initial
                self.game.place_in_duel(1, card, 0)
                self.combat()
                self.assertEqual((self.enemy.hp, self.enemy.statuses.get("威压", 0)), (remaining, pressure))
                self.assertEqual(self.actor.statuses["崩解"], disintegration)
                self.assertEqual(len(self.left.cardspace.hand.content), drew)
                if name in ("瓦解", "绝望"):
                    self.assertNotIn("虚弱", self.enemy.statuses)
                    if name == "绝望":
                        self.assertEqual(self.right.next_turn_common_cost, -2)
                    self.end()
                    self.game.start_turn()
                    self.assertEqual(self.enemy.statuses["虚弱"], 2 if name == "瓦解" else 4)

    def test_will_resident_hit_and_ruin_mode_exit(self):
        self.deploy()
        will = self.cards["贯彻他的意志"]
        foe = self.training(self.enemy, [dict(type="block", level=6, base_value=30)])
        self.actor.hp = 8
        self.game.place_in_duel(1, will, 0)
        self.game.place_in_duel(2, foe, 0)
        self.combat(lambda player: self.game.special.apply(player, next(
            o for o in self.game.special.options(player) if o.kind == "decline_option")))
        self.assertEqual(will.instantiated_dice[0].clash_result, "lose")
        self.assertEqual(self.enemy.hp, 11)
        self.assertEqual(will.instantiated_dice[0].modified_level, 5)
        self.end()
        self.game.start_turn()
        self.ctx.dispatch_pipeline("on_turn_start")
        ruin = self.cards["毁灭"]
        self.game.place_in_duel(1, ruin, 0)
        self.combat()
        self.assertEqual((self.enemy.hp, self.enemy.statuses["威压"]), (1, 2))
        self.assertEqual(self.actor.hp, 13)
        self.assertNotIn("毁灭模式", self.actor.statuses)
        self.assertEqual(self.actor.statuses["崩解"], 3)
        die = self.cards["惩戒"].get_current_die(self.game)
        self.ctx.dispatch_pipeline("before_dice_use", source=self.actor, card=die.card, die=die)
        self.assertEqual(die.modified_level, 5)

    def test_paid_shatter_chooses_exact_hidden_card(self):
        self.deploy()
        shatter = self.cards["破碎"]
        hidden = self.training(self.enemy, [dict(type="slash", level=4)])
        other = self.training(self.enemy, [dict(type="block", level=3)])
        self.game.place_in_duel(2, hidden, 0)
        self.game.place_in_duel(2, other, 1)
        deck, hand = self.left.cardspace.draw, self.left.cardspace.hand
        deck.move_card_to(deck.content.index(shatter), hand)
        self.game.run_placement()
        self.assertNotIn(shatter, self.game.legal_placements())
        phase = self.game.pre_reveal
        self.game.start_pre_reveal_declarations()
        phase.declare_attack(shatter, character=self.enemy)
        phase.pass_intercept(1, self.right)
        if phase.can_attack(self.left):
            phase.end_attack(self.left)
        phase.begin_resolution()

        def select(owner):
            self.assertIs(owner, self.left)
            self.assertEqual(self.game.special.card_decision.candidates, (hidden, other))
            self.assertNotIn(hidden.name, _card_choice_view(hidden, owner)["label"])
            self.game.special.apply(owner, next(o for o in self.game.special.options(owner) if o.target_card is hidden))

        self.combat(select)
        self.assertEqual(hidden.state, CardState.NEGATED)
        self.assertEqual(other.state, CardState.PLACED_FACE_DOWN)
        self.assertEqual((self.enemy.hp, self.actor.statuses["崩解"], self.enemy.statuses["威压"]), (15, 1, 1))
        self.assertFalse(shatter.meets_use_requirements())
