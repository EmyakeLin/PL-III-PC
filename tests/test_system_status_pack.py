import unittest
from unittest.mock import patch

from game import Game
from models.character import Character
from models.dice import Dice
from models.opcode import OpCode
from player.player import Player


def fighter(player, **rules):
    return Character(dict(id="fighter", name="测试角色", rank="NORMAL", max_hp=15, skills=[], **rules), player)


class SystemStatusPackTests(unittest.TestCase):
    def test_detached_character_resolves_stacked_statuses_through_the_same_damage_events(self):
        actor = fighter(Player(1, "甲"))
        actor.add_status("burn", 8)
        actor.add_status("fatal_stagger", 2)
        actor.add_shield("normal", 4)
        actor.on_turn_end()
        self.assertEqual((actor.hp, actor.shield), (15, 0))
        self.assertEqual(actor.statuses, {"烧伤": 4, "致命失衡": 1})

        actor.add_status("bleed", 6)
        actor.after_damage_part()
        self.assertEqual((actor.hp, actor.statuses["裂血"], actor.bleed_burst), (13, 4, True))
        actor.begin_dice_round()
        actor.after_damage_part()
        actor.after_damage_part()
        self.assertEqual((actor.hp, actor.bleed_burst), (10, False))
        self.assertNotIn("裂血", actor.statuses)
        actor.after_damage_part()
        self.assertEqual(actor.hp, 10)

    def test_aliases_share_stacks_costs_checks_and_notifications_in_a_bare_game(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right])
        actor = fighter(left)
        observed = []
        game.context.register_entries(actor, [{
            "trigger": "AFTER STATUS", "when": {"status": "呼吸"},
            "operation": lambda ctx: observed.append(ctx.event["actual_delta"]),
        }])
        game.context.eval_block([actor, "呼吸法", 8, OpCode.STATUS])
        self.assertEqual(observed, [6])
        die = Dice(dict(type="slash", level=1))
        with patch.object(game.rng, "randint", return_value=6) as roll:
            self.assertTrue(actor.on_attack_hit(die, fighter(right)))
            self.assertEqual(game.context.eval_block([actor, "breath", 1, OpCode.SPEND_STATUS]), 1)
            self.assertFalse(actor.on_attack_hit(die, fighter(right)))
        self.assertEqual(roll.call_args.args, (1, 6))
        self.assertEqual(actor.statuses, {"呼吸": 5})

    def test_stagger_check_uses_the_pack_die_and_failure_from_zero(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right])
        actor = fighter(left)
        with patch.object(game.rng, "randint", return_value=20) as roll:
            self.assertFalse(actor.trigger_stagger())
            self.assertEqual(actor.statuses, {"失衡": 2})
            actor.add_status("stagger", 99)
            self.assertTrue(actor.trigger_stagger())
        self.assertEqual(roll.call_args.args, (1, 20))
        self.assertEqual(actor.statuses, {"失衡": 15, "致命失衡": 1})
