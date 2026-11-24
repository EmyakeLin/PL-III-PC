"""Discriminating semantic tests for Rear Duel (后置交锋):
1. Placement permissions, front-anchor requirement, and customizable rear capacity (`REAR_CAPACITY` / `SET_REAR_CAPACITY`).
2. Unified clash formula across 1v2 / 2v1 / 2v2:
   - All-lose rounds (`F1 + R1 > F2`, `F1 < F2`, `R1 < F2`) where all 3 dice get `"lose"` and fire `on_clash_lose`.
   - Enemy front winner strictly hits opposing front character (`F1.character`), never rear character (`R1.character`).
   - Double-win rounds (`F1 > F2` and `R1 > F2`) where both `F1` and `R1` land hits on `F2.character`.
   - Asymmetric `2v2` (`F` vs `enemy_F + enemy_R`, `R` vs `enemy_F`, both targeting `enemy_F`) and seamless transition (`2v2 -> 1v1`) when one track naturally exhausts its dice while the front card stays valid.
3. Special dice (`skip` / `block` / `evade`) lane distinction:
   - Front `skip` skips the entire round and triggers `on_clash_skip`; Rear `skip` neither skips the round nor triggers `on_clash_skip`.
   - Unopposed Front `block` triggers `on_clash_skip`; unopposed Rear `block` sits out without `on_clash_skip`; clashing Rear `block` contributes its clash score to `F + R`.
4. Cascade invalidation (`CardState.NEGATED`, `reason="rear_anchor_lost"`):
   - Front destroyed, negated, bounced, unpaid, or front character killed immediately invalidates attached rear cards; natural dice exhaustion does NOT invalidate rear cards.
5. Dynamic entry insertion (`INSERT_SKILL` at `"rear_duel"` with `{"prepaid": true}`) paying `2 * cost` in status (`能源`) without consuming `used_duels` or team cost, joining Round 1 immediately.
6. Top-level bridge (`Displayer` & `BattleMatch`) exposing `place_rear`, concealed `duels_rear` owners, `combat.sides[].rear`, and `lane`-tagged `fx_events`.
"""
import io
import json
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from battle_ui.match import BattleMatch
from displayer import Displayer, hand_key
from entry.entry import Entry
from game import Game
from models.card import Card, CardState
from models.character import Character
from models.opcode import OpCode
from models.special_actions import SpecialAction
from player.player import Player


