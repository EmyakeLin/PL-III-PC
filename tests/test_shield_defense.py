"""Execution-path tests for the generic shield defense channel."""
import unittest

from context.context import Context
from models.character import Character
from models.opcode import OpCode
from tests.test_entry_execution_paths import TraceContext, actor_for


def _named_actor(player, ident, name, hp=20):
    actor = Character({"id": ident, "name": name, "rank": "NORMAL", "max_hp": hp, "skills": []}, player)
    player.characters.append(actor)
    return actor


class ShieldDefenseChannelTests(unittest.TestCase):
    def _pierce_two_to_one_rule(self):
        return {
            "trigger": "BEFORE APPLY_DAMAGE",
            "subject": "target",
            "when": [{"left": "$event.penetration", "op": "eq", "right": "pierce"}],
            "operation": {
                "op": "program",
                "code": [
                    "$event.shield_defenses",
                    "$self",
                    [
                        "normal",
                        "SKIP_SHIELD_EROSION",
                        "$event.holder",
                        "normal",
                        "SHIELD_COUNT",
                        "avail",
                        "STORE",
                        "$event.remaining",
                        "$local.avail",
                        2,
                        "FLOOR_DIV",
                        "MIN",
                        "blocked",
                        "STORE",
                        "$local.blocked",
                        2,
                        "MUL",
                        "spent",
                        "STORE",
                        "$local.blocked",
                        0,
                        "GT",
                        [
                            "$event.holder",
                            "normal",
                            "$local.spent",
                            "$local.blocked",
                            "SHIELD_ABSORB",
                        ],
                        "WHEN",
                        "$event.remaining",
                        "$local.blocked",
                        "SUB",
                        "left_dmg",
                        "STORE",
                        "$local.avail",
                        "$local.spent",
                        "SUB",
                        "left_shield",
                        "STORE",
                        "$local.left_dmg",
                        0,
                        "GT",
                        "$local.left_shield",
                        0,
                        "GT",
                        "AND",
                        [
                            "$event.holder",
                            "normal",
                            "$local.left_shield",
                            "$local.left_dmg",
                            "MIN",
                            "SHIELD_ERODE",
                        ],
                        "WHEN",
                    ],
                    "ADD_SHIELD_DEFENSE",
                ],
            },
        }

    def test_solo_two_for_one_rule_preserves_unneeded_remainder_and_erodes_on_overflow(self):
        cases = (
            (0, 1, 0, 1, 0, 0),
            (1, 1, 0, 1, 0, 1),
            (2, 1, 0, 0, 1, 0),
            (3, 1, 1, 0, 1, 0),
            (3, 2, 0, 1, 1, 1),
            (5, 2, 1, 0, 2, 0),
            (10**6, 3, 10**6 - 6, 0, 3, 0),
        )
        for start_shield, incoming, end_shield, expected_hp_lost, expected_abs, expected_erode in cases:
            with self.subTest(start_shield=start_shield, incoming=incoming):
                ctx = TraceContext()
                actor = actor_for(ctx, 1)
                actor.hp = 30
                actor.shield = start_shield
                ctx.register_entries(actor, [self._pierce_two_to_one_rule()])

                receipt = ctx.deal_damage(None, actor, incoming, penetration="pierce", result_field=None)
                self.assertEqual(actor.shield, end_shield)
                self.assertEqual(30 - actor.hp, expected_hp_lost)
                self.assertEqual(receipt["hp_lost"], expected_hp_lost)
                self.assertIn(OpCode.ADD_SHIELD_DEFENSE, ctx.operations)
                self.assertEqual(ctx.stack, [])

                seen = []
                ctx2 = TraceContext()
                actor2 = actor_for(ctx2, 1)
                actor2.hp = 30
                actor2.shield = start_shield
                ctx2.register_entries(actor2, [self._pierce_two_to_one_rule()])
                ctx2.register_entries(None, [{
                    "trigger": "AFTER APPLY_DAMAGE",
                    "operation": lambda vm: seen.append((vm.event["shield_absorbed"], vm.event["shield_eroded"], vm.event["shield_lost"])),
                }])
                ctx2.deal_damage(None, actor2, incoming, penetration="pierce")
                self.assertEqual(seen, [(expected_abs, expected_erode, expected_abs + expected_erode)])

    def test_custom_rule_can_express_any_block_formula_without_engine_flags(self):
        ctx = TraceContext()
        actor = actor_for(ctx, 1)
        actor.hp = 20
        actor.concept_shield = 2
        ctx.register_entries(actor, [{
            "trigger": "BEFORE APPLY_DAMAGE",
            "subject": "target",
            "operation": {
                "op": "program",
                "code": [
                    "$event.shield_defenses",
                    "$self",
                    [
                        "$event.holder", "concept", "SHIELD_COUNT", 0, "GT",
                        "$event.remaining", 0, "GT", "AND",
                        [
                            "$event.holder", "concept", 1,
                            "$event.remaining", 3, "MIN",
                            "SHIELD_ABSORB",
                        ],
                        "WHEN",
                    ],
                    "ADD_SHIELD_DEFENSE",
                ],
            },
        }])
        lost = ctx.deal_damage(None, actor, 5, penetration="normal", result_field="hp_lost")
        self.assertEqual(actor.concept_shield, 1)
        self.assertEqual(lost, 2)
        self.assertEqual(actor.hp, 18)

    def test_ally_shield_borrowing_and_multi_defender_ordering(self):
        ctx = TraceContext()
        donor_a = actor_for(ctx, 1)
        donor_a.id, donor_a.name = "donor_a", "盾卫甲"
        donor_b = _named_actor(donor_a.player, "donor_b", "盾卫乙")
        victim = _named_actor(donor_a.player, "victim", "受击者")
        attacker = actor_for(ctx, 2)
        donor_a.reinforced_shield = 2
        donor_a.shield = 3
        donor_b.reinforced_shield = 4
        victim.hp = 20
        victim.shield = 1

        def borrow_entry(cap_per_hit):
            return {
                "trigger": "BEFORE APPLY_DAMAGE",
                "subject": "any",
                "when": [
                    {"left": "$event.target.player", "op": "eq", "right": "$self.player"},
                    {"left": "$event.target", "op": "ne", "right": "$self"},
                ],
                "operation": {
                    "op": "program",
                    "code": [
                        "$event.shield_defenses",
                        "$self",
                        [
                            "$event.holder", "reinforced",
                            "$event.remaining", "$event.holder", "reinforced", "SHIELD_COUNT", "MIN",
                            cap_per_hit, "MIN", "DUP",
                            "SHIELD_ABSORB",
                        ],
                        "ADD_SHIELD_DEFENSE",
                    ],
                },
            }

        ctx.register_entries(donor_a, [borrow_entry(2)])
        ctx.register_entries(donor_b, [borrow_entry(3)])

        with ctx.collect_facts() as facts:
            lost = ctx.deal_damage(attacker, victim, 4, penetration="pierce", result_field="hp_lost")

        self.assertEqual(lost, 0)
        self.assertEqual(victim.hp, 20)
        self.assertEqual(victim.shield, 0)
        self.assertEqual(donor_a.reinforced_shield, 0)
        self.assertEqual(donor_b.reinforced_shield, 2)
        settled = [data for kind, data in facts if kind == "damage_settled"][-1]
        self.assertEqual(settled["absorbed"]["reinforced_shield"], 4)
        self.assertEqual(settled["eroded"]["shield"], 1)
        self.assertEqual(len(settled["borrowed_absorbed"]), 2)

        donor_b.is_alive = False
        victim.hp = 20
        lost2 = ctx.deal_damage(attacker, victim, 3, penetration="pierce", result_field="hp_lost")
        self.assertEqual(donor_b.reinforced_shield, 2)
        self.assertEqual(lost2, 3)

    def test_shield_settlement_opcodes_validate_context_and_channel(self):
        ctx = Context()
        actor = actor_for(ctx, 1)
        for code in (
            [actor, "normal", 1, 1, OpCode.SHIELD_ABSORB],
            [actor, "normal", 1, OpCode.SHIELD_ERODE],
            ["normal", OpCode.SKIP_SHIELD_EROSION],
            ["not_a_list", actor, [], OpCode.ADD_SHIELD_DEFENSE],
            [[], actor, "not_a_block", OpCode.ADD_SHIELD_DEFENSE],
        ):
            with self.subTest(code=code), self.assertRaises(ValueError):
                ctx.eval_block(code)
