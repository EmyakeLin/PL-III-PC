"""Play the bellfounder's and shipbreaker's card text through regular duels."""
import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.character import Character
from player.player import Player


class LightcoreBossTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = {data["name"]: data for data in load_characters_from_packs()}

    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(43))
        self.game.first_player = self.left
        self.target = self.recruit(self.right, dict(id="target", name="标靶", rank="NORMAL", max_hp=30, skills=[]))

    @staticmethod
    def recruit(player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def choose(self, name):
        self.boss = self.recruit(self.left, self.pool[name])
        self.game.start_turn()
        self.left.max_cost = 12
        return self.boss

    def play(self, *names):
        for index, name in enumerate(names):
            card = next(card for card in self.boss.skills if card.name == name)
            self.assertTrue(self.game.place_in_duel(1, card, index))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1500):
            self.game.next_step()
            if not self.game.pipeline.in_duel_phase or self.game.is_over:
                return
        self.fail("交锋未结束")

    def test_only_flying_clapper_is_ranged_and_can_open_pre_reveal(self):
        boss = self.choose("阙鸣")
        self.assertEqual((boss.max_hp, boss.max_duels, len(boss.skills)), (17, 3, 7))
        self.left.draw_card(7)
        self.game.pre_reveal.start()
        self.assertEqual([(c.name, c.range_level) for c in self.game.pre_reveal.attack_cards(self.left)],
                         [("百步飞椎", 2)])
        self.assertTrue(all(card.range_level == 0 for card in boss.skills[:-1]))

    def test_bell_resonance_builds_guard_and_is_capped(self):
        boss = self.choose("阙鸣")
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((len(self.left.cardspace.hand.content), boss.statuses["钟振"], boss.shield), (1, 1, 2))
        boss.add_status("钟振", 7)
        self.game.finish_turn()
        self.game.start_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((len(self.left.cardspace.hand.content), boss.statuses["钟振"], boss.shield), (2, 4, 3))

    def test_seven_then_four_sounds_against_the_refilled_integrity(self):
        boss = self.choose("阙鸣")
        boss.add_status("钟振", 2)
        self.target.lightcore_hp, self.target.max_lightcore_hp = 4, 12
        self.target.shield = 7
        self.play("复鸣")
        self.assertEqual((self.target.hp, self.target.lightcore_hp, self.target.max_lightcore_hp), (15, 4, 8))
        self.assertEqual((self.target.shield, boss.reinforced_shield), (7, 2))
        self.assertNotIn("钟振", boss.statuses)

    def test_insufficient_resonance_is_consumed_without_echo(self):
        boss = self.choose("阙鸣")
        boss.add_status("钟振", 1)
        initial = self.target.lightcore_hp
        self.play("复鸣")
        self.assertEqual((self.target.hp, self.target.lightcore_hp), (30, initial - 7))
        self.assertNotIn("钟振", boss.statuses)

    def test_charged_ultimate_uses_piercing_direct_damage(self):
        boss = self.choose("阙鸣")
        boss.add_status("钟振", 3)
        self.target.shield = 6
        self.play("百步飞椎")
        self.assertNotIn("钟振", boss.statuses)
        self.assertEqual(boss.skills[-1].final_bonus, 3)
        self.assertEqual((self.target.hp, self.target.shield), (25, 1))
        self.assertEqual(self.target.lightcore_hp, self.target.max_lightcore_hp)

    def test_chalk_and_pincers_follow_each_direct_segment_even_into_shields(self):
        boss = self.choose("沈砾")
        self.assertEqual((boss.max_hp, boss.max_duels, len(boss.skills)), (16, 3, 7))
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((boss.shield, len(self.left.cardspace.hand.content)), (2, 1))
        self.target.shield = 8
        initial = self.target.lightcore_hp
        self.play("弹粉线", "拔铆钳")
        self.assertEqual((self.target.hp, self.target.shield), (30, 4))
        self.assertEqual((self.target.lightcore_hp, boss.shield), (initial - 3 - 2 - 2, 4))
        self.assertNotIn("粉线", self.target.statuses)

    def test_sounding_finishes_low_integrity_without_spending_chalk(self):
        self.choose("沈砾")
        self.target.add_status("粉线", 1)
        self.target.lightcore_hp = 4
        self.play("验龙骨")
        self.assertEqual(self.target.statuses["粉线"], 1)
        self.assertEqual((self.target.lightcore_hp, self.target.max_lightcore_hp), (40, 40))
        self.assertEqual(self.target.hp, 15)

    def test_sounding_at_five_deals_piercing_then_two_lightcore(self):
        self.choose("沈砾")
        self.target.add_status("粉线", 1)
        self.target.lightcore_hp = 5
        self.target.shield = 4
        self.play("验龙骨")
        self.assertEqual((self.target.hp, self.target.shield, self.target.lightcore_hp), (28, 2, 3))
        self.assertNotIn("粉线", self.target.statuses)

    def test_strip_marks_before_the_piercing_die_uses_one_line(self):
        self.choose("沈砾")
        initial = self.target.lightcore_hp
        self.play("整舷剥离")
        self.assertEqual((self.target.lightcore_hp, self.target.hp), (initial - 5 - 2, 27))
        self.assertEqual(self.target.statuses["粉线"], 1)
