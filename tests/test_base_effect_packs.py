import io
import json
import random
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from game import Game
from loader import PACKS, load_characters_from_packs
from models.card import Card
from models.character import Character
from player.player import Player


class SharedEffectPackTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        shutil.copy(PACKS / "yellow_storm.json", self.directory)
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(31))
        self.game.first_player = self.left

    def recruit(self):
        sa, = load_characters_from_packs(self.directory)
        self.assertEqual(sa["id"], "plan_b_sa")
        actor = Character(sa, self.left)
        self.left.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        self.right.characters.append(Character(
            dict(id="target", name="陪练", max_hp=40, rank="NORMAL", skills=[]), self.right))
        return actor

    def test_sa_alone_uses_and_expires_shared_dice_levels(self):
        sa = self.recruit()
        self.game.start_turn()
        sa.add_status("崩析", 4)
        card = next(card for card in sa.skills if card.name == "彻灭心神")
        self.assertTrue(self.game.place_in_duel(1, card, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(500):
            self.game.next_step()
            if not self.game.pipeline.in_duel_phase:
                break
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertEqual([die.roll_max for die in card.instantiated_dice], [4, 6, 16])
        die = card.instantiated_dice[1]
        sa.add_status("骰子等级提升", 2)
        self.assertEqual(die.resolve_level(), die.printed_level.value + 1)
        self.game.finish_turn()
        self.assertEqual(die.resolve_level(), die.printed_level.value)

    def test_standalone_effect_pack_can_supply_speed_and_final_score(self):
        effects = self.directory / "effects"
        effects.mkdir()
        (effects / "training.json").write_text(json.dumps({
            "name": "训练状态包",
            "status_rules": {"步法": {"per_stack": {"speed": 2, "final_score": 3}}},
        }), encoding="utf-8")
        actor = self.recruit()
        actor.add_status("步法", 2)
        actor.add_status("束缚", 1)
        with patch.object(self.game.rng, "randint", return_value=2):
            self.assertEqual(actor.roll_speed(), 5)
        for kind, expected in (("evade", 12), ("blank", 6)):
            with self.subTest(kind=kind):
                card = Card(self.left, dict(id=kind, name=kind, cost=0, dice=[
                    dict(type=kind, level=2, base_value=1, multiplier=2)]), actor)
                die = card.get_current_die(self.game)
                die.value = 2
                self.assertEqual((die.base_value, die.value, die.get_value()), (1, 2, expected))


class SharedRestrictionPackTests(unittest.TestCase):
    def test_restriction_without_lin_qiu_uses_hand_order_and_clears_after_passing(self):
        with TemporaryDirectory() as directory:
            shutil.copy(PACKS / "plan_b_heris.json", directory)
            heris, = load_characters_from_packs(directory)
        team, enemy = Player(1, "甲"), Player(2, "乙")
        game = Game([team, enemy], rng=random.Random(31))
        game.deploy_rosters([[heris, heris], [heris]])
        game.first_player = team
        game.start_turn()
        team.draw_card(6)
        hand = team.cardspace.hand.content
        ranked = sorted(hand, key=lambda card: -card.cost)
        team.characters[0].add_status("限制", 3)
        self.assertEqual(ranked[2].cost, ranked[3].cost)
        self.assertEqual({c for c in hand if c.character.skill_restricted(c)}, set(ranked[:3]))
        game.finish_turn()
        self.assertEqual(team.team_statuses, {"限制": 3})
        game.prepare_turn()
        self.assertFalse(any(c.character.skill_restricted(c) for c in hand))
