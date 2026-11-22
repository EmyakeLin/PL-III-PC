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
from models.card import Card
from models.conditions import COMPARISONS, skill_state_allows
from models.opcode import OpCode
from models.roster import RosterDraft
from models.turn_history import TurnHistory
from player.draw_choice import DrawChoice
from player.player import Player
from player.target_order import TargetOrder
from terminal_bridge import TerminalBridge
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
    def test_compiler_keeps_literals_quotes_and_fields_distinct(self):
        from entry.compiler import Field, Local, Program, Word, compile_program
        vocabulary = CommandSet()

        @vocabulary.define("INNER")
        def inner():
            return ["$event.number", {"local": "n"}, {"literal": "ADD"}, "ADD"]

        @vocabulary.define("OUTER")
        def outer():
            return [["INNER"], "STORE"]

        self.assertEqual(compile_program(["OUTER"], expand=vocabulary.expand),
                         Program((Program((Field("event.number"), Local("n"), "ADD", OpCode.ADD)),
                                  Word("STORE"))))
        vocabulary.define("CYCLE")(lambda: [["CYCLE"]])
        with self.assertRaisesRegex(ValueError, "CYCLE → CYCLE"):
            compile_program(["CYCLE"], expand=vocabulary.expand)

    def test_registered_program_reads_each_invocations_event(self):
        entry = Entry.from_spec(None, {"trigger": "tick", "operation": {
            "op": "program", "code": ["$event.number", "n", "STORE", {"local": "n"}, "POP"]}})
        vm = TracedContext()
        program = entry.compiled_operation["code"]
        for n in (-2**94, 0, 31):
            with vm.binding(number=n):
                vm._invoke(entry)
            self.assertIs(entry.compiled_operation["code"], program)
            self.assertEqual([stack for op, timing, stack in vm.trace
                              if op == OpCode.POP and timing == "BEFORE"][-1], (n,))


    def test_legacy_hand_condition_exposes_filter_membership_and_nonempty_check(self):
        from models.opcode import OpCode as O
        regular = SimpleNamespace(out_of_combat=False)
        extra = SimpleNamespace(out_of_combat=True)
        for skills, hand, expected in (([], [], False), ([extra], [extra], False),
                                       ([regular, extra], [], False), ([regular, extra], [regular], True)):
            vm = TracedContext()
            player = SimpleNamespace(cardspace=SimpleNamespace(hand=SimpleNamespace(content=hand)))
            actor = SimpleNamespace(is_alive=True, player=player, skills=skills)
            entry = Entry.from_spec(actor, {"trigger": "example", "operation": []})
            run_program(vm, entry, ["$own_skills_in_hand", "POP"])
            before = [op for op, timing, _ in vm.trace if timing == "BEFORE"]
            self.assertEqual(before, [O.FILTER] + [O.NOT] * len(skills)
                             + [O.DUP, O.ALL_IN, O.SWAP, O.SIZE, O.GT, O.AND, O.POP])
            self.assertIs(vm.trace[-2][2][-1], expected)

    def test_filter_restores_the_enclosing_stack_and_event_on_a_bad_predicate(self):
        vm = Context()
        vm.push("outer")
        for invalid in ([], [1, 2]):
            with self.assertRaisesRegex(ValueError, "一个结果"):
                vm.eval_block([[1], invalid, OpCode.FILTER])
            self.assertEqual(vm.stack, ["outer"])
            self.assertEqual(vm.event, {})

    def test_call_reads_the_requested_receipt_field_without_repeating_the_operation(self):
        from entry.compiler import compile_program
        vm = TracedContext()
        for opcode in OpCode:
            for result in (None, False, 0, -15, 2**88):
                trace = []
                def execute(code, **options):
                    trace.append((code, options))
                    return result
                vm.execute_op = execute
                program = compile_program([{"call": opcode.name, "result": "paid_in_full", "default": "missing"}])
                program.instructions[0].execute(vm)
                self.assertEqual(vm.pop(), "missing" if result is None else result)
                self.assertEqual(trace, [(opcode, {"result_field": "paid_in_full"})])
        for word, opcode in (("SPEND_STATUS_IN_FULL", OpCode.SPEND_STATUS),
                             ("SPEND_ABILITY_EFFECT_IN_FULL", OpCode.SPEND_ABILITY_EFFECT)):
            instruction, = compile_program([word]).instructions
            self.assertEqual((instruction.opcode, instruction.options, instruction.result, instruction.default),
                             (opcode, (("require_full", True),), "paid_in_full", False))
        with self.assertRaises(ValueError):
            compile_program([{"call": "DRAW", "with": {"authority": 2}}])

    def test_board_queries_preserve_seat_member_slot_order_and_exclude_destroyed_cards(self):
        from models.duel import DuelSlot
        left, right = Player(3, "甲"), Player(9, "乙")
        a, b, c = [SimpleNamespace(is_alive=True, player=p) for p in (left, left, right)]
        a.name, b.name, c.name = "a", "b", "c"
        left.characters, right.characters = [a, b], [c]
        slots = [DuelSlot(), DuelSlot()]
        for slot, owner, name, broken in [(slots[0], b, "B", False), (slots[1], a, "A", False),
                                          (slots[0], a, "gone", True), (slots[1], c, "C", False)]:
            slot.add_content(owner.player.side, SimpleNamespace(character=owner, id=name, destroyed=broken))
        vm = TracedContext()
        vm.game = SimpleNamespace(players=[left, right], board_slots=lambda: iter(slots))
        entry = Entry.from_spec(a, {"trigger": "tick", "operation": []})
        for field, expected in (("$own_board_skills", ["A"]), ("$target_board_skills", ["C"]),
                                ("$board_skills", ["A", "B", "C"])):
            vm.trace.clear()
            with vm.binding(target=c, bindings={"holder": "outside"}):
                run_program(vm, entry, [field, "POP"])
                self.assertEqual(vm.event["bindings"], {"holder": "outside"})
            self.assertEqual([card.id for card in vm.trace[-2][2][-1]], expected)
        c.is_alive = False
        with vm.binding(target=c):
            run_program(vm, entry, ["$target_board_skills", "POP"])
        self.assertEqual(vm.trace[-2][2][-1], [])

    def test_duel_slot_offset_and_remaining_cards_vary_independently(self):
        from models.duel import DuelSlot
        vm = Context()
        slots = [DuelSlot() for _ in range(3)]
        space = SimpleNamespace(space=slots, current_duel_index=1)
        for side in (-3, 0, 7):
            slots[2].content[side] = [side, "middle", "last"]
            for offset in (-2**81, -1, 0, 1, 2**81):
                for start in range(5):
                    slots[2].current_card_index[side] = start
                    vm.eval_block([space, offset, OpCode.SLOT_AT_OFFSET, side, OpCode.REMAINING_CARDS])
                    expected = [side, "middle", "last"][start:] if offset == 1 else []
                    self.assertEqual(vm.pop(), expected)

    def test_shared_divmod_vocabulary_only_composes_existing_instructions(self):
        vm = TracedContext()
        entry = Entry.from_spec(None, {"trigger": "tick", "operation": []})
        for numerator in (-2**94, -9, -1, 0, 1, 9, 2**91):
            for denominator in (-11, -1, 1, 2, 8, 2**77):
                vm.trace.clear()
                run_program(vm, entry, [numerator, "value", "STORE", f"DIVMOD $local.value {denominator:+d}",
                                        "POP", "POP"])
                before = [(code, stack) for code, timing, stack in vm.trace if timing == "BEFORE"]
                self.assertEqual([code for code, _ in before], [
                    OpCode.WITH_BINDINGS, OpCode.FLOOR_DIV, OpCode.DUP, OpCode.MUL,
                    OpCode.SWAP, OpCode.SUB, OpCode.POP, OpCode.POP])
                self.assertEqual(before[-2][1], divmod(numerator, denominator))
        vm.push("outer")
        with self.assertRaises(ZeroDivisionError):
            run_program(vm, entry, ["DIVMOD 42 0"])
        self.assertEqual(vm.stack, ["outer"])

    def test_printed_roll_updates_distinguish_current_and_future_rolls(self):
        from models.dice import Dice
        for node, opcode, timing, immediate in (
                ("other", None, None, False), ("other", "ROLL", "BEFORE", False),
                ("other", "ROLL", "AFTER", True), ("on_dice_clash", None, None, True)):
            for verb in ("roll_set", "roll_add"):
                for amount in (-2**70, 0, 13):
                    vm = TracedContext()
                    die = Dice({"type": "blunt", "level": 1})
                    die.value = 2
                    entry = Entry.from_spec(None, {"trigger": "tick", "operation": {"op": verb, "amount": amount}})
                    with vm.binding(node_id=node, opcode=opcode, timing=timing, die=die):
                        run_effect(vm, entry, entry.compiled_operation)
                    changed = amount if verb == "roll_set" else 2 + amount
                    self.assertEqual(die.value, min(4, max(1, changed)) if immediate else 2)
                    writes = [op for op, timing, _ in vm.trace if timing == "BEFORE"
                              and op in (OpCode.UPDATE_ROLL, OpCode.QUEUE_ROLL_UPDATE)]
                    self.assertEqual(writes, [OpCode.UPDATE_ROLL if immediate else OpCode.QUEUE_ROLL_UPDATE])
                    vm.eval_block([3, 3, 0, die, OpCode.ROLL])
                    settled = amount if verb == "roll_set" else 3 + amount
                    self.assertEqual(die.value, 3 if immediate else min(4, max(1, settled)))
                    self.assertNotIn(die, vm.roll_adjustments)

    def test_damage_modifier_preserves_grade_channel_and_exact_integer(self):
        for name in ("damage_add", "damage_multiply", "armor"):
            for grade in ("normal", "pierce", "concept"):
                for value in (-2**85 - 1, -0.25, 0, 2**96 + 1):
                    for nested_damage in (True, False):
                        vm = TracedContext()
                        damage, hit = [], []
                        entry = Entry.from_spec(None, {"trigger": "tick", "operation": {
                            "op": name, "grade": grade, "amount": value}})
                        with vm.binding(opcode="DAMAGE" if nested_damage else "ROLL", modifiers=damage,
                                        hit_modifiers=hit):
                            run_effect(vm, entry, entry.compiled_operation)
                        self.assertEqual(damage if nested_damage else hit, [(name, value, grade)])
                        self.assertEqual(hit if nested_damage else damage, [])
                        self.assertEqual(sum(1 for op, timing, _ in vm.trace
                                             if op is OpCode.ADD_DAMAGE_MODIFIER and timing == "BEFORE"), 1)

    def test_zone_search_and_placement_have_separate_subjects_and_commit_points(self):
        from models.duel import DuelSlot
        vm = TracedContext()
        player = Player(2, "甲")
        owner, teammate = (SimpleNamespace(is_alive=True, player=player) for _ in range(2))
        first = SimpleNamespace(id="x", destroyed=False, character=teammate, player=player)
        second = SimpleNamespace(id="x", destroyed=False, character=owner, player=player)
        dead = SimpleNamespace(id="x", destroyed=True, character=owner, player=player)
        slot = DuelSlot()
        placements = []
        vm.game = SimpleNamespace(active_duelspace=SimpleNamespace(space=[slot]),
                                  place_in_duel=lambda *args: placements.append(args))
        for zone in ("hand", "draw", "delayed_discard", "out_of_combat"):
            pile = player.cardspace.zone(zone)
            pile.content[:] = [dead, first, second]
            entry = Entry.from_spec(owner, {"trigger": "tick", "operation": {"op": "place_skill",
                                    "card_id": "x", "zone": zone}})
            with vm.binding(duel=slot):
                run_effect(vm, entry, entry.compiled_operation)
                run_program(vm, entry, ["$self", "x", zone, "FIND_SKILL", "POP"])
            self.assertEqual(placements.pop(), (player.side, first, 0))
            self.assertIs(vm.trace[-2][2][-1], second)
            with vm.binding(duel=DuelSlot()):
                run_effect(vm, entry, entry.compiled_operation)
            self.assertEqual(placements, [])
            pile.content.clear()
        with self.assertRaisesRegex(ValueError, "未知牌区"):
            run_program(vm, entry, ["$self", "x", "missing", "FIND_SKILL", "POP"])

    def test_random_selection_and_transferring_a_specific_card_are_independent(self):
        from unittest.mock import Mock
        vm = TracedContext()
        vm.game = SimpleNamespace(rng=Mock())
        left, right = Player(-2, "甲"), Player(7, "乙")
        giver = SimpleNamespace(player=left, is_alive=True, combat_name="a")
        ally = SimpleNamespace(player=left, is_alive=True, combat_name="b")
        enemy = SimpleNamespace(player=right, is_alive=True, combat_name="c")
        cards = [Card(left, {"id": str(i), "name": str(i), "cost": 1}, giver) for i in range(4)]
        left.cardspace.hand.content.extend(cards)
        entry = Entry.from_spec(None, {"trigger": "tick", "operation": []})
        for sample in ([], ["only"], [None, 0, False, -1, 2**107, "last"]):
            for index in range(max(1, len(sample))):
                vm.game.rng.randint.reset_mock()
                vm.game.rng.randint.return_value = index
                with vm.binding(sample=sample):
                    run_program(vm, entry, ["RANDOM_ITEM $event.sample", "POP"])
                self.assertEqual(vm.trace[-2][2][-1], sample[index] if sample else None)
                if sample:
                    vm.game.rng.randint.assert_called_once_with(0, len(sample) - 1)
                else:
                    vm.game.rng.randint.assert_not_called()
        vm.game.rng.randint.reset_mock()
        moved = vm.eval_block([left, cards[2], ally, OpCode.TRANSFER_HAND_CARD])
        self.assertIs(moved, cards[2])
        self.assertIs(moved.character, ally)
        self.assertEqual(cards, left.cardspace.hand.content)
        vm.game.rng.randint.assert_not_called()
        vm.game.rng.randint.return_value = 1
        vm.trace.clear()
        with vm.collect_facts() as facts:
            self.assertIs(vm.eval_block([giver, enemy, OpCode.TAKE_HAND_CARD]), cards[1])
        self.assertEqual([kind for kind, _ in facts], ["hand_card_taken"])
        with vm.collect_facts() as public:
            vm.eval_block([1, 4, OpCode.RANDOM_INT])
            vm.pop()
        self.assertEqual([kind for kind, _ in public], ["random_check"])
        self.assertIs(cards[1].character, enemy)
        self.assertIs(cards[1].printed_owner, giver)
        steps = [op for op, timing, _ in vm.trace if timing == "BEFORE"]
        self.assertLess(steps.index(OpCode.SAMPLE_INT), steps.index(OpCode.TRANSFER_HAND_CARD))
        self.assertEqual(right.cardspace.hand.content, [cards[1]])
        self.assertIsNone(vm.eval_block([left, cards[1], ally, OpCode.TRANSFER_HAND_CARD]))
        self.assertIsNone(vm.eval_block([giver, ally, OpCode.TAKE_HAND_CARD]))
        self.assertEqual([call.args for call in vm.game.rng.randint.call_args_list], [(0, 3), (1, 4)])
        self.assertEqual(vm.stack, [])

    def test_skill_copy_separates_the_printed_source_from_the_new_controller(self):
        from entry.compiler import compile_program
        from models.special_actions import SkillCopy

        vm = TracedContext()
        sources = [SimpleNamespace(id=key, printed_data={"name": name}) for key, name in
                   [("another", "first"), ("same", "second"), ("same", "last")]]
        owner, recipient = SimpleNamespace(skills=sources), object()
        entry = Entry.from_spec(None, {"trigger": "tick", "operation": []})
        with vm.binding(holder=owner, recipient_actor=recipient, copy_data=sources[2].printed_data):
            for skill_id, expected in (("another", sources[0]), ("same", sources[1]), ("missing", None)):
                vm.trace.clear()
                run_program(vm, entry, ["$event.holder", {"literal": skill_id}, "COPY_SKILL", "POP"])
                selected = vm.trace[-2][2][-1]
                self.assertEqual(selected, SkillCopy(owner, expected.printed_data) if expected else None)
                self.assertEqual([op for op, timing, _ in vm.trace if timing == "BEFORE"
                                  and op in (OpCode.FILTER, OpCode.FIRST)], [OpCode.FILTER, OpCode.FIRST])
            vm.trace.clear()
            run_program(vm, entry, ["$event.recipient_actor", "$event.copy_data", "SKILL_COPY", "POP"])
            self.assertEqual(vm.trace[-2][2][-1], SkillCopy(recipient, sources[2].printed_data))
            self.assertEqual([op for op, timing, _ in vm.trace if timing == "BEFORE"], [OpCode.POP])
        self.assertIs(compile_program(["COPY_SKILL"]).instructions[-1], OpCode.WITH_BINDINGS)

    def test_optional_fields_and_unknown_names_have_distinct_results(self):
        vm = TracedContext()
        entry = Entry.from_spec(None, {"trigger": "tick", "operation": []})
        with vm.binding(target=object()):
            for name, expected in (("$target_alive", False), ("$target_lightcore_hp", 0),
                                   ("$damage_die", None), ("$event.absent", None)):
                run_program(vm, entry, [name, "POP"])
                self.assertEqual(vm.trace[-2][2][-1], expected)
            with self.assertRaisesRegex(ValueError, "不存在的字段"):
                run_program(vm, entry, ["$不存在的字段", "POP"])
            self.assertEqual(vm.stack, [])

    def test_inline_native_instructions_preserve_every_declared_operand(self):
        from entry.compiler import Field, compile_program
        from models.opcodes import OPERANDS
        from entry.commands import builtins
        for opcode, names in OPERANDS.items():
            if opcode.name in builtins.definitions or not names:
                continue
            args = ["$event." + name for name in names]
            line = " ".join((opcode.name, *args))
            self.assertEqual(compile_program([line]).instructions,
                             (*[Field(arg[1:]) for arg in args], opcode))
            with self.assertRaises(ValueError):
                compile_program([line + " 7"])

    def test_team_status_visits_members_and_keeps_outer_bindings(self):
        from entry.compiler import compile_program
        vm = TracedContext()
        source = SimpleNamespace(is_alive=True)
        targets = [SimpleNamespace(is_alive=alive, id=i) for i, alive in enumerate([True, False, True])]
        source.player = SimpleNamespace(characters=targets)
        entry = Entry.from_spec(source, {"trigger": "tick", "operation": []})
        for name in ("s", "未知 状态"):
            for quantity in (-1, 0, 1, 2**70):
                for operation in ("TEAM_STATUS", "NEXT_TEAM_STATUS"):
                    target_opcode = OpCode.STATUS if operation == "TEAM_STATUS" else OpCode.QUEUE_STATUS
                    calls = []
                    execute = Context.execute_op.__get__(vm)
                    def capture(opcode, **kwargs):
                        if opcode == target_opcode:
                            params = [vm.pop() for _ in range(3 if opcode == OpCode.STATUS else 4)][::-1]
                            calls.append(params)
                            return
                        return execute(opcode, **kwargs)
                    vm.execute_op = capture
                    outer = {"subject": "outer"}
                    with vm.binding(bindings=outer):
                        run_program(vm, entry, ["$self", {"literal": name}, quantity, operation])
                        self.assertIs(vm.event["bindings"], outer)
                    prefix = [] if operation == "TEAM_STATUS" else [source]
                    self.assertEqual(calls, [prefix + [target, name, quantity] for target in targets
                                             if target.is_alive and quantity > 0])
                    self.assertEqual(vm.stack, [])
                    self.assertIn(OpCode.WITH_BINDINGS, compile_program([operation]).instructions)

    def test_card_face_and_position_lock_are_independent_at_every_card_state(self):
        from models.card import CardState
        class Subject:
            name = "隐藏名称"
        card = Subject()
        for window in (True, False):
            for state in CardState:
                vm = TracedContext()
                locks = set()
                vm.game = SimpleNamespace(special=SimpleNamespace(window_open=lambda phase: window, locked_cards=locks))
                card.state = state
                entry = Entry.from_spec(None, {"trigger": "example", "operation": {"op": "reveal_lock"}})
                with vm.binding(target=card), vm.collect_facts() as facts:
                    run_effect(vm, entry, entry.compiled_operation)
                applies = window and state is CardState.PLACED_FACE_DOWN
                self.assertIs(card.state, CardState.PLACED_FACE_UP if applies else state)
                self.assertEqual(card in locks, applies)
                writes = [op for op, timing, _ in vm.trace if timing == "BEFORE"
                          and op in (OpCode.SET_CARD_FACE, OpCode.SET_PLACEMENT_LOCK)]
                self.assertEqual(writes, [OpCode.SET_CARD_FACE, OpCode.SET_PLACEMENT_LOCK] if applies else [])
                self.assertEqual(len(facts), 2 if applies else 0)
                with vm.collect_facts() as independent:
                    vm.eval_block([card, True, OpCode.SET_PLACEMENT_LOCK])
                    vm.eval_block([card, False, OpCode.SET_PLACEMENT_LOCK])
                self.assertNotIn(card, locks)
                self.assertIs(card.state, CardState.PLACED_FACE_UP if applies else state)
                if state is CardState.PLACED_FACE_DOWN and not applies:
                    self.assertTrue(all(card.name not in format_fact(*fact) for fact in independent))

    def test_legacy_draw_selects_the_entry_target_and_supplies_it_to_listeners(self):
        from entry.compiler import TargetedProgram
        for text in ("Draw: 0", {"op": "draw_card", "amount": 0}, "DRAW"):
            vm = TracedContext()
            player = Player(7, "乙")
            target = SimpleNamespace(player=player)
            entry = Entry.from_spec(None, {"trigger": "tick", "target": "target", "operation": text})
            self.assertIsInstance(entry.compiled_operation, TargetedProgram)
            observed = []
            vm.register_entries(None, [{"trigger": "BEFORE DRAW",
                                         "operation": lambda ctx: observed.append((ctx.event["target"], ctx.event["player"]))}])
            with vm.binding(target=target):
                run_effect(vm, entry, entry.compiled_operation)
            self.assertEqual(observed, [(target, player)])
            self.assertEqual(vm.stack, [])

    def test_deferred_card_answers_keep_their_own_locals_and_do_not_imply_play(self):
        from models.special_actions import SpecialAction, SpecialActions
        vm = TracedContext()
        player = Player(1, "甲")
        game = vm.game = SimpleNamespace(context=vm, is_over=False, players=[player], board_slots=lambda: [])
        game.special = SpecialActions(game)
        owner = SimpleNamespace(is_alive=True, player=player, skill_restricted=lambda card: True)
        card = Card.__new__(Card)
        card.player, card.character, card.destroyed = player, owner, False
        player.cardspace.hand.content.append(card)
        spec = {"optional": False, "require_playable_hand": False, "bindings": {"price": -3},
                "then": {"op": "program", "code": ["$chosen_card", "POP", {"local": "n"}, "POP",
                                                   "$bindings.price", "POP"]}}
        entry = Entry.from_spec(owner, {"trigger": "tick", "operation": {"op": "program", "code": [
            "$event.serial", "n", "STORE", "$event.candidates", {"literal": spec}, "CHOOSE_CARD"]}})
        for n in (-7, 2**80):
            with vm.binding(serial=n, candidates=[card, card]):
                vm._invoke(entry)
        for n in (-7, 2**80):
            self.assertEqual(game.special.options(player), [SpecialAction("choose_card", target_card=card)])
            vm.trace.clear()
            game.special.apply(player, SpecialAction("choose_card", target_card=card))
            self.assertEqual([stack[-1] for op, timing, stack in vm.trace if op == OpCode.POP and timing == "BEFORE"],
                             [card, n, -3])
        self.assertIsNone(game.special.card_decision)
        playable = Entry.from_spec(owner, {"trigger": "tick", "operation": {"op": "program", "code": [
            "$event.candidates", {"literal": {**spec, "require_playable_hand": True}}, "CHOOSE_CARD"]}})
        with vm.binding(serial=0, candidates=[card]):
            vm._invoke(playable)
        self.assertIsNone(game.special.card_decision)

    def test_author_lines_compile_in_printed_order_for_both_permitted_factions(self):
        import json
        from pathlib import Path
        from entry.compiler import Field, Program
        root = Path(__file__).resolve().parents[1] / "_packs"
        files = ("wind_plan_b", "plan_b_heck", "plan_b_heris", "plan_b_li_ling", "xinxing_lin_qiu")
        compiled = {}
        def visit(node):
            if isinstance(node, dict):
                if "operation" in node and "trigger" in node:
                    entry = Entry.from_spec(None, node)
                    if "description" in node:
                        compiled[node["description"]] = entry.compiled_operation
                for child in node.values():
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        for filename in files:
            visit(json.loads((root / (filename + ".json")).read_text(encoding="utf-8")))
        self.assertEqual(compiled["获得1隧道，抽1卡，施加1星结。"], Program((
            Field("self"), "隧道", 1, OpCode.STATUS, Field("recipient_player"), 1, OpCode.DRAW,
            Field("skill_target"), "星结", 1, OpCode.STATUS)))
        self.assertEqual(compiled["下回合获得2迅捷。"], Program((
            Field("self"), Field("self"), "迅捷", 2, OpCode.QUEUE_STATUS)))

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
                    player = SimpleNamespace(cardspace=zones, side=7)
                    actor = SimpleNamespace(is_alive=True, player=player)
                    entry = Entry.from_spec(actor, {"trigger": "example", "operation": operation})
                    vm = TracedContext()
                    run_effect(vm, entry, entry.operation)
                    self.assertEqual(vm.trace, [(OpCode.DRAW, "BEFORE", (player, amount)),
                                                (OpCode.DRAW, "AFTER", ())])
                    self.assertEqual(zones.hand.content, list("abc"[:max(0, amount)]))


