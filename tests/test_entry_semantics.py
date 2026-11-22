"""Exercise entry lowering and VM execution in isolation from a match or card pack."""

from collections import Counter
from types import SimpleNamespace
import unittest

from context.context import Context
from entry.commands import CommandSet, expand_command
from entry.entry import Entry
from entry.effects import run_effect
from entry.program import run_program
from game import Game
from models.character import Character
from models.opcode import OpCode
from models.roster import RosterDraft
from player.draw_choice import DrawChoice
from terminal_events import format_fact


class TracedContext(Context):
    def __init__(self):
        super().__init__()
        self.trace = []

    def dispatch_opcode(self, opcode, timing):
        self.trace.append((opcode, timing, tuple(self.stack)))
        return super().dispatch_opcode(opcode, timing)


class RoundCounterTests(unittest.TestCase):
    def test_queries_and_recording_are_independent(self):
        for initial in (0, 1, 2, 19, 2**100):
            for key in ("", "次数/一", "second key"):
                with self.subTest(initial=initial, key=key):
                    subject = SimpleNamespace(round_triggers=Counter({key: initial}))
                    vm = TracedContext()
                    for _ in range(2):
                        vm.eval_block([subject, key, OpCode.ROUND_TRIGGER_COUNT])
                        self.assertEqual(vm.pop(), initial)
                    vm.eval_block([subject, key, OpCode.RECORD_ROUND_TRIGGER])
                    self.assertEqual(subject.round_triggers[key], initial + 1)
                    self.assertEqual(vm.stack, [])
                    self.assertEqual([op for op, timing, _ in vm.trace if timing == "BEFORE"],
                                     [OpCode.ROUND_TRIGGER_COUNT] * 2 + [OpCode.RECORD_ROUND_TRIGGER])

    def test_old_spelling_reads_compares_then_records(self):
        actor = SimpleNamespace(is_alive=True, player=None, round_triggers=Counter())
        entry = Entry.from_spec(actor, {"trigger": "example", "operation": []})
        for expected in (True, False, False):
            vm = TracedContext()
            run_program(vm, entry, ["k", "ONCE_PER_ROUND", "POP"])
            self.assertEqual([op for op, timing, _ in vm.trace if timing == "BEFORE"],
                             [OpCode.DUP, OpCode.SWAP, OpCode.ROUND_TRIGGER_COUNT, OpCode.LT,
                              OpCode.SWAP, OpCode.SWAP, OpCode.RECORD_ROUND_TRIGGER, OpCode.POP])
            self.assertIs(vm.trace[-2][2][-1], expected)
        self.assertEqual(actor.round_triggers["k"], 3)
        parent = actor.round_triggers
        Character.begin_dice_round(actor)
        self.assertEqual(actor.round_triggers["k"], 0)
        self.assertEqual(parent["k"], 3)


class CommandTests(unittest.TestCase):
    def test_operand_types_and_extension(self):
        vocabulary = CommandSet()

        @vocabulary.define("PAIR")
        def pair(left, right):
            return [left, right]

        for number in (-2**97, -1, 0, 1, 27, 2**101):
            self.assertEqual(vocabulary.expand(f"PAIR {number} $target"), [number, "$target"])
        for text in ("含 空格", "$target", "DRAW", "false"):
            self.assertEqual(vocabulary.expand(f'PAIR "{text}" true'), [{"literal": text}, True])
        for line in ("PAIR 7", "PAIR 1 2 3", 'PAIR "a"b', 'PAIR "unterminated'):
            with self.assertRaises(ValueError):
                vocabulary.expand(line)
        self.assertIsNone(vocabulary.expand("UNKNOWN 1"))

    def test_draw_reaches_the_same_executor_from_both_entry_forms(self):
        for amount in (-1, 0, 1, 3, 2**90):
            line = f"DRAW {amount}"
            self.assertEqual(expand_command(line), ["$recipient_player", amount, OpCode.DRAW])
            for operation in (line, {"op": "program", "code": [line]}):
                with self.subTest(operation=operation):
                    class Pile:
                        def __init__(self, cards):
                            self.content = list(cards)

                        def move_card_to(self, index, other):
                            other.content.append(self.content.pop(index))

                    zones = SimpleNamespace(draw=Pile("abc"), hand=Pile([]))
                    player = SimpleNamespace(cardspace=zones)
                    actor = SimpleNamespace(is_alive=True, player=player)
                    entry = Entry.from_spec(actor, {"trigger": "example", "operation": operation})
                    vm = TracedContext()
                    run_effect(vm, entry, entry.operation)
                    self.assertEqual(vm.trace, [(OpCode.DRAW, "BEFORE", (player, amount)),
                                                (OpCode.DRAW, "AFTER", ())])
                    self.assertEqual(zones.hand.content, list("abc"[:max(0, amount)]))


