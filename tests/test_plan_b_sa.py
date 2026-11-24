"""Execution-path and boundary regression tests for the modernized PlanB Sa pack."""

import io
import random
import unittest
from contextlib import redirect_stdout

from entry.compiler import compile_program
from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.dice import Dice
from models.opcode import OpCode
from player.player import Player


class PlanBSaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = next(spec for spec in load_characters_from_packs() if spec["id"] == "plan_b_sa")

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "萨方"), Player(2, "陪练方")
        self.game = Game([self.left, self.right], rng=random.Random(31))
        self.game.first_player = self.left
        self.sa = self.recruit(self.left, self.pack)
        self.target = self.dummy("前锋", max_hp=30)
        self.cards = {card.name: card for card in self.sa.skills}
        self.game.start_turn()

    @staticmethod
    def recruit(player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def dummy(self, name, *, max_hp=30):
        return self.recruit(self.right, dict(id=name, name=name, max_hp=max_hp, rank="NORMAL", skills=[]))

    def oppose(self, bases, *, slot=0, actor=None, die_type="slash", range_level=0):
        actor = actor or self.target
        spec = dict(
            id=f"opp_{slot}_{len(actor.skills)}",
            name="陪练牌",
            cost=0,
            range_level=range_level,
            dice=[dict(type=die_type, level=1, base_value=base, entries=[]) for base in bases],
        )
        card = Card(self.right, spec, actor)
        actor.skills.append(card)
        self.assertTrue(self.game.place_in_duel(2, card, slot))
        return card

    def fight_card(self, card, *, slot=0):
        self.assertTrue(self.game.place_in_duel(1, card, slot))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1200):
            if self.game.is_over or not self.game.pipeline.in_duel_phase:
                return card
            self.game.next_step()
        self.fail("交锋未在预期步数内完成")

    def advance_to_next_turn_prepared(self):
        self.game.finish_turn()
        self.game.context.dispatch_pipeline("on_turn_end")
        self.game.start_turn()

    def activate_collapse(self, target):
        return self.game.context.eval_block([target, "崩析", OpCode.ACTIVATE_STATUS])

    def test_pack_loads_and_compiles_all_programs_without_legacy_syntax(self):
        self.assertEqual(self.pack["faction"], "PlanB")
        self.assertEqual(self.pack["rank"], "BOSS")
        self.assertEqual(len(self.pack["skills"]), 7)
        for status_name in ("崩析", "崩裂", "弥合", "崩离"):
            self.assertIn(status_name, self.pack["status_rules"])
            self.assertIn("polarity", self.pack["status_rules"][status_name])
        activation_code = self.pack["status_rules"]["崩析"]["activation"]["operation"]["code"]
        compile_program(activation_code)
        for entries in self.pack["status_entries"].values():
            for entry in entries:
                op = entry.get("operation")
                if isinstance(op, dict) and op.get("op") == "program":
                    compile_program(op["code"])

    def test_collapse_burst_uses_original_max_hp_and_schedules_weakness(self):
        self.target.max_hp = self.target.original_max_hp = self.target.hp = 16
        self.assertFalse(self.activate_collapse(self.target))
        self.target.add_status("崩离", 4)
        self.target.add_status("崩析", 1)
        self.sa.hp = 8
        self.assertTrue(self.activate_collapse(self.target))
        # ceil(16 / 3) = 6; max_hp=12 -> hp=6; Sa heals floor(6 / 2) = 3 -> 11.
        self.assertEqual((self.target.hp, self.target.max_hp, self.sa.hp), (6, 12, 11))
        self.assertNotIn("崩析", self.target.statuses)
        self.advance_to_next_turn_prepared()
        self.assertEqual(self.target.statuses.get("虚弱"), 1)

    def test_collapse_at_eight_bursts_immediately_for_others_but_waits_for_turn_end_on_sa(self):
        self.target.max_hp = self.target.original_max_hp = self.target.hp = 16
        self.target.add_status("崩析", 7)
        self.target.add_status("崩析", 1)
        self.assertEqual(self.target.hp, 10)
        self.assertNotIn("崩析", self.target.statuses)

        self.sa.add_status("崩析", 9)
        self.assertFalse(self.activate_collapse(self.sa))
        self.assertEqual(self.sa.statuses["崩析"], 9)
        self.game.context.dispatch_pipeline("before_turn_end")
        self.assertNotIn("崩析", self.sa.statuses)
        # ceil(15 / 3) = 5 damage, Sa heals floor(5 / 2) = 2 -> 15 - 5 + 2 = 12.
        self.assertEqual(self.sa.hp, 12)

    def test_fissure_and_mending_threshold_pair_and_turn_end_settlement(self):
        # Threshold pair: 1 stack does not modify incoming collapse; 2 stacks does.
        self.target.add_status("崩裂", 1)
        self.target.add_status("崩析", 1)
        self.assertEqual(self.target.statuses["崩析"], 1)
        self.target.add_status("崩裂", 1)
        self.target.add_status("崩析", 1)
        self.assertEqual(self.target.statuses["崩析"], 3)

        self.target.add_status("弥合", 3)
        self.target.add_status("崩析", 1)
        # +1 from 崩裂(>=2), -1 from 弥合(>=2) => net +1 -> 4.
        self.assertEqual(self.target.statuses["崩析"], 4)

        # High mending can zero burst without scheduling weakness.
        self.target.max_hp = self.target.original_max_hp = self.target.hp = 16
        self.target.add_status("弥合", 10)
        self.assertTrue(self.activate_collapse(self.target))
        self.assertEqual(self.target.hp, 16)
        self.assertNotIn("崩析", self.target.statuses)

        # Turn end settles remaining 崩裂/弥合 into 崩析 and clears them.
        self.sa.add_status("崩析", 5)
        self.sa.add_status("弥合", 2)
        self.target.clear_status("弥合")
        self.target.clear_status("崩裂")
        self.target.add_status("崩裂", 1)
        self.game.context.dispatch_pipeline("before_turn_end")
        self.assertEqual(self.sa.statuses.get("崩析"), 3)
        self.assertNotIn("弥合", self.sa.statuses)
        self.assertEqual(self.target.statuses.get("崩析"), 1)
        self.assertNotIn("崩裂", self.target.statuses)

    def test_separation_is_permanent_and_does_not_reduce_lightcore_max(self):
        self.target.max_hp = self.target.original_max_hp = self.target.hp = 16
        self.target.add_status("崩离", 4)
        self.target.add_status("崩离", -2)
        self.target.clear_status("崩离")
        self.assertEqual(self.game.context.eval_block([self.target, "崩离", "all", OpCode.SPEND_STATUS]), 0)
        self.assertEqual((self.target.statuses.get("崩离"), self.target.max_hp, self.target.hp), (4, 12, 12))
        self.target.add_status("崩离", 12)
        self.assertEqual((self.target.max_hp, self.target.hp, self.target.is_alive), (0, 0, False))

    def test_collapse_damage_penalty_and_once_per_die_spread(self):
        self.sa.add_status("崩析", 6)
        card = Card(self.sa.player, dict(id="probe", name="测试", cost=0, dice=[]), self.sa)
        die = Dice(dict(type="slash", level=2, entries=[]), self.game)
        die.card = card
        with self.game.context.binding(die=die, card=card):
            # 6 collapse => -2 on attack damage_part.
            self.assertEqual(self.game.context.deal_damage(self.sa, self.target, 2, damage_part=True, damage_die=die), 0)
            self.assertEqual(self.target.statuses.get("崩析", 0), 0)
            # Dealing >=1 twice on the same die spreads collapse only once (scheduled because target has 0).
            self.target.shield = 2
            self.assertEqual(self.game.context.deal_damage(self.sa, self.target, 3, damage_part=True, damage_die=die), 1)
            self.assertEqual(self.game.context.deal_damage(self.sa, self.target, 3, damage_part=True, damage_die=die), 1)
            self.assertEqual(self.target.statuses.get("崩析", 0), 0)

            # Once target already has collapse, a new die spreads immediately.
            self.target.add_status("崩析", 1)
            next_die = Dice(dict(type="slash", level=2, entries=[]), self.game)
            next_die.card = card
            self.assertEqual(self.game.context.deal_damage(self.sa, self.target, 2, damage_die=next_die), 2)
            self.assertEqual(self.target.statuses.get("崩析"), 2)

        self.advance_to_next_turn_prepared()
        # Only 1 scheduled collapse from the first die (plus existing 2 => 3), plus 1 weakness from taking damage.
        self.assertEqual(self.target.statuses.get("崩析"), 3)
        self.assertEqual(self.target.statuses.get("虚弱"), 1)

    def test_s_entry_plan_b_and_mending_fissure_threshold_pairs(self):
        # Pair A: 3 cards in hand + 1 drawn = 4 (<5) => Plan B does not trigger; 3 collapse (<4) => 弥合裂隙 does not trigger.
        self.left.draw_card(3)
        self.sa.hp = 8
        self.sa.add_status("崩析", 3)
        self.sa.add_status("虚弱", 3)
        cost_before, duels_before = self.left.available_cost, self.sa.max_duels
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual(len(self.left.cardspace.hand.content), 4)
        self.assertEqual((self.sa.hp, self.sa.max_duels, self.left.available_cost),
                         (10, duels_before, cost_before + 2))
        self.assertEqual((self.sa.statuses.get("虚弱"), self.sa.statuses.get("弥合", 0)), (3, 0))

        # Pair B: now 4 cards in hand + 1 drawn = 5 (>=5) => Plan B triggers; 4 collapse (>=4) => 弥合裂隙 triggers.
        self.sa.add_status("崩析", 1)
        cost_before, duels_before = self.left.available_cost, self.sa.max_duels
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual(len(self.left.cardspace.hand.content), 5)
        self.assertEqual((self.sa.hp, self.sa.max_duels, self.left.available_cost),
                         (12, duels_before + 1, cost_before + 3))
        self.assertEqual((self.sa.statuses.get("虚弱"), self.sa.statuses.get("弥合")), (1, 1))

    def test_shatter_body_lock_will_trace_rift_and_crush_mind(self):
        # 崩毁肉体
        self.sa.add_status("崩析", 1)
        self.oppose([50, -50, -50])
        card = self.fight_card(self.cards["崩毁肉体"])
        self.assertEqual([d.clash_result for d in card.instantiated_dice], ["lose", "win", "win"])
        self.assertEqual((self.sa.statuses.get("崩析"), len(self.left.cardspace.hand.content)), (1, 1))
        self.assertEqual(self.target.hp, 26)

        # 意志锁死: 5 collapse snapshots +1 level BEFORE gaining the 6th stack.
        self.setUp()
        self.sa.add_status("崩析", 5)
        self.sa.hp = 9
        self.oppose([-50, -50])
        card = self.fight_card(self.cards["意志锁死"])
        self.assertEqual((self.sa.statuses.get("崩析"), card.level_bonus, self.sa.hp), (6, 1, 10))
        self.assertEqual(self.target.hp, 30)
        self.assertEqual(self.target.statuses.get("崩析"), 2)
        self.advance_to_next_turn_prepared()
        self.assertEqual(self.target.statuses.get("骰子等级降低"), 1)

        # 彻灭心神: 4 collapse grants 1 骰子等级降低, die 2 clash lose schedules 2 强壮, die 3 deals 2 pierce.
        self.setUp()
        self.sa.add_status("崩析", 4)
        self.oppose([-50, 50, -50])
        card = self.fight_card(self.cards["彻灭心神"])
        self.assertEqual(self.sa.statuses.get("骰子等级降低"), 1)
        self.assertTrue(card.instantiated_dice[-1].did_deal_damage)
        self.assertEqual(self.target.hp, 27)
        self.advance_to_next_turn_prepared()
        self.assertEqual(self.target.statuses.get("强壮"), 2)

    def test_flash_rift_redirects_last_die_or_pursues_current_opponent(self):
        # Case A: Next duel has a target -> damage and scheduled 崩裂 go to next_target.
        next_target = self.dummy("后卫", max_hp=30)
        self.oppose([-50, -50, -50], slot=0)
        self.oppose([], actor=next_target, slot=1)
        card = self.fight_card(self.cards["闪进解离"])
        self.assertEqual(card.instantiated_dice[-1].clash_result, "win")
        self.assertEqual((self.target.hp, next_target.hp), (29, 29))
        self.advance_to_next_turn_prepared()
        self.assertEqual((self.target.statuses.get("崩裂", 0), next_target.statuses.get("崩裂")), (0, 1))

        # Case B: No next duel target -> 狂暴毁灭 pursues current opponent with 1 pierce, no 崩裂.
        self.setUp()
        segments = []
        self.game.context.register_entries(self.sa, [dict(
            trigger="AFTER DAMAGE", subject="source",
            operation=lambda ctx: segments.append(
                (ctx.event["damage_die"], ctx.event["target"], ctx.event["damage_amount"], ctx.event["penetration"])
            ),
        )])
        self.oppose([-50, -50, -50], slot=0)
        card = self.fight_card(self.cards["闪进解离"])
        last = card.instantiated_dice[-1]
        self.assertEqual([s[1:] for s in segments if s[0] is last], [(self.target, 1, "pierce")])
        self.advance_to_next_turn_prepared()
        self.assertEqual(self.target.statuses.get("崩裂", 0), 0)

    def test_disintegrate_finisher_priority_and_range_suppression(self):
        finisher = next(c["dice"][-1] for c in self.pack["skills"] if c["id"] == "sa_disintegrate")

        def run_finisher(sa_stacks, target_stacks, *, cancel_damage_part=False, range_level=0):
            self.setUp()
            self.target.max_hp = self.target.original_max_hp = self.target.hp = 15
            self.sa.hp = 8
            if sa_stacks:
                self.sa.add_status("崩析", sa_stacks)
            if target_stacks:
                self.target.add_status("崩析", target_stacks)
            damage = []
            self.game.context.register_entries(self.target, [dict(
                trigger="AFTER DAMAGE", subject="target",
                operation=lambda ctx: damage.append((ctx.event["damage_cause"], ctx.event["damage_amount"])),
            )])
            if cancel_damage_part:
                self.game.context.register_entries(self.target, [dict(
                    trigger="BEFORE DAMAGE",
                    when=[{"left": "$event.damage_part", "op": "eq", "right": True}],
                    operation={"op": "cancel"},
                )])
            probe = Card(self.left, dict(id="probe_finisher", name="末骰测试", cost=0, dice=[finisher]), self.sa)
            self.sa.skills.append(probe)
            self.oppose([-50], die_type="block", range_level=range_level)
            self.fight_card(probe)
            return damage

        # 1. Target has 1 collapse, zero damage_part -> forces burst before passive, schedules 崩离.
        damage = run_finisher(6, 1)
        self.assertEqual(damage, [("崩析爆发", 5), (None, 0)])
        self.assertNotIn("崩析", self.target.statuses)
        self.assertEqual(self.sa.hp, 10)
        self.advance_to_next_turn_prepared()
        self.assertEqual((self.target.statuses.get("虚弱"), self.target.statuses.get("崩离")), (1, 1))

        # 2. Target has 0 collapse -> cannot force burst, falls back to 焦黄风暴 applying 1 collapse.
        damage = run_finisher(6, 0)
        self.assertEqual(damage, [(None, 0)])
        self.assertEqual(self.target.statuses.get("崩析"), 1)
        self.advance_to_next_turn_prepared()
        self.assertEqual(self.target.statuses.get("崩离", 0), 0)

        # 3. Printed damage cancelled -> after_dice_use finisher forces burst before 狂暴毁灭 chase.
        damage = run_finisher(0, 1, cancel_damage_part=True)
        self.assertEqual(damage, [("崩析爆发", 5)])

        # 4. Range suppressed -> neither forces burst nor chases.
        damage = run_finisher(6, 1, range_level=1)
        self.assertEqual(damage, [])
        self.assertEqual(self.target.statuses.get("崩析"), 1)

    def test_yellow_wind_branches_and_disintegrate_combo_recovery(self):
        def run_wind(stacks):
            self.setUp()
            self.left.max_cost = 30
            self.left.cost = 30
            self.target.hp = self.target.max_hp = self.target.original_max_hp = 100
            self.sa.add_status("崩析", stacks)
            levels = []
            self.game.context.register_entries(self.sa, [dict(
                trigger="AFTER RESOLVE_DIE_LEVEL", subject="source",
                operation=lambda ctx: levels.append((ctx.event["die"].position, ctx.event["result"])),
            )])
            self.oppose([-30, -30, -30, -30, -30])
            wind = self.cards["黄风漫天"]
            self.fight_card(wind)
            self.assertEqual(self.left.cardspace.out_of_combat.content, [wind])
            return levels

        # High collapse (>=6): -2 level, locks collapse, repeats printed-level-4 final die twice.
        self.assertEqual(run_wind(6), [(1, 2), (2, 1), (3, 4), (3, 4), (3, 4)])
        self.assertEqual(self.sa.statuses.get("崩析"), 6)

        # Low collapse (<=5): loses 4 collapse, +2 level, locks final die at 4 without repeats.
        self.assertEqual(run_wind(5), [(1, 6), (2, 5), (3, 4)])
        self.assertEqual(self.sa.statuses.get("崩析"), 1)

        # High wind destroys next-duel enemy skills (not slot 2) and doubles target 崩离 on each final-die hit.
        self.setUp()
        self.left.max_cost = 30
        self.left.cost = 30
        self.target.hp = self.target.max_hp = self.target.original_max_hp = 100
        ally_enemy = self.dummy("后排", max_hp=30)
        self.sa.add_status("崩析", 6)
        self.target.add_status("崩离", 1)
        self.oppose([-30, -30, -30, -30, -30], slot=0)
        next_card = self.oppose([], actor=ally_enemy, slot=1)
        later_card = self.oppose([], actor=ally_enemy, slot=2)
        self.fight_card(self.cards["黄风漫天"])
        self.assertTrue(next_card.destroyed)
        self.assertFalse(later_card.destroyed)
        self.assertEqual(ally_enemy.statuses.get("崩析"), 2)
        # 1 -> 2 -> 4 -> 8 across 3 hits of the repeated final die.
        self.assertEqual(self.target.statuses.get("崩离"), 8)

        # Combo recovery: 黄风漫天 + 分崩离析 + 闪进解离 recovers 黄风漫天 to draw bottom.
        self.setUp()
        self.left.max_cost = 30
        self.left.cost = 30
        wind = self.cards["黄风漫天"]
        for slot, card in enumerate((wind, self.cards["分崩离析"], self.cards["闪进解离"])):
            self.assertTrue(self.game.place_in_duel(1, card, slot))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1200):
            if not self.game.pipeline.in_duel_phase:
                break
            self.game.next_step()
        zones = self.left.cardspace
        self.assertEqual(zones.out_of_combat.content, [wind])
        self.game.finish_turn()
        self.game.context.dispatch_pipeline("on_turn_end")
        self.assertFalse(zones.out_of_combat.content)
        self.assertIs(zones.draw.content[-1], wind)
        self.assertEqual(zones.draw.content.count(wind), 1)

        # Negative pair: using 分崩离析 without 闪进解离 does NOT recover 黄风漫天.
        self.setUp()
        self.left.max_cost = 30
        self.left.cost = 30
        wind = self.cards["黄风漫天"]
        for slot, card in enumerate((wind, self.cards["分崩离析"])):
            self.assertTrue(self.game.place_in_duel(1, card, slot))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1200):
            if not self.game.pipeline.in_duel_phase:
                break
            self.game.next_step()
        self.game.finish_turn()
        self.game.context.dispatch_pipeline("on_turn_end")
        self.assertEqual(self.left.cardspace.out_of_combat.content, [wind])

    def test_disintegrate_use_branches(self):
        # Branch 1 (<=4): gains 2 崩析.
        self.sa.add_status("崩析", 4)
        self.left.max_cost = 10
        self.left.cost = 10
        self.oppose([-50, -50, -50, -50])
        self.fight_card(self.cards["分崩离析"])
        self.assertEqual(self.sa.statuses.get("崩析"), 6)

        # Branch 2 (5..6): no gain/loss, no extra 崩裂 from on_skill_use.
        self.setUp()
        self.sa.add_status("崩析", 5)
        self.left.max_cost = 10
        self.left.cost = 10
        self.oppose([-50, -50, -50, -50])
        self.fight_card(self.cards["分崩离析"])
        self.assertEqual(self.sa.statuses.get("崩析"), 5)

        # Branch 3 (>=7): loses 2 崩析 and schedules 1 崩裂 on target (plus 1 from die 2 hit = 2 total).
        self.setUp()
        self.sa.add_status("崩析", 7)
        self.left.max_cost = 10
        self.left.cost = 10
        self.oppose([-50, -50, -50, -50])
        self.fight_card(self.cards["分崩离析"])
        self.assertEqual(self.sa.statuses.get("崩析"), 5)
        self.advance_to_next_turn_prepared()
        self.assertEqual(self.target.statuses.get("崩裂"), 2)


if __name__ == "__main__":
    unittest.main()
