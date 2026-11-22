import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from player.player import Player


class HerisTests(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(91))
        self.game.first_player = self.left
        template = next(c for c in load_characters_from_packs() if c["id"] == "plan_b_heris")
        self.heris = self.recruit(self.left, template)
        self.target = self.partner(self.right, "标靶")
        self.cards = {card.name: card for card in self.heris.skills}
        self.game.start_turn()

    @staticmethod
    def recruit(player, template):
        actor = Character(template, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def partner(self, player, name):
        return self.recruit(player, dict(id=name, name=name, rank="NORMAL", max_hp=100, skills=[]))

    @staticmethod
    def exercise(actor, name, die_entries, *, kind="blunt", base=0, **traits):
        return Card(actor.player, dict(id=name, name=name, cost=0, dice=[
            dict(type=kind, level=1, base_value=base, entries=effects) for effects in die_entries
        ], **traits), actor)

    def fight(self, cards, opponent=None):
        for slot, card in enumerate(cards):
            self.assertTrue(self.game.place_in_duel(1, card, slot))
        if opponent:
            self.assertTrue(self.game.place_in_duel(2, opponent, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1600):
            self.game.next_step()
            if not self.game.pipeline.in_duel_phase or self.game.is_over:
                return
        self.fail(self.log.getvalue()[-2000:])

    def test_b_rank_heal_and_plan_b_check_own_three_cards(self):
        self.assertEqual((self.heris.hp, len(self.cards), self.heris.max_duels), (6, 3, 2))
        self.heris.hp = 4
        self.left.draw_card(3)
        cost = self.left.available_cost
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.heris.hp, self.heris.max_duels, self.left.available_cost), (5, 3, cost + 1))

    def test_hammer_with_one_energy_hits_a_fresh_target_and_spends_what_it_can(self):
        self.heris.add_status("能源", 1)
        self.fight([self.cards["重锤！"]])
        self.assertEqual((self.target.hp, self.target.statuses["烧伤"]), (99, 1))
        self.assertEqual(self.heris.rule_state.get("火焰之锤次数", 0), 0)
        self.assertEqual(self.heris.rule_state["能源消耗余量"], 1)
        self.assertNotIn("能源", self.heris.statuses)

    def test_first_two_qualifying_blunts_apply_burn_then_subsequent_blunts_gain_damage(self):
        self.target.add_status("烧伤", 14)
        self.fight([self.exercise(self.heris, "四次打击", [["1物理"]] * 4)])
        self.assertEqual((self.target.hp, self.target.statuses["烧伤"]), (92, 16))
        self.assertEqual(self.heris.rule_state["火焰之锤次数"], 2)
        self.game.finish_turn()
        self.game.start_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.fight([self.cards["重锤！"]])
        self.assertEqual(self.heris.rule_state["火焰之锤次数"], 1)

    def test_conversion_reads_burn_on_use_then_again_at_second_hit(self):
        self.target.add_status("烧伤", 6)
        self.heris.add_status("能源", 4)
        self.fight([self.cards["烈火化能"]])
        self.assertEqual(self.heris.statuses["能源"], 10)
        self.assertEqual(self.target.statuses["烧伤"], 9)
        self.assertEqual(len(self.left.cardspace.hand.content), 1)

    def test_crush_uses_paid_energy_and_the_actual_burn_consumed_by_each_die(self):
        ally = self.partner(self.left, "队友")
        self.target.add_status("烧伤", 6)
        self.heris.add_status("能源", 8)
        crush = self.cards["击溃！"]
        self.fight([crush])
        self.assertEqual((crush.level_bonus, crush.use_state["首骰额外烧伤"]), (2, 4))
        self.assertEqual([die.base_value for die in crush.instantiated_dice], [2, 2, 2])
        self.assertEqual([die.roll_max for die in crush.instantiated_dice], [16, 20, 8])
        self.assertEqual(self.heris.statuses["凝聚"], 1)
        self.assertEqual(self.heris.statuses["能源"], 8)
        self.assertEqual(ally.statuses["能源"], 2)
        self.assertEqual(self.target.statuses["烧伤"], 2)
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual((self.target.statuses["虚弱"], self.target.statuses["束缚"]), (1, 1))

    def test_concentrated_resident_loss_lands_the_effects_but_skips_printed_damage(self):
        self.heris.add_status("凝聚", 3)
        self.target.add_status("烧伤", 10)
        opponent = self.exercise(self.target, "挡住三骰", [[], [], []], kind="block", base=40)
        self.fight([self.cards["击溃！"]], opponent)
        first, second, third = self.cards["击溃！"].instantiated_dice
        self.assertEqual([die.clash_result for die in (first, second, third)], ["lose"] * 3)
        self.assertEqual([die.landed_hits for die in (first, second, third)], [1, 0, 0])
        self.assertEqual(self.target.hp, 97)
        self.assertEqual(self.target.statuses["烧伤"], 8)
        self.assertEqual(self.heris.statuses["能源"], 5)

    def test_crush_keeps_the_range_it_ignored_on_use_if_concentration_changes(self):
        crush = self.cards["击溃！"]
        self.heris.add_status("凝聚", 1)
        self.assertEqual(crush.effective_ignore_range, 0)
        self.heris.add_status("凝聚", 1)
        self.assertEqual(crush.effective_ignore_range, 2)
        self.game.context.register_entries(self.heris, [
            dict(trigger="after_dice_hit", operation=lambda ctx: self.heris.clear_status("凝聚"))
        ])
        ranged = self.exercise(self.target, "强化远程", [[], [], []], base=-40, range_level=2)
        self.fight([crush], ranged)
        self.assertNotIn("凝聚", self.heris.statuses)
        self.assertEqual(crush.effective_ignore_range, 2)
        self.assertEqual([die.landed_hits for die in crush.instantiated_dice], [1, 1, 1])

    def test_each_ally_can_prompt_one_free_copy_per_turn_without_the_printed_hammer(self):
        alice = self.partner(self.left, "先手")
        bob = self.partner(self.left, "后手")
        self.heris.add_status("能源", 5)
        self.target.add_status("烧伤", 25)
        hammer = self.cards["重锤！"]
        hammers = []
        self.game.context.register_entries(self.heris, [
            dict(trigger="on_skill_use", operation=lambda ctx: hammers.append(ctx.event["card"]))
        ])
        self.fight([self.exercise(alice, "两次点火", [["引燃"], ["引燃"]]),
                    self.exercise(bob, "一记点火", [["引燃"]])])
        self.assertEqual([card.id for card in hammers], [hammer.id, hammer.id])
        self.assertTrue(all(card is not hammer for card in hammers))
        self.assertEqual(len(set(hammers)), 2)
        self.assertIn(hammer, self.left.cardspace.draw.content)
        self.assertEqual((self.heris.statuses["能源"], self.heris.used_independent_cost), (1, 0))
        self.assertEqual(self.left.used_cost, 0)

        self.game.finish_turn()
        self.game.start_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.target.add_status("烧伤", 8)
        self.fight([self.exercise(alice, "再次点火", [["引燃"]])])
        self.assertEqual(len(hammers), 3)
        self.assertNotIn("能源", self.heris.statuses)


if __name__ == "__main__":
    unittest.main()
