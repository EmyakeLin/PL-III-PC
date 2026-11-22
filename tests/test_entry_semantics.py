"""Exercise entry lowering and VM execution in isolation from a match or card pack."""

from collections import Counter
from types import SimpleNamespace
import unittest

from context.context import Context
from entry.commands import CommandSet, expand_command
from entry.entry import Entry
from entry.effects import run_effect
from entry.program import run_program
from models.character import Character
from models.opcode import OpCode


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


if __name__ == "__main__":
    unittest.main()
