import io
import random
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from models.card import Card
from models.character import Character
from models.dice import DiceLevel
from player.player import Player


class SkillDiceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.game = Game([Player(1, "甲"), Player(2, "乙")], rng=random.Random(19))
        self.game.first_player = self.game.players[0]
        self.actors = []
        for player in self.game.players:
            actor = Character(dict(id=player.name, name=player.name, rank="NORMAL", max_hp=20, skills=[]), player)
            player.characters.append(actor)
            self.actors.append(actor)
        self.game.start_turn()

    def card(self, actor, dice):
        card = Card(actor.player, dict(id="skill", name="技能", cost=1, dice=dice), actor)
        actor.skills.append(card)
        return card

    def test_skill_and_die_modifiers_stack_without_changing_printed_dice(self):
        actor = self.actors[0]
        card = self.card(actor, [dict(type="guard", level=3, roll_max=10), dict(type="slash", level=2)])
        guard = card.get_current_die(self.game)
        guard.value = 99
        self.assertEqual((guard.level, guard.get_value()), (DiceLevel.D8, 10))
        actor.add_status("强壮", 3)
        actor.add_status("虚弱", 1)
        card.final_bonus = 2
        card.level_bonus = 1
        guard.value = 99
        self.assertEqual((guard.level, guard.roll_max, guard.value, guard.get_value()), (DiceLevel.D12, 12, 12, 16))
        guard.add_levels(2)
        self.assertEqual(guard.level, DiceLevel.D20)
        card.advance_die()
        attack = card.get_current_die(self.game)
        attack.value = 1
        self.assertEqual((attack.level, attack.get_value()), (DiceLevel.D8, 5))
        card.use_state["spent"] = 8
        card.reset_for_draw()
        fresh = card.get_current_die(self.game)
        self.assertEqual((fresh.level, fresh.roll_max, card.final_bonus, card.use_state), (DiceLevel.D8, 10, 0, {}))

    def test_repeated_die_gets_a_new_round_opponent_and_hit(self):
        attacker, defender = self.actors
        pairs, hits = [], []

        def on_hit(ctx):
            die = ctx.event["die"]
            hits.append(die)
            if len(hits) <= 3:
                self.assertTrue(die.request_repeat())
                self.assertFalse(die.request_repeat())

        def on_clash(ctx):
            die, other = ctx.event["die"], ctx.event["opponent_die"]
            pairs.append((die.position, other.position))

        hit_entry = dict(trigger="on_dice_hit", operation=on_hit)
        attack = self.card(attacker, [
            dict(type="blunt", level=1, base_value=20, entries=["1", hit_entry]),
            dict(type="pierce", level=1, base_value=20, entries=["2"]),
        ])
        guard = self.card(defender, [dict(type="guard", level=1) for _ in range(4)])
        self.game.context.register_entries(attacker, [dict(trigger="on_dice_clash", operation=on_clash)])
        for card in (attack, guard):
            self.assertTrue(self.game.place_in_duel(card.player.side, card, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", return_value=2) as roll:
            for _ in range(250):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertEqual(roll.call_count, 8)
        self.assertEqual(pairs, [(1, 1), (1, 2), (1, 3), (1, 4)])
        self.assertEqual((len(hits), len(set(hits)), defender.hp), (4, 4, 14))
        self.assertEqual(len(attack.dice), 2)
        self.assertEqual(self.game.used_cards, [attack, guard])
        self.game.finish_turn()
        self.assertFalse(any(entry.owner in hits for entry in self.game.context.entries))
        self.assertEqual(attack.get_current_die(self.game).position, 1)
        attack.advance_die()
        self.assertEqual(attack.get_current_die(self.game).position, 2)

    def test_blank_dice_only_compare_and_never_execute_their_entries(self):
        left, right = self.actors
        left.add_status("强壮", 8)
        seen = []
        for actor in self.actors:
            for result in ("win", "draw", "lose"):
                self.game.context.register_entries(actor, [dict(
                    trigger=f"on_clash_{result}",
                    operation=lambda ctx, r=result: seen.append((ctx.event["source"], r)),
                )])

        def forbidden(ctx):
            self.fail(f"空白骰的词条进入了 {ctx.event}")

        printed = ["9", *[dict(trigger=stage, operation=forbidden) for stage in (
            "before_dice_use", "BEFORE ROLL", "AFTER CLASH", "on_clash_win", "on_clash_draw",
            "on_clash_lose", "on_clash_skip", "on_dice_hit")]]
        duels = [(20, "slash", 0), (0, "blank", 0), (20, None, 0),
                 (0, "guard", 20), (0, "slash", 20)]
        for i, (base, opposing_kind, opposing_base) in enumerate(duels):
            card = self.card(left, [dict(type="blank", level=1, base_value=base, entries=printed)])
            die = card.get_current_die(self.game)
            die.value = 1
            self.assertEqual(die.get_value(), 1 + base)
            self.assertFalse(die.is_passive or die.is_attack)
            self.assertEqual(self.game.context.register_entries(die, printed), [])
            self.game.context.resolve_hit(die, right)
            self.assertTrue(self.game.place_in_duel(left.player.side, card, i))
            if opposing_kind:
                other = self.card(right, [dict(type=opposing_kind, level=1,
                                               base_value=opposing_base, entries=["1"])])
                self.assertTrue(self.game.place_in_duel(right.player.side, other, i))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", return_value=1) as roll:
            for _ in range(400):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertEqual(roll.call_count, 8)
        self.assertEqual(seen, [(left, "win"), (right, "lose"), (left, "draw"), (right, "draw"),
                                (left, "lose"), (right, "win"), (left, "lose"), (right, "win")])
        self.assertEqual((left.hp, right.hp), (19, 20))
