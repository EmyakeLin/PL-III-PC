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
    def test_draw_command_reaches_the_same_draw_opcode_for_each_amount(self):
        from entry.compiler import prepare_effect
        from player.card_space import CardSpace

        for count in (0, 1, 2, 10**12):
            ctx = TraceContext()
            actor = actor_for(ctx, 1)
            player = actor.player
            player.cardspace = CardSpace(player)
            cards = [Card(player, {"id": str(i), "name": str(i), "cost": 0}, actor) for i in range(3)]
            player.cardspace.draw.content.extend(cards)
            operation = f"DRAW {count}"
            self.assertEqual(prepare_effect(operation).instructions[-2:], (count, OpCode.DRAW))
            resolve_entry(ctx, actor, {"trigger": "on_skill_use", "operation": operation}, source=actor)
            self.assertEqual(ctx.operations, [OpCode.DRAW])
            self.assertEqual(player.cardspace.hand.content, cards[:count])
            self.assertEqual(player.cardspace.draw.content, cards[count:])

    def test_retired_words_conditions_and_damage_options_fail_when_compiled(self):
        from entry.compiler import compile_program

        for tokens in (["ONCE_PER_ROUND"], ["$enemies"], ["DAMAGE_ADD"], [{"op": "damage_add", "amount": 2}],
                       [{"op": "damage", "amount": 2, "from_die": True}],
                       [{"keyword": "引燃", "final_divisor": 2}]):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                compile_program(tokens)
        with self.assertRaises(ValueError):
            Entry.from_spec(None, {"trigger": "BEFORE STATUS", "when": {"amount_at_least": 1},
                                   "operation": {"op": "program", "code": []}})
        self.assertEqual(compile_program([{"literal": "DAMAGE_ADD"}]).instructions, ("DAMAGE_ADD",))

    def test_removed_configuration_cannot_silently_enable_an_action_or_erase_a_restriction(self):
        from loader import EffectDefinitions, _add_effects

        for flag in ("restrict_highest_hand_cost", "overflow_batch"):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, flag):
                _add_effects(EffectDefinitions(), {"status_rules": {"例": {flag: True}}})
        action = {"requires_draw_pile": True}
        for pack in ({"characters": [{"actions": [action]}]}, {"ability_rules": {"例": {"action": action}}}):
            with self.assertRaisesRegex(ValueError, "when"):
                _add_effects(EffectDefinitions(), pack)

        for name in ("plan_b_heck.json", "plan_b_heris.json", "plan_b_li_ling.json",
                     "wind_plan_b.json", "xinxing_lin_qiu.json"):
            with self.subTest(pack=name):
                _add_effects(EffectDefinitions(), json.loads((PACKS / name).read_text(encoding="utf-8")))

    def test_a_public_keyword_named_after_a_structured_operation_activates_its_status(self):
        for keyword in ("damage", "cancel", "program"):
            ctx = TraceContext()
            actor = actor_for(ctx, 1)
            actor.statuses["样本"] = 1
            actor.game.status_rules["样本"] = {"activation": {"keywords": [keyword],
                "operation": {"op": "program", "code": ["$event.target", "已发动", 1, "STATUS"]}}}
            with ctx.binding(source=actor, target=actor):
                ctx._invoke(Entry.from_spec(actor, {"trigger": "on_dice_hit", "operation": {"keyword": keyword}}))
            self.assertEqual(actor.statuses["已发动"], 1)
            self.assertEqual(ctx.operations, [OpCode.ACTIVATE_STATUS, OpCode.STATUS])

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
    game = SimpleNamespace(context=ctx, card_serial=0, status_entries={}, status_rules={}, ability_rules={},
                           turn_end_statuses=set(), resolving_duel=None)
    seat = SimpleNamespace(side=side, name=str(side), game=game, register_faction_passives=lambda actor: None)
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


