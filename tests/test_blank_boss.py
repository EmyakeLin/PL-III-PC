"""Printed 空白 rules through the damage, payment, reveal and dice pipelines."""
import io
import random
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from player.player import Player


class BlankBossTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = next(c for c in load_characters_from_packs() if c["id"] == "blank_boss")

    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(23))
        self.game.first_player = self.left
        self.actor = self.recruit(self.left, self.spec)
        dummy = dict(id="dummy", name="陪练", rank="NORMAL", max_hp=30, skills=[])
        self.enemy = self.recruit(self.right, dummy)
        self.game.start_turn()
        self.actor.hp = 10
        self.left.max_cost = self.right.max_cost = 10

    def recruit(self, player, spec):
        character = Character(spec, player)
        player.characters.append(character)
        character.init_cards()
        character.setup_deck()
        return character

    def place(self, name, index=0):
        card = next(card for card in self.actor.skills if card.name == name)
        self.assertTrue(self.game.place_in_duel(self.left.side, card, index))
        return card

    def counter(self, dice, index=0):
        card = Card(self.right, dict(id=f"fixture{index}", name="陪练技能", cost=0, dice=dice), self.enemy)
        self.enemy.skills.append(card)
        self.assertTrue(self.game.place_in_duel(self.right.side, card, index))
        return card

    @staticmethod
    def slash(base=0, damage=0):
        return dict(type="slash", level=1, base_value=base, entries=[f"{damage}物理"])

    def fight(self):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=lambda lo, hi: lo), patch("builtins.input", return_value=""):
            for _ in range(1300):
                self.game.next_step()
                if self.game.is_over or not self.game.pipeline.in_duel_phase:
                    return
        self.fail("常规交锋未结束")

    def test_qualification_high_water_mark_and_haste(self):
        self.assertEqual((self.actor.max_hp, self.actor.max_duels), (15, 3))
        self.assertEqual([c.cost for c in self.actor.skills], [1, 2, 3, 2, 2, 3, 4])
        self.actor.hp = 15
        self.actor.add_status("能源", 7)
        self.assertEqual((self.actor.statuses["能源"], self.actor.ability_effects["抽卡资格"]), (8, 2))
        self.actor.add_ability_effect("抽卡资格", -1)
        self.actor.add_status("能源", -1)
        self.actor.hp = 10
        self.actor.speed, self.right.speed = 5, 3
        cost = self.left.available_cost
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.actor.statuses["能源"], self.actor.ability_effects["抽卡资格"]), (8, 1))
        self.assertEqual((self.left.available_cost, self.actor.shield, self.actor.ability_effects["洞察"]), (cost + 1, 2, 1))
        self.actor.add_status("能源", 4)
        self.assertEqual(self.actor.ability_effects["抽卡资格"], 2)
        self.game.finish_turn()
        self.assertNotIn("抽卡资格", self.actor.ability_effects)
        self.game.start_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual(self.actor.ability_effects["抽卡资格"], 3)

    def test_low_hp_verdict_uses_own_hp(self):
        self.actor.hp = 6
        with patch.object(self.game.rng, "randint", return_value=5):
            self.assertEqual(self.game.context.deal_damage(self.actor, self.enemy, 2), 2)
        with patch.object(self.game.rng, "randint", return_value=6):
            self.assertEqual(self.game.context.deal_damage(self.actor, self.enemy, 2), 3)

    def test_blank_prevents_death_at_zero_and_cashes_energy_once(self):
        self.actor.add_status("能源", 5)
        self.actor.hp = 4
        self.counter([self.slash(damage=3), self.slash(damage=3), self.slash(damage=2)])
        self.fight()
        self.assertTrue(self.actor.is_alive)
        self.assertEqual((self.actor.hp, self.actor.statuses["空白已发动"]), (0, 1))
        self.game.context.dispatch_pipeline("before_turn_end")
        self.assertEqual(self.actor.hp, 6)  # 亡怒回复1，再将5能源转为5生命。
        self.assertNotIn("能源", self.actor.statuses)
        self.game.finish_turn()
        self.assertNotIn("本回合无法死亡", self.actor.statuses)
        self.game.context.deal_damage(self.enemy, self.actor, 6)
        self.assertFalse(self.actor.is_alive)

    def test_sequence_pays_then_hits_and_wins_defensive_die(self):
        self.actor.add_status("能源", 2)
        self.place("斩·突·闪")
        self.counter([self.slash(-3), self.slash(-3), self.slash(-3)])
        self.fight()
        self.assertEqual((self.actor.hp, self.enemy.hp), (11, 29))
        self.assertEqual(self.actor.statuses["能源"], 4)
        self.assertEqual(len(self.left.cardspace.hand.content), 1)

    def test_blank_counts_shielded_damage_per_duel(self):
        self.actor.shield = 12
        self.counter([self.slash(damage=3)], index=0)
        self.counter([self.slash(damage=3)], index=1)
        self.counter([self.slash(damage=6)], index=2)
        observed = []
        self.game.context.register_entries(self.actor, [{
            "trigger": "AFTER DAMAGE", "subject": "target",
            "operation": lambda ctx: observed.append((ctx.event["hp_lost"],
                                                       self.actor.statuses.get("空白已发动", 0))),
        }])
        self.fight()
        self.assertEqual(observed, [(0, 0), (0, 0), (0, 1)])
        self.assertEqual(self.actor.hp, 10)

    def test_direct_life_loss_during_immunity_and_expiry_at_zero(self):
        self.actor.hp = 1
        self.counter([self.slash(damage=6)])
        self.fight()
        self.assertTrue(self.actor.is_alive)
        self.actor.heal(2)
        self.actor.lose_hp(3)
        self.assertEqual((self.actor.hp, self.actor.is_alive), (0, True))
        self.game.context.register_entries(self.actor, [{"trigger": "BEFORE HEAL", "operation": "Cancel"}])
        self.game.context.dispatch_pipeline("before_turn_end")
        self.game.finish_turn()
        self.assertFalse(self.actor.is_alive)
        self.assertIs(self.game.winner, self.right)

    def test_offensive_snapshot_base_value_piercing_and_delayed_rewards(self):
        self.actor.add_status("能源", 6)
        self.enemy.shield = 5
        card = self.place("趁机攻势")
        self.counter([self.slash(-2), self.slash(-2)])
        self.fight()
        self.assertEqual([d.base_value for d in card.instantiated_dice], [2, 2, 2])
        self.assertEqual((self.enemy.hp, self.enemy.shield, self.actor.statuses["能源"]), (27, 2, 5))
        self.assertEqual((self.actor.next_turn_duels, self.left.next_turn_common_cost), (1, 1))
        self.game.finish_turn()
        self.game.start_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual(self.actor.shield, 1)

    def test_guard_repeats_on_a_win_and_stops_when_unopposed(self):
        card = self.place("全面防守")
        self.counter([self.slash(-2), self.slash(-2)])
        self.fight()
        self.assertEqual(len(card.instantiated_dice), 3)
        self.assertEqual(self.actor.statuses["能源"], 6)
        self.game.finish_turn()
        self.game.start_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual(self.actor.shield, 3)

    def test_guard_changes_at_five_without_discount(self):
        self.actor.add_status("能源", 5)
        self.place("全面防守")
        self.fight()
        self.assertEqual((self.actor.statuses["能源"], self.enemy.hp), (5, 26))
        self.assertEqual(self.actor.used_independent_cost + self.left.used_cost, 3)

    def test_guard_changes_form_and_pays_discount(self):
        self.actor.add_status("能源", 9)
        card = self.place("全面防守")
        self.fight()
        self.assertEqual(self.actor.statuses["能源"], 5)
        self.assertEqual(self.actor.used_independent_cost + self.left.used_cost, 1)
        self.assertEqual((len(card.instantiated_dice), card.instantiated_dice[0].base_value, self.enemy.hp), (1, 6, 26))

    def test_read_splits_high_pair_and_takes_remaining_die(self):
        card = self.place("看破")
        enemy_card = self.counter([self.slash(11, 1), self.slash(0, 3)])
        self.fight()
        self.assertIsNone(card.instantiated_dice[0].clash_result)
        self.assertTrue(enemy_card.destroyed)
        self.assertEqual((self.actor.hp, self.enemy.hp), (9, 27))

    def test_read_cannot_take_dice_if_its_hit_was_cancelled(self):
        self.game.context.register_entries(self.enemy, [{
            "trigger": "BEFORE RESOLVE_HIT", "subject": "target", "operation": "Cancel",
        }])
        self.place("看破")
        enemy_card = self.counter([self.slash(11, 1), self.slash(0, 3)])
        self.fight()
        self.assertFalse(enemy_card.destroyed)
        self.assertEqual((self.actor.hp, self.enemy.hp), (6, 30))

    def test_pin_removes_shields_destroys_card_and_checks_target_energy(self):
        self.actor.add_status("能源", 2)
        self.enemy.add_status("能源", 8)
        for kind in ("normal", "reinforced", "concept"):
            self.enemy.add_shield(kind, 4)
        self.place("牵制射击")
        foe = self.counter([self.slash(-5), self.slash(-5), self.slash(-5, 10)])
        self.fight()
        self.assertTrue(foe.destroyed)
        self.assertEqual((self.enemy.shield, self.enemy.reinforced_shield, self.enemy.concept_shield), (0, 0, 0))
        self.assertEqual((self.enemy.hp, self.enemy.statuses["虚弱"], self.enemy.statuses["能源"]), (30, 2, 10))

    def test_pin_destroys_both_dice_before_result(self):
        self.actor.add_status("能源", 2)
        card = self.place("牵制射击")
        foe = self.counter([self.slash(3, 5)])
        self.fight()
        for die in (card.instantiated_dice[0], foe.instantiated_dice[0]):
            self.assertTrue(die.destroyed)
            self.assertIsNone(die.clash_result)
        self.assertEqual(self.actor.hp, 10)

    def test_sight_dormant_when_evade_unopposed(self):
        self.actor.add_status("能源", 2)
        self.place("空白准镜")
        self.fight()
        self.assertEqual(self.enemy.hp, 27)

    def test_sight_extra_dice_only_after_evade_wins(self):
        self.actor.add_status("能源", 2)
        self.place("空白准镜")
        self.counter([self.slash(-4), self.slash(-4)])
        self.fight()
        self.assertEqual(self.enemy.hp, 25)

    def test_sight_needs_full_energy_payment(self):
        self.actor.add_status("能源", 1)
        self.place("空白准镜")
        self.fight()
        self.assertEqual(self.enemy.hp, 30)
        self.assertEqual(self.actor.statuses["能源"], 1)
        self.assertEqual(self.actor.used_independent_cost + self.left.used_cost, 0)

    def test_bloom_burns_opponents_energy_and_keeps_own(self):
        self.actor.add_status("能源", 8)
        self.enemy.add_status("能源", 5)
        card = self.place("能源绽放")
        self.counter([self.slash(-1), self.slash(-1)])
        self.fight()
        self.assertEqual((self.enemy.hp, self.actor.statuses["能源"]), (22, 10))
        self.assertNotIn("能源", self.enemy.statuses)
        self.assertEqual(card.instantiated_dice[1].final_score, 9)

    def test_lethal_energy_burst_clears_its_targets_energy(self):
        self.enemy.hp = 6
        self.enemy.add_status("能源", 5)
        self.place("能源绽放")
        self.fight()
        self.assertFalse(self.enemy.is_alive)
        self.assertNotIn("能源", self.enemy.statuses)
        self.assertNotIn("能源", self.actor.statuses)

    def test_bloom_lost_die_grants_four_plus_two_and_reduces_incoming_damage(self):
        self.actor.add_status("能源", 8)
        self.place("能源绽放")
        self.counter([self.slash(15, 3), self.slash(15, 3)])
        self.fight()
        self.assertEqual(self.actor.hp, 6)
        self.assertEqual(self.actor.statuses["能源"], 14)