class RosterExecutorTests(unittest.TestCase):
    def test_missing_or_extra_rosters_are_rejected_before_creating_any_character(self):
        game = Game.__new__(Game)
        game.players = [Player(1, "甲"), Player(2, "乙")]
        for teams in ([], [[{}]], [[{}], []], [[{}], [{}], [{}]]):
            with self.assertRaisesRegex(ValueError, "席位"):
                game.deploy_rosters(teams)
            self.assertTrue(all(not player.characters for player in game.players))

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

    def test_draw_listeners_cannot_submit_the_same_decision_again(self):
        game = Game.__new__(Game)
        game.is_over = False
        draw = SimpleNamespace(content=["a", "b"], move_card_to=lambda *_: None)
        player = SimpleNamespace(cardspace=SimpleNamespace(draw=draw))
        choice = game.pending_draw = DrawChoice.from_deck(player, 2, 1)
        trace = []
        game._continue_drawing = lambda: trace.append("next")
        def draw_cards(n):
            trace.append(n)
            with self.assertRaisesRegex(ValueError, "已经结束"):
                game.complete_draw(choice, ["a"])
        player.draw_card = draw_cards
        for invalid in (None, [], [["foreign"]]):
            with self.assertRaises(ValueError):
                game.complete_draw(choice, invalid)
            self.assertIs(game.pending_draw, choice)
        game.complete_draw(choice, ["b"])
        self.assertEqual(trace, [1, "next"])
        self.assertIsNone(game.pending_draw)

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
    def test_damage_records_only_absorption_and_erosion_from_this_hit(self):
        for grade, expected in {
            "normal": ({"reinforced_shield": 3, "shield": 2}, {}, 4),
            "pierce": ({"reinforced_shield": 3}, {"shield": 2}, 6),
            "concept": ({"concept_shield": 4}, {"shield": 2, "reinforced_shield": 3}, 5),
        }.items():
            actor = Character.__new__(Character)
            actor._effect_context = vm = Context()
            actor.player, actor.id, actor.name = SimpleNamespace(side=2), "p", "乙"
            actor.is_alive, actor.hp, actor._base_max_hp, actor._status_max_hp_delta = True, 30, 30, 0
            actor.shield, actor.reinforced_shield, actor.concept_shield = 2, 3, 4
            actor.check_death = lambda: None
            # A nested listener creates a shield after the hit has already worn the old one down.
            actor._status_event = lambda _: actor.add_shield("normal", 50)
            with vm.collect_facts() as facts:
                lost = actor.apply_resolved_damage(9, grade)
            self.assertEqual([kind for kind, _ in facts], ["shield_balance", "damage_settled"])
            damage = facts[-1][1]
            self.assertEqual((damage["absorbed"], damage["eroded"], lost), expected)
            self.assertEqual(damage["hp"], 30 - lost)

    def test_table_projects_every_initiative_attempt_before_the_next_user_action(self):
        from battle_ui.table_bridge import TableBridge
        vm = Context()
        table = TableBridge(vm)
        vm.record("turn_opened", number=5)
        for attempt, scores in enumerate(((3, 3), (0, 0), (-1, 2)), 1):
            for side, speed in enumerate(scores, 1):
                vm.record("initiative_die", side=side, character_id=side, character_name=str(side),
                          raw=7, speed=speed, modifiers={"迅捷": 3})
                vm.record("team_speed", side=side, speed=speed, dropped=None)
            if scores[0] == scores[1]:
                vm.record("speed_tied")
            else:
                vm.record("initiative", side=2, player="乙")
        table.emit("hand_off", side=2)
        self.assertEqual([x["seq"] for x in table.events], [1, 2, 3, 4])
        self.assertEqual([x["turn"] for x in table.events], [5] * 4)
        self.assertEqual([x["winner_side"] for x in table.speed_rolls], [None, None, 2])
        self.assertEqual([x["attempt"] for x in table.speed_rolls], [1, 2, 3])
        self.assertEqual(table.speed_rolls[-1]["sides"][0]["rolls"][0]["raw"], 7)
        vm.record("turn_opened", number=6)
        self.assertEqual(table.speed_rolls, ())
        self.assertEqual(len(table.events), 4)

    def test_bot_order_uses_the_secondary_field_only_for_ties(self):
        p = Player(1, "甲")
        opponent = SimpleNamespace(characters=[SimpleNamespace(is_alive=True, hp=n, lightcore_hp=k)
                                               for n, k in [(2, 3), (3, 1), (2, 2)]])
        self.assertIs(p.choose_one_sided_target(opponent), opponent.characters[1])
        p.target_priority = (("hp", 1), ("lightcore_hp", 1))
        self.assertIs(p.choose_one_sided_target(opponent), opponent.characters[2])

    def test_each_hit_mode_records_one_hit_before_its_effects(self):
        for mode in ("full", "damage_only", "effects_only"):
            for index in (1, 2, 25):
                vm = Context()
                source = SimpleNamespace(combat_name="甲", is_alive=True)
                target = SimpleNamespace(combat_name="乙", is_alive=True)
                card = SimpleNamespace(character=source, name="技能", destroyed=False)
                die = SimpleNamespace(is_attack=True, card=card, entries=[], destroyed=False)
                source.on_attack_hit = lambda *_: vm.record("checked_critical")
                with vm.binding(hit_mode=mode, hit_index=index), vm.collect_facts() as facts:
                    self.assertTrue(vm.execute_hit_parts(die, target))
                self.assertEqual(list(facts), [
                    ("hit", {"mode": mode, "index": index, "source": "甲", "target": "乙", "card": "技能"}),
                    ("checked_critical", {}),
                ])
                self.assertEqual(bool(format_fact(*facts[0])), mode != "full" or index > 1)

    def test_observers_receive_completed_facts_in_order_and_can_detach(self):
        vm = Context()
        vm.record("outside", sample=0)
        with vm.collect_facts() as outer:
            vm.record("first", sample=-1)
            with vm.collect_facts() as inner:
                vm.record("second", sample=9)
            vm.record("third", sample=0)
        vm.record("outside", sample=1)
        self.assertEqual([kind for kind, _ in outer], ["first", "second", "third"])
        self.assertEqual(list(inner), [("second", {"sample": 9})])

    def test_every_shield_spelling_reaches_one_operation_and_yields_its_actual_total(self):
        from models.character import SHIELD_FIELDS

        for kind, field in SHIELD_FIELDS.items():
            for amount in (-13, -2, 0, 1, 2**80):
                vm = TracedContext()
                actor = SimpleNamespace(combat_name="甲", shield=3, reinforced_shield=3, concept_shield=3)
                actor.record = vm.record
                actor.add_shield = lambda key, delta: Character.add_shield(actor, key, delta)
                with vm.collect_facts() as facts:
                    vm.eval_block([actor, kind, amount, OpCode.SHIELD])
                total = max(0, 3 + amount)
                self.assertEqual(getattr(actor, field), total)
                changes = [("shield_balance", {"field": field, "before": 3, "after": total})] if total != 3 else []
                self.assertEqual(list(facts), changes + [
                    ("shield_changed", {"target": "甲", "shield": kind, "total": total})])
                self.assertEqual(vm.trace, [(OpCode.SHIELD, "BEFORE", (actor, kind, amount)),
                                            (OpCode.SHIELD, "AFTER", ())])
                self.assertIn(str(total), format_fact(*facts[-1]))


