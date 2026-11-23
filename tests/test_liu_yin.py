"""流阴及其引入的拼点规则，经真实卡面、词条和执行器结算。"""
import random
import unittest
from unittest.mock import patch

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
