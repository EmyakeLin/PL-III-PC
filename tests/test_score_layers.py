import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from models.card import Card
from models.character import Character
from models.duel import ClashPair
from player.player import Player


class ScoreLayers(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        players = [Player(1, "甲"), Player(2, "乙")]
        self.game = Game(players)
        self.game.first_player = players[0]
        self.cards = []
        for player, base in zip(players, (1, 5)):
            actor = Character(dict(id=player.name, name=player.name, rank="NORMAL", max_hp=10, skills=[]), player)
            player.characters.append(actor)
            card = Card(player, dict(id="test", name="测试技能", cost=0,
                                     dice=[dict(type="slash", level=2, base_value=base, entries=["1"])]), actor)
            self.cards.append(card)
            actor.skills.append(card)
        self.game.start_turn()

    def listen(self, owner, trigger, code, **spec):
        self.game.context.register_entries(owner, [{
            "trigger": trigger, "operation": {"op": "program", "code": code}, **spec,
        }])

    def battle(self, roll):
        for skill in self.cards:
            self.game.place_in_duel(skill.player.side, skill, 0)
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", return_value=roll):
            for _ in range(200):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
        self.assertFalse(self.game.pipeline.in_duel_phase)

    def test_clash_floor_is_independent_of_final_score_and_runs_once_per_comparison(self):
        card, opposing = self.cards
        actor = card.character
        actor.add_status("强壮", 1)
        actor.add_status("试验层数", 14)
        self.listen(actor, "BEFORE RESOLVE_CLASH_SCORE",
                    ["$value_ref", "$self", "试验层数", "STATUS_COUNT", 10, "MIN", "VALUE_FLOOR"])
        self.listen(actor, "BEFORE RESOLVE_CLASH_SCORE", [1, "SUB"])
        self.listen(actor, "AFTER RESOLVE_CLASH_SCORE", ["$self", "求值次数", 1, "STATUS"])
        self.listen(actor, "on_clash_win", ["$card", "最终", "$final_score", "SET_SKILL_STATE",
                                           "$card", "拼点", "$clash_score", "SET_SKILL_STATE"])
        self.battle(2)
        die = card.instantiated_dice[0]
        self.assertEqual((die.base_value, die.value, die.get_value(), die.clash_score), (1, 2, 4, 10))
        self.assertEqual(card.use_state, {"最终": 4, "拼点": 10})
        self.assertEqual(opposing.character.hp, 9)
        self.assertIn("最终 4 → 拼点 10", self.log.getvalue())
        self.assertEqual(actor.statuses["求值次数"], 1)
        self.assertEqual(self.game.context.stack, [])

    def test_ceiling_can_target_final_or_clash_independently(self):
        left, right = self.cards
        self.listen(left.character, "BEFORE RESOLVE_FINAL_SCORE", ["$value_ref", 8, "VALUE_CEILING"])
        self.listen(left.character, "BEFORE RESOLVE_FINAL_SCORE", [10, "ADD"])
        self.listen(right.character, "BEFORE RESOLVE_CLASH_SCORE", ["$value_ref", 5, "VALUE_CEILING"])
        a, b = [c.get_current_die(self.game) for c in self.cards]
        a.value = b.value = 2
        pair = ClashPair({1: a, 2: b})
        self.assertEqual(pair.clash_check(), {1: "win", 2: "lose"})
        self.assertEqual((a.final_score, a.clash_score, b.final_score, b.clash_score), (8, 8, 7, 5))

    def test_level_uses_all_modifiers_then_applies_bounds_without_erasing_them(self):
        card = self.cards[0]
        die = card.get_current_die(self.game)
        actor = card.character
        self.listen(actor, "BEFORE RESOLVE_DIE_LEVEL", [
            "$value_ref", "$printed_level", "VALUE_FLOOR", "$value_ref", "$printed_level", "VALUE_CEILING",
        ], when={"owner_status_at_least": {"免疫": 1}})
        self.listen(actor, "BEFORE RESOLVE_DIE_LEVEL", ["$self", "降低", "STATUS_COUNT", "SUB"])
        actor.add_status("降低", 2)
        self.assertEqual(die.resolve_level(), 1)
        card.level_bonus = 2
        die.add_levels(1)
        self.assertEqual(die.resolve_level(), 3)
        actor.add_status("免疫", 1)
        with patch.object(self.game.rng, "randint", return_value=6) as roll:
            die.roll()
        roll.assert_called_once_with(1, 6)
        self.assertEqual((die.level.value, die.printed_level.value), (2, 2))
        actor.add_status("免疫", -1)
        self.assertEqual(die.resolve_level(), 3)

    def test_skill_level_change_between_roll_and_comparison_updates_current_die(self):
        card = self.cards[0]
        self.listen(card.character, "on_dice_clash", ["$card", -1, "SKILL_LEVEL_ADD"])
        self.battle(6)
        die = card.instantiated_dice[0]
        self.assertEqual((die.roll_max, die.value, die.final_score), (4, 4, 5))
