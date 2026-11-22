"""Trace printed entry programs through the compiler and the real opcode handlers."""
import itertools
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from context.context import Context
from entry.entry import Entry
from models.card import Card
from models.dice import Dice
from models.opcode import OpCode


PACKS = Path(__file__).resolve().parents[1] / "_packs"


def printed_skill(pack, ident):
    character = json.loads((PACKS / pack).read_text(encoding="utf-8"))["characters"][0]
    return next(skill for skill in character["skills"] if skill["id"] == ident)


class TraceContext(Context):
    def __init__(self):
        super().__init__()
        self.operations = []

    def execute_op(self, opcode, **fields):
        self.operations.append(opcode)
        return super().execute_op(opcode, **fields)


class CharacterFixture:
    def __init__(self):
        self.is_alive = True
        self.player = SimpleNamespace(side=1)
        self.statuses = {}
        self.ability_rules = {}

    def canonical_status_name(self, name):
        return name


def make_use(ident, pos):
    spec = printed_skill("plan_b_heck.json", ident)
    actor = CharacterFixture()
    card = Card(None, spec, actor)
    die = Dice(spec["dice"][pos])
    die.card = card
    return actor, card, die


def fire(ctx, owner, trigger, **fields):
    specs = [spec for spec in owner.entries if isinstance(spec, dict) and spec["trigger"] == trigger]
    with ctx.binding(**fields):
        for spec in specs:
            ctx._invoke(Entry.from_spec(owner, spec))


class PrintedCountingTests(unittest.TestCase):
    def test_victories_are_read_from_this_use_even_if_win_effects_were_suppressed(self):
        outcomes = ("win", "lose", "draw", None)
        for pair in itertools.product(outcomes, repeat=2):
            with self.subTest(pair=pair):
                actor, card, die = make_use("heck_flame_lunge", 3)
                card.instantiated_dice = [SimpleNamespace(clash_result=r, win_branch_skipped=True) for r in pair]
                card.instantiated_dice.extend([None, die])
                card.use_state["wins"] = 99
                ctx = TraceContext()
                fire(ctx, die, "before_dice_use", card=card, die=die, source=actor)
                self.assertIn(OpCode.FILTER, ctx.operations)
                self.assertIn(OpCode.SIZE, ctx.operations)
                self.assertEqual(die.use_state.get("lunge_finish", False), pair.count("win") == 2)
                self.assertEqual(OpCode.DIE_LEVEL_ADD in ctx.operations, pair.count("win") == 2)

    def test_repeats_count_used_dice_independently_of_requested_repeats(self):
        for limit, used, repeated in itertools.product((0, 1, 3, 10**12), (0, 1, 2), (False, True)):
            with self.subTest(limit=limit, used=used, repeated=repeated):
                actor, card, die = make_use("heck_decisive_thrust", 0)
                actor.statuses["能源"] = 1
                card.use_state.update(repeat_limit=limit, 首骰已重复=used)
                card.instantiated_dice = [SimpleNamespace(repeat_requested=True)] * 8 + [die]
                die.is_repeat = repeated
                ctx = TraceContext()
                fire(ctx, die, "on_dice_use", card=card, die=die, source=actor)
                self.assertEqual(card.use_state["首骰已重复"], used + repeated)
                self.assertEqual(OpCode.SET_SKILL_STATE in ctx.operations, repeated)
                fire(ctx, die, "after_dice_use", card=card, die=die, source=actor)
                self.assertEqual(die.repeat_requested, used + repeated < limit)
                self.assertEqual(OpCode.REPEAT_DIE in ctx.operations, used + repeated < limit)