class CollectionAndTargetTests(unittest.TestCase):
    def test_redirect_skips_used_and_invalid_cards_only_in_the_next_slot(self):
        from models.card import CardState
        from models.duel import DuelSlot

        skill = printed_skill("wind_plan_b.json", "annolin_drifting_sword")
        for has_next, eligible in itertools.product((False, True), repeat=2):
            ctx = TraceContext()
            actor, enemy = actor_for(ctx, 1), actor_for(ctx, 2)
            card = Card(None, skill, actor)
            die = Dice(skill["dice"][3])
            die.card = card
            slot = DuelSlot()
            cards = [Card(enemy.player, skill, enemy) for _ in range(5)]
            slot.content[2] = cards
            slot.current_card_index[2] = 1
            cards[1].destroyed = True
            cards[2].state = CardState.NEGATED
            cards[3].character = SimpleNamespace(is_alive=False)
            cards[4].destroyed = not eligible
            space = SimpleNamespace(current_duel_index=0, space=[DuelSlot()] + ([slot] if has_next else []))
            ctx.game = SimpleNamespace(active_duelspace=space, players=[actor.player, enemy.player])
            resolve_entry(ctx, die, die.entries[0], source=actor, card=card, die=die)
            self.assertTrue(die.attack_redirected)
            self.assertIs(die.attack_target, enemy if has_next and eligible else None)
            for op in (OpCode.SLOT_AT_OFFSET, OpCode.REMAINING_CARDS, OpCode.FILTER, OpCode.FIRST, OpCode.ROUTE_DIE_ATTACK):
                self.assertEqual(ctx.operations.count(op), 1)

    def test_boundary_declares_candidates_and_revalidates_the_chosen_physical_card(self):
        from models.duel import DuelSlot
        from models.special_actions import SpecialAction, SpecialActions
        from player.card_space import CardSpace

        skill = printed_skill("xinxing_lin_qiu.json", "lin_qiu_boundary")
        ctx = TraceContext()
        actor, target, teammate = [actor_for(ctx, side) for side in (1, 2, 2)]
        for char in (actor, target, teammate):
            char.player.cardspace = CardSpace(char.player)
        card = Card(actor.player, skill, actor)
        die = Dice(skill["dice"][0])
        die.card = card
        first, second, dead, other = [Card(c.player, skill, c) for c in (target, target, target, teammate)]
        dead.destroyed = True
        slots = [DuelSlot(), DuelSlot()]
        slots[0].content[2], slots[1].content[2] = [first, dead, other], [second]
        game = SimpleNamespace(is_over=False, players=[actor.player, target.player], context=ctx, board_slots=lambda: slots)
        ctx.game = game
        game.special = SpecialActions(game)
        event = dict(source=actor, target=target, die=die, card=card)
        entry = die.entries[2]
        resolve_entry(ctx, die, entry, **event)
        choices = game.special.options(actor.player)
        self.assertEqual(choices, [SpecialAction("choose_card", target_card=c) for c in (first, second)])
        slots[0].content[2].remove(first)
        with self.assertRaises(ValueError):
            game.special.apply(actor.player, choices[0])
        self.assertTrue(game.special.apply(actor.player, choices[1]))
        resolve_entry(ctx, die, entry, **event)
        self.assertTrue(second.destroyed)
        self.assertFalse(first.destroyed or other.destroyed)
        self.assertEqual(ctx.operations.count(OpCode.CHOOSE_CARD), 1)
        self.assertEqual(ctx.operations.count(OpCode.DESTROY), 1)

    def test_vortex_is_spent_from_the_character_marked_at_skill_use(self):
        from unittest.mock import Mock

        skill = printed_skill("wind_plan_b.json", "annolin_vortex_sword")
        for initial, left in itertools.product((0, 1, 9), (0, 1, 4)):
            with self.subTest(initial=initial, left=left):
                ctx = TraceContext()
                actor, chosen, later = [actor_for(ctx, side) for side in (1, 2, 2)]
                card = Card(None, skill, actor)
                choose = Mock(return_value=chosen)
                ctx.game = SimpleNamespace(pipeline=SimpleNamespace(resolve_skill_target=choose))
                ctx.register_entries(card, skill["entries"])
                chosen.statuses["涡流"] = initial
                ctx.dispatch_pipeline("on_skill_use", source=actor, card=card, target=None)
                chosen.statuses["涡流"], later.statuses["涡流"] = left, 9
                ctx.dispatch_pipeline("after_skill_use", source=actor, card=card, target=later)
                self.assertEqual(choose.call_count, 1)
                self.assertEqual(ctx.operations.count(OpCode.SPEND_STATUS), int(initial > 0))
                self.assertEqual(chosen.statuses.get("涡流", 0), max(0, left - int(initial > 0)))
                self.assertEqual(later.statuses["涡流"], 9)

    def test_discard_settles_the_selected_physical_card_at_any_hand_position(self):
        from player.card_space import CardSpace
        ctx = TraceContext()
        for size in (0, 1, 5):
            for position in range(-1, size):
                player = SimpleNamespace(game=None)
                player.cardspace = CardSpace(player)
                hand = player.cardspace.hand
                cards = [Card(player, {"id": str(i), "name": str(i), "cost": 0}) for i in range(size)]
                hand.content.extend(cards)
                selected = cards[position] if position >= 0 else Card(player, {"id":"absent","name":"absent","cost":0})
                with ctx.binding():
                    result = ctx.eval_block([player, selected, OpCode.DISCARD])
                self.assertEqual(result is selected, position >= 0)
                self.assertEqual(hand.content, [c for c in cards if c is not selected])
                self.assertEqual(player.cardspace.delayed_discard.content, [selected] if position >= 0 else [])

    def test_known_and_missing_targets_do_not_request_a_second_selection(self):
        from unittest.mock import Mock

        printed = printed_skill("xinxing_lin_qiu.json", "lin_qiu_plume_sword")
        spec = printed["entries"][0]
        for known, selectable, stacks in itertools.product((False, True), (False, True), (0, 5, 6, 12, 10**9)):
            ctx = TraceContext()
            actor, enemy = actor_for(ctx, 1), actor_for(ctx, 2)
            enemy.statuses["星结"] = stacks
            card = Card(None, printed, actor)
            select = Mock(return_value=enemy if selectable else None)
            ctx.game = SimpleNamespace(pipeline=SimpleNamespace(resolve_skill_target=select))
            resolve_entry(ctx, card, spec, source=actor, target=enemy if known else None, card=card)
            self.assertEqual(select.call_count, int(not known))
            self.assertEqual(ctx.operations.count(OpCode.SELECT_SKILL_TARGET), int(not known))
            self.assertEqual(card.level_bonus, min(2, stacks // 6) if known or selectable else 0)

    def test_hand_threshold_is_printed_and_other_peoples_cards_do_not_count(self):
        for pack, needed in (("plan_b_heck.json", 5), ("plan_b_heris.json", 3), ("plan_b_li_ling.json", 3),
                             ("wind_plan_b.json", 5), ("xinxing_lin_qiu.json", 7)):
            char_spec = json.loads((PACKS / pack).read_text(encoding="utf-8"))["characters"][0]
            specs = [e for p in char_spec["passive_skills"] for e in p["entries"]]
            spec = next(e for e in specs if "集满" in e.get("description", "") or "均在手中" in e.get("description", "")
                        or "都在手中" in e.get("description", ""))
            for count in (0, needed-1, needed, needed+1):
                ctx = TraceContext()
                actor = actor_for(ctx, 1)
                class Skill:
                    pass
                regular = [Skill() for _ in range(needed + 1)]
                outside = Skill()
                for card in regular:
                    card.out_of_combat = False
                outside.out_of_combat = True
                actor.skills = regular + [outside]
                actor.player.cardspace = SimpleNamespace(hand=SimpleNamespace(content=regular[:count]+[outside, Skill()]))
                actor.player.available_cost = 6
                actor.player.turn_cost_adjustment = 0
                resolve_entry(ctx, actor, spec, source=actor)
                self.assertIn(OpCode.FILTER, ctx.operations)
                self.assertIn(OpCode.SIZE, ctx.operations)
                if pack.startswith("xinxing"):
                    self.assertEqual(actor.statuses["隧道"], 1+int(count >= needed))
                else:
                    self.assertEqual(actor.turn_duel_bonus, int(count >= needed))

    def test_group_damage_visits_primary_first_only_after_a_landed_hit(self):
        printed = printed_skill("wind_plan_b.json", "annolin_burst")
        spec = printed["dice"][1]["entries"][0]
        for landed, primary_index in itertools.product((False, True), range(3)):
            class DamageTrace(TraceContext):
                def execute_op(self, opcode, **fields):
                    if opcode == OpCode.DAMAGE:
                        attack, grade, amount, target = self.pop(), self.pop(), self.pop(), self.pop()
                        visits.append((target, amount, grade, attack))
                        return amount
                    return super().execute_op(opcode, **fields)
            ctx = DamageTrace()
            actor = actor_for(ctx, 1)
            enemies = [actor_for(ctx, 2) for _ in range(3)]
            opposing = enemies[0].player
            opposing.characters = enemies
            ctx.game = SimpleNamespace(players=[actor.player, opposing])
            actor.statuses["涡流"] = 6
            card = Card(None, printed, actor)
            die = Dice(printed["dice"][1])
            die.card = card
            primary = enemies[primary_index]
            visits = []
            resolve_entry(ctx, die, spec, source=actor, target=primary, card=card, die=die, result=landed)
            order = [primary] + [e for e in enemies if e is not primary]
            self.assertEqual(visits, [(e, 6 if e is primary else 4, "normal", "slash") for e in order] if landed else [])


class DamageAndPaymentTests(unittest.TestCase):
    def test_tunnel_checks_the_pending_gain_after_other_listeners(self):
        pack = json.loads((PACKS / "xinxing_lin_qiu.json").read_text(encoding="utf-8"))
        passives = pack["characters"][0]["passive_skills"]
        node = next(p for p in passives if p["name"] == "新星隧道节点 D-VII型")
        listener = next(e for e in node["entries"] if e["trigger"] == "BEFORE STATUS")
        for opened, printed, shift in itertools.product((0, 1), (0, 1, 7), (-2, 0, 4)):
            with self.subTest(opened=opened, printed=printed, shift=shift):
                ctx = TraceContext()
                actor = actor_for(ctx, 1)
                actor.statuses["隧道开启"] = opened
                ctx.register_entries(actor, [
                    {"trigger": "BEFORE STATUS", "operation": {"op": "program", "code": [shift, "ADD"]}},
                    listener,
                ])
                ctx.eval_block([actor, "隧道", printed, OpCode.STATUS])
                reduction = int(opened and printed + shift >= 1)
                self.assertEqual(ctx.operations.count(OpCode.SUB), reduction)
                self.assertEqual(actor.statuses.get("隧道", 0), max(0, printed + shift - reduction))

    def test_star_lock_snapshot_selects_once_in_seat_order_and_settles_after_publication(self):
        pack = json.loads((PACKS / "xinxing_lin_qiu.json").read_text(encoding="utf-8"))
        for threshold in (1, 6, 23):
            class PublicationTrace(TraceContext):
                def publish(self, name, fields):
                    publications.append((name, list(fields["targets"])))
                    late.status_overflow["星结"] = threshold + 1
                    super().publish(name, fields)
            ctx = PublicationTrace()
            a, b, late = [actor_for(ctx, n) for n in (1, 2, 1)]
            a.player.characters.append(late)
            rules = pack["status_rules"].copy()
            rules["星结"] = dict(rules["星结"], overflow_threshold=threshold)
            ctx.game = SimpleNamespace(players=[a.player, b.player], first_player=b.player, status_rules=rules)
            for character in (a, b, late):
                character.statuses["星结"] = 10
                character.status_overflow["星结"] = threshold - int(character is late)
            publications = []
            ctx.register_status_programs(rules)
            ctx.register_status_programs(rules)
            ctx.dispatch_pipeline("before_turn_end")
            ctx.dispatch_pipeline("before_turn_end")
            self.assertEqual(publications, [("on_star_lock", [b, a])])
            self.assertEqual([c.statuses["星结"] for c in (a, b, late)], [6, 6, 10])
            self.assertEqual(ctx.operations.count(OpCode.SET_STATUS_OVERFLOW), 2)
            self.assertEqual(ctx.operations.count(OpCode.PUBLISH), 1)

    def test_finish_damage_and_destruction_follow_victories_even_when_win_effects_were_skipped(self):
        for wins in range(4):
            ctx = TraceContext()
            actor, target = actor_for(ctx, 1), actor_for(ctx, 2)
            printed = printed_skill("plan_b_heck.json", "heck_flame_lunge")
            card, opponent = Card(None, printed, actor), Card(None, printed, target)
            die = Dice(printed["dice"][3])
            die.card = card
            card.instantiated_dice = [SimpleNamespace(clash_result="win", win_branch_skipped=True)
                                      for _ in range(wins)] + [die]
            target.game.status_rules["烧伤"] = {"activation":{"keywords":["ignite"],"operation":{"op":"program","code":[]}}}
            event = dict(source=actor, target=target, card=card, die=die, damage_die=die,
                         damage_part=True, opponent_card=opponent, modifiers=[], hit_modifiers=[])
            fire(ctx, die, "before_dice_use", **event)
            fire(ctx, die, "BEFORE DAMAGE", **event)
            fire(ctx, die, "on_dice_hit", **event)
            self.assertEqual(event["modifiers"], [("damage_add", 1, "normal")] if wins >= 2 else [])
            self.assertEqual(event["hit_modifiers"], [])
            self.assertEqual(opponent.destroyed, wins >= 2)

    def test_payment_uses_its_receipt_even_when_another_listener_spends_energy(self):
        printed = printed_skill("plan_b_heck.json", "heck_energy_analysis")
        listener = next(e for e in printed["dice"][1]["entries"] if isinstance(e, dict) and e["trigger"] == "BEFORE DAMAGE")
        for price, balance, doubled in itertools.product((1, 4, 11), (0, 3, 20), (False, True)):
            ctx = TraceContext()
            actor = actor_for(ctx, 1)
            actor.statuses.update({"能源": balance, "凝聚": price, "全开": int(doubled)})
            card = Card(None, printed, actor)
            die = Dice(printed["dice"][1])
            die.card = card
            nested = {"trigger":"AFTER SPEND_STATUS","subject":"source","operation":{"op":"program","code":[
                "$self", "能源", 2, {"call":"SPEND_STATUS"}]}}
            ctx.register_entries(actor, [nested])
            segment, hit = [], []
            resolve_entry(ctx, die, listener, source=actor, target=actor, card=card, die=die, damage_die=die,
                          damage_part=True, modifiers=segment, hit_modifiers=hit)
            bonus = price // 2 * (1 + doubled) if balance >= price else 0
            self.assertEqual(die.use_state["analysis_burn"], bonus)
            self.assertEqual(segment, [("damage_add", bonus, "normal")] if balance >= price else [])
            self.assertEqual(hit, [])
            self.assertEqual(actor.statuses.get("能源", 0), max(0, balance-price-2) if balance >= price else balance)
            self.assertNotIn("spent_statuses", card.use_state)
            follow = next(e for e in printed["dice"][1]["entries"] if isinstance(e, dict) and e["trigger"] == "on_dice_hit")
            resolve_entry(ctx, die, follow, source=actor, target=actor, card=card, die=die)
            self.assertEqual(actor.statuses.get("烧伤", 0), bonus)

    def test_ignite_reward_only_counts_the_status_change_issued_by_the_activation(self):
        printed = printed_skill("plan_b_heris.json", "heris_crush")
        reward = next(e for e in printed["dice"][0]["entries"] if isinstance(e, dict) and e["trigger"] == "AFTER STATUS")
        ctx = TraceContext()
        actor, target = actor_for(ctx, 1), actor_for(ctx, 2)
        target.statuses["烧伤"] = 9
        target.game.status_rules["烧伤"] = {"activation":{"keywords":["ignite","引燃"],
            "operation":{"op":"program","code":["$event.target","烧伤",-2,"STATUS"]}}}
        card = Card(None, printed, actor)
        die = Dice(printed["dice"][0])
        die.card = card
        ctx.register_entries(die, [reward])
        ctx.register_entries(actor, [{"trigger":"AFTER STATUS","subject":"source",
            "when":[{"left":"$event.status","op":"eq","right":"烧伤"}],
            "operation":{"op":"program","code":["$event.target","烧伤",-1,"STATUS"]}}])
        with ctx.binding(source=actor, target=target, card=card, die=die):
            ctx._invoke(Entry.from_spec(actor, {"trigger":"on_dice_hit","operation":{"keyword":"ignite","credit":"die"}}))
        self.assertEqual(target.statuses["烧伤"], 6)
        self.assertEqual(actor.statuses["能源"], 2)
        self.assertEqual(ctx.operations.count(OpCode.STATUS), 3)
