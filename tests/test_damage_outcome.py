import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from models.card import Card
from models.character import Character
from player.player import Player


class DamageOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        left, right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([left, right], rng=random.Random(11))
        self.game.first_player = left
        self.source, self.target = [
            Character(dict(id=p.name, name=p.name, max_hp=20, rank="NORMAL", skills=[]), p)
            for p in (left, right)]
        left.characters.append(self.source)
        right.characters.append(self.target)
        self.game.start_turn()
        self.damage = []
        self.listen(self.source, "AFTER DAMAGE", self.record_damage, subject="source")

    def listen(self, owner, trigger, operation, **options):
        self.game.context.register_entries(owner, [dict(trigger=trigger, operation=operation, **options)])

    def record_damage(self, ctx):
        event = ctx.event
        self.damage.append((event["damage_die"], event["damage_amount"], event["damage_dealt"],
                            event["damage_received"], event["hp_lost"]))

    def play(self, *printed_entries, opponent_range=None):
        card = Card(self.source.player, dict(id="skill", name="测试攻击", cost=0, dice=[
            dict(type="slash", level=1, entries=list(entries)) for entries in printed_entries
        ]), self.source)
        self.source.skills.append(card)
        self.assertTrue(self.game.place_in_duel(1, card, 0))
        if opponent_range is not None:
            block = Card(self.target.player, dict(id="guard", name="格挡", cost=0,
                         range_level=opponent_range,
                         dice=[dict(type="block", level=1, base_value=20, entries=[])]), self.target)
            self.target.skills.append(block)
            self.assertTrue(self.game.place_in_duel(2, block, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(600):
            if not self.game.pipeline.in_duel_phase:
                return card.instantiated_dice
            self.game.next_step()
        self.fail(self.log.getvalue()[-1800:])

    def test_zero_support_only_and_positive_absorbed_by_shield(self):
        self.target.shield = 3
        zero, support, absorbed, penetrating = self.play(
            ["0物理"], ["Shield: 1"], ["3物理"], ["2超穿甲"])
        self.assertEqual(self.damage, [
            (zero, 0, True, False, 0),
            (absorbed, 3, True, True, 0),
            (penetrating, 2, True, True, 2),
        ])
        self.assertEqual([d.did_deal_damage for d in (zero, support, absorbed, penetrating)],
                         [True, False, True, True])
        self.assertEqual((support.landed_hits, self.source.shield), (1, 1))

    def test_armor_reducing_a_segment_to_zero_preserves_its_success(self):
        self.listen(self.target, "BEFORE DAMAGE", "Armor: 4", subject="target")
        die, = self.play(["2物理"])
        self.assertEqual(self.damage, [(die, 0, True, False, 0)])
        self.assertTrue(die.did_deal_damage)

    def test_damage_callers_can_distinguish_a_settled_zero_from_a_cancelled_segment(self):
        deal = self.game.context.deal_damage
        self.assertIs(deal(self.source, self.target, 0, result_field="damage_dealt"), True)
        self.assertIs(self.target.take_damage(0, result_field="damage_received"), False)
        self.listen(self.target, "BEFORE DAMAGE", "Cancel")
        self.assertIs(self.target.take_damage(3, result_field="damage_dealt"), False)
        self.assertIs(deal(self.source, None, 3, result_field="damage_dealt"), False)

    def test_cancelled_damage_keeps_landed_hit_but_has_no_damage_outcome(self):
        self.listen(self.target, "BEFORE RESOLVE_DAMAGE", "Cancel", subject="target")
        die, = self.play(["0物理", "4穿甲"])
        self.assertEqual(die.landed_hits, 1)
        self.assertFalse(die.did_deal_damage)
        self.assertEqual(self.damage, [])
        self.assertEqual(self.target.hp, 20)

    def test_lightcore_and_real_damage_do_not_count_as_direct_damage(self):
        original_integrity = self.target.lightcore_hp
        lightcore, real = self.play(["2光点伤害"], ["3真实伤害"])
        self.assertEqual(self.damage, [])
        self.assertFalse(lightcore.did_deal_damage)
        self.assertFalse(real.did_deal_damage)
        self.assertEqual((self.target.lightcore_hp, self.target.hp), (original_integrity - 2, 17))

    def test_effect_damage_persists_across_hits_and_restarts_on_repeat(self):
        before, hits, after = [], [], []
        for trigger, observations in (("before_dice_use", before), ("after_dice_hit", hits),
                                      ("after_dice_use", after)):
            self.listen(self.source, trigger,
                        lambda ctx, out=observations: out.append(ctx.event["die"].did_deal_damage),
                        subject="source")
        repeat = dict(trigger="on_dice_use", operation=dict(op="program", code=[
            "$is_repeat", "NOT", ["$die", "REPEAT_DIE"], "WHEN"]))
        first_hit = dict(hit_index=1, is_repeat=False)
        extra_hit = dict(trigger="before_dice_hit", when=first_hit, operation=dict(
            op="program", code=["$die", "full", "QUEUE_HIT"]))
        effect_damage = dict(trigger="on_dice_hit", when=first_hit, operation=dict(
            op="program", code=["$target", 0, "pierce", "slash", "DAMAGE"]))
        original, repeated = self.play([repeat, extra_hit, effect_damage])
        self.assertEqual([original.landed_hits, repeated.landed_hits], [2, 1])
        self.assertEqual(self.damage, [(original, 0, True, False, 0)])
        self.assertEqual(before, [False, False])
        self.assertEqual(hits, [True, True, False])
        self.assertEqual(after, [True, False])

    def register_followup(self):
        self.listen(self.source, "after_dice_use", dict(op="program", code=[
            "$is_attack", "$did_deal_damage", "NOT", "AND",
            [dict(op="damage", amount=1, grade="pierce", from_die=True)], "WHEN"
        ]), subject="source")

    def test_losing_melee_die_can_deal_attributed_followup_after_use(self):
        self.register_followup()
        die, = self.play(["3物理"], opponent_range=0)
        self.assertEqual(die.clash_result, "lose")
        self.assertEqual(self.damage, [(die, 1, True, True, 1)])
        self.assertTrue(die.did_deal_damage)

    def test_level_one_range_advantage_blocks_the_same_followup(self):
        self.register_followup()
        die, = self.play(["3物理"], opponent_range=1)
        self.assertEqual(die.clash_result, "lose")
        self.assertEqual(self.damage, [])
        self.assertFalse(die.did_deal_damage)

    def test_independent_character_damage_during_hit_keeps_followup_available(self):
        self.listen(self.source, "on_dice_hit", dict(op="damage", amount=2), subject="source")
        self.register_followup()
        die, = self.play(["Shield: 1"])
        self.assertEqual(self.damage, [(None, 2, True, True, 2), (die, 1, True, True, 1)])

    def test_nested_bleed_burst_belongs_to_the_status(self):
        burst = []
        self.listen(self.target, "AFTER DAMAGE", lambda ctx: burst.append(
            (ctx.event["damage_die"], ctx.event["damage_amount"])),
            subject="target", when={"damage_cause": "裂血爆发"})
        self.target.add_status("裂血", 6)
        die, = self.play(["1物理"])
        self.assertEqual(self.damage, [(die, 1, True, True, 1)])
        self.assertEqual(burst, [(None, 1)])

    def test_zero_prevents_followup_but_positive_amount_is_needed_for_propagation(self):
        self.register_followup()
        self.listen(self.source, "AFTER DAMAGE", dict(op="program", code=[
            "$damage_dealt", ["$self", "造成次数", 1, "STATUS"], "WHEN",
            "$damage_received", ["$target", "受伤次数", 1, "STATUS"], "WHEN",
            "$damage_die", "$damage_amount", 1, "GE", "AND",
            ["$target", "传播次数", 1, "STATUS"], "WHEN",
        ]), subject="source")
        self.target.shield = 2
        zero, positive = self.play(["0物理"], ["2物理"])
        self.assertEqual(self.damage, [(zero, 0, True, False, 0), (positive, 2, True, True, 0)])
        self.assertEqual(self.source.statuses.get("造成次数"), 2)
        self.assertEqual(self.target.statuses, {"受伤次数": 1, "传播次数": 1})
