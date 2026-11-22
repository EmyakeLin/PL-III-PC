"""Play the surveyor's printed resource effects through the combat pipeline."""
import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.character import Character
from player.player import Player


class SurveyorTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "雾港"), Player(2, "对手")
        self.game = Game([self.left, self.right], rng=random.Random(19))
        self.game.first_player = self.left
        data = next(c for c in load_characters_from_packs() if c["id"] == "mistport_cen_yao")
        self.surveyor = self.recruit(self.left, data)
        self.target = self.recruit(self.right, dict(id="target", name="标靶", rank="NORMAL", max_hp=30, skills=[]))
        self.game.start_turn()

    @staticmethod
    def recruit(player, data):
        character = Character(data, player)
        player.characters.append(character)
        character.init_cards()
        character.setup_deck()
        return character

    def play(self, *names):
        cards = []
        for slot, name in enumerate(names):
            card = next(card for card in self.surveyor.skills if card.name == name)
            self.assertTrue(self.game.place_in_duel(self.left.side, card, slot))
            cards.append(card)
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1000):
            self.game.next_step()
            if not self.game.pipeline.in_duel_phase:
                return cards
        self.fail("交锋未结束")

    def test_tide_log_draws_and_only_refills_empty_calibration(self):
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.surveyor.statuses["校准"], len(self.left.cardspace.hand.content)), (1, 1))
        self.surveyor.add_status("校准", 1)
        self.game.finish_turn()
        self.game.start_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.surveyor.statuses["校准"], len(self.left.cardspace.hand.content)), (2, 2))

    def test_sounding_supplies_the_following_transit_and_delays_bind(self):
        _, transit = self.play("试水标", "双标成线")
        self.assertNotIn("校准", self.surveyor.statuses)
        self.assertEqual(transit.final_bonus, 2)
        self.assertEqual(self.target.hp, 26)
        self.assertNotIn("束缚", self.target.statuses)
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual(self.target.statuses["束缚"], 1)

    def test_melee_caps_calibration_and_funds_both_horizon_hits(self):
        self.surveyor.add_status("校准", 2)
        self.play("收线换尺", "地平线回声")
        self.assertEqual(self.surveyor.statuses["校准"], 1)
        self.assertEqual(self.target.hp, 30 - 1 - 3 - 2)

    def test_horizon_keeps_the_last_stack_without_damage_bonus(self):
        self.surveyor.add_status("校准", 1)
        self.play("地平线回声")
        self.assertEqual(self.surveyor.statuses["校准"], 1)
        self.assertEqual(self.target.hp, 30 - 2 - 1)

    def test_only_the_three_survey_shots_can_open_a_pre_reveal_duel(self):
        self.left.draw_card(5)
        phase = self.game.pre_reveal
        phase.start()
        self.assertEqual([(c.name, c.range_level) for c in phase.legal_cards()],
                         [("试水标", 1), ("双标成线", 2), ("地平线回声", 3)])
        brace = next(c for c in self.surveyor.skills if c.name == "折尺架势")
        self.assertEqual((brace.range_level, brace.ignore_range), (0, 1))
        with self.assertRaises(ValueError):
            phase.declare_attack(brace, character=self.target)
        phase.declare_attack(phase.legal_cards()[0], character=self.target)
        phase.end_attack()
        phase.pass_intercept(1, self.right)
        phase.begin_resolution()
        for _ in range(500):
            self.game.next_step()
            if not self.game.pipeline.in_duel_phase:
                break
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertFalse(self.game.cards_revealed)
        self.assertEqual((self.surveyor.statuses["校准"], self.target.hp), (1, 28))
