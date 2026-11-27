"""Regression checks for the battle chronicle."""

import io
import random
import unittest
from contextlib import redirect_stdout

from battle_ui.chronicle import BattleChronicle, format_die_formula
from game import Game
from loader import load_characters_from_packs
from models.dice import Dice, DiceLevel
from models.opcode import OpCode
from models.special_actions import SpecialAction
from pipeline.pipeline import Pipeline, SidePipeline
from player.player import Player


class EndToEndBackendAuditTests(unittest.TestCase):
    def test_turn_end_recycle_format_no_dict_and_no_stray_dollar_in_markdown(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(3))
        game.deploy_rosters([[pool["plan_b_annolin"]], [pool["plan_b_heck"]]])
        chronicle = BattleChronicle(game)
        game.start_turn()
        game.context.record("duel_started", series="regular", number=1)
        game.context.record("hp_lost", target=p2.characters[0].combat_name, lost=4,
                            hp=p2.characters[0].hp - 4, maximum=p2.characters[0].max_hp)
        game.finish_turn()

        md = chronicle.to_markdown(viewer_side=1, unlock_all=True)
        self.assertNotIn("{'side':", md)
        self.assertRegex(md, r"第 \d+ 回合结束（P1 回收 \d+ 张、P2 回收 \d+ 张）。")
        self.assertNotIn("$", md)

    def test_direct_damage_with_after_apply_damage_trigger_single_counts_and_keeps_shields(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(5))
        game.deploy_rosters([[pool["plan_b_annolin"]], [pool["plan_b_heck"]]])
        chronicle = BattleChronicle(game)
        game.start_turn()
        atk = p1.characters[0]
        dfd = p2.characters[0]
        dfd.add_shield("normal", 3)
        dfd.add_shield("reinforced", 2)
        chronicle.flush()

        # Simulate an `AFTER APPLY_DAMAGE` entry (e.g. `偏转力场` status gain) firing BEFORE `direct_damage` record!
        game.context.register_entries(dfd, [{
            "trigger": "AFTER APPLY_DAMAGE",
            "operation": {"op": "program", "code": ["$self", "守护", 1, "STATUS"]},
        }])
        game.context.record("duel_started", series="regular", number=1)
        with game.context.binding(source=atk, target=dfd, side=1, card=atk.skills[0],
                                  modifiers=[], incoming_modifiers=[], damage_precomputed=True,
                                  damage_die=None):
            game.context.eval_block([dfd, 8, "normal", "effect", OpCode.DAMAGE])

        snap = chronicle.snapshot(viewer_side=1, unlock_all=True)
        t1 = snap["turns"][0]
        self.assertEqual(t1["stats"]["damage_by_side"]["1"], 3)
        duel = next(b for b in t1["blocks"] if b["kind"] == "duel")
        self.assertEqual(duel["summary"]["hp_delta"]["2"], -3)
        damage_items = [it for rnd in duel["rounds"] for it in rnd["items"] if it["category"] == "damage"]
        self.assertEqual(len(damage_items), 1)
        self.assertIn("强化盾抵消2 / 普通盾抵消3", damage_items[0]["formula"])

    def test_hidden_card_replaced_before_reveal_stays_secret_after_cards_revealed(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(7))
        game.deploy_rosters([[pool["nova_lin_qiu"]], [pool["lan_qing"]]])
        chronicle = BattleChronicle(game)
        game.first_player = p1
        game.start_turn()
        game.run_placement()
        p1.draw_card(3)
        card_a, card_b = p1.cardspace.hand.content[0], p1.cardspace.hand.content[1]
        self.assertNotEqual(card_a.id, card_b.id)

        self.assertTrue(game.place_in_duel(1, card_a, 0))
        chronicle.record_action(
            "place",
            side=1,
            actor_id=card_a.character.id,
            actor_name=card_a.character.name,
            card_id=card_a.id,
            card_name=card_a.name,
            cost=card_a.cost,
            duel_number=1,
            face_up=False,
            instance_id=card_a.instance_id,
        )
        card_b.data["anytime_replace"] = True
        act = SpecialAction("replace", card_b, target_card=card_a)
        self.assertTrue(game.special.apply(p1, act))

        # Before reveal: P2 sees neither A nor B
        pre_p2 = chronicle.to_markdown(viewer_side=2)
        self.assertNotIn(card_a.name, pre_p2)
        self.assertNotIn(card_b.name, pre_p2)

        # Reveal: P2 sees B (now on board), MUST NOT see withdrawn A in text or entities!
        game.reveal_cards()
        post_p2 = chronicle.to_markdown(viewer_side=2)
        self.assertIn(card_b.name, post_p2)
        self.assertNotIn(card_a.name, post_p2)
        post_entities = [
            e for b in chronicle.snapshot(viewer_side=2)["turns"][0]["blocks"]
            for r in b["rounds"] for it in r["items"] for e in it["entities"]
        ]
        self.assertFalse(any(e.get("name") == card_a.name for e in post_entities))
        self.assertTrue(any(e.get("name") == card_b.name for e in post_entities))

        # Game over: full unlock exposes A as well
        post_full = chronicle.to_markdown(viewer_side=2, unlock_all=True)
        self.assertIn(card_a.name, post_full)

    def test_standalone_character_facts_no_duplicate_with_opcode_and_missing_facts(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(9))
        game.deploy_rosters([[pool["plan_b_annolin"]], [pool["plan_b_heck"]]])
        chronicle = BattleChronicle(game)
        game.start_turn()
        actor = p1.characters[0]

        # Opcode operations should produce 1 entry each (not doubled by character.py balance facts)
        game.context.eval_block([actor, 3, OpCode.LOSE_HP])
        game.context.eval_block([actor, 2, OpCode.HEAL])
        game.context.eval_block([actor, "normal", 4, OpCode.SHIELD])
        game.context.eval_block([actor, "烧伤", 3, OpCode.STATUS])
        items_after_opcodes = [it["text"] for b in chronicle.snapshot(1)["turns"][0]["blocks"]
                               for r in b["rounds"] for it in r["items"]]
        self.assertEqual(sum("失去 3 点生命" in t for t in items_after_opcodes), 1)
        self.assertEqual(sum("恢复 2 点生命" in t for t in items_after_opcodes), 1)
        self.assertEqual(sum("普通盾 → 4" in t for t in items_after_opcodes), 1)
        self.assertEqual(sum("烧伤 +3 → 3" in t for t in items_after_opcodes), 1)

        # Direct kernel mutations (outside opcodes) must STILL log once!
        actor.lose_hp(1)
        actor.heal(1)
        actor.add_shield("normal", 2)
        actor.clear_status("烧伤")
        items_after_direct = [it["text"] for b in chronicle.snapshot(1)["turns"][0]["blocks"]
                              for r in b["rounds"] for it in r["items"]]
        self.assertEqual(sum("失去 1 点生命" in t for t in items_after_direct), 1)
        self.assertEqual(sum("恢复 1 点生命" in t for t in items_after_direct), 1)
        self.assertEqual(sum("普通盾 4 → 6" in t for t in items_after_direct), 1)
        self.assertEqual(sum("清空 3 层 烧伤" in t for t in items_after_direct), 1)

        # Missing facts & crash-prone attack_declared(duel_index=None)
        card = actor.skills[0]
        with game.context.binding(source=actor, side=1, card=card):
            p1.common_cost = 5
            actor.independent_cost = 1
            game.context.pay_skill_cost(card)
        game.context.record("attack_declared", series="pre_reveal", number=1, player=p1.name,
                            card=card.name, target=p2.characters[0].name, duel_index=None)
        game.context.record("unopposed_clash_lose", actor=actor.combat_name)
        game.context.record("rear_card_invalidated", side=1, card=card.name, card_id=card.id)
        game.context.record("hand_card_taken", receiver=actor.combat_name, from_side=2)
        game.context.record("card_face_changed", card=card.name, face="up")
        game.context.record("placement_lock", card=card.name, locked=True)
        game.context.record("ability_changed", target=actor.combat_name, name="充能", total=2)
        game.context.record("ability_spent", target=actor.combat_name, name="充能", amount=1, total=1)

        all_txt = "\n".join(
            it["text"] for b in chronicle.snapshot(1, unlock_all=True)["turns"][0]["blocks"]
            for r in b["rounds"] for it in r["items"]
        )
        self.assertIn("费用支付：", all_txt)
        self.assertIn("判定拼点落败", all_txt)
        self.assertIn("后置技能", all_txt)
        self.assertIn("接过一张技能牌", all_txt)
        self.assertIn("翻正", all_txt)
        self.assertIn("锁定位置", all_txt)
        self.assertIn("使用 1 次充能 → 剩余 1 次", all_txt)

    def test_custom_die_formula_with_multiplier_and_resolve_final_score_effect(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(17))
        c1_def = {"id": "test_a", "name": "甲", "rank": "NORMAL", "max_hp": 12,
                  "skills": [{"id": "s1", "name": "斩击", "cost": 1, "dice": []}]}
        c2_def = {"id": "test_b", "name": "乙", "rank": "NORMAL", "max_hp": 12,
                  "skills": [{"id": "s2", "name": "格挡", "cost": 1, "dice": []}]}
        game.deploy_rosters([[c1_def], [c2_def]])
        game.start_turn()
        actor = p1.characters[0]
        card = actor.skills[0]
        die = Dice({"type": "slash", "level": int(DiceLevel.D6.value),
                    "base_value": 2, "multiplier": 3, "calc_formula": "b + v * m"}, game=game)
        die.card = card
        die.value = 4  # raw calc = 2 + 4 * 3 = 14
        game.context.register_entries(actor, [{
            "trigger": "BEFORE RESOLVE_FINAL_SCORE",
            "operation": {"op": "program", "code": [2, "ADD"]},
        }])
        final_val = die.resolve_value(OpCode.RESOLVE_FINAL_SCORE, die.calculate_final_score())
        self.assertEqual(final_val, 16)

        pipe = SidePipeline(1, game, lane="front")
        pipe.card = card
        pipe.die = die
        detail = Pipeline._die_roll_detail(pipe, result="win")
        self.assertEqual(detail["final_effect_bonus"], 2)
        expr, _ = format_die_formula(detail)
        self.assertIn("公式[b + v * m]", expr)
        self.assertIn("效果修正+2", expr)
        self.assertIn("= 最终16", expr)
