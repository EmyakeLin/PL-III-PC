import io
import random
import unittest
from contextlib import redirect_stdout

from displayer import Displayer
from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.opcode import OpCode
from player.player import Player


class HeckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = next(c for c in load_characters_from_packs() if c["id"] == "plan_b_heck")

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(31))
        self.game.first_player = self.left
        self.heck = self.recruit(self.left, self.pack)
        self.target = self.dummy(self.right, "陪练")
        self.cards = {c.name: c for c in self.heck.skills}
        self.game.start_turn()
        self.left.max_cost = 10

    @staticmethod
    def recruit(p, data):
        actor = Character(data, p)
        p.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def dummy(self, p, name):
        return self.recruit(p, dict(id=name, name=name, max_hp=100, rank="NORMAL", skills=[]))

    def training_skill(self, actor, bases, **traits):
        return Card(actor.player, dict(id="test", name="陪练技能", cost=0, dice=[
            dict(type="pierce", level=1, base_value=base, entries=[]) for base in bases
        ], **traits), actor)

    def fight(self, name, opposing=()):
        card = self.cards[name] if isinstance(name, str) else name
        self.assertTrue(self.game.place_in_duel(1, card, 0))
        if opposing:
            self.assertTrue(self.game.place_in_duel(2, self.training_skill(self.target, opposing), 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1800):
            self.game.next_step()
            if self.game.is_over or not self.game.pipeline.in_duel_phase:
                return card
        self.fail(self.log.getvalue()[-2500:])

    def full_power(self, energy):
        self.heck.add_status("能源", energy)
        self.game.context.dispatch_pipeline("on_turn_start")

    def test_first_full_power_draws_both_specials_and_only_counts_the_five_regular_cards(self):
        self.assertEqual((len(self.heck.skills), len(self.left.cardspace.draw.content),
                          len(self.left.cardspace.out_of_combat.content)), (7, 5, 2))
        self.left.draw_card(4)
        self.heck.hp = 7
        cost = self.left.available_cost
        self.full_power(12)
        self.assertEqual((self.heck.hp, self.heck.max_duels, self.left.available_cost), (9, 5, cost + 3))
        self.assertEqual((len(self.left.cardspace.hand.content), self.heck.statuses["强壮"]), (7, 2))
        self.assertEqual(self.cards["装填"].name, "开火")
        self.game.context.eval_block([self.heck, "能源", 6, OpCode.SPEND_STATUS])
        self.assertEqual(self.cards["装填"].name, "开火")
        self.game.finish_turn()
        self.assertEqual(self.cards["装填"].name, "装填")
        self.assertNotIn("强壮", self.heck.statuses)
        # Putting a special back outside combat does not grant it on later full-power turns.
        retired = self.cards["枪刃迸射"]
        self.left.cardspace.hand.move_card_to(retired, self.left.cardspace.out_of_combat)
        self.game.start_turn()
        self.full_power(6)
        self.assertIn(retired, self.left.cardspace.out_of_combat.content)

    def test_crossing_twelve_midturn_loads_ammo_and_winning_blocks_without_switching_form(self):
        self.heck.add_status("能源", 11)
        card = self.fight("装填", [-50, -50])
        self.assertEqual((card.name, self.heck.statuses["能源"], self.heck.statuses["弹药"]), ("装填", 17, 2))
        self.assertNotIn("全开", self.heck.statuses)

    def test_forced_form_exposes_real_dice_and_cannot_refill_itself(self):
        card = self.cards["装填"]
        self.left.draw_card(5)
        self.full_power(12)
        view = Displayer(self.game, viewer_side=1)
        hand = view.snapshot()["players"][0]["hand"]
        fire = next(row for row in hand if row["id"] == card.id)
        self.assertEqual((fire["name"], fire["range_level"], fire["use_restricted"]), ("开火", 2, True))
        self.assertEqual([die["resource_cost"]["amount"] for die in fire["dice"]], [1, 1])
        self.assertNotIn(card, self.game.pre_reveal.playable_hand(self.left))
        self.assertIn(card, self.game.pre_reveal.playable_hand(self.left, for_use=False))
        self.assertFalse(self.game.place_in_duel(1, card, 0))
        self.heck.add_status("弹药", 2)
        self.fight(card)
        self.assertEqual((self.heck.statuses.get("弹药", 0), self.heck.statuses["能源"]), (0, 12))
        self.assertEqual(self.target.hp, 98)

    def test_skill_form_tracks_the_current_controller_of_a_borrowed_card(self):
        card = self.cards["装填"]
        self.full_power(12)
        card.set_controller(self.target)
        self.assertEqual((card.name, card.effective_range), ("装填", 0))
        self.target.add_status("全开", 1)
        self.assertEqual((card.name, card.effective_range), ("开火", 2))
        self.target.clear_status("全开")
        card.return_to_printed_owner()
        self.assertIs(card.character, self.heck)
        self.assertEqual((card.name, card.effective_range), ("开火", 2))

    def test_flame_lunge_pays_levels_builds_burn_and_adds_only_one_skill_ignition(self):
        self.heck.add_status("能源", 6)
        card = self.fight("烈焰刺挑", [-50] * 4)
        self.assertEqual([d.roll_max for d in card.instantiated_dice], [8, 8, 16, 16])
        self.assertEqual(self.heck.rule_state["剑刃近战命中"], 3)
        self.assertEqual(card.use_state["extra_ignite"], 1)
        self.assertTrue(card.instantiated_dice[-1].use_state["lunge_finish"])
        self.assertTrue(self.game.duelspace.space[0].get_content(2)[0].destroyed)

    def test_an_unopposed_lunge_lights_the_third_hit_without_counting_clash_wins(self):
        self.heck.add_status("能源", 6)
        burn_after_hit = []
        self.game.context.register_entries(self.heck, [{
            "trigger": "after_dice_hit", "subject": "source",
            "operation": lambda ctx: burn_after_hit.append(self.target.statuses.get("烧伤", 0)),
        }])
        card = self.fight("烈焰刺挑")
        self.assertEqual(burn_after_hit[:3], [3, 8, 10])
        self.assertFalse(card.use_state.get("wins"))
        self.assertTrue(card.use_state.get("extra_ignite"))
        self.assertFalse(card.instantiated_dice[-1].use_state.get("lunge_finish"))
        self.assertEqual(self.heck.rule_state["剑刃近战命中"], 3)

    def test_ranged_ally_spends_hecks_energy_six_times_and_only_adds_to_clash_scores(self):
        ally = self.dummy(self.left, "队友")
        self.heck.add_status("能源", 15)
        self.game.context.eval_block([self.heck, "能源", 7, OpCode.SPEND_STATUS])
        self.target.add_status("烧伤", 16)
        shot = self.fight(self.training_skill(ally, [0] * 8, range_level=1), [-50] * 8)
        self.assertEqual([d.clash_score - d.final_score for d in shot.instantiated_dice], [4] * 8)
        self.assertEqual((self.heck.statuses["能源"], self.heck.statuses["凝聚"]), (2, 1))
        self.assertNotIn("能源", ally.statuses)

    def test_burning_slash_contests_two_excess_dice_with_its_real_hit_entries(self):
        self.heck.add_status("能源", 5)
        self.heck.add_status("凝聚", 2)
        card = self.fight("灼燃斩", [-50] * 4)
        enemy_card = self.game.duelspace.space[0].get_content(2)[0]
        self.assertEqual([die.clash_result for die in enemy_card.instantiated_dice],
                         ["lose", "lose", "lose", None])
        self.assertEqual((self.target.hp, self.target.statuses["烧伤"]), (97, 6))
        self.assertEqual(self.heck.rule_state["剑刃近战命中"], 3)
        self.assertEqual(self.game.used_cards.count(card), 1)
        self.assertFalse(self.heck.reserved_dice)

    def test_energy_analysis_levels_spends_and_doubles_the_rounded_bonus_in_full_power(self):
        self.full_power(12)
        self.heck.add_status("凝聚", 3)
        card = self.fight("能源反解析")
        finisher = card.instantiated_dice[1]
        self.assertEqual((finisher.roll_max, finisher.effective_ignore_range), (16, 3))
        self.assertEqual((self.target.hp, self.target.statuses["烧伤"]), (98, 4))
        self.assertEqual(self.heck.statuses["能源"], 18)

    def test_excess_energy_and_evade_modify_later_base_values(self):
        self.heck.add_status("能源", 20)
        card = self.fight("赤炎剑", [-50] * 3)
        self.assertEqual([d.base_value for d in card.instantiated_dice], [2, 4, 8])
        self.assertEqual(self.heck.statuses["能源"], 14)
        last = card.instantiated_dice[-1]
        self.assertEqual(self.target.statuses["烧伤"], 2 + last.final_score // 4)

    def test_decisive_thrust_pays_for_its_doubled_ignition_and_snapshots_repeat_limit(self):
        self.full_power(12)
        self.heck.add_status("凝聚", 1)
        self.target.add_status("烧伤", 12)
        card = self.fight("贯彻之刺")
        self.assertEqual(len(card.instantiated_dice), 2)
        self.assertEqual(card.use_state["spent_statuses"]["能源"], 12)
        self.assertEqual(self.target.hp, 88)
        self.assertEqual(self.target.statuses["烧伤"], 5)

    def test_unfunded_analysis_keeps_its_energy_and_skips_its_bonus(self):
        self.heck.add_status("凝聚", 4)
        # Leave two energy between its first hit and its second die.
        self.game.context.register_entries(self.heck, [{
            "trigger": "after_dice_hit",
            "operation": {"op": "program", "code": [
                "$self", "能源", "$self", "能源", "STATUS_COUNT", 2, "SUB", "SPEND_STATUS", "POP",
            ]},
            "turn_limit": {"key": "陪练抽空能源", "count": 1},
        }])
        self.fight("能源反解析")
        self.assertEqual(self.target.hp, 100)
        self.assertEqual(self.target.statuses["烧伤"], 2)
        self.assertEqual(self.heck.statuses["能源"], 2)

    def test_one_round_of_ammo_jumps_from_first_shot_to_printed_finisher(self):
        self.full_power(12)
        self.heck.add_status("凝聚", 3)
        self.heck.add_status("弹药", 1)
        self.target.add_status("烧伤", 12)
        card = self.fight("枪刃迸射")
        dice = [d for d in card.instantiated_dice if d is not None]
        self.assertEqual([d.position for d in dice], [1, 4])
        self.assertEqual(dice[-1].get_value(), 2 * dice[-1].value + 5)
        self.assertEqual((self.target.hp, self.target.statuses["烧伤"]), (92, 7))
        self.assertEqual(self.heck.statuses.get("弹药", 0), 0)
        self.assertEqual(self.heck.statuses["能源"], 1)
