"""流阴及其引入的拼点规则，经真实卡面、词条和执行器结算。"""
import random
import unittest
from unittest.mock import Mock, patch

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.duel import ClashPair
from models.opcode import OpCode
from player.player import Player


class LiuYinTests(unittest.TestCase):
    def setUp(self):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(17))
        self.game.first_player = self.left
        self.actor, self.enemy = [self.recruit(p, dict(id=p.name, name=p.name, rank="NORMAL",
                                                       max_hp=18, skills=[])) for p in self.game.players]

    def recruit(self, player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def die(self, actor):
        card = Card(actor.player, dict(name="取值测试", id="roll", cost=0,
                                       dice=[dict(type="slash", level=3, final_bonus=4)]), actor)
        return card.get_current_die(self.game)

    def test_choices_sample_the_modified_value_twice_and_roll_once(self):
        die = self.die(self.actor)
        paths = []
        ctx = self.game.context
        ctx.register_entries(self.actor, [
            dict(trigger="BEFORE RESOLVE_ROLL_VALUE", operation={"op":"program","code":[-1,"MUL",9,"ADD"]}),
            *[dict(trigger="AFTER " + name, operation=lambda vm, name=name: paths.append(name))
              for name in ("RESOLVE_ROLL_VALUE", "ROLL")]
        ])
        for ability, expected in (("优势次数", 6), ("劣势次数", 2)):
            self.actor.add_ability_effect(ability, 2)
            paths.clear()
            with patch.object(self.game.rng, "randint", side_effect=[3, 7]):
                self.assertEqual(die.roll(clash=True), expected + 4)
            self.assertEqual(die.value, expected)
            self.assertEqual(paths, ["RESOLVE_ROLL_VALUE", "RESOLVE_ROLL_VALUE", "ROLL"])
            self.assertEqual(self.actor.ability_effects[ability], 1)
            with patch.object(self.game.rng, "randint", return_value=5) as rng:
                die.roll()
                self.actor.roll_speed()
                self.assertEqual(rng.call_count, 2)
            self.assertEqual(self.actor.ability_effects[ability], 1)
            self.actor.spend_ability_effect(ability)

    def test_opposing_uses_cancel_on_grant(self):
        for first, second in (("优势次数", "劣势次数"), ("劣势次数", "优势次数")):
            for amount in (1, 2, 5):
                self.actor.ability_effects.clear()
                self.actor.add_ability_effect(first, 2)
                self.actor.add_ability_effect(second, amount)
                expected = {first: 1} if amount == 1 else {second: 3} if amount == 5 else {}
                self.assertEqual(self.actor.ability_effects, expected)

    def test_cancelled_grant_preserves_opposite_uses(self):
        self.actor.add_ability_effect("优势次数", 2)
        self.game.context.register_entries(self.actor, [dict(trigger="BEFORE ABILITY_EFFECT",
            subject="target", when=[dict(left="$event.ability",op="eq",right="劣势次数")],
            operation={"op":"cancel"})])
        self.actor.add_ability_effect("劣势次数", 1)
        self.assertEqual(self.actor.ability_effects, {"优势次数":2})

    def deploy(self):
        data = next(c for c in load_characters_from_packs() if c["id"] == "liu_yin")
        self.liu = self.recruit(self.left, data)
        self.cards = {card.id: card for card in self.liu.skills}
        self.game.start_turn()
        self.ctx = self.game.context

    def fight(self, card, opposing=None, *, balance=100):
        self.left.max_cost = self.right.max_cost = balance
        self.assertTrue(self.game.place_in_duel(self.left.side, card, 0))
        if opposing:
            self.assertTrue(self.game.place_in_duel(self.right.side, opposing, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with self.game.context.collect_facts() as facts:
            for _ in range(2000):
                if not self.game.pipeline.in_duel_phase or self.game.is_over:
                    return facts
                self.game.next_step()
        self.fail("交锋未完成")

    def test_three_stacks_convert_only_eligible_physical_segments(self):
        self.deploy()
        self.liu.add_status("环境同调", 3)
        self.assertEqual((self.liu.hp, self.liu.lightcore_hp, self.liu.max_duels), (18, 28, 4))
        self.assertEqual(self.liu.statuses["环境压制"], 18)
        self.assertEqual(len([c for c in self.liu.skills if not c.out_of_combat]), 11)
        facts = self.fight(self.cards["liu_execution"])
        self.assertEqual([e["amount"] for kind, e in facts if kind == "lightcore_damage"], [4, 4, 7])
        self.assertFalse(any(kind == "direct_damage" for kind, _ in facts))
        with self.ctx.collect_facts() as facts:
            self.ctx.deal_damage(self.liu, self.enemy, 2)
        self.assertEqual([k for k, _ in facts if k in ("direct_damage", "lightcore_damage")],
                         ["direct_damage", "lightcore_damage"])

    def test_overwrite_crossed_thresholds_choose_enemy_and_pay_zero(self):
        self.deploy()
        other = self.recruit(self.right, dict(id="enemy2", name="第二名敌人", rank="NORMAL", max_hp=18, skills=[]))
        self.liu.add_status("领域洞悉", 21)
        self.liu.add_status("领域洞悉", -13)
        self.liu.add_status("领域洞悉", 2)
        self.game.finish_turn()
        self.game.start_turn()
        choice = Mock()
        choice.resolve.return_value = other
        self.left.target_order = choice
        self.ctx.dispatch_pipeline("on_before_reveal_phase_start")
        slots = self.game.pre_reveal.space.space
        self.assertEqual(len(slots), 2)
        self.assertEqual(choice.resolve.call_args.args[0], [self.enemy, other])
        self.assertEqual([slot.target_character for slot in slots], [other, self.enemy])
        self.assertIsNot(slots[0].attack_card, slots[1].attack_card)
        self.assertTrue(all(slot.attack_card.temporary and slot.attack_card.cost == 3 for slot in slots))
        self.left.max_cost = self.liu.independent_cost = 0
        self.game.start_pre_reveal_declarations()
        for slot in slots:
            slot.ready = True
        self.game.pre_reveal.phase = "ready"
        self.game.pre_reveal.begin_resolution()
        with self.ctx.collect_facts() as facts:
            for _ in range(500):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
            else:
                self.fail("开牌前交锋未结算")
        self.assertEqual([e["cost"] for k, e in facts if k == "skill_payment"], [0, 0])
        self.assertEqual(self.liu.statuses["环境同调"], 2)

    def test_reversal_swaps_the_conditions_and_preserves_draws_and_scores(self):
        self.deploy()
        first = self.cards["liu_invisible"].get_current_die(self.game)
        other = self.die(self.enemy)
        other.final_bonus = 0
        pair = ClashPair({1:first, 2:other})
        for a, b, result in ((3, 7, "win"), (7, 3, "lose"), (3, 3, "draw")):
            first.value, other.value = a, b
            self.assertEqual(pair.clash_check()[1], result)
            self.assertEqual((first.clash_score, other.clash_score), (a, b))

    def test_percentage_uses_max_hp_concept_shield_and_separate_light_segment(self):
        self.deploy()
        self.enemy.max_hp = 17
        self.enemy.hp = 12
        self.enemy.concept_shield = 4
        self.liu.add_status("环境同调", 3)
        self.liu.add_status("战甲", 1)
        facts = self.fight(self.cards["liu_armor"])
        self.assertEqual([(e["amount"], e["grade"], e["lost"]) for k,e in facts if k=="direct_damage"],
                         [(6, "concept", 2)])
        self.assertEqual([e["amount"] for k,e in facts if k=="lightcore_damage"], [6])

    def test_instant_death_compares_authority_for_each_attempt(self):
        self.deploy()
        self.ctx.register_entries(self.enemy, [dict(trigger="BEFORE CHECK_DEATH", subject="target",
            authority="较高话语权", operation={"op":"cancel"})])
        with self.ctx.binding(authority=0):
            for _ in range(3):
                self.assertFalse(self.ctx.eval_block([self.enemy, OpCode.INSTANT_DEATH]))
        self.assertTrue(self.enemy.is_alive)
        with self.ctx.binding(authority=2):
            self.assertTrue(self.ctx.eval_block([self.enemy, OpCode.INSTANT_DEATH]))
        self.assertFalse(self.enemy.is_alive)

    def emit_use(self, card, target=None):
        self.ctx.dispatch_pipeline("on_skill_use", side=self.left.side, source=self.liu,
                                   card=card, target=target or self.enemy)

    def test_rewind_merges_actual_stacks_and_restores_life_without_heal(self):
        self.deploy()
        self.liu.add_status("环境压制", -13)
        self.liu.hp = 12
        self.liu.add_status("强壮", 2)
        self.liu.add_status("虚弱", 2)
        self.emit_use(self.cards["liu_rewind"])
        self.liu.hp = 8
        self.liu.add_status("强壮", 1)
        self.liu.add_status("虚弱", -1)
        self.liu.add_status("束缚", 2)
        self.liu.add_status("环境压制", -7)
        self.assertEqual(self.liu.hp, 8)
        self.liu.add_status("环境压制", 2)
        with self.ctx.collect_facts() as facts:
            self.liu.add_status("环境压制", -1)
        self.assertEqual(self.liu.hp, 12)
        self.assertEqual(self.liu.statuses["强壮"], 3)
        self.assertEqual(self.liu.statuses["虚弱"], 1)
        self.assertNotIn("束缚", self.liu.statuses)
        self.assertFalse(any(k in ("healed", "lightcore_damage") for k,_ in facts))
        self.assertFalse(any(effect.terms.event == "on_status_changed" for effect in self.ctx.scheduled_effects))

    def test_adaptation_uses_actual_safe_payment_then_heals_separately(self):
        self.deploy()
        self.liu.add_status("领域洞悉", 10)
        self.liu.hp = 3
        card = self.cards["liu_adapt"]
        self.emit_use(card)
        self.assertEqual((self.liu.hp, self.liu.statuses["领域洞悉"]), (1, 12))
        self.ctx.dispatch_pipeline("after_skill_use", side=self.left.side, source=self.liu,
                                   card=card, target=self.enemy)
        self.assertEqual((self.liu.hp, self.enemy.lightcore_hp), (2, 27))

    def test_zero_release_subsequent_reduction_and_armor_actual_gain(self):
        self.deploy()
        self.liu.add_status("战甲", 1)
        self.liu.add_status("领域洞悉", 29)
        self.liu.add_status("环境压制", -18)
        self.assertEqual((self.liu.statuses["领域洞悉"], self.liu.statuses["能源"]), (30, 30))
        self.liu.add_status("环境压制", 4)
        self.liu.add_status("环境压制", -2)
        self.assertEqual((self.liu.statuses["环境压制"], self.liu.statuses["能源"]), (4, 32))

    def test_extreme_range_triggers_retaliation_but_protected_skill_stays_live(self):
        self.deploy()
        other = Card(self.right, dict(id="range", name="远程", cost=0, range_level=3, dice=[]), self.enemy)
        protected = self.cards["liu_overwrite"]
        protected.set_range_opponent(other)
        self.assertEqual(protected.range_deficit, 2)
        self.ctx.eval_block([protected, OpCode.DESTROY])
        self.assertFalse(protected.destroyed)
        self.assertIsNone(self.ctx.eval_block([protected, OpCode.NEGATE_SKILL]))
        self.assertFalse(other.destroyed)
        self.cards["liu_blade"].set_range_opponent(other)
        self.assertTrue(other.destroyed)
        self.assertEqual(self.enemy.ability_effects["劣势次数"], 1)
        self.assertEqual(self.liu.statuses["环境压制"], 14)

    def test_self_destruction_retaliates_once(self):
        self.deploy()
        other = self.die(self.enemy).card
        other.dice[0]["base_value"] = -50
        self.liu.hp = 15
        self.fight(self.cards["liu_hope"], other)
        self.assertEqual((self.liu.hp, self.enemy.ability_effects.get("劣势次数")), (16, 1))
        self.assertTrue(other.destroyed)

    def test_each_collapse_heal_including_a_nested_collapse(self):
        self.deploy()
        self.liu.add_status("环境同调", 3)
        self.liu.hp = 10
        self.actor.lightcore_hp = self.enemy.lightcore_hp = 1
        with self.ctx.collect_facts() as facts, self.ctx.binding(source=self.liu):
            self.ctx.eval_block([self.enemy, 1, OpCode.LIGHTCORE_DAMAGE])
        self.assertEqual([e["amount"] for k,e in facts if k=="healed"], [3, 3])
        self.assertEqual(self.liu.hp, 16)
        self.assertEqual(self.liu.lightcore_hp, 22)

    def test_returned_finisher_ends_only_this_duel(self):
        self.deploy()
        card = self.cards["liu_annihilate"]
        self.liu.add_status("环境同调", 3)
        other = Card(self.right, dict(id="break", name="毁牌", cost=0, dice=[dict(
            type="slash", level=1, base_value=120, entries=["1物理",dict(
                trigger="on_dice_hit", operation={"op":"program","code":["$event.opponent_card","DESTROY"]})])]), self.enemy)
        following = Card(self.right, dict(id="next",name="下一场",cost=0,dice=[
            dict(type="slash",level=1,entries=["1光点"])]), self.enemy)
        self.assertTrue(self.game.place_in_duel(self.right.side, other, 0))
        self.assertTrue(self.game.place_in_duel(self.right.side, following, 1))
        skipped = Card(self.right, dict(id="unused",name="本场待用",cost=0,dice=[
            dict(type="slash",level=1,entries=["1光点"])]), self.enemy)
        self.game.duelspace.space[0].add_content(self.right.side, skipped)
        facts = self.fight(card)
        self.assertIn(card, self.left.cardspace.hand.content)
        self.assertFalse(card.destroyed)
        self.assertEqual([e["card"] for k,e in facts if k=="skill_used"].count("下一场"), 1)
        self.assertFalse(any(k == "skill_used" and e["card"] == "本场待用" for k,e in facts))

    def test_finisher_fixed_range_collapse_and_three_lethal_attempts(self):
        self.deploy()
        self.enemy.lightcore_hp = 1
        self.liu.add_status("能源", 5)
        self.liu.add_status("骰子等级降低", 4)
        card = self.cards["liu_annihilate"]
        die = card.get_current_die(self.game)
        die.resolve_level()
        self.assertEqual(die.roll_max, 100)
        attempts = []
        self.ctx.register_entries(self.enemy, [
            dict(trigger="BEFORE CHECK_DEATH", subject="target", operation=lambda ctx: (
                attempts.append(ctx.event["lethal"]), ctx.cancel_op(0)))])
        self.fight(card)
        self.assertEqual(attempts, [True, True, True])
        self.assertTrue(self.enemy.is_alive)
        self.assertEqual((self.enemy.hp, self.enemy.lightcore_hp, self.enemy.max_lightcore_hp), (9,20,20))
        self.assertNotIn("能源", self.liu.statuses)

    def test_prison_blanks_eight_in_first_actual_duel_only(self):
        self.deploy()
        self.ctx.dispatch_pipeline("after_skill_use", side=self.left.side, source=self.liu,
                                   card=self.cards["liu_prison"], target=self.enemy)
        self.game.finish_turn()
        self.game.start_turn()
        cards = [Card(self.right, dict(id=str(i), name=str(i), cost=0, dice=[
            dict(type="slash", level=4, final_bonus=9, entries=["1光点"]) for _ in range(n)]), self.enemy)
                 for i,n in enumerate((2,1))]
        for i,card in enumerate(cards):
            self.assertTrue(self.game.place_in_duel(self.right.side, card, i))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=[8,9,8]):
            for _ in range(1000):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
        self.assertEqual([(die.type, die.value) for c in cards for die in c.instantiated_dice],
                         [("blank",8), ("slash",9), ("slash",8)])

    def test_invisible_pays_each_repeat_and_uses_snapshot_at_twelve(self):
        for energy, count, remaining in ((11,1,11),(12,3,0),(19,4,1)):
            with self.subTest(energy=energy):
                self.setUp()
                self.deploy()
                self.liu.add_status("能源", energy)
                facts = self.fight(self.cards["liu_invisible"])
                self.assertEqual(len([e for k,e in facts if k == "hit"]), count)
                self.assertEqual(self.liu.statuses.get("能源",0), remaining)

    def test_sustained_threshold_and_budget_refill(self):
        self.deploy()
        self.liu.add_status("强壮", 2)
        self.liu.add_status("环境同调", 3)
        self.left.turn_common_cost_bonus = -self.game.gamerule.MAX_BASIC_COST
        self.left.reset_on_turn_start()
        self.assertEqual(self.left.max_cost, 4)
        self.assertEqual((self.liu.statuses["迅捷"], self.liu.statuses["强壮"]), (1,3))
        self.liu.add_status("环境同调", -2)
        self.assertNotIn("迅捷", self.liu.statuses)
        self.assertEqual(self.liu.statuses["强壮"], 2)

    def test_failed_payment_preserves_first_discount(self):
        self.deploy()
        self.left.max_cost = self.liu.independent_cost = 0
        self.assertFalse(self.ctx.pay_skill_cost(self.cards["liu_execution"])["paid"])
        self.assertTrue(self.ctx.pay_skill_cost(self.cards["liu_blade"])["paid"])
        self.assertFalse(self.ctx.pay_skill_cost(self.cards["liu_shadow"])["paid"])

    def test_skill_range_matching_preserves_the_other_dice_only_range(self):
        self.deploy()
        card = self.cards["liu_execution"]
        opposing = self.die(self.enemy).card
        self.assertEqual(card.paired_ranges(opposing, 0, 2), (0, 2))
        opposing.data["range_level"] = 2
        self.assertEqual(card.paired_ranges(opposing), (2, 2))
        self.assertEqual(self.cards["liu_hope"].paired_ranges(opposing), (0, 1))

    def test_rewind_restores_insight_without_an_energy_gain(self):
        self.deploy()
        self.liu.add_status("领域洞悉", 15)
        self.liu.add_status("战甲", 1)
        self.liu.add_status("环境压制", -10)
        self.emit_use(self.cards["liu_rewind"])
        self.liu.add_status("领域洞悉", -2)
        self.liu.add_status("环境压制", -6)
        self.assertEqual(self.liu.statuses["领域洞悉"], 15)
        self.assertNotIn("能源", self.liu.statuses)

    def test_overlapping_rewinds_keep_their_own_thresholds(self):
        self.deploy()
        self.liu.hp = 12
        self.liu.add_status("环境压制", -14)
        self.emit_use(self.cards["liu_rewind"])
        self.liu.hp = 10
        self.emit_use(self.cards["liu_rewind"])
        self.liu.hp = 8
        self.liu.add_status("环境压制", -6)
        self.assertEqual(self.liu.hp, 10)
        self.liu.add_status("环境压制", -6)
        self.assertEqual(self.liu.hp, 12)

    def test_dismember_upgrades_only_later_dice_and_requires_all_three_hits(self):
        for remote, miss, expected in ((0,False,[5,4,4,4]),(1,False,[5,3,3,2]),(0,True,[5,3,3])):
            with self.subTest(remote=remote, miss=miss):
                self.setUp()
                self.deploy()
                self.liu.add_status("环境同调", 1)
                card = self.cards["liu_dismember"]
                enemy = Card(self.right, dict(id="guard",name="对阵",cost=0,range_level=remote,dice=[
                    dict(type="block",level=1,base_value=(100 if miss and i==0 else -100))
                    for i in range(4)]), self.enemy)
                self.fight(card, enemy)
                used = [d for d in card.instantiated_dice if d is not None]
                self.assertEqual([d.level.value for d in used],expected)

    def test_heart_and_shadow_use_exact_thresholds(self):
        for hand, gain in ((4,0),(5,1),(8,1),(9,2)):
            with self.subTest(hand=hand):
                self.setUp()
                self.deploy()
                pile = self.left.cardspace.draw
                for _ in range(hand):
                    pile.move_card_to(0, self.left.cardspace.hand)
                self.ctx.dispatch_pipeline("on_turn_start")
                self.assertEqual(self.liu.statuses.get("领域洞悉",0),gain)
        self.enemy.lightcore_hp = 15
        self.emit_use(self.cards["liu_shadow"])
        self.assertNotIn("骰子等级提升", self.liu.statuses)
        self.enemy.lightcore_hp = 14
        self.emit_use(self.cards["liu_shadow"])
        self.assertEqual(self.liu.statuses["骰子等级提升"],1)