class TargetExecutorTests(unittest.TestCase):
    def test_each_unbound_selection_resumes_at_its_own_instruction(self):
        player = Player(1, "甲")
        enemies = [SimpleNamespace(is_alive=True, hp=hp) for hp in (2, 10, 3)]
        enemy = SimpleNamespace(characters=enemies)
        calls = []
        choices = iter((enemies[2], enemies[0]))
        bridge = TerminalBridge(SimpleNamespace(players=[player], context=Context()))
        def respond(seat, choice):
            self.assertIs(seat, player)
            self.assertEqual(choice.candidates, tuple(enemies))
            self.assertIs(choice.default, enemies[1])
            calls.append("choose")
            return next(choices)
        bridge.choose_target = respond
        def resolve():
            calls.append("before")
            first = player.choose_one_sided_target(enemy)
            calls.append("between")
            second = player.choose_one_sided_target(enemy)
            calls.append("after")
            return first, second
        with bridge.session():
            self.assertEqual(bridge.execute(resolve), (enemies[2], enemies[0]))
        self.assertEqual(calls, ["before", "choose", "between", "choose", "after"])
        self.assertIsNone(player.target_order)
        self.assertIs(player.choose_one_sided_target(enemy), enemies[1])

    def test_interrupted_target_question_restores_the_prior_declaration(self):
        from threading import get_ident
        player = Player(3, "甲")
        original = player.target_order = TargetOrder()
        enemy = SimpleNamespace(characters=[SimpleNamespace(is_alive=True, hp=n) for n in (3, 5)])
        bridge = TerminalBridge(SimpleNamespace(players=[player], context=Context()))
        threads = []
        def command():
            threads.append(get_ident())
            player.choose_one_sided_target(enemy)
        def decline(seat, choice):
            threads.append(get_ident())
            raise KeyboardInterrupt
        bridge.choose_target = decline
        with bridge.session(), self.assertRaises(KeyboardInterrupt):
            bridge.execute(command)
        self.assertNotEqual(*threads)
        self.assertEqual(threads[-1], get_ident())
        self.assertIs(player.target_order, original)
        self.assertFalse(original.offered.done())

    def test_zero_and_single_targets_preserve_the_next_reservation(self):
        player = Player(7, "甲")
        order = player.target_order = TargetOrder()
        enemy = SimpleNamespace(characters=[])
        self.assertIsNone(player.choose_one_sided_target(enemy))
        target = SimpleNamespace(is_alive=True, hp=5)
        enemy.characters.append(target)
        self.assertIs(player.choose_one_sided_target(enemy), target)
        self.assertIs(player.target_order, order)
        self.assertFalse(order.offered.done())
        with self.assertRaises(ValueError):
            order.submit(target)


