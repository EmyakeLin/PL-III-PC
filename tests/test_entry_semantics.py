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


if __name__ == "__main__":
    unittest.main()
