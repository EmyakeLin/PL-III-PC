"""Trace the shared status definitions loaded by the PvE roster."""
import unittest

from entry.play_conditions import record_hand_play
from loader import base_effects
from models.card import Card
from models.opcode import OpCode
from player.card_space import CardSpace
from tests.test_entry_execution_paths import TraceContext, actor_for, resolve_entry


def holder():
    ctx = TraceContext()
    actor = actor_for(ctx, 1)
    ctx.game = actor.game
    defs = base_effects()
    actor.game.status_rules.update(defs.status_rules)
    actor.game.status_entries.update(defs.status_entries)
    return ctx, actor


class SharedStatusTests(unittest.TestCase):
    def test_hand_restriction_records_owner_cost_rank_and_uses_current_layers(self):
        ctx, actor = holder()
        teammate = actor_for(ctx, 1)
        zones = actor.player.cardspace = CardSpace(actor.player)
        cards = [Card(actor.player, {"id": str(n), "name": str(n), "cost": cost}, owner)
                 for n, (owner, cost) in enumerate(((teammate, 9), (actor, 2), (actor, 2), (actor, 1)))]
        zones.hand.content.extend(cards)
        actor.add_status("限制", 1)
        self.assertEqual([actor.skill_restricted(c) for c in cards], [False, True, False, False])
        played = cards[2]
        record_hand_play(played)
        zones.hand.move_card_to(played, zones.delayed_discard)
        zones.hand.content.reverse()
        self.assertFalse(actor.skill_restricted(played))
        actor.add_status("限制", 1)
        self.assertTrue(actor.skill_restricted(played))

    def test_focus_compares_both_balances_and_shares_one_turn_quota(self):
        ctx, actor = holder()
        actor.add_status("能源", 2)
        actor.add_status("凝聚", 2)
        self.assertEqual(actor.statuses["能源"], 2)
        actor.add_status("凝聚", 2)
        self.assertEqual(actor.statuses["能源"], 3)
        ctx.dispatch_pipeline("on_turn_limits_reset", source=actor)
        self.assertEqual(actor.statuses["能源"], 3)
        ctx.turn_entry_uses.clear()
        ctx.dispatch_pipeline("on_turn_limits_reset", source=actor)
        self.assertEqual(actor.statuses["能源"], 4)

    def test_burn_resolves_damage_then_reduces_stacks_even_if_shielded(self):
        for count in (1, 3, 4, 12, 20):
            for shield in (0, 99):
                with self.subTest(count=count, shield=shield):
                    ctx, actor = holder()
                    actor.add_status("烧伤", count)
                    actor.shield = shield
                    ctx.operations.clear()
                    ctx.dispatch_pipeline("on_character_turn_end", source=actor, target=actor)
                    path = [op for op in ctx.operations if op in (OpCode.ACTIVATE_STATUS, OpCode.DAMAGE, OpCode.STATUS)]
                    expected = [OpCode.ACTIVATE_STATUS, OpCode.DAMAGE, OpCode.STATUS] if count >= 4 else []
                    self.assertEqual(path, expected)
                    damage = min(3, count // 4)
                    self.assertEqual(actor.statuses.get("烧伤", 0), count - (count // 4 + 2) if count >= 4 else count)
                    self.assertEqual(actor.hp, actor.max_hp - max(0, damage - shield))
                    self.assertEqual(ctx.stack, [])

    def test_ignite_reads_and_debits_the_selected_target_even_below_four_stacks(self):
        for count in (1, 3, 4, 20):
            with self.subTest(count=count):
                ctx, target = holder()
                source = actor_for(ctx, 2)
                source.statuses["烧伤"] = 8
                target.add_status("烧伤", count)
                ctx.operations.clear()
                resolve_entry(ctx, source, {"trigger": "on_dice_hit", "operation": {"keyword": "ignite"}},
                              source=source, target=target)
                self.assertEqual(ctx.operations.count(OpCode.ACTIVATE_STATUS), 1)
                self.assertEqual(ctx.operations.count(OpCode.DAMAGE), int(count >= 4))
                self.assertEqual(target.hp, target.max_hp - min(3, count // 4))
                self.assertEqual(target.statuses.get("烧伤", 0), max(0, count - count // 4 - 2))
                self.assertEqual(source.statuses["烧伤"], 8)
                self.assertEqual(ctx.stack, [])

    def test_bleed_compares_its_own_layers_before_duel_damage(self):
        for stacks in (1, 2, 3, 6, 9):
            ctx, actor = holder()
            actor.add_status("裂血", stacks)
            actor.shield = 3
            ctx.operations.clear()
            ctx.dispatch_pipeline("on_character_duel_start", source=actor, target=actor)
            self.assertEqual(ctx.operations.count(OpCode.DAMAGE), int(stacks >= 3))
            self.assertEqual(actor.hp, actor.max_hp - int(stacks >= 3))

    def test_fatal_stagger_charges_only_once_per_round_even_on_full_absorption(self):
        ctx, actor = holder()
        actor.shield = 20
        actor.add_status("致命失衡", 2)
        ctx.operations.clear()
        for amount in (0, 1, 1):
            actor.take_damage(amount)
        self.assertEqual(actor.shield, 16)
        self.assertEqual(actor.hp, actor.max_hp)
        self.assertEqual(actor.statuses["致命失衡"], 1)
        self.assertEqual(ctx.operations.count(OpCode.ROUND_TRIGGER_COUNT), 2)
        self.assertEqual(ctx.operations.count(OpCode.RECORD_ROUND_TRIGGER), 1)
        actor.begin_dice_round()
        actor.take_damage(1)
        self.assertNotIn("致命失衡", actor.statuses)
        self.assertEqual(ctx.operations.count(OpCode.RECORD_ROUND_TRIGGER), 2)
