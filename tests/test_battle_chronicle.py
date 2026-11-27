"""Dedicated backend tests for BattleChronicle, fog-of-war redaction, exact math breakdowns,
restrained canonical terminology, and Phase 1A-1B Displayer / ArenaEngine presentation fixes.
"""

import random
import unittest

from battle_ui.chronicle import BattleChronicle, format_damage_formula, format_die_formula
from game import Game
from loader import load_characters_from_packs
from models.dice import DiceLevel
from models.opcode import OpCode
from player.player import Player


class BattleChronicleAndPresentationTests(unittest.TestCase):
    def test_damage_uses_actual_source_even_when_source_is_target(self):
        for target_side in (1, 2):
            for op in (OpCode.DAMAGE, OpCode.REAL_DAMAGE):
                with self.subTest(target_side=target_side, op=op):
                    game = self._make_simple_game()
                    chronicle = BattleChronicle(game)
                    source = game.players[0].characters[0]
                    target = game.players[target_side - 1].characters[0]
                    before = target.hp
                    with game.context.binding(source=source, target=target, side=1, card=source.skills[0],
                                              damage_cause="测试伤害", modifiers=[], incoming_modifiers=[],
                                              damage_precomputed=True, damage_die=None):
                        args = [target, 2, "normal", "effect"] if op == OpCode.DAMAGE else [target, 2]
                        game.context.eval_block([*args, op])
                    lost = before - target.hp
                    self.assertGreater(lost, 0)
                    turn = chronicle.snapshot(1)["turns"][0]
                    self.assertEqual(turn["stats"]["damage_by_side"], {"1": lost, "2": 0})

    def _make_simple_game(self, seed=11):
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲席"), Player(2, "乙席")
        game = Game([p1, p2], rng=random.Random(seed))
        game.deploy_rosters([[pool["nova_lin_qiu"]], [pool["lan_qing"]]])
        return game

    def test_die_and_damage_formulas_distinguish_modifiers_and_shield_erosion(self):
        # Case A: boosted die level (1~8 vs printed 1~6), base+2, multiplier x2, status-1, clash_score vortex floor
        expr_a, range_a = format_die_formula({
            "die_type": "slash",
            "printed_level": int(DiceLevel.D6.value),
            "level": int(DiceLevel.D8.value),
            "roll_max": 8,
            "base_value": 2,
            "rolled_value": 5,
            "multiplier": 2,
            "die_final_bonus": 1,
            "card_final_bonus": 0,
            "status_final_bonus": -1,
            "final_score": 14,
            "clash_score": 16,
            "formula": "+",
        })
        self.assertEqual(range_a, "1~8（原1~6）")
        self.assertIn("(基础2 + 掷5)×2", expr_a)
        self.assertIn("骰修正+1", expr_a)
        self.assertIn("状态-1", expr_a)
        self.assertIn("= 最终14 → 拼点16（拼点修正+2）", expr_a)

        # Case B: plain unboosted die
        expr_b, range_b = format_die_formula({
            "die_type": "pierce",
            "printed_level": int(DiceLevel.D6.value),
            "level": int(DiceLevel.D6.value),
            "roll_max": 6,
            "base_value": 0,
            "rolled_value": 4,
            "multiplier": 1,
            "die_final_bonus": 0,
            "card_final_bonus": 0,
            "status_final_bonus": 0,
            "final_score": 4,
            "clash_score": 4,
            "formula": "+",
        })
        self.assertEqual(range_b, "1~6")
        self.assertEqual(expr_b, "掷4 = 最终4")

        # Damage formula distinguishes piercing erosion vs reinforced absorption
        dmg_pierce = format_damage_formula(
            base_amount=6,
            outgoing=8,
            multiplier=1.5,
            incoming=12,
            grade="piercing",
            absorbed={"reinforced_shield": 5, "shield": 0},
            eroded={"shield": 12},
            hp_lost=7,
            hp_after=23,
            max_hp=30,
        )
        self.assertIn("原始6 → 攻方修正后8", dmg_pierce)
        self.assertIn("倍率×1.5", dmg_pierce)
        self.assertIn("入盾前12（穿甲伤害）", dmg_pierce)
        self.assertIn("强化盾抵消5", dmg_pierce)
        self.assertIn("普通盾磨损12", dmg_pierce)
        self.assertIn("实扣生命 7（剩余 23/30）", dmg_pierce)

    def test_chronicle_enforces_fog_of_war_before_reveal_and_unlocks_cleanly(self):
        game = self._make_simple_game(seed=19)
        chronicle = BattleChronicle(game)
        game.context.record("turn_opened", number=1)
        c1 = game.players[0].characters[0]
        sk_name = c1.skill_data[0]["name"]
        sk_id = c1.skill_data[0]["id"]

        chronicle.record_action(
            "draw_bottom",
            side=1,
            count=1,
            card_names=[sk_name],
        )
        chronicle.record_action(
            "place",
            side=1,
            actor_id=c1.id,
            actor_name=c1.name,
            card_id=sk_id,
            card_name=sk_name,
            cost=2,
            duel_number=1,
            face_up=False,
        )

        # Before cards_revealed: P1 sees card names, P2 sees redacted text & zero leaked card entities
        snap_p1 = chronicle.snapshot(viewer_side=1)
        snap_p2 = chronicle.snapshot(viewer_side=2)
        p1_texts = [it["text"] for b in snap_p1["turns"][0]["blocks"] for r in b["rounds"] for it in r["items"]]
        p2_texts = [it["text"] for b in snap_p2["turns"][0]["blocks"] for r in b["rounds"] for it in r["items"]]
        p2_entities = [e for b in snap_p2["turns"][0]["blocks"] for r in b["rounds"] for it in r["items"] for e in it["entities"]]
        self.assertTrue(any(sk_name in t for t in p1_texts))
        self.assertFalse(any(sk_name in t for t in p2_texts))
        self.assertFalse(any(e["kind"] == "card" for e in p2_entities))

        # After cards_revealed: board placement is revealed to P2, while private draw_bottom remains hidden until match end!
        game.context.record("cards_revealed", duels=[])
        snap_p2_rev = chronicle.snapshot(viewer_side=2)
        rev_items = [it for b in snap_p2_rev["turns"][0]["blocks"] for r in b["rounds"] for it in r["items"]]
        self.assertFalse(sk_name in rev_items[0]["text"])  # draw_bottom stays private during live play
        self.assertTrue(sk_name in rev_items[1]["text"])   # board placement is now public

        # Post-match unlock_all reveals draw_bottom too
        snap_end = chronicle.snapshot(viewer_side=2, unlock_all=True)
        self.assertTrue(snap_end["unlocked_all"])
        end_items = [it for b in snap_end["turns"][0]["blocks"] for r in b["rounds"] for it in r["items"]]
        self.assertTrue(sk_name in end_items[0]["text"])

    def test_chronicle_lightcore_and_combat_records_use_strictly_canonical_restrained_terms(self):
        game = self._make_simple_game(seed=23)
        chronicle = BattleChronicle(game)
        c1 = game.players[0].characters[0]
        c2 = game.players[1].characters[0]

        game.context.record("turn_opened", number=1)
        game.context.record("duel_started", series="regular", number=1)
        game.context.record("lightcore_damage", side=2, character_id=c2.id, character_name=c2.name,
                            source=c1.name, amount=4, hp=6, maximum=10)
        game.context.record("lightcore_overflow", side=2, character_id=c2.id, character_name=c2.name,
                            lost=2, hp=8, maximum=10)
        game.context.record("lightcore_collapse", side=2, character_id=c2.id, character_name=c2.name)
        game.context.record("lightcore_restored", side=2, character_id=c2.id, character_name=c2.name,
                            hp=8, maximum=8)

        md = chronicle.to_markdown(viewer_side=1, unlock_all=True)
        self.assertIn("造成 4 点光点伤害（完整度 6/10）", md)
        self.assertIn("新光点生命条扣除 2 点（完整度 8/10）", md)
        self.assertIn(f"{c2.name} 的光点形态群崩塌。", md)
        for forbidden in ("光核", "崩解", "结构战报", "迷雾", "☠", "⚔", "★"):
            self.assertNotIn(forbidden, md)
