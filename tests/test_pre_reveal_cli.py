import io
import re
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from models.character import Character
from player.player import Player
from pre_reveal_cli import run_declarations


class PreRevealCliTests(unittest.TestCase):
    def test_players_choose_actions_from_public_table_while_other_responses_are_pending(self):
        a, b = Player(1, "甲"), Player(2, "乙")
        game = Game([a, b])
        game.first_player = a
        for player, labels in [(a, ("甲一", "甲二", "甲保留")), (b, ("乙反攻", "乙迎击", "乙保留"))]:
            skills = [dict(id=name, name=name, cost=1, dice=[], pre_reveal=name != "乙迎击")
                      for name in labels]
            actor = Character(dict(id=player.name, name=player.name, rank="NORMAL",
                                   max_hp=6, skills=skills), player)
            player.characters.append(actor)
            actor.init_cards()
            for card in actor.skills:
                player.cardspace.hand.add_card(card)

        steps = [
            (None, "甲 · 主动出牌"), (a, "甲一"), (a, "乙　生命"),
            (None, "乙 · 回应开牌前交锋 1"), (b, ""),
            (None, "甲 · 主动出牌"), (a, "甲二"), (a, "乙　生命"),
            (None, "甲 · 结束主动进攻"),
            (None, "乙 · 主动出牌"), (b, "乙反攻"), (b, "甲　生命"),
            (None, "乙 · 回应开牌前交锋 2"), (b, "乙迎击"),
            (None, "乙 · 结束主动进攻"),
            (None, "甲 · 回应开牌前交锋 3"), (a, "放行开牌前交锋 3"),
            (None, "乙 · 回应开牌前交锋 1"), (b, "放行开牌前交锋 1"),
        ]
        output = io.StringIO()
        offset = 0

        def answer(prompt):
            nonlocal offset
            player, pick = steps.pop(0)
            self.assertIs(game._private_player, player)
            menu = output.getvalue()[offset:]
            offset = output.tell()
            if player is None:
                self.assertNotIn("甲保留", menu)
                self.assertNotIn("乙保留", menu)
            if not pick:
                return ""
            options = re.findall(r"^  \[(\d+)\] (.+)$", menu, re.MULTILINE)
            return next(key for key, label in options if pick in label)

        phase = game.pre_reveal
        phase.start()
        with redirect_stdout(output), patch("builtins.input", answer):
            run_declarations(game)
        self.assertFalse(steps)
        self.assertIsNone(game._private_player)
        self.assertEqual(phase.phase, "ready")
        slots = phase.space.space
        self.assertEqual([slot.attack_card.name for slot in slots], ["甲一", "甲二", "乙反攻"])
        self.assertEqual([slot.intercept_card.name if slot.intercept_card else None for slot in slots],
                         [None, "乙迎击", None])
        self.assertTrue(all(slot.ready for slot in slots))
