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


class WAACombatTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.data = {data["name"]: data for data in load_characters_from_packs()}
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(17))
        self.game.first_player = self.left
        dummy = dict(id="dummy", name="陪练", rank="NORMAL", max_hp=60, skills=[])
        self.enemy = self.character(dummy, self.right)

    def character(self, data, player):
        char = Character(data, player)
        player.characters.append(char)
        char.init_cards()
        char.setup_deck()
        return char

    def team(self, *names):
        actors = [self.character(self.data[name], self.left) for name in names]
        self.game.start_turn()
        return actors

    def use(self, actor, skill, opposing_dice=0, slot=0):
        card = next(card for card in actor.skills if card.name == skill)
        self.assertTrue(self.game.place_in_duel(actor.player.side, card, slot))
        if opposing_dice:
            dice = [dict(type="slash", level=1, base_value=-10) for _ in range(opposing_dice)]
            opponent = Card(self.right, dict(id="oppose", name="对练", cost=0, dice=dice), self.enemy)
            self.enemy.skills.append(opponent)
            self.assertTrue(self.game.place_in_duel(self.right.side, opponent, slot))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", return_value=1):
            for _ in range(600):
                self.game.next_step()
                if not self.game.pipeline.in_duel_phase:
                    break
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertIn(card, self.game.used_cards)
        return card

    def next_turn(self):
        self.game.finish_turn()
        self.game.context.dispatch_pipeline("on_turn_end")
        self.game.start_turn()

    def test_above_threshold_hand_only_grants_charge_on_crossing(self):
        actors = self.team("莱克", "格罗琳娜", "厄尔克斯")
        self.left.draw_card(4)
        self.assertEqual([a.statuses.get("充能") for a in actors], [1, 1, 1])
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual([a.statuses.get("充能") for a in actors], [1, 1, 1])
        self.left.draw_card(1)
        self.assertEqual([a.statuses.get("充能") for a in actors], [1, 1, 1])

    def test_assault_evade_full_health_and_strength(self):
        lake, = self.team("莱克")
        card = self.use(lake, "突击攻击", opposing_dice=2)
        self.assertEqual(card.final_bonus, 2)
        self.assertEqual(lake.statuses, {"充能": 2, "强壮": 2})
        self.assertEqual(len(self.left.cardspace.hand.content), 1)
        self.assertTrue(lake.won_clash_this_turn)
        self.next_turn()
        self.assertEqual(lake.max_duels, 2)
        self.assertNotIn("强壮", lake.statuses)

    def test_assault_evade_heals_injured_actor_instead(self):
        lake, = self.team("莱克")
        lake.hp -= 2
        self.use(lake, "突击攻击", opposing_dice=2)
        self.assertEqual(lake.hp, 5)
        self.assertEqual(lake.next_turn_duels, 0)
        self.assertFalse(self.left.cardspace.hand.content)

    def test_contract_uses_d10_and_spends_for_its_damageless_last_die(self):
        lake, = self.team("莱克")
        card = self.use(lake, "执行委托", opposing_dice=1)
        self.assertEqual(card.instantiated_dice[0].roll_max, 10)
        self.assertEqual((lake.statuses["充能"], self.enemy.hp), (1, 57))

    def test_finisher_caps_both_conversions_and_schedules_ally_charge(self):
        lake, ally = self.team("莱克", "格罗琳娜")
        lake.add_status("充能", 16)
        card = self.use(lake, "猛烈斩杀")
        self.assertEqual((card.final_bonus, card.level_bonus), (7, 2))
        self.assertEqual([die.roll_max for die in card.instantiated_dice], [16, 20])
        self.assertEqual((lake.statuses["充能"], self.enemy.hp), (1, 57))
        self.next_turn()
        self.assertEqual((lake.statuses["充能"], ally.statuses["充能"]), (3, 2))
        self.assertEqual(self.enemy.statuses["虚弱"], 1)
        self.assertEqual(lake.max_duels, 2)  # 单方面命中不能算应变所指的拼点胜利。

    def test_delay_rechecks_charge_after_winning_its_first_die(self):
        agent, = self.team("格罗琳娜")
        self.left.speed, self.right.speed = 3.5, 3
        agent.add_status("充能", 3)
        card = self.use(agent, "阻滞", opposing_dice=1)
        self.assertEqual(card.final_bonus, 1)
        self.assertEqual([die.final_bonus for die in card.instantiated_dice], [0, 1])
        self.assertEqual(card.instantiated_dice[0].roll_max, 12)
        self.assertEqual(agent.statuses["充能"], 6)
        self.next_turn()
        self.assertEqual(self.enemy.statuses, {"束缚": 1, "虚弱": 1})

    def test_quick_follow_through_and_next_turn_haste(self):
        agent, = self.team("格罗琳娜")
        card = self.use(agent, "快进", slot=1)
        self.assertEqual(card.level_bonus, 1)
        self.assertEqual(agent.statuses["充能"], 1)
        self.next_turn()
        self.assertEqual(agent.statuses["迅捷"], 1)
        self.game.record_clash_result(agent, "lose")  # 第一交锋己方输过一次。
        card = self.use(agent, "快进", slot=1)
        self.assertEqual(card.level_bonus, 0)
        self.assertEqual(agent.statuses["充能"], 1)

    def test_opportunity_extra_damage_draw_fee_and_group_distribution(self):
        agent, ally = self.team("格罗琳娜", "厄尔克斯")
        agent.add_status("充能", 16)
        card = self.use(agent, "借机")
        self.assertEqual([die.roll_max for die in card.instantiated_dice], [12, 20, 16])
        self.assertEqual(card.final_bonus, 3)
        self.assertEqual(self.enemy.hp, 56)
        self.assertEqual(len(self.left.cardspace.hand.content), 1)
        self.assertEqual((agent.statuses["充能"], ally.statuses["充能"]), (3, 3))
        self.next_turn()
        self.assertEqual(self.left.max_cost, 6)

    def test_opportunity_low_charge_gain_affects_that_skills_dice(self):
        agent, ally = self.team("格罗琳娜", "莱克")
        agent.add_status("充能", 4)
        card = self.use(agent, "借机")
        self.assertEqual(card.final_bonus, 0)
        self.assertEqual([die.roll_max for die in card.instantiated_dice], [12, 20, 16])
        self.assertEqual((agent.statuses["充能"], ally.statuses["充能"]), (2, 2))
        self.assertEqual(self.enemy.hp, 58)

    def test_opportunity_at_sixteen_charge_still_adds_damage_when_spending_is_sealed(self):
        agent, = self.team("格罗琳娜")
        agent.add_status("充能", 16)
        agent.add_status("能源封印", 1)
        card = self.use(agent, "借机")
        self.assertEqual(self.enemy.hp, 56)
        self.assertEqual(agent.statuses["充能"], 16)
        self.assertEqual(card.use_state.get("spent_statuses", {}), {})

    def test_pure_load_on_defensive_wins(self):
        tech, = self.team("厄尔克斯")
        self.use(tech, "纯能填装", opposing_dice=2)
        self.assertEqual(tech.statuses, {"充能": 3, "纯能": 2})

    def test_skipped_defensive_dice_only_grant_after_skill_pure(self):
        tech, = self.team("厄尔克斯")
        self.use(tech, "纯能填装")
        self.assertEqual(tech.statuses, {"纯能": 1})

    def test_dissipate_pays_surcharge_before_pure_falls_below_three(self):
        tech, ally = self.team("厄尔克斯", "莱克")
        tech.hp -= 1
        tech.add_status("充能", 8)
        tech.add_status("纯能", 3)
        card = self.use(tech, "能源逸散", opposing_dice=1)
        self.assertEqual(card.final_bonus, 2)
        self.assertEqual(card.use_state["spent_statuses"], {"充能": 5, "纯能": 2})
        self.assertEqual((tech.hp, self.enemy.hp, self.enemy.statuses["虚弱"]), (9, 57, 2))
        self.assertEqual(tech.statuses, {"充能": 8, "纯能": 1})
        self.assertEqual(ally.statuses["充能"], 2)

    def test_dissipate_spends_the_last_charge_without_granting_the_skill_bonus(self):
        tech, = self.team("厄尔克斯")
        tech.add_status("充能", 1)
        card = self.use(tech, "能源逸散")
        self.assertEqual(card.final_bonus, 0)
        self.assertEqual(card.use_state["spent_statuses"], {"充能": 1})
        self.assertNotIn("充能", tech.statuses)

    def test_dissipate_must_cover_the_surcharge_to_gain_the_skill_bonus(self):
        tech, = self.team("厄尔克斯")
        tech.add_status("充能", 4)
        tech.add_status("纯能", 3)
        card = self.use(tech, "能源逸散")
        self.assertEqual(card.final_bonus, 0)
        self.assertEqual(card.use_state["spent_statuses"], {"充能": 4, "纯能": 2})

    def test_burst_with_eight_charge_upgrades_pierce_and_keeps_charge_from_repeats(self):
        tech, ally = self.team("厄尔克斯", "格罗琳娜")
        tech.add_status("充能", 8)
        tech.add_status("纯能", 9)
        self.assertEqual(tech.statuses["纯能"], 5)
        card = self.use(tech, "武器增压迸发")
        self.assertEqual((card.cost, card.final_bonus), (5, 4))
        self.assertEqual(self.left.used_cost, 4)
        self.assertEqual([die.position for die in card.instantiated_dice], [1, 2, 3, 3, 3, 3])
        self.assertEqual(card.instantiated_dice[1].roll_max, 12)
        self.assertEqual(card.use_state["spent_statuses"], {"充能": 8, "纯能": 3})
        self.assertEqual((self.enemy.hp, ally.statuses["充能"]), (49, 3))
        self.assertEqual(tech.statuses, {"纯能": 2, "充能": 1})

    def test_burst_with_seven_charge_drains_and_seals_before_first_die(self):
        tech, = self.team("厄尔克斯")
        tech.add_status("充能", 7)
        tech.add_status("纯能", 2)
        first_die = []

        def observe(ctx):
            if ctx.event["die"].position == 1:
                skill = ctx.event["card"]
                spent = skill.use_state.get("spent_statuses", {})
                first_die.append((dict(tech.statuses), dict(spent), skill.final_bonus))

        self.game.context.register_entries(tech, [{"trigger": "before_dice_use", "operation": observe}])
        card = self.use(tech, "武器增压迸发")
        self.assertEqual(first_die, [({"纯能": 3, "能源封印": 1}, {"充能": 7}, 2)])
        self.assertEqual(card.instantiated_dice[1].roll_max, 12)
        self.assertEqual([die.position for die in card.instantiated_dice], [1, 2, 3])
        self.assertEqual(card.use_state["spent_statuses"], {"充能": 7})
        self.assertEqual(tech.statuses, {"纯能": 3, "能源封印": 1})
        self.assertEqual(self.enemy.hp, 54)
