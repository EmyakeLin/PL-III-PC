import io
import random
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from models.card import CardState
from models.character import Character
from models.opcode import OpCode
from pipeline.pipeline_errors import PipelineFinished
from player.player import Player


def character_data(name):
    return dict(id=name, name=name, rank="ELITE", max_hp=12, passive_skills=[], skills=[
        dict(id=f"{name}-{index}", name=f"{name}-{index}", cost=2, dice=[], entries=[])
        for index in range(5)
    ])


class TurnRules(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        redirect = redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.a, self.b = Player(1, "A"), Player(2, "B")
        self.game = Game([self.a, self.b], rng=random.Random(3))

    def add_character(self, player, name):
        character = Character(character_data(name), player)
        player.characters.append(character)
        character.init_cards()
        character.setup_deck()
        return character

    def test_roster_limit_and_reservation(self):
        pool = [character_data(str(i)) for i in range(6)]
        with patch("builtins.input", side_effect=["1"] * 6):
            self.game.select_character(pool)
        self.assertEqual([len(p.characters) for p in self.game.players], [3, 3])
        self.assertEqual(len(self.a.cardspace.draw.content), 15)
        self.assertEqual(len(pool), 6)

        small = Game([Player(1, "A"), Player(2, "B")])
        with patch("builtins.input", side_effect=["1", "1"]):
            small.select_character(pool[:2])
        self.assertEqual([len(p.characters) for p in small.players], [1, 1])

    def test_turn_limit_and_turn_number_cover_opening_and_closing_events(self):
        actor = self.add_character(self.a, "a")
        self.add_character(self.b, "b")
        ctx = self.game.context
        for node in ("before_turn_start", "on_turn_start", "after_turn_end"):
            ctx.register_entries(actor, [{
                "trigger": node,
                "operation": {"op": "program", "code": ["$self", node, "$turn_number", "STATUS"]},
                "turn_limit": {"key": "once", "count": 1} if node != "after_turn_end" else None,
            }])
        for total in (1, 3):
            ctx.dispatch_pipeline("before_turn_start")
            self.game.start_turn()
            ctx.dispatch_pipeline("on_turn_start")
            self.game.finish_turn()
            ctx.dispatch_pipeline("after_turn_end")
            self.assertEqual(actor.statuses, {"before_turn_start": total, "after_turn_end": total})

    def test_first_draw_and_empty_or_short_multicharacter_deck(self):
        a1 = self.add_character(self.a, "a1")
        a2 = self.add_character(self.a, "a2")
        self.add_character(self.b, "b")
        with patch("builtins.input", side_effect=["4"]):
            self.game.draw_phase()
        self.assertEqual(self.a.cardspace.hand.content, a1.skills[:3])
        self.assertEqual(self.a.cardspace.draw.content[-1], a1.skills[3])
        self.assertEqual(len(self.b.cardspace.hand.content), 3)
        self.game.turn_count = 1
        self.a.cardspace.draw.content.clear()
        with patch("builtins.input", side_effect=AssertionError("牌库不足时不要求弃牌")):
            self.a.draw_for_turn()
            self.a.cardspace.draw.content.extend(a2.skills[:2])
            self.a.draw_for_turn()
        self.assertEqual(self.a.cardspace.hand.content[-2:], a2.skills[:2])

    def test_dead_character_excluded_from_draw_count_and_duplicate_indices_rejected(self):
        first = self.add_character(self.a, "a")
        second = self.add_character(self.a, "b")
        third = self.add_character(self.a, "c")
        self.game.turn_count = 1
        with patch("builtins.input", side_effect=["4 4", "0 3", "3,4"]) as asks:
            self.a.draw_for_turn()
        self.assertEqual(asks.call_count, 3)
        self.assertEqual(self.a.cardspace.hand.content, first.skills[:2])
        second.is_alive = third.is_alive = False
        with patch("builtins.input", side_effect=AssertionError("单存活角色直接抽两张")):
            self.a.draw_for_turn()
        self.assertEqual(len(self.a.cardspace.hand.content), 4)

    def test_empty_turn_draws_before_speed_and_ends_after_reroll(self):
        self.add_character(self.a, "a")
        self.add_character(self.b, "b")
        events = []
        def roll(lower, upper):
            self.assertEqual((lower, upper), (1, 4))
            self.assertEqual(len(self.a.cardspace.hand.content), 3)
            return next(rolls)
        rolls = iter((2, 2, 1, 4))
        with patch.object(self.game.rng, "randint", side_effect=roll), \
                patch.object(Player, "place_card", return_value="ended"):
            with self.assertRaises(PipelineFinished):
                for _ in range(80):
                    events.append(self.game.next_step())
        self.assertLess(events.index("logic_draw_cards"), events.index("logic_resolve_speed"))
        self.assertIs(self.game.first_player, self.b)
        self.assertEqual(self.game.turn_count, 1)

    def test_placement_windows_allow_one_card_pass_and_end(self):
        self.game.first_player = self.b
        choices = iter(("placed", "placed", "passed", "ended", "placed", "ended"))
        actors = []
        def choose(player, game):
            actors.append((player.name, game.placed_this_window))
            return next(choices)
        with patch.object(Player, "place_card", choose):
            self.game.run_placement()
        self.assertEqual(actors, [("B", 0), ("A", 0), ("A", 1), ("B", 0), ("A", 0), ("A", 1)])

    def test_placement_binding_reveal_and_recycle_order(self):
        first = self.add_character(self.a, "a")
        self.add_character(self.b, "b")
        one, two, discard = first.skills[:3]
        self.a.cardspace.draw.move_card_to(one, self.a.cardspace.hand)
        self.a.cardspace.draw.move_card_to(two, self.a.cardspace.hand)
        self.a.cardspace.draw.move_card_to(discard, self.a.cardspace.delayed_discard)
        seen = []
        dispatch = self.game.context.dispatch_pipeline
        def record(name, **event):
            seen.append((name, event["side"], event["card"]))
            return dispatch(name, **event)
        with patch.object(self.game.context, "dispatch_pipeline", record):
            self.assertTrue(self.game.auto_place_in_duel(self.a.side, one))
            self.assertTrue(self.game.auto_place_in_duel(self.a.side, two))
        self.assertEqual([x[0] for x in seen], ["before_place", "on_hand_changed", "on_place", "after_place"] * 2)
        self.assertEqual(seen[3][1:], (1, one))
        self.assertFalse(self.a.cardspace.hand.content)
        self.assertIs(one.state, CardState.PLACED_FACE_DOWN)
        self.game.reveal_cards()
        self.assertIs(two.state, CardState.PLACED_FACE_UP)
        self.game.used_cards.extend([two, one])
        self.game.finish_turn()
        self.assertEqual(self.a.cardspace.draw.content[-3:], [two, one, discard])
        self.assertIs(one.state, CardState.DEFAULT)
        self.assertFalse(self.game.used_cards)
        self.assertEqual((self.a.max_cost, first.independent_cost), (0, 0))
        self.a.reset_on_turn_start()
        self.assertEqual((self.a.max_cost, first.independent_cost), (5, 1))

    def test_payment_only_at_use_and_no_partial_payment(self):
        first = self.add_character(self.a, "a")
        self.game.start_turn()
        card = first.skills[0]
        self.game.auto_place_in_duel(1, card)
        self.assertEqual((first.used_independent_cost, self.a.used_cost), (0, 0))
        self.a.used_cost = 5
        self.assertFalse(self.a.pay_skill_cost(card))
        self.assertEqual((first.used_independent_cost, self.a.used_cost), (0, 5))
        self.a.used_cost = 0
        self.assertTrue(self.a.pay_skill_cost(card))
        self.assertEqual((first.used_independent_cost, self.a.used_cost), (1, 1))

    def test_cancelled_placement_keeps_hand_successful_after_event_sees_only_board(self):
        actor = self.add_character(self.a, "a")
        card = actor.skills[0]
        self.a.cardspace.draw.move_card_to(card, self.a.cardspace.hand)
        ctx = self.game.context

        def cancel(opcode, timing):
            if opcode is OpCode.PLACE and timing == "BEFORE":
                ctx.cancel_op()

        with patch.object(ctx, "dispatch_opcode", cancel):
            self.assertFalse(self.game.auto_place_in_duel(1, card))
        self.assertIn(card, self.a.cardspace.hand.content)
        self.assertEqual(actor.used_duels, 0)

        def verify(opcode, timing):
            if opcode is OpCode.PLACE and timing == "AFTER":
                self.assertNotIn(card, self.a.cardspace.hand.content)
                self.assertIn(card, self.game.duelspace.space[0].content[1])

        with patch.object(ctx, "dispatch_opcode", verify):
            self.assertTrue(self.game.auto_place_in_duel(1, card))