class TurnHistoryTests(unittest.TestCase):
    def test_queries_preserve_multiplicity_owner_series_outcome_and_turn(self):
        class Actor:
            pass
        a, b = Actor(), Actor()
        a.player = b.player = object()
        other = Actor()
        other.player = object()
        history = TurnHistory()
        vm = TracedContext()
        regular, instant = object(), object()
        vm.game = SimpleNamespace(turn_history=history, duel_position=lambda: (regular, 3))
        for subject, uses in ((a, 5), (b, 3), (other, 1)):
            for _ in range(uses):
                history.record_skill(subject, "same")
            vm.eval_block([subject, "same", OpCode.SKILL_USE_COUNT])
            self.assertEqual(vm.pop(), uses)
        for outcome in ("win", "lose", "draw"):
            for position, actor in (((regular, 2), a), ((regular, 2), a), ((regular, 2), b),
                                    ((instant, 2), a), ((regular, 3), a), ((regular, 2), other)):
                history.record_clash(position, actor, outcome)
            vm.eval_block([a.player, outcome, -1, OpCode.DUEL_OFFSET, OpCode.CLASH_COUNT])
            self.assertEqual(vm.pop(), 3)
            vm.eval_block([a, outcome, None, OpCode.CLASH_COUNT])
            self.assertEqual(vm.pop(), 4)
        history.clear()
        self.assertEqual(history.clash_count(a.player, "draw"), 0)
        self.assertEqual(history.skill_uses[a, "same"], 0)


