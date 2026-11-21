"""Exercise Sa's damage replacements against a real opponent in the clash pipeline."""
import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from player.player import Player


class SaDamagePriorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sa_data = next(c for c in load_characters_from_packs() if c["id"] == "plan_b_sa")
        cls.finisher = next(c["dice"][-1] for c in cls.sa_data["skills"] if c["id"] == "sa_disintegrate")

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        left, right = Player(1, "先手"), Player(2, "后手")
        self.game = Game([left, right], rng=random.Random(14))
        self.game.first_player = left
        self.sa = Character(self.sa_data, left)
        self.target = Character(dict(id="opponent", name="陪练", skills=[], rank="NORMAL", max_hp=15), right)
        left.characters.append(self.sa)
        right.characters.append(self.target)
        self.game.start_turn()
        self.damage = []
        self.game.context.register_entries(self.target, [dict(
            trigger="AFTER DAMAGE", subject="target",
            operation=lambda ctx: self.damage.append((ctx.event["damage_cause"], ctx.event["damage_amount"])))])

    def clash(self, die, *, enemy_wins=False, range_level=0):
        for actor, spec, level in (
            (self.sa, die, 0),
            (self.target, dict(type="block", level=1, base_value=50 if enemy_wins else -50, entries=[]), range_level),
        ):
            card = Card(actor.player, dict(id="probe", name="测试技能", cost=0, range_level=level, dice=[spec]), actor)
            actor.skills.append(card)
            self.assertTrue(self.game.place_in_duel(actor.player.side, card, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(300):
            self.game.next_step()
            if self.game.is_over or not self.game.pipeline.in_duel_phase:
                return
        self.fail(self.log.getvalue())

    def test_winning_zero_applies_one_stack_and_neither_propagates_nor_chases(self):
        self.sa.add_status("崩析", 6)
        self.clash(dict(type="slash", level=3, entries=["1物理"]))
        self.assertEqual(self.damage, [(None, 0)])
        self.assertEqual(self.target.statuses["崩析"], 1)
        self.assertEqual(self.game.next_turn_statuses, [])

    def test_finisher_forces_a_single_existing_stack_before_the_passive(self):
        self.sa.hp = 8
        self.sa.add_status("崩析", 6)
        self.target.add_status("崩析", 1)
        self.clash(self.finisher)
        self.assertEqual(self.damage, [("崩析爆发", 5), (None, 0)])
        self.assertNotIn("崩析", self.target.statuses)
        self.assertEqual(self.sa.hp, 10)
        self.assertEqual([(r[2], r[3]) for r in self.game.next_turn_statuses if r[1] is self.target],
                         [("虚弱", 1), ("崩离", 1)])

    def test_finisher_cannot_create_an_explosion_from_zero_stacks(self):
        self.sa.add_status("崩析", 6)
        self.clash(self.finisher)
        self.assertEqual(self.damage, [(None, 0)])
        self.assertEqual(self.target.statuses["崩析"], 1)
        self.assertEqual(self.game.next_turn_statuses, [])

    def test_cancelled_printed_damage_triggers_finisher_before_the_after_use_chase(self):
        self.game.context.register_entries(self.target, [
            dict(trigger="BEFORE DAMAGE", when={"damage_part": True}, operation="Cancel")])
        self.target.add_status("崩析", 1)
        self.clash(self.finisher)
        self.assertEqual(self.damage, [("崩析爆发", 5)])

    def test_suppressed_die_neither_chases_nor_activates_enemy_status(self):
        self.sa.add_status("崩析", 6)
        self.target.add_status("崩析", 1)
        self.clash(self.finisher, range_level=1)
        self.assertEqual(self.damage, [])
        self.assertEqual(self.target.statuses["崩析"], 1)

    def test_losing_an_attack_still_chases_at_the_six_stack_rate(self):
        self.sa.add_status("崩析", 6)
        self.clash(dict(type="slash", level=3, entries=["0物理"]), enemy_wins=True)
        self.assertEqual(self.damage, [(None, 2)])
        self.assertEqual([(r[2], r[3]) for r in self.game.next_turn_statuses], [("崩析", 1)])