class RearDuelSemanticTests(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(1024))
        self.game.first_player = self.left
        self.c1 = self.recruit(self.left, "甲前", max_duels=3)
        self.c2 = self.recruit(self.left, "甲后", max_duels=3, rear_duel=True)
        self.foe1 = self.recruit(self.right, "乙前", max_duels=3)
        self.foe2 = self.recruit(self.right, "乙后", max_duels=3, rear_duel=True)
        self.game.start_turn()
        self.left.max_cost = self.right.max_cost = 100

    @staticmethod
    def recruit(player, name, *, max_hp=60, max_duels=2, rear_duel=False, passives=()):
        data = {
            "id": name,
            "name": name,
            "rank": "NORMAL",
            "max_hp": max_hp,
            "max_duels": max_duels,
            "skills": [],
            "passive_skills": [{"name": f"{name}被动", "entries": list(passives)}] if passives else [],
        }
        if rear_duel:
            data["rear_duel"] = True
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    @staticmethod
    def make_card(actor, name, dice_specs, *, cost=0, rear_duel=False, anytime_play=(), entries=(), in_hand=True):
        data = {
            "id": name,
            "name": name,
            "cost": cost,
            "dice": list(dice_specs),
            "entries": list(entries),
        }
        if rear_duel:
            data["rear_duel"] = True
        if anytime_play:
            data["anytime_play"] = list(anytime_play)
        card = Card(actor.player, data, actor)
        actor.skills.append(card)
        if in_hand:
            actor.player.cardspace.hand.add_card(card)
        return card

    @staticmethod
    def slash_die(score, *, damage=3, entries=()):
        # With randint patched to return 1, level=1 (1..4 -> 1) + base_value=(score - 1) yields exact `score`.
        return {
            "type": "slash",
            "level": 1,
            "base_value": score - 1,
            "entries": [f"{damage}物理", *entries],
        }

    @staticmethod
    def block_die(score, *, entries=()):
        return {
            "type": "block",
            "level": 1,
            "base_value": score - 1,
            "entries": list(entries),
        }

    def eval_query(self, block):
        self.game.context.eval_block(block)
        return self.game.context.pop()

    def fight_fixed_low(self):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=lambda low, high: low):
            for _ in range(5000):
                if self.game.is_over or not self.game.pipeline.in_duel_phase:
                    return
                self.game.next_step()
        self.fail("交锋未在步数上限内结算完成")

    # ------------------------------------------------------------------
    # 1. Placement eligibility, anchor requirement & rear capacity
    # ------------------------------------------------------------------
    def test_rear_placement_eligibility_and_capacity_boundaries(self):
        front_card = self.make_card(self.c1, "常规斩", [self.slash_die(5)])
        ineligible = self.make_card(self.c1, "无权卡", [self.slash_die(4)])
        rear_card_1 = self.make_card(self.c2, "后援一", [self.slash_die(4)])
        rear_card_2 = self.make_card(self.c2, "后援二", [self.slash_die(4)])

        self.game.run_placement()
        # Before any front card exists, rear placement has no legal slot.
        self.assertEqual(self.game.legal_rear_placements().get(rear_card_1, []), [])
        self.assertFalse(self.game.place_in_duel(1, rear_card_1, 0, rear=True))

        # Place front card on Duel 1.
        self.assertTrue(self.game.place_in_duel(1, front_card, 0))
        slot = self.game.duelspace.space[0]

        # Ineligible character/card still cannot enter rear duel; eligible card can.
        self.assertFalse(self.game.may_place_rear(ineligible))
        self.assertNotIn(ineligible, self.game.legal_rear_placements())
        self.assertEqual(self.game.legal_rear_placements().get(rear_card_1), [0])

        used_before = self.c2.used_duels
        self.assertTrue(self.game.place_in_duel(1, rear_card_1, 0, rear=True))
        self.assertEqual(self.c2.used_duels, used_before + 1)
        self.assertEqual(slot.play_mode(rear_card_1), "rear")
        self.assertIsNone(slot.play_mode(front_card))

        # Default capacity is 1 -> second rear card is rejected.
        self.assertEqual(self.eval_query([slot, 1, OpCode.REAR_CAPACITY]), 1)
        self.assertEqual(self.game.legal_rear_placements().get(rear_card_2, []), [])
        self.assertFalse(self.game.place_in_duel(1, rear_card_2, 0, rear=True))

        # Raising rear capacity to 2 via SET_REAR_CAPACITY unlocks the second rear card.
        self.assertEqual(self.game.context.eval_block([slot, 1, 2, OpCode.SET_REAR_CAPACITY]), 2)
        self.assertEqual(self.eval_query([slot, 1, OpCode.REAR_CAPACITY]), 2)
        self.assertEqual(self.game.legal_rear_placements().get(rear_card_2), [0])
        self.assertTrue(self.game.place_in_duel(1, rear_card_2, 0, rear=True))

        self.assertEqual(self.eval_query([slot, 1, OpCode.REAR_SLOT_CARDS]), [rear_card_1, rear_card_2])
        self.assertEqual(self.eval_query([slot, 1, OpCode.SLOT_CARDS]), [front_card, rear_card_1, rear_card_2])

    # ------------------------------------------------------------------
    # 2. 1v2 All-Lose vs Enemy Front Win Target vs Double Win
    # ------------------------------------------------------------------
    def test_one_vs_two_all_lose_vs_enemy_front_targeting_vs_double_win(self):
        # Case A: F1=5, R1=6 (sum 11) vs F2=8 -> ALL THREE LOSE!
        f1 = self.make_card(self.c1, "前五", [self.slash_die(5, damage=4)])
        r1 = self.make_card(self.c2, "后六", [self.slash_die(6, damage=5)])
        f2 = self.make_card(self.foe1, "敌八", [self.slash_die(8, damage=7)])
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.assertTrue(self.game.place_in_duel(2, f2, 0))

        lose_events = []
        self.game.context.entries.append(Entry.from_spec(None, {
            "trigger": "on_clash_lose",
            "operation": lambda ctx: lose_events.append((ctx.event["card"].name, ctx.event["lane"])),
        }))
        self.fight_fixed_low()

        d_f1, d_r1, d_f2 = f1.instantiated_dice[0], r1.instantiated_dice[0], f2.instantiated_dice[0]
        self.assertEqual((d_f1.clash_result, d_r1.clash_result, d_f2.clash_result), ("lose", "lose", "lose"))
        self.assertEqual((d_f1.landed_hits, d_r1.landed_hits, d_f2.landed_hits), (0, 0, 0))
        self.assertCountEqual(lose_events, [("前五", "front"), ("后六", "rear"), ("敌八", "front")])
        self.assertEqual((self.c1.hp, self.c2.hp, self.foe1.hp), (60, 60, 60))

        # Case B: F1=5 (c1), R1=6 (c2) vs F2=12 (foe1) -> F2 wins (12 > 11) and hits STRICTLY c1!
        self.setUp()
        f1 = self.make_card(self.c1, "前五", [self.slash_die(5, damage=4)])
        r1 = self.make_card(self.c2, "后六", [self.slash_die(6, damage=5)])
        f2 = self.make_card(self.foe1, "敌十二", [self.slash_die(12, damage=9)])
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.assertTrue(self.game.place_in_duel(2, f2, 0))
        self.fight_fixed_low()

        d_f1, d_r1, d_f2 = f1.instantiated_dice[0], r1.instantiated_dice[0], f2.instantiated_dice[0]
        self.assertEqual((d_f1.clash_result, d_r1.clash_result, d_f2.clash_result), ("lose", "lose", "win"))
        self.assertEqual(d_f2.landed_hits, 1)
        self.assertEqual(self.c1.hp, 51)
        self.assertEqual(self.c2.hp, 60)  # Rear character never absorbs opposing front's win damage!

        # Case C: F1=7 (c1), R1=6 (c2) vs F2=5 (foe1) -> BOTH F1 and R1 win and BOTH hit foe1!
        self.setUp()
        f1 = self.make_card(self.c1, "前七", [self.slash_die(7, damage=4)])
        r1 = self.make_card(self.c2, "后六", [self.slash_die(6, damage=5)])
        f2 = self.make_card(self.foe1, "敌五", [self.slash_die(5, damage=9)])
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.assertTrue(self.game.place_in_duel(2, f2, 0))
        self.fight_fixed_low()

        d_f1, d_r1, d_f2 = f1.instantiated_dice[0], r1.instantiated_dice[0], f2.instantiated_dice[0]
        self.assertEqual((d_f1.clash_result, d_r1.clash_result, d_f2.clash_result), ("win", "win", "lose"))
        self.assertEqual((d_f1.landed_hits, d_r1.landed_hits, d_f2.landed_hits), (1, 1, 0))
        self.assertEqual(self.foe1.hp, 51)  # 60 - 4 - 5 = 51

    # ------------------------------------------------------------------
    # 3. 2v2 Asymmetric Clash & Exhaustion Transition (2v2 -> 1v1)
    # ------------------------------------------------------------------
    def test_two_vs_two_asymmetric_formula_and_exhaustion_transitions(self):
        # Round 1 (2v2):
        #   Left:  F1=10 (1 die), R1=[9, 8] (2 dice)  -> sum 19
        #   Right: F2=[8, 6] (2 dice), R2=6 (1 die)   -> sum 14
        # Expected Round 1:
        #   F1 (10 vs 14) -> lose! (Distinguishes from naive F1vF2 where 10 > 8 would win!)
        #   R1[0] (9 vs F2=8) -> win! Hits foe1 for 4!
        #   F2[0] (8 vs 19) -> lose!
        #   R2 (6 vs F1=10) -> lose!
        # Round 2 (F1 and R2 naturally exhausted -> automatic 1v1 between R1[1]=8 and F2[1]=6):
        #   slot.has_valid_front_anchor(1) stays True!
        #   R1[1] (8 vs 6) -> win! Hits foe1 for 5!
        f1 = self.make_card(self.c1, "甲前一骰", [self.slash_die(10, damage=3)])
        r1 = self.make_card(self.c2, "甲后二骰", [self.slash_die(9, damage=4), self.slash_die(8, damage=5)])
        f2 = self.make_card(self.foe1, "乙前二骰", [self.slash_die(8, damage=3), self.slash_die(6, damage=3)])
        r2 = self.make_card(self.foe2, "乙后一骰", [self.slash_die(6, damage=4)])

        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.assertTrue(self.game.place_in_duel(2, f2, 0))
        self.assertTrue(self.game.place_in_duel(2, r2, 0, rear=True))

        duel_Lifecycle = []
        for trig in ("on_duel_start", "on_duel_end"):
            self.game.context.entries.append(Entry.from_spec(None, {
                "trigger": trig,
                "operation": lambda ctx, t=trig: duel_Lifecycle.append((t, ctx.event["side"], ctx.event["lane"])),
            }))

        self.fight_fixed_low()
        slot = self.game.duelspace.space[0]
        self.assertTrue(slot.has_valid_front_anchor(1))
        self.assertNotEqual(r1.state, CardState.NEGATED)

        # Round 1 results
        self.assertEqual(f1.instantiated_dice[0].clash_result, "lose")
        self.assertEqual(r1.instantiated_dice[0].clash_result, "win")
        self.assertEqual(f2.instantiated_dice[0].clash_result, "lose")
        self.assertEqual(r2.instantiated_dice[0].clash_result, "lose")
        # Round 2 results (R1[1] vs F2[1])
        self.assertEqual(r1.instantiated_dice[1].clash_result, "win")
        self.assertEqual(f2.instantiated_dice[1].clash_result, "lose")
        # Both of R1's wins hit foe1 (front target), never foe2 (rear)!
        self.assertEqual((self.foe1.hp, self.foe2.hp), (51, 60))
        self.assertEqual((self.c1.hp, self.c2.hp), (60, 60))
        # Rear tracks must NEVER duplicate on_duel_start / on_duel_end!
        self.assertEqual(duel_Lifecycle, [
            ("on_duel_start", 1, "front"),
            ("on_duel_start", 2, "front"),
            ("on_duel_end", 1, "front"),
            ("on_duel_end", 2, "front"),
        ])

    # ------------------------------------------------------------------
    # 4. Special Dice (`skip` & `block`) on Front vs Rear Lanes
    # ------------------------------------------------------------------
    def test_skip_and_passive_dice_differ_between_front_and_rear_lanes(self):
        # Subcase A: Rear `skip` does NOT skip the round and does NOT fire `on_clash_skip`;
        # Front still clashes in Round 1, and Rear advances to its 2nd die in Round 2!
        skip_logs = []
        skip_entry = {
            "trigger": "on_clash_skip",
            "operation": lambda ctx: skip_logs.append((ctx.event["card"].name, ctx.event["lane"])),
        }
        f1 = self.make_card(self.c1, "前斩", [self.slash_die(7, damage=3), self.slash_die(4, damage=2)])
        r1 = self.make_card(self.c2, "后跳再斩", [
            {"type": "skip", "entries": [skip_entry]},
            self.slash_die(8, damage=4),
        ])
        f2 = self.make_card(self.foe1, "敌连斩", [self.slash_die(5, damage=3), self.slash_die(6, damage=3)])
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.assertTrue(self.game.place_in_duel(2, f2, 0))
        self.fight_fixed_low()

        self.assertEqual(skip_logs, [])  # Rear skip NEVER triggers on_clash_skip!
        # Round 1: F1[0]=7 clashed F2[0]=5 and won!
        self.assertEqual((f1.instantiated_dice[0].clash_result, f2.instantiated_dice[0].clash_result), ("win", "lose"))
        # Round 2: F1[1]=4 + R1[1]=8 (sum 12) clashed F2[1]=6 -> R1[1] won, F1[1] lost, F2[1] lost!
        self.assertEqual(
            (f1.instantiated_dice[1].clash_result, r1.instantiated_dice[1].clash_result, f2.instantiated_dice[1].clash_result),
            ("lose", "win", "lose"),
        )
        self.assertEqual(self.foe1.hp, 53)  # 60 - 3 (Round 1 F1) - 4 (Round 2 R1)

        # Subcase B: Front `skip` DOES skip the entire round and fires `on_clash_skip` ONLY on Front!
        self.setUp()
        skip_logs = []
        skip_entry = {
            "trigger": "on_clash_skip",
            "operation": lambda ctx: skip_logs.append((ctx.event["card"].name, ctx.event["lane"])),
        }
        f1 = self.make_card(self.c1, "前跳", [{"type": "skip", "entries": [skip_entry]}])
        r1 = self.make_card(self.c2, "后留斩", [self.slash_die(4, damage=2, entries=[skip_entry]), self.slash_die(8, damage=5)])
        f2 = self.make_card(self.foe1, "敌双斩", [self.slash_die(4, damage=2, entries=[skip_entry]), self.slash_die(5, damage=3)])
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.assertTrue(self.game.place_in_duel(2, f2, 0))
        self.fight_fixed_low()

        # Both front dice (`前跳` and `敌双斩`[0]) triggered `on_clash_skip`; rear `后留斩`[0] was skipped WITHOUT firing `on_clash_skip`!
        self.assertCountEqual(skip_logs, [("前跳", "front"), ("敌双斩", "front")])
        self.assertEqual(
            (f1.instantiated_dice[0].clash_result, r1.instantiated_dice[0].clash_result, f2.instantiated_dice[0].clash_result),
            ("skip", "skip", "skip"),
        )
        # Round 2 clashed R1[1]=8 vs F2[1]=5 cleanly!
        self.assertEqual((r1.instantiated_dice[1].clash_result, f2.instantiated_dice[1].clash_result), ("win", "lose"))
        self.assertEqual(self.foe1.hp, 55)

        # Subcase C: Unopposed Front `block` triggers `on_clash_skip`; unopposed Rear `block` does NOT!
        self.setUp()
        passive_skips = []
        on_skip = {
            "trigger": "on_clash_skip",
            "operation": lambda ctx: passive_skips.append((ctx.event["card"].name, ctx.event["lane"])),
        }
        f1 = self.make_card(self.c1, "前守", [self.block_die(5, entries=[on_skip])])
        r1 = self.make_card(self.c2, "后守", [self.block_die(6, entries=[on_skip])])
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.fight_fixed_low()
        self.assertEqual(passive_skips, [("前守", "front")])

    # ------------------------------------------------------------------
    # 5. Cascade Invalidation on Front Destroy / Unpaid / Owner Death
    # ------------------------------------------------------------------
    def test_cascade_invalidation_distinguishes_front_failure_from_natural_completion(self):
        # Case A: Destroying front card before combat immediately negates rear card.
        f1 = self.make_card(self.c1, "被毁前卡", [self.slash_die(6)])
        r1 = self.make_card(self.c2, "连坐后卡", [self.slash_die(7, damage=6)])
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))

        disabled = []
        self.game.context.entries.append(Entry.from_spec(None, {
            "trigger": "on_skill_disabled",
            "operation": lambda ctx: disabled.append((ctx.event["card"].name, ctx.event.get("reason"))),
        }))
        self.game.context.eval_block([f1, OpCode.DESTROY])
        self.assertEqual(r1.state, CardState.NEGATED)
        self.assertIn(("连坐后卡", "rear_anchor_lost"), disabled)
        self.fight_fixed_low()
        self.assertEqual(self.foe1.hp, 60)

        # Case B: Front card fails cost payment (`max_cost = 0` for 2-cost front) -> 0-cost rear card ALSO invalidated!
        self.setUp()
        self.left.max_cost = 0
        used_names = []
        self.game.context.entries.append(Entry.from_spec(None, {
            "trigger": "on_skill_use",
            "operation": lambda ctx: used_names.append(ctx.event["card"].name),
        }))
        f1 = self.make_card(self.c1, "欠费前卡", [self.slash_die(6)], cost=2)
        r1 = self.make_card(self.c2, "零费后卡", [self.slash_die(8, damage=9)], cost=0)
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.fight_fixed_low()
        self.assertEqual(used_names, [])
        self.assertEqual(r1.state, CardState.NEGATED)
        self.assertEqual(self.foe1.hp, 60)

        # Case C: Mid-duel death of front character `c1` in Round 1 immediately withdraws `r1`'s Round 2 die!
        self.setUp()
        self.c1.hp = 5
        f1 = self.make_card(self.c1, "薄命前卡", [self.slash_die(4, damage=2), self.slash_die(4, damage=2)])
        r1 = self.make_card(self.c2, "长续航后卡", [self.slash_die(4, damage=2), self.slash_die(9, damage=10)])
        f2 = self.make_card(self.foe1, "致命重斩", [self.slash_die(12, damage=10), self.slash_die(5, damage=2)])
        self.assertTrue(self.game.place_in_duel(1, f1, 0))
        self.assertTrue(self.game.place_in_duel(1, r1, 0, rear=True))
        self.assertTrue(self.game.place_in_duel(2, f2, 0))
        self.fight_fixed_low()

        self.assertFalse(self.c1.is_alive)
        self.assertTrue(self.c2.is_alive)
        self.assertEqual(r1.state, CardState.NEGATED)
        # R1's 2nd die (9 vs 5) was never instantiated or rolled because c1 died in Round 1!
        self.assertIsNone(r1.instantiated_dice[1])
        self.assertEqual(self.foe1.hp, 60)

    # ------------------------------------------------------------------
    # 6. Dynamic Rear Insertion (`INSERT_SKILL` at `"rear_duel"` + `prepaid: true`)
    # ------------------------------------------------------------------
    def test_colossus_dynamic_rear_insertion_pays_double_energy_without_duel_quota(self):
        # 余晖巨像使用技能时，自身可以将一张卡置于其后置交锋（无需占用置卡机会），以巨像的能源支付2倍的卡牌费用以打出。
        colossus_passive = {
            "trigger": "on_skill_use",
            "subject": "source",
            "when": [{"left": "$event.lane", "op": "eq", "right": "front"}],
            "operation": {
                "op": "program",
                "code": [
                    "$player.cardspace.hand.content",
                    [
                        "$event.item.character", "$self", "IS",
                        "$event.item.destroyed", "NOT", "AND",
                        "$self", "$event.item", "SKILL_RESTRICTED", "NOT", "AND",
                        "$self", "能源", "STATUS_COUNT", "$event.item", "CARD_COST", 2, "MUL", "GE", "AND",
                    ],
                    "FILTER",
                    {
                        "literal": {
                            "optional": True,
                            "require_playable_hand": True,
                            "then": {
                                "op": "program",
                                "code": [
                                    "$event.chosen_card", "CARD_COST", 2, "MUL", "req_energy", "STORE",
                                    "$self", "能源", {"local": "req_energy"},
                                    {"call": "SPEND_STATUS", "result": "result", "default": 0},
                                    {"local": "req_energy"}, "EQ",
                                    [
                                        "$event.chosen_card",
                                        {"literal": {"prepaid": True}},
                                        "SKILL_USE",
                                        "$event.duel",
                                        "rear_duel",
                                        "INSERT_AT",
                                        "INSERT_SKILL",
                                    ],
                                    "WHEN",
                                ],
                            },
                        }
                    },
                    "CHOOSE_CARD",
                ],
            },
        }
        colossus = self.recruit(self.left, "余晖巨像", max_duels=1, passives=[colossus_passive])
        colossus.add_status("能源", 7)

        front = self.make_card(colossus, "巨像主炮", [self.slash_die(6, damage=4)], cost=2)
        affordable_rear = self.make_card(colossus, "副炮齐射", [self.slash_die(7, damage=5)], cost=3)
        too_expensive = self.make_card(colossus, "超载歼灭", [self.slash_die(9, damage=9)], cost=4)
        enemy_front = self.make_card(self.foe1, "敌方迎击", [self.slash_die(10, damage=6)], cost=0)

        # Restrict team max_cost to 2 (exact cost of front!) and max_duels to 1 (already full after front!).
        self.left.max_cost = 2
        self.assertTrue(self.game.place_in_duel(1, front, 0))
        self.assertEqual(colossus.used_duels, colossus.max_duels)
        self.assertTrue(self.game.place_in_duel(2, enemy_front, 0))

        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=lambda low, high: low):
            for _ in range(400):
                if self.game.special.decision_owner is not None or not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
            self.assertIs(self.game.special.decision_owner, self.left)
            opts = self.game.special.options(self.left)
            # Only `affordable_rear` (2*3=6 <= 7) passes `where`; `too_expensive` (2*4=8 > 7) is filtered out!
            chosen_cards = [o.target_card for o in opts if o.kind == "choose_card"]
            self.assertEqual(chosen_cards, [affordable_rear])
            self.assertTrue(self.game.special.apply(self.left, opts[0]))

            for _ in range(2000):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()

        # Verify:
        # 1. Paid 6 能源 (7 -> 1), team used_cost stayed at 2, used_duels stayed at 1!
        self.assertEqual(colossus.statuses.get("能源", 0), 1)
        self.assertEqual(self.left.used_cost, 2)
        self.assertEqual(colossus.used_duels, 1)
        # 2. `affordable_rear` paired immediately in Round 1 alongside `front`:
        #    front=6, rear=7 (sum 13) vs enemy_front=10 -> all 3 dice rolled and ALL 3 LOST (6<10, 7<10, 10<13)!
        self.assertEqual(
            (
                front.instantiated_dice[0].clash_result,
                affordable_rear.instantiated_dice[0].clash_result,
                enemy_front.instantiated_dice[0].clash_result,
            ),
            ("lose", "lose", "lose"),
        )
        self.assertIn(too_expensive, self.left.cardspace.hand.content)

    # ------------------------------------------------------------------
    # 7. Top-Level Bridge (`BattleMatch` & `Displayer`)
    # ------------------------------------------------------------------
    def test_top_level_bridge_match_and_displayer_expose_rear_lanes_and_fx_events(self):
        p1_front_spec = {
            "id": "p1_front",
            "name": "先锋",
            "rank": "NORMAL",
            "max_hp": 40,
            "max_duels": 2,
            "skills": [
                {"id": f"s_front_{i}", "name": "正斩", "cost": 1, "dice": [self.slash_die(7, damage=3)]}
                for i in range(3)
            ],
        }
        p1_rear_spec = {
            "id": "p1_rear",
            "name": "后卫",
            "rank": "NORMAL",
            "max_hp": 40,
            "max_duels": 2,
            "rear_duel": True,
            "skills": [
                {"id": f"s_rear_{i}", "name": "协斩", "cost": 1, "dice": [self.slash_die(6, damage=4)]}
                for i in range(3)
            ],
        }
        p2_spec = {
            "id": "p2_foe",
            "name": "劲敌",
            "rank": "NORMAL",
            "max_hp": 40,
            "max_duels": 2,
            "skills": [
                {"id": f"s_foe_{i}", "name": "强劈", "cost": 1, "dice": [self.slash_die(8, damage=5)]}
                for i in range(3)
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_path = Path(tmpdir) / "rear_test_pack.json"
            pack_path.write_text(
                json.dumps({"characters": [p1_front_spec, p1_rear_spec, p2_spec]}, ensure_ascii=False),
                encoding="utf-8",
            )
            match = BattleMatch(
                roster=[["p1_front", "p1_rear"], ["p2_foe"]],
                seed=77,
                extra_packs=[pack_path],
                initial_handoff=False,
            )

        # Advance until placement
        for _ in range(30):
            st = match.snapshot()
            if st["mode"] == "placement":
                break
            if st["mode"] == "handoff":
                match.act("ready", st["revision"])
            elif st["mode"] == "draw_select":
                prompt = st["draw_select"]
                discards = [c["action_key"] for c in prompt["candidates"][:prompt["discard_count"]]]
                match.act("draw_bottom", st["revision"], card_ids=discards)
            else:
                match.act("next", st["revision"])

        # Drive placement: when side 1 places `s_front`, `s_rear` unlocks `rear_targets` for Duel 1!
        saw_rear_unlocked = False
        placed_rear = False
        for _ in range(16):
            st = match.snapshot()
            if st["mode"] == "handoff":
                match.act("ready", st["revision"])
                continue
            if st["mode"] != "placement":
                break
            active = st["active_side"]
            hand = st["frame"]["players"][active - 1]["hand"]
            if active == 1:
                front_item = next((c for c in hand if c["id"].startswith("s_front_") and c["action_key"] in st["legal_cards"]), None)
                rear_item = next((c for c in hand if c["id"].startswith("s_rear_") and c["action_key"] in st["legal_rear_cards"]), None)
                if not saw_rear_unlocked and front_item:
                    self.assertEqual(st["legal_rear_cards"], [])
                    match.act("place", st["revision"], card_id=front_item["action_key"])
                elif not placed_rear and rear_item:
                    saw_rear_unlocked = True
                    self.assertEqual(st["rear_targets"][rear_item["action_key"]], [1])
                    match.act("place_rear", st["revision"], card_id=rear_item["action_key"], duel_number=1)
                    placed_rear = True
                elif st["can_pass"]:
                    match.act("pass", st["revision"])
                else:
                    match.act("end", st["revision"])
            else:
                foe_item = next((c for c in hand if c["id"].startswith("s_foe_") and c["action_key"] in st["legal_cards"]), None)
                if foe_item and (not st["frame"]["duels"] or not st["frame"]["duels"][0]["sides"][1]["cards"]):
                    match.act("place", st["revision"], card_id=foe_item["action_key"])
                elif st["can_pass"]:
                    match.act("pass", st["revision"])
                else:
                    match.act("end", st["revision"])

        self.assertTrue(saw_rear_unlocked)
        self.assertTrue(placed_rear)

        # Check rear card & owner projection on Duel 1
        snap_after = match.snapshot()
        duel_view = snap_after["frame"]["duels"][0]
        p1_duel_side = next(s for s in duel_view["sides"] if s["side"] == 1)
        self.assertEqual(len(p1_duel_side["rear_cards"]), 1)
        self.assertEqual([o["character_id"] for o in snap_after["card_owners"]["duels_rear"]["1:1"]], ["p1_rear"])

        # Step through combat and collect all emitted fx_events and live combat rear snapshots!
        fx_collected = list(snap_after.get("fx_events", []))
        saw_live_rear = False
        for _ in range(80):
            cur = match.snapshot()
            if cur["frame"]["combat"]:
                c_side1 = next(s for s in cur["frame"]["combat"]["sides"] if s["side"] == 1)
                if c_side1.get("rear") and str(c_side1["rear"].get("card_id", "")).startswith("s_rear_"):
                    saw_live_rear = True
            if cur["frame"]["turn"] > 1 or cur["mode"] in ("finished", "draw_select"):
                break
            if cur["mode"] == "handoff":
                res = match.act("ready", cur["revision"])
            elif cur["mode"] == "pre_attack":
                res = match.act("end_attacks", cur["revision"])
            else:
                res = match.act("next", cur["revision"])
            fx_collected.extend(res.get("fx_events", []))

        self.assertTrue(saw_live_rear)
        roll_lanes = {
            (sd.get("side"), sd.get("lane"))
            for e in fx_collected
            if e.get("kind") == "dice_roll"
            for sd in e.get("sides", [])
        }
        self.assertIn((1, "front"), roll_lanes)
        self.assertIn((1, "rear"), roll_lanes)
        self.assertIn((2, "front"), roll_lanes)
        clash_events = [e for e in fx_collected if e.get("kind") == "dice_clash"]
        self.assertTrue(any(
            any(sd.get("lane") == "rear" for sd in ev.get("sides", []))
            for ev in clash_events
        ))


if __name__ == "__main__":
    unittest.main()