class ConditionExecutorTests(unittest.TestCase):
    def test_pending_operand_is_read_after_earlier_listeners_and_queries_emit_no_ops(self):
        for op, compare in COMPARISONS.items():
            for initial, replacement in ((0, 5), (5, 0), (2, 2), (2**80, -7)):
                vm = TracedContext()
                player = Player(4, "甲")
                seen = []
                def replace_amount(ctx):
                    ctx.pop()
                    ctx.push(replacement)
                clauses = [{"left": "$pending.amount", "op": op, "right": 2}]
                vm.register_entries(None, [
                    {"trigger": "BEFORE NEXT_TURN_COST", "operation": replace_amount},
                    {"trigger": "BEFORE NEXT_TURN_COST", "when": clauses,
                     "operation": lambda ctx: seen.append(ctx.peek(0))},
                ])
                vm.eval_block([player, initial, OpCode.NEXT_TURN_COST])
                self.assertEqual(seen, [replacement] if compare(replacement, 2) else [])
                self.assertEqual(player.next_turn_common_cost, replacement)
                self.assertEqual(vm.stack, [])
                self.assertNotIn(OpCode.LT, [op for op, _, _ in vm.trace])

    def test_status_comparison_accepts_independent_names_values_and_missing_entities(self):
        from entry.predicates import compile_when
        vm = Context()
        status = "自定义·层数/甲"
        owner = SimpleNamespace(is_alive=True, statuses={status: 5})
        for value in (-7, 0, 5, 2**91):
            vm.event = {"target": SimpleNamespace(statuses={"比较": value})}
            condition = [{"left": {"field": "$self.statuses", "key": status, "default": 0}, "op": "lt",
                          "right": {"field": "$event.target.statuses", "key": "比较", "default": 0}}]
            entry = Entry.from_spec(owner, {"trigger": "tick", "operation": [], "when": condition})
            self.assertIs(entry.conditions[0].matches(vm, entry, False), 5 < value)
            del vm.event["target"]
            self.assertFalse(entry.conditions[0].matches(vm, entry, False))
        with self.assertRaisesRegex(ValueError, "条件字段"):
            compile_when([{"left": "$pending.amount", "op": "eq", "right": 0}], OpCode.DRAW, "AFTER")

    def test_pack_parser_accepts_the_same_dice_gates_the_executor_accepts(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from loader import EffectDefinitions, load_characters_from_packs

        with TemporaryDirectory() as directory, patch("loader._shared_effects", return_value=EffectDefinitions()):
            card = {"id": "gate", "name": "符号", "cost": 0, "dice": []}
            char = {"id": "a", "name": "甲", "rank": "NORMAL", "max_hp": 11,
                    "skills": [card, dict(card, id="b"), dict(card, id="c")]}
            path = Path(directory) / "synthetic.json"
            for gate in ["flag", *({"key": "k", "op": op, "value": n}
                                   for op in COMPARISONS for n in (-2**89, 0, 2**95))]:
                card["dice"] = [{"type": "blunt", "level": 1, "requires_skill_state": gate}]
                path.write_text(json.dumps({"characters": [char]}), encoding="utf-8")
                loaded, = load_characters_from_packs(directory)
                self.assertEqual(loaded["skills"][0]["dice"][0]["requires_skill_state"], gate)
            for invalid in (5, {}, {"key": "x", "op": "ge"}, {"key": "x", "op": "typo", "value": 42}):
                card["dice"][0]["requires_skill_state"] = invalid
                path.write_text(json.dumps({"characters": [char]}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "骰位启用条件"):
                    load_characters_from_packs(directory)

    def test_each_comparison_observes_the_actual_value_on_both_sides_of_the_threshold(self):
        for op, compare in COMPARISONS.items():
            for threshold in (-11, 0, 1, 2, 2**70):
                condition = {"op": op, "value": threshold, "key": "k", "status": "s", "form": "f"}
                actor = SimpleNamespace(statuses={})
                card = SimpleNamespace(character=actor, printed_data={"form_when": condition}, _form=None)
                changes = []
                def change(key):
                    changes.append(key)
                    card._form = key
                card.set_form = change
                expected = []
                for actual in (threshold - 1, threshold, threshold, threshold + 1, threshold):
                    actor.statuses["s"] = actual
                    Card.refresh_status_form(card)
                    active = compare(actual, threshold)
                    self.assertIs(skill_state_allows({"k": actual}, condition), active)
                    key = "f" if active else None
                    if key != (expected[-1] if expected else None):
                        expected.append(key)
                self.assertEqual(changes, expected)

    def test_stagger_publishes_one_outcome_even_when_zero_or_multiple_checks_run(self):
        from battle_ui.table_bridge import TableBridge
        from unittest.mock import Mock
        for checks, rolls in (({}, []), ({"a": 3, "b": 3}, [1, 2]), ({"a": 1, "b": 1}, [3, 4])):
            actor = Character.__new__(Character)
            rng = Mock()
            rng.randint.side_effect = rolls
            actor._effect_context = vm = Context()
            actor.game = SimpleNamespace(rng=rng, is_over=False, status_rules={
                name: {"check": {"event": "stagger", "sides": 4}} for name in checks})
            actor.is_alive, actor.id, actor.name, actor.player = True, "one", "甲", Player(3, "p")
            actor.statuses = {**checks, "失衡": 8}
            table = TableBridge(vm)
            with vm.collect_facts() as facts:
                outcome = actor.trigger_stagger()
            self.assertEqual([record["roll"] for kind, record in facts if kind == "status_check"], rolls)
            self.assertEqual(len(table.events), 1)
            self.assertEqual(table.events[0]["stacks_before"], 8)
            self.assertIs(table.events[0]["triggered"], outcome)
            self.assertIs(outcome, any(r <= n for r, n in zip(rolls, checks.values())))

    def test_a_success_does_not_hide_another_status_check(self):
        from unittest.mock import Mock

        for rolls in ((1, 1), (1, 4), (4, 1), (4, 4)):
            rng = Mock()
            rng.randint.side_effect = rolls
            trace = []
            owner = SimpleNamespace(is_alive=True, game=SimpleNamespace(rng=rng, is_over=False),
                                    statuses={"a": 2, "b": 2}, _effect_context=Context())
            owner.record = owner._effect_context.record
            owner.status_rules = {key: {"check": {"event": "critical", "sides": 4,
                                  "success": key + "+", "failure": key + "-"}} for key in ("a", "b")}
            owner._effect_context._invoke = lambda entry: trace.append(entry.operation)
            self.assertIs(Character._roll_status_check(owner, "critical"), any(n <= 2 for n in rolls))
            self.assertEqual(trace, [key + ("+" if roll <= 2 else "-") for key, roll in zip("ab", rolls)])
            self.assertEqual(rng.randint.call_count, 2)


class OverflowBatchTests(unittest.TestCase):
    def test_threshold_freezes_recipients_then_executes_only_the_printed_followup(self):
        import json
        from pathlib import Path
        from loader import EffectDefinitions, _add_effects

        pack = Path(__file__).resolve().parents[1] / "_packs" / "xinxing_lin_qiu.json"
        printed = json.loads(pack.read_text(encoding="utf-8-sig"))["status_rules"]["星结"]["overflow_batch"]
        clear = "SET_STATUS_OVERFLOW $item $event.status 0"
        cap = "CAP_STATUS $item $event.status 6"
        options = [
            ({}, [], (12, 6)),
            ({"then": {"op": "program", "code": ["$targets", [clear], "EACH"]}},
             [OpCode.SET_STATUS_OVERFLOW] * 2, (12, 0)),
            ({"then": {"op": "program", "code": ["$targets", [cap], "EACH"]}},
             [OpCode.STATUS], (6, 6)),
            ({"reduce_to": 6}, [OpCode.SET_STATUS_OVERFLOW, OpCode.STATUS, OpCode.SET_STATUS_OVERFLOW], (6, 0)),
            (printed, [OpCode.SET_STATUS_OVERFLOW, OpCode.STATUS, OpCode.SET_STATUS_OVERFLOW], (6, 0)),
        ]
        for options_for_rule, expected_ops, expected_balance in options:
            with self.subTest(batch=options_for_rule):
                batch = {"threshold": 6, "event": "observe", **options_for_rule}
                definitions = EffectDefinitions()
                _add_effects(definitions, {"status_rules": {"星结": {"cap": 12, "overflow_batch": batch}}})
                vm = TracedContext()
                left, right = Player(3, "甲"), Player(9, "乙")
                game = SimpleNamespace(context=vm, players=[left, right], first_player=right, is_over=False,
                                       _overflow_settled_turn=-1, turn_count=8, status_rules=definitions.status_rules,
                                       status_entries={}, ability_rules={}, turn_end_statuses=set(), resolving_duel=None)
                vm.game = left.game = right.game = game
                def make_actor(seat, name, stacks, overflow):
                    actor = Character({"id": name, "name": name, "rank": "NORMAL", "skills": [], "max_hp": 4}, seat)
                    seat.characters.append(actor)
                    actor.statuses["星结"] = stacks
                    actor.status_overflow["星结"] = overflow
                    return actor
                first = make_actor(right, "first", 7, 6)
                second = make_actor(left, "second", 4, 7)
                late = make_actor(left, "late", 9, 5)
                observed = []
                def observe(ctx):
                    observed.append((ctx.event["targets"], first.status_overflow["星结"]))
                    first.statuses["星结"] = 12
                    late.status_overflow["星结"] = 9
                vm.register_entries(None, [{"trigger": batch["event"], "operation": observe}])
                Game.resolve_status_batches(game)
                Game.resolve_status_batches(game)
                self.assertEqual(observed, [((first, second), 6)])
                writes = [op for op, timing, _ in vm.trace if timing == "BEFORE"
                          and op in (OpCode.SET_STATUS_OVERFLOW, OpCode.STATUS)]
                self.assertEqual(writes, expected_ops)
                self.assertEqual((first.statuses["星结"], first.status_overflow.get("星结", 0)), expected_balance)
                self.assertEqual((second.statuses["星结"], late.statuses["星结"], late.status_overflow["星结"]), (4, 9, 9))
                self.assertEqual(vm.stack, [])

    def test_overflow_balance_is_independent_of_threshold_and_ordinary_stacks(self):
        actor = SimpleNamespace(status_overflow={"other": 14}, statuses={"λ": 2}, canonical_status_name=lambda n: n,
                                status_rules={"λ": {"overflow_batch": {"threshold": 37}}})
        vm = Context()
        for value in (1, 36, 37, 38, 2**173, 0):
            vm.eval_block([actor, "λ", value, OpCode.SET_STATUS_OVERFLOW])
            self.assertEqual(actor.status_overflow.get("λ", 0), value)
            self.assertEqual(actor.status_overflow["other"], 14)
            self.assertEqual(actor.statuses, {"λ": 2})
        for invalid in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                vm.eval_block([actor, "λ", invalid, OpCode.SET_STATUS_OVERFLOW])
        self.assertNotIn("λ", actor.status_overflow)
        vm.eval_block([actor, "manually recorded", 19, OpCode.SET_STATUS_OVERFLOW])
        self.assertEqual(actor.status_overflow["manually recorded"], 19)

    def test_tracking_a_capped_status_can_be_enabled_without_scheduling_a_batch(self):
        from loader import EffectDefinitions, _add_effects
        vm = Context()
        player = Player(1, "甲")
        definitions = EffectDefinitions()
        _add_effects(definitions, {"status_rules": {
            "a": {"cap": 4, "track_overflow": True}, "b": {"cap": 4}
        }})
        vm.game = player.game = SimpleNamespace(context=vm, status_rules=definitions.status_rules, status_entries={},
                                                ability_rules={}, turn_end_statuses=set(), resolving_duel=None,
                                                players=[player])
        actor = Character({"id": "one", "name": "甲", "rank": "NORMAL", "max_hp": 4, "skills": []}, player)
        for name in ("a", "b"):
            for amount in (4, 0, 2**90, -2, 2, 3):
                actor.apply_status_delta(name, amount)
        self.assertEqual(actor.status_overflow, {"a": 2**90 + 3})
        self.assertEqual(actor.statuses, {"a": 4, "b": 4})
        self.assertIn(str(2**90 + 3), actor.combat_summary())


class RangeConditionTests(unittest.TestCase):
    def test_skill_and_die_range_gates_compare_the_actual_skill_value(self):
        from models.card import describe_range_traits
        from models.dice import Dice

        for trait, field in (("range_level", "effective_range"), ("ignore_range", "effective_ignore_range")):
            for operator, compare in COMPARISONS.items():
                for level in range(4):
                    condition = {"skill_state": {"key": "计数", "op": operator, "value": 2}, "amount": level}
                    spec = {trait + "_when": condition}
                    base = {"id": "skill", "name": "牌", "cost": 1}
                    card = Card(None, {**base, **spec})
                    die = Dice({"type": "blunt", "level": 1, **spec})
                    die.card = Card(None, base)
                    self.assertIn("计数", describe_range_traits(spec)[0])
                    for value in (None, -2**90, 0, 1, 2, 3, 2**90):
                        for owner in (card, die.card):
                            owner.use_state = {} if value is None else {"计数": value}
                        expected = level if compare(0 if value is None else value, 2) else 0
                        self.assertEqual(getattr(card, field), expected)
                        self.assertEqual(getattr(die, field), expected)


class HistoryNodeTests(unittest.TestCase):
    def test_only_live_paid_uses_increment_before_on_use_listeners(self):
        from pipeline import combat_steps
        from pipeline.pipeline import Pipeline, SidePipeline

        history = TurnHistory()
        vm = TracedContext()
        game = vm.game = SimpleNamespace(context=vm, turn_history=history)
        owner = object()
        card = SimpleNamespace(character=owner, id="same")
        pipe = SidePipeline(9)
        pipe.card = card
        driver = SimpleNamespace(game=game, _card_live=lambda p: not p.withdrawn, _event=lambda p: {"card": p.card})
        node = next(n for n in combat_steps.SKILL if n.id == "on_skill_use")
        observed = []
        vm.register_entries(None, [{"trigger": node.id, "operation": lambda ctx: observed.append(
            (ctx.event["card"], history.skill_uses[owner, card.id], pipe.used))}])
        for withdrawn, paid in ((False, None), (False, False), (True, True), (False, True), (False, True)):
            pipe.withdrawn, pipe.paid, pipe.used = withdrawn, paid, False
            Pipeline._execute(driver, node, pipe)
            self.assertEqual(pipe.used, bool(paid and not withdrawn))
        self.assertEqual(observed, [(card, 1, True), (card, 2, True)])

    def test_clash_history_precedes_result_branches_even_when_the_winning_branch_is_suppressed(self):
        from pipeline.pipeline import Pipeline, SidePipeline

        game = Game.__new__(Game)
        game.context, game.turn_history = Context(), TurnHistory()
        position = ("series", 2)
        game.duel_position = lambda: position
        left, right = Player(3, "甲席"), Player(9, "乙席")
        pipes = [SidePipeline(p.side) for p in (left, right)]
        for pipe, player in zip(pipes, (left, right)):
            actor = Character.__new__(Character)
            actor.player, actor.game, actor.name = player, None, player.name
            pipe.card = SimpleNamespace(character=actor, range_deficit=0)
            pipe.die = SimpleNamespace(type="block", final_score=6, clash_score=4, queued_hits=(), win_branch_skipped=False)
        for outcomes, deficit in ((("win", "lose"), 0), (("win", "lose"), 2), (("draw", "draw"), 3),
                                  (("lose", "win"), 1)):
            game.turn_history.clear()
            pipes[0].card.range_deficit = deficit
            for pipe in pipes:
                pipe.die.win_branch_skipped = False
                pipe.queue.clear()
            visited, hits = [], []
            def advance(result_pipes, stops):
                for pipe, result in zip(pipes, outcomes):
                    self.assertEqual(game.turn_history.clash_count(pipe.card.character, result, position), 1)
                    self.assertEqual(pipe.die.clash_result, result)
                visited.append(tuple(p.side for p in result_pipes))
                return ()
            def hit(pipe):
                hits.append(pipe.side)
                return ()
            driver = SimpleNamespace(game=game, _frame=SimpleNamespace(), _run_to=advance, _hit=hit)
            list(Pipeline._resolve_results(driver, pipes, dict(zip((left.side, right.side), outcomes))))
            allowed = [p.side for p in pipes if not p.die.win_branch_skipped]
            self.assertEqual(visited[0], tuple(allowed))
            self.assertEqual(hits, [p.side for p, result in zip(pipes, outcomes)
                                    if result == "win" and not p.die.win_branch_skipped])
            self.assertEqual(pipes[0].die.win_branch_skipped, outcomes[0] == "win" and deficit >= 2)


class ExecutionBoundaryTests(unittest.TestCase):
    def test_cancelling_the_invocation_restores_the_stack_and_skips_its_next_instruction(self):
        vm = TracedContext()
        player = Player(1, "甲")
        entry = Entry.from_spec(None, {"trigger": "tick", "operation": {"op": "program", "code": [
            "$event.who", 2, "DRAW", "$event.who", 3, "DRAW"]}})
        def cancel_caller(ctx):
            ctx.event["execution"].cancelled = True
        vm.register_entries(None, [{"trigger": "BEFORE DRAW", "operation": cancel_caller}])
        vm.push("enclosing")
        with vm.binding(who=player):
            vm._invoke(entry)
        draws = [(timing, stack[-1]) for opcode, timing, stack in vm.trace if opcode == OpCode.DRAW]
        self.assertEqual(draws, [("BEFORE", 2)])
        self.assertEqual(vm.stack, ["enclosing"])
        self.assertEqual((vm.executions, vm.op_stack, vm.event), ([], [], {}))

    def test_each_executable_opcode_declares_its_stack_contract(self):
        from models.opcodes import DISPATCH_TABLE, OPERANDS
        # ENTRY is the listener-dispatch frame surrounding a rule invocation.
        self.assertEqual(set(DISPATCH_TABLE), set(OpCode) - {OpCode.ENTRY})
        self.assertEqual(set(DISPATCH_TABLE), set(OPERANDS))
        for opcode, names in OPERANDS.items():
            self.assertEqual(len(names), len(set(names)), opcode)
            self.assertTrue(all(isinstance(name, str) and name.isidentifier() for name in names))

    def test_kernel_modules_have_no_console_calls_or_presentation_dependencies(self):
        import ast
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        sources = [
            "game.py", "loader.py", "gamerule.py", "context/context.py",
            "entry/commands.py", "entry/compiler.py", "entry/entry.py", "entry/effects.py", "entry/program.py",
            "entry/field_aliases.py", "entry/predicates.py", "entry/references.py", "entry/stack_words.py",
            "entry/legacy_operations.py", "entry/arithmetic_operations.py", "entry/status_operations.py",
            "entry/collection_operations.py",
            "models/card.py", "models/character.py", "models/conditions.py", "models/damage.py", "models/dice.py",
            "models/duel.py", "models/identities.py", "models/opcode.py", "models/opcodes.py", "models/pre_reveal.py",
            "models/roster.py", "models/special_actions.py", "models/turn_history.py", "models/values.py",
            "player/card_space.py", "player/draw_choice.py", "player/player.py", "player/target_order.py",
            "pipeline/pipeline.py", "pipeline/pipeline_base.py", "pipeline/pipeline_steps.py", "pipeline/combat_steps.py",
        ]
        presentation = {"main", "terminal_bridge", "terminal_events", "pre_reveal_cli", "special_actions_cli",
                        "displayer", "battle_ui", "battle_mcp"}
        for source in sources:
            tree = ast.parse((root / source).read_text(encoding="utf-8-sig"), filename=source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = [node.module or ""]
                else:
                    imports = []
                self.assertFalse(any(name.split(".")[0] in presentation for name in imports), (source, imports))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ("print", "input"), (source, node.lineno))


class StatusAliasTests(unittest.TestCase):
    def test_data_aliases_obey_canonical_name_precedence_and_keep_snapshot_compatibility(self):
        import json
        from pathlib import Path
        from displayer import Displayer
        from loader import EffectDefinitions, _add_effects
        aliases = json.loads((Path(__file__).resolve().parents[1] / "_packs/effects/status_aliases.json")
                             .read_text(encoding="utf-8"))
        for order in (True, False):
            rules = {"status_rules": {"能源": {"aliases": ["battery"], "cap": 12}, "出血": {"aliases": ["bleed"]}}}
            defs = EffectDefinitions()
            for pack in ((aliases, rules) if order else (rules, aliases)):
                _add_effects(defs, pack)
            defs.resolve_aliases()
            vm, seat = Context(), Player(2, "乙")
            seat.game = vm.game = SimpleNamespace(context=vm, status_rules=defs.status_rules, status_entries={},
                                                   ability_rules={}, turn_end_statuses=set(), cards_revealed=False)
            actor = Character({"id": "one", "name": "一", "rank": "NORMAL", "skills": [], "max_hp": 4}, seat)
            self.assertEqual([actor.canonical_status_name(n) for n in ("能源", "energy", "battery", "unknown")],
                             ["能源", "能源", "能源", "unknown"])
            actor.game.status_rules["energy"] = {}
            self.assertEqual(actor.canonical_status_name("energy"), "energy")
            for active in (True, False):
                actor.statuses["出血"] = 2
                actor.active_statuses = {"出血"} if active else set()
                view = Displayer._character(SimpleNamespace(_game=seat.game), actor, True)
                self.assertIs(view["bleed_burst"], active)
            self.assertFalse(hasattr(Character, "bleed_burst"))


class PreRevealBindingTests(unittest.TestCase):
    def test_slot_selection_and_card_binding_are_independent_at_resolution(self):
        from models.duel import DuelSlot
        from models.pre_reveal import PreRevealPhase
        for occupied in (False, True):
            for bind in ("slot", "declared_card"):
                for response in ("replace", "pulled", "intercept"):
                    with self.subTest(occupied=occupied, bind=bind, response=response):
                        left, right = Player(2, "甲"), Player(5, "乙")
                        actors = [SimpleNamespace(is_alive=True, player=p) for p in (left, right)]
                        left.characters, right.characters = [actors[0]], [actors[1]]
                        regular = DuelSlot()
                        game = SimpleNamespace(players=[left, right], duelspace=SimpleNamespace(space=[regular, DuelSlot()]),
                                               context=Context(), pipeline=SimpleNamespace(in_use=lambda *_: False))
                        phase = PreRevealPhase(game)
                        spec = {"id": "a", "name": "a", "cost": 1, "pre_reveal_bind": bind}
                        if occupied:
                            spec["pre_reveal_target"] = "occupied_enemy_slot"
                        attack = Card(left, spec, actors[0])
                        original, replacement = [Card(right, {"id": n, "name": n, "cost": 1}, actors[1])
                                                 for n in ("A", "B")]
                        regular.add_content(right.side, original)
                        targets = phase.attack_targets(attack)
                        self.assertIn((None, 0), targets)
                        self.assertEqual((None, 1) in targets, not occupied and bind == "slot")
                        self.assertEqual((actors[1], None) in targets, not occupied)
                        phase.attack_cards = lambda _: [attack]
                        phase._refresh = lambda **_: None
                        left.cardspace.hand.content.append(attack)
                        duel = phase.declare_attack(attack, duel_index=0)
                        self.assertIs(duel.required_card, original if bind == "declared_card" else None)
                        regular.remove_card(original)
                        if response == "replace":
                            regular.add_content(right.side, replacement)
                        elif response == "pulled":
                            phase.pulled_owners[(0, right.side)] = actors[1]
                        else:
                            duel.intercept_card = replacement
                            duel.add_content(right.side, replacement)
                        duel.ready = True
                        succeeds = bind == "slot" or response == "intercept"
                        self.assertEqual(duel.prepare(phase), succeeds)
                        self.assertIs(duel.pulled_card, replacement if response == "replace" and succeeds else None)
                        self.assertIs(duel.resolved_target, actors[1] if succeeds else None)


if __name__ == "__main__":
    unittest.main()