class RosterExecutorTests(unittest.TestCase):
    def test_rejected_choices_leave_both_teams_and_pool_intact(self):
        members = [{"id": key} for key in "abcd"]
        draft = RosterDraft(members, seats=2, maximum=7)
        self.assertEqual(draft.limit, 3)
        for invalid in ([], members, members[:1] * 2, [{"id": "absent"}]):
            with self.assertRaises(ValueError):
                draft.submit(invalid)
            self.assertEqual(draft.pool, members)
            self.assertEqual(draft.teams, [])
        draft.submit(members[1:3])
        draft.submit([members[3], members[0]])
        self.assertEqual(draft.teams, [members[1:3], [members[3], members[0]]])

    def test_a_mirror_is_released_only_after_a_team_finishes(self):
        mirror = {"id": "m", "mirror_allowed": True}
        draft = RosterDraft([mirror], seats=2, maximum=3)
        draft.submit([mirror])
        draft.submit([mirror])
        self.assertEqual(draft.teams, [[mirror], [mirror]])
        with self.assertRaises(ValueError):
            draft.submit([mirror])


class DrawExecutorTests(unittest.TestCase):
    def test_every_candidate_can_be_kept_or_bottomed_in_any_order(self):
        from itertools import permutations

        for deck_size in range(5):
            deck = tuple(range(deck_size))
            for look in range(6):
                for keep in range(look + 1):
                    candidates = deck[:look]
                    for bottom in permutations(candidates, max(0, len(candidates) - keep)):
                        calls = []
                        draw = SimpleNamespace(content=list(deck))
                        def move(card, destination):
                            self.assertIs(draw, destination)
                            calls.append(("bottom", card))
                            draw.content.remove(card)
                            draw.content.append(card)
                        draw.move_card_to = move
                        player = SimpleNamespace(cardspace=SimpleNamespace(draw=draw),
                                                 draw_card=lambda n: calls.append(("draw", n)))
                        choice = DrawChoice.from_deck(player, look, keep)
                        choice.settle(bottom)
                        self.assertEqual(calls, [("bottom", card) for card in bottom]
                                         + [("draw", min(keep, len(candidates)))])
                        self.assertEqual(draw.content, [card for card in deck if card not in bottom] + list(bottom))

    def test_rejects_stale_foreign_duplicate_and_wrong_count_before_moving(self):
        draw = SimpleNamespace(content=list("abcd"))
        player = SimpleNamespace(cardspace=SimpleNamespace(draw=draw))
        choice = DrawChoice.from_deck(player, 3, 1)
        for invalid in ((), ("a",), ("a", "a"), ("a", "d"), ("a", "b", "c")):
            with self.assertRaises(ValueError):
                choice.settle(invalid)
        draw.content.reverse()
        with self.assertRaises(ValueError):
            choice.settle(("a", "b"))


class PlacementExecutorTests(unittest.TestCase):
    def test_only_confirmed_placements_consume_the_current_window(self):
        for capacity in (1, 2, 3, 8):
            game = Game.__new__(Game)
            left, right = SimpleNamespace(side=1), SimpleNamespace(side=2)
            game.first_player, game.players = left, [left, right]
            game.ended_player, game.is_over = [], False
            game.gamerule = SimpleNamespace(PLACE_CAPACITY=capacity)
            card = object()
            moves = []
            game.legal_placements = lambda: [card]
            def place(side, selected):
                moves.append((side, selected))
                return True
            game.auto_place_in_duel = place
            game.run_placement()
            for who, choice, after in ((right, card, "continue"), (left, object(), "continue"),
                                       (left, None, "pass"), (left, card, "unknown")):
                with self.assertRaises(ValueError):
                    game.submit_placement(who, choice, after=after)
            self.assertEqual(moves, [])
            game.submit_placement(left, card)
            self.assertIs(game.placing, right)
            for _ in range(capacity):
                game.submit_placement(right, card)
            self.assertIs(game.placing, left)
            self.assertEqual(moves, [(1, card)] + [(2, card)] * capacity)
            game.submit_placement(left, after="end")
            game.submit_placement(right, after="end")
            self.assertIsNone(game.placing)


class BattleFactTests(unittest.TestCase):
    def test_every_shield_spelling_reaches_one_operation_and_yields_its_actual_total(self):
        from models.character import SHIELD_FIELDS

        for kind, field in SHIELD_FIELDS.items():
            for amount in (-13, -2, 0, 1, 2**80):
                vm = TracedContext()
                actor = SimpleNamespace(combat_name="甲", shield=3, reinforced_shield=3, concept_shield=3)
                actor.add_shield = lambda key, delta: Character.add_shield(actor, key, delta)
                with vm.collect_facts() as facts:
                    vm.eval_block([actor, kind, amount, OpCode.SHIELD])
                total = max(0, 3 + amount)
                self.assertEqual(getattr(actor, field), total)
                self.assertEqual(list(facts), [("shield_changed", {"target": "甲", "shield": kind, "total": total})])
                self.assertEqual(vm.trace, [(OpCode.SHIELD, "BEFORE", (actor, kind, amount)),
                                            (OpCode.SHIELD, "AFTER", ())])
                self.assertIn(str(total), format_fact(*facts[0]))


if __name__ == "__main__":
    unittest.main()
