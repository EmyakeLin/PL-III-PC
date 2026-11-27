"""Dedicated backend tests for BattleChronicle, fog-of-war redaction, exact math breakdowns,
restrained canonical terminology, and Phase 1A-1B Displayer / ArenaEngine presentation fixes.
"""

import random
import unittest

from battle_mcp.engine import ArenaEngine
from battle_ui.chronicle import BattleChronicle, format_damage_formula, format_die_formula
from battle_ui.match import BattleMatch
from displayer import Displayer
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

    def test_displayer_projects_runtime_die_level_and_dual_form_traits_and_team_statuses(self):
        game = self._make_simple_game(seed=29)
        p1 = game.players[0]
        p1.draw_card(3)
        card = p1.cardspace.hand.content[0]
        printed_lvl = int(card.dice[0]["level"])
        card.level_bonus = 1
        card.final_bonus = 2
        p1.team_statuses["隧道开启"] = 1

        disp = Displayer(game, viewer_side=1)
        frame = disp.snapshot()
        hand_views = [c for c in frame["players"][0]["hand"] if c["id"] == card.id]
        self.assertGreaterEqual(len(hand_views), 1)
        die_view = hand_views[0]["dice"][0]
        self.assertEqual(die_view["printed_level"], printed_lvl)
        self.assertEqual(die_view["level"], printed_lvl + 1)
        self.assertGreater(die_view["roll_max"], 0)
        self.assertEqual(die_view["final_bonus"], 2)
        self.assertIn("team_status_details", frame["players"][0])

        # Verify Lin Qiu's `空断` carries `resource_cost` & `range_traits`, and Lan Qing's `电叉·回环舞` carries `form_when`
        void_cut = next(s for s in disp.catalog()["players"][0]["characters"][0]["skills"] if s["id"] == "lin_qiu_void_cut")
        self.assertEqual(void_cut["resource_cost"], {"status": "隧道", "amount": 2})
        lan_dance = next(s for s in disp.catalog()["players"][1]["characters"][0]["skills"] if s["id"] == "lan_dance_2")
        self.assertEqual(lan_dance["form_when"], {"status": "电叉·回环舞·活化", "form": "active", "snapshot": "use"})

    def test_arena_engine_preserves_dissolved_temporary_clash_cards(self):
        eng = ArenaEngine([["plan_b_annolin"], ["plan_b_heck"]], seed=41)
        while not eng.state(1)["duels"]:
            req = eng.required_sides()
            if req:
                s = req[0]
                ds = eng.state(s).get("draw_select")
                if ds:
                    eng.draw_bottom(s, [c.get("action_key") or c["id"] for c in ds["cards"][:ds["discard_count"]]])
                else:
                    eng.apply(s, eng.options(s)[0])
            else:
                eng.advance()
        temp_card = (eng.game.players[0].cardspace.hand.content or eng.game.players[0].cardspace.draw_pile.content)[0]
        temp_card.destroyed = True
        eng._temporary_clashes[("regular", 1, 1, temp_card)] = {
            "id": temp_card.id,
            "instance_id": temp_card.instance_id,
            "name": temp_card.name,
            "character_id": "plan_b_annolin",
            "cost": 0,
            "dice": [],
            "entries": [],
        }
        st = eng.state(1)
        duel_1 = st["duels"][0]
        side_1 = next(s for s in duel_1["sides"] if s["side"] == 1)
        self.assertTrue(any(c.get("instance_id") == temp_card.instance_id and c.get("dissolved") is True for c in side_1.get("resolved_cards", [])))


if __name__ == "__main__":
    unittest.main()
