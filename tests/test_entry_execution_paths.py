"""Trace printed entry programs through the compiler and the real opcode handlers."""
import itertools
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from context.context import Context
from entry.entry import Entry
from models.card import Card
from models.character import Character
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


def actor_for(ctx, side):
    game = SimpleNamespace(context=ctx, status_entries={}, status_rules={}, ability_rules={},
                           turn_end_statuses=set(), resolving_duel=None)
    seat = SimpleNamespace(side=side, game=game, register_faction_passives=lambda actor: None)
    actor = Character({"id": str(side), "name": str(side), "rank": "NORMAL", "max_hp": 9, "skills": []}, seat)
    seat.characters = [actor]
    game.players = [seat]
    return actor


def resolve_entry(ctx, owner, spec, **event):
    entry = Entry.from_spec(owner, spec)
    with ctx.binding(**event):
        if ctx._matches(entry):
            ctx._invoke(entry)


class HitOriginTests(unittest.TestCase):
    def test_first_hit_bonus_requires_damage_from_the_same_die_and_skill(self):
        printed = printed_skill("xinxing_lin_qiu.json", "lin_qiu_plume_sword")
        spec = next(e for e in printed["entries"] if e["trigger"] == "BEFORE DAMAGE")
        for index, origin, granted in itertools.product((1, 2), ("this", "other", None), (False, True)):
            ctx = TraceContext()
            actor = actor_for(ctx, 1)
            card = Card(None, printed, actor)
            die = Dice(printed["dice"][0])
            die.card = card
            card.use_state["first_hit_bonus"] = granted
            other = Dice(printed["dice"][1])
            other.card = card
            damage_die = {"this": die, "other": other, None: None}[origin]
            segment, hit = [], []
            resolve_entry(ctx, card, spec, source=actor, target=actor, card=card, die=die,
                          hit_index=index, damage_die=damage_die, modifiers=segment, hit_modifiers=hit)
            self.assertEqual(bool(segment), granted and index == 1 and origin == "this")
            self.assertEqual(hit, [])

    def test_plume_limits_success_per_use_and_can_retry_after_failure(self):
        pack = json.loads((PACKS / "xinxing_lin_qiu.json").read_text(encoding="utf-8"))
        passive = next(p for p in pack["characters"][0]["passive_skills"] if p["name"] == "羽流·林秋")
        ctx = TraceContext()
        actor = actor_for(ctx, 1)
        actor.statuses["羽流·林秋"] = 6
        _, card, die = make_use("heck_flame_lunge", 3)
        card.character = actor
        die.clash_result = "win"
        rolls = iter((12, 1))
        ctx.game = SimpleNamespace(rng=SimpleNamespace(randint=lambda low, high: next(rolls)))
        for index in (1, 2, 3):
            resolve_entry(ctx, actor, passive["entries"][1], source=actor, target=actor, card=card,
                          die=die, hit_index=index, clash_result="win")
        self.assertEqual(list(die.queued_hits), [("full", "羽流")])
        self.assertEqual(ctx.operations.count(OpCode.RANDOM_INT), 2)
        self.assertEqual(actor.statuses["本回合羽流判定成功"], 1)

    def test_resident_penalty_only_follows_its_own_queued_hit(self):
        pack = json.loads((PACKS / "xinxing_lin_qiu.json").read_text(encoding="utf-8"))
        passive = next(p for p in pack["characters"][0]["passive_skills"] if p["name"] == "星结标定剑柄")
        ctx = TraceContext()
        actor = actor_for(ctx, 1)
        spec = printed_skill("xinxing_lin_qiu.json", "lin_qiu_void_cut")
        card = Card(None, spec, actor)
        die = Dice(spec["dice"][1])
        die.card = card
        card.use_state["resident_die"] = die
        event = dict(source=actor, target=actor, card=card, die=die)
        resolve_entry(ctx, actor, passive["entries"][2], **event)
        self.assertEqual(list(die.queued_hits), [("damage_only", "星结标定剑柄")])
        for mode, origin in [die.queued_hits.popleft(), ("damage_only", "其他来源"), ("full", None)]:
            modifiers = []
            resolve_entry(ctx, actor, passive["entries"][3], **event, hit_mode=mode,
                          hit_origin=origin, hit_modifiers=modifiers)
            self.assertEqual(modifiers, [("damage_add", -1, "concept")] if origin == "星结标定剑柄" else [])

    def test_void_cut_partial_payment_and_unconditional_status_loss(self):
        spec = printed_skill("xinxing_lin_qiu.json", "lin_qiu_void_cut")
        entries = spec["dice"][1]["entries"]
        for active, available, marks, uses in itertools.product((False, True), (0, 1, 2, 99),
                                                                 (0, 1, 4, 5, 12), (0, 2)):
            with self.subTest(active=active, available=available, marks=marks, uses=uses):
                ctx = TraceContext()
                actor, target = actor_for(ctx, 1), actor_for(ctx, 2)
                actor.statuses.update({"隧道": available, "隧道开启": int(active)})
                target.statuses["星结"] = marks
                card = Card(None, spec, actor)
                card.use_state["duel_penalties"] = uses
                die = Dice(spec["dice"][1])
                die.card = card
                event = dict(source=actor, target=target, die=die, card=card)
                resolve_entry(ctx, die, entries[1], **event)
                self.assertEqual(actor.statuses.get("隧道", 0), max(0, available - 2) if active else available)
                self.assertEqual(card.use_state.get("sever_die") is die, active)
                resolve_entry(ctx, die, entries[3], **event)
                self.assertEqual(target.statuses.get("星结", 0), max(0, marks - 2))
                self.assertEqual(target.next_turn_duels, -(marks // 5) if active and uses < 2 else 0)
                self.assertEqual(ctx.operations.count(OpCode.STATUS), 1)
