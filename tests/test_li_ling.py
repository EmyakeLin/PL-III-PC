import io
import random
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from player.player import Player


class LiLingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = next(c for c in load_characters_from_packs() if c["id"] == "plan_b_li_ling")

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(24))
        self.game.first_player = self.left
        self.actor = self.recruit(self.left, self.pack)
        self.target = self.recruit(self.right, dict(id="target", name="陪练", max_hp=100, rank="NORMAL", skills=[]))
        self.cards = {c.name: c for c in self.actor.skills}
        self.game.start_turn()
        self.left.max_cost = 10

    @staticmethod
    def recruit(player, spec):
        actor = Character(spec, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def fight(self, name, *, opponent=None):
        card = self.cards[name]
        self.assertTrue(self.game.place_in_duel(1, card, 0))
        if opponent:
            self.assertTrue(self.game.place_in_duel(2, opponent, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1800):
            self.game.next_step()
            if self.game.is_over or not self.game.pipeline.in_duel_phase:
                return card
        self.fail(self.log.getvalue()[-2400:])

    def opposed(self, base, size, **traits):
        return Card(self.right, dict(id="spar", name="陪练技能", cost=0, **traits,
            dice=[dict(type="pierce", level=1, base_value=base, entries=[]) for _ in range(size)]), self.target)

    def test_speed_dice_use_energy_ladder_concentration_minimum_then_swiftness(self):
        self.actor.add_status("能源", 3)
        with patch.object(self.game.rng, "randint", side_effect=lambda low, high: low) as roll:
            for energy, focus, bounds in ((0, 0, (1, 4)), (1, 0, (1, 6)),
                                          (4, 2, (3, 8)), (4, 12, (8, 8))):
                self.actor.add_status("能源", energy)
                self.actor.add_status("凝聚", focus)
                self.assertEqual(self.actor.roll_speed(), bounds[0])
                roll.assert_called_with(*bounds)
            self.actor.add_status("迅捷", 1)
            self.assertEqual(self.actor.roll_speed(), 9)
        self.actor.clear_status("能源")
        self.actor.clear_status("迅捷")
        self.actor.clear_status("凝聚")
        self.actor.add_status("凝聚", 5)
        with patch.object(self.game.rng, "randint", return_value=4) as roll:
            self.assertEqual(self.actor.roll_speed(), 4)
            roll.assert_called_once_with(4, 4)

    def test_chain_at_two_energy_in_a_fast_duel_skips_four_energy_die_then_burns(self):
        self.actor.speed, self.target.speed, self.right.speed = 7, 3, 20
        self.actor.add_status("能源", 2)
        card = self.fight("连环穿刺")
        first, second, third, last = card.instantiated_dice
        self.assertIsNone(first)
        self.assertEqual([d.landed_hits for d in (second, third, last)], [1, 1, 1])
        self.assertEqual([d.level.value for d in (second, third, last)], [4, 4, 3])
        self.assertEqual((card.use_state["spent_statuses"]["能源"], self.actor.statuses["能源"]), (2, 1))
        self.assertEqual((self.target.hp, self.target.statuses["烧伤"]), (99, 7))
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual((self.actor.statuses["迅捷"], self.target.statuses["束缚"]), (3, 1))

    def test_sky_at_four_speed_lead_can_hit_extreme_range_with_only_seven_energy(self):
        self.actor.add_status("能源", 7)
        self.actor.speed, self.target.speed = 5, 1
        card = self.fight("机动·贯彻长空", opponent=self.opposed(-40, 2, range_level=3))
        self.assertEqual(self.actor.statuses["能源"], 7)
        self.assertEqual([d.base_value for d in card.instantiated_dice], [0, 0])
        self.assertEqual([d.landed_hits for d in card.instantiated_dice], [1, 1])
        self.assertEqual(self.target.hp, 97)

    def test_sky_pre_reveal_opens_at_three_and_recomputes_range_against_the_interceptor(self):
        card = self.cards["机动·贯彻长空"]
        self.actor.add_status("凝聚", 2)
        self.left.draw_card(3)
        self.assertFalse(card.can_open_pre_reveal)
        self.assertTrue(card.meets_use_requirements())
        self.actor.add_status("凝聚", 1)
        slow = self.recruit(self.right, dict(id="slow", name="慢速陪练", max_hp=30, rank="NORMAL", skills=[]))
        self.actor.speed, slow.speed, self.target.speed = 6, 1, 4
        reply = self.opposed(-40, 2, range_level=3)
        self.right.cardspace.hand.add_card(reply)
        phase = self.game.pre_reveal
        phase.start()
        self.assertIn(card, phase.attack_cards(self.left))
        phase.declare_attack(card, character=slow)
        phase.intercept(reply, 1)
        if phase.can_attack(self.left):
            phase.end_attack(self.left)
        phase.begin_resolution()
        for _ in range(500):
            self.game.next_step()
            if not self.game.pipeline.in_duel_phase:
                break
        self.assertEqual([d.type for d in card.instantiated_dice], ["blank", "blank"])
        self.assertEqual((slow.hp, self.target.hp), (30, 100))

    def test_sky_pays_eight_and_increases_base_before_the_multiplier(self):
        self.actor.add_status("能源", 8)
        self.actor.add_status("凝聚", 2)
        self.actor.speed, self.target.speed = 4, 1
        card = self.fight("机动·贯彻长空", opponent=self.opposed(0, 2))
        first, second = card.instantiated_dice
        self.assertEqual((first.base_value, second.base_value), (2, 2))
        self.assertEqual(second.final_score, (2 + second.value) * 2)
        self.assertEqual(card.use_state["spent_statuses"]["能源"], 8)

    def test_independent_chains_use_rounded_final_damage_and_recheck_remaining_stacks(self):
        self.actor.add_status("能源", 8)
        self.actor.add_status("凝聚", 2)
        self.target.add_status("烧伤", 20)
        receipts = []
        self.game.context.register_entries(self.target, [dict(trigger="AFTER DAMAGE", subject="target",
            operation=lambda ctx: receipts.append((ctx.event.get("damage_die"), ctx.event["damage_amount"])))])
        with patch.object(self.game.rng, "randint", return_value=1):
            card = self.fight("连环穿刺", opponent=self.opposed(-40, 4))
        first, second, third, last = card.instantiated_dice
        self.assertEqual([amount for die, amount in receipts if die is first], [3, 2, 1])
        self.assertEqual([amount for die, amount in receipts if die is third], [1, 1])
        self.assertEqual([d.final_score - d.value for d in (first, second, third, last)], [0, 8, 8, 10])
        # The successful ignition at one remaining layer consumes it and grants
        # energy and Bind even though there is no burn damage segment.
        self.assertEqual(self.actor.statuses["能源"], 8 - 6 + 6)
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual(self.target.statuses["束缚"], 6)
        self.assertNotIn("迅捷", self.actor.statuses)

    def test_chain_counts_burn_lost_between_die_use_and_the_clash_roll(self):
        self.target.add_status("烧伤", 4)
        # The defender responds during its first die's use, after both before-use windows.
        reply = self.opposed(-40, 2)
        self.game.context.register_entries(self.target, [{
            "trigger": "on_dice_use", "operation": {"op": "program", "code": ["$self", "烧伤", -4, "STATUS"]}
        }])
        card = self.fight("连环穿刺", opponent=reply)
        first_attack = card.instantiated_dice[1]
        self.assertEqual(first_attack.final_score - first_attack.value, 2)

    def test_a_failed_first_reroll_stops_immediately_using_the_residual_burn(self):
        self.target.add_status("烧伤", 12)
        self.actor.add_status("凝聚", 3)
        with patch.object(self.game.rng, "randint", return_value=8) as rng:
            self.fight("机动·贯彻长空")
        self.assertEqual(self.target.statuses["烧伤"], 7)
        rng.assert_called_once_with(1, 20)

    def test_b_rank_plan_b_and_cycle(self):
        self.actor.hp = 4
        self.left.draw_card(3)
        common = self.left.available_cost
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.actor.hp, self.actor.max_duels, self.left.available_cost), (5, 3, common + 1))
        self.actor.add_status("能源", 2)
        self.actor.add_status("凝聚", 2)
        card = self.fight("能源循环", opponent=self.opposed(-40, 2))
        self.assertEqual([d.final_bonus for d in card.instantiated_dice], [2, 2])
        self.assertEqual(self.actor.statuses["能源"], 10)
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual(self.actor.statuses["迅捷"], 1)
