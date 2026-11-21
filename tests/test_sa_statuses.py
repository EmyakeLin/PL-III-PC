import io
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.dice import Dice
from models.opcode import OpCode
from player.player import Player


class SaStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = next(spec for spec in load_characters_from_packs() if spec["id"] == "plan_b_sa")

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        left, right = Player(1, "甲方"), Player(2, "乙方")
        self.game = Game([left, right])
        self.ctx = self.game.context
        self.game.first_player = left
        self.sa = Character(self.pack, left)
        self.target = Character(dict(id="target", name="陪练", rank="NORMAL", max_hp=16, skills=[]), right)
        left.characters.append(self.sa)
        right.characters.append(self.target)
        self.game.start_turn()

    def activate(self, target):
        return self.ctx.eval_block([target, "崩析", OpCode.ACTIVATE_STATUS])

    def test_early_activation_needs_a_holder_and_uses_original_hp(self):
        self.assertFalse(self.activate(self.target))
        self.target.add_status("崩离", 4)
        self.target.add_status("崩析", 1)
        self.sa.hp = 8
        self.assertTrue(self.activate(self.target))
        self.assertEqual((self.target.hp, self.target.max_hp, self.sa.hp), (6, 12, 11))
        self.assertNotIn("崩析", self.target.statuses)
        self.assertIn("崩析爆发 对 陪练 造成 6 点伤害", self.log.getvalue())
        self.assertEqual([(t, n) for _, t, n, _, _ in self.game.next_turn_statuses], [(self.target, "虚弱")])

    def test_attaining_eight_explodes_immediately_but_sa_waits_for_turn_end(self):
        self.target.add_status("崩析", 7)
        self.target.add_status("崩析", 1)
        self.assertEqual(self.target.hp, 10)
        self.assertNotIn("崩析", self.target.statuses)
        self.sa.add_status("崩析", 9)
        self.assertFalse(self.activate(self.sa))
        self.assertEqual(self.sa.statuses["崩析"], 9)
        self.game.context.dispatch_pipeline("before_turn_end")
        self.assertNotIn("崩析", self.sa.statuses)
        self.assertEqual(self.sa.hp, 12)

    def test_status_modifiers_apply_to_grant_and_to_burst_before_shields(self):
        self.target.add_status("崩裂", 2)
        self.target.add_status("崩析", 1)
        self.assertEqual(self.target.statuses["崩析"], 2)
        self.target.add_status("弥合", 3)
        self.target.add_status("崩析", 1)
        self.assertEqual(self.target.statuses["崩析"], 3)
        self.sa.hp = 8
        self.target.concept_shield = 5
        self.activate(self.target)
        self.assertEqual((self.target.hp, self.target.concept_shield, self.sa.hp), (16, 0, 10))
        self.assertIn("崩析爆发 对 陪练 造成 5 点伤害", self.log.getvalue())

    def test_high_mending_can_zero_burst_without_scheduling_weakness(self):
        self.target.add_status("崩析", 1)
        self.target.add_status("弥合", 6)
        self.assertTrue(self.activate(self.target))
        self.assertNotIn("崩析", self.target.statuses)
        self.assertEqual((self.target.hp, self.game.next_turn_statuses), (16, []))

    def test_nested_activation_and_unrelated_reactive_damage_do_not_duplicate_a_burst(self):
        self.target.add_status("崩析", 1)
        self.sa.hp = 8
        self.ctx.register_entries(self.sa, [{
            "trigger": "AFTER DAMAGE", "subject": "any", "when": {"damage_cause": "崩析爆发"},
            "operation": {"op": "program", "code": [
                "$target", "崩析", "ACTIVATE_STATUS", "POP",
                "$target", 2, "pierce", "none", "DAMAGE",
            ]},
        }])
        self.assertTrue(self.activate(self.target))
        self.assertEqual((self.target.hp, self.sa.hp), (8, 11))
        self.assertNotIn("崩析", self.target.statuses)
        self.assertEqual(self.log.getvalue().count("崩析爆发 对"), 1)

    def test_lethal_burst_removes_the_status_and_notifies_a_living_witness(self):
        self.target.add_status("崩析", 1)
        self.target.hp, self.sa.hp = 1, 8
        self.assertTrue(self.activate(self.target))
        self.assertFalse(self.target.is_alive)
        self.assertNotIn("崩析", self.target.statuses)
        self.assertEqual(self.sa.hp, 11)

    def test_end_of_turn_settles_and_removes_temporary_modifiers(self):
        self.sa.add_status("崩析", 5)
        self.sa.add_status("弥合", 2)
        self.target.add_status("崩裂", 1)
        self.game.context.dispatch_pipeline("before_turn_end")
        self.assertEqual((self.sa.statuses, self.target.statuses), ({"崩析": 3}, {"崩析": 1}))

    def test_separation_is_permanent_and_max_hp_loss_is_not_damage(self):
        self.target.add_status("崩离", 4)
        self.target.add_status("崩离", -2)
        self.target.clear_status("崩离")
        self.assertEqual(self.ctx.eval_block([self.target, "崩离", "all", OpCode.SPEND_STATUS]), 0)
        self.assertEqual((self.target.statuses, self.target.hp, self.target.original_max_hp),
                         ({"崩离": 4}, 12, 16))
        self.target.add_status("崩离", 12)
        self.assertEqual((self.target.max_hp, self.target.hp, self.target.is_alive), (0, 0, False))
        self.assertEqual(self.target.max_lightcore_hp, Character.initial_lightcore_max(16))

    def test_dice_damage_reduction_and_once_per_use_spread_use_opcodes(self):
        self.sa.add_status("崩析", 6)
        card = Card(self.sa.player, dict(id="t", name="测试", cost=0, dice=[]), self.sa)
        die = Dice(dict(type="slash", level=2, entries=[]), self.game)
        die.card = card
        with self.ctx.binding(die=die, card=card):
            self.assertEqual(self.ctx.deal_damage(self.sa, self.target, 2, damage_part=True, damage_die=die), 0)
            self.assertEqual(self.game.next_turn_statuses, [])
            self.target.shield = 2
            for _ in range(2):
                self.assertEqual(self.ctx.deal_damage(self.sa, self.target, 3, damage_part=True, damage_die=die), 1)
            self.assertEqual(self.target.hp, 16)
            self.assertEqual([(t, n, v) for _, t, n, v, _ in self.game.next_turn_statuses],
                             [(self.target, "崩析", 1)])
            self.target.add_status("崩析", 1)
            next_die = Dice(dict(type="slash", level=2, entries=[]), self.game)
            next_die.card = card
            self.assertEqual(self.ctx.deal_damage(self.sa, self.target, 2, damage_die=next_die), 2)
            self.assertEqual(self.target.statuses["崩析"], 2)
            self.assertEqual([n for _, _, n, _, _ in self.game.next_turn_statuses], ["崩析", "虚弱"])
