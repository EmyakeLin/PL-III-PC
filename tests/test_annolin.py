"""Exercise the printed PlanB card pack through the normal duel pipeline."""
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


class AnnolinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = {char["name"]: char for char in load_characters_from_packs()}

    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(27))
        self.game.first_player = self.left
        self.actor = self.recruit(self.left, self.pool["安诺琳"])
        self.enemy = self.dummy(self.right, "主目标")
        self.game.start_turn()

    def recruit(self, player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def dummy(self, player, name):
        return self.recruit(player, dict(id=name, name=name, rank="NORMAL", max_hp=30, skills=[]))

    def place(self, character, skill, slot=0):
        card = next(card for card in character.skills if card.name == skill)
        self.assertTrue(self.game.place_in_duel(character.player.side, card, slot))
        return card

    def place_fixture(self, character, dice, slot=0):
        name = f"陪练{len(character.skills)}"
        card = Card(character.player, dict(id=name, name=name, cost=0, dice=dice), character)
        character.skills.append(card)
        return self.place(character, name, slot)

    def battle(self):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", return_value=1), patch("builtins.input", return_value=""):
            for _ in range(1000):
                self.game.next_step()
                if not self.game.pipeline.in_duel_phase:
                    return
        self.fail("交锋未能结束")

    def new_turn(self):
        self.game.finish_turn()
        self.game.context.dispatch_pipeline("on_turn_end")
        self.game.start_turn()

    def test_extra_draw_collects_fifth_personal_card_before_plan_b_checks(self):
        self.assertEqual(self.actor.max_duels, 3)
        self.assertEqual([card.cost for card in self.actor.skills], [1, 2, 2, 3, 5])
        ally = self.recruit(self.left, self.pool["莱克"])
        zones = self.left.cardspace
        for card in self.actor.skills[:3] + ally.skills[:1]:
            zones.draw.move_card_to(card, zones.hand)
        self.actor.hp = 4
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual(len(zones.hand.content), 5)
        self.assertNotIn(self.actor.skills[-1], zones.hand.content)
        self.assertEqual((self.actor.max_duels, self.left.available_cost), (3, 5))
        self.assertEqual((self.actor.hp, self.actor.statuses["涡流"]), (6, 4))
        self.new_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertIn(self.actor.skills[-1], zones.hand.content)
        self.assertEqual((self.actor.max_duels, self.left.available_cost, self.actor.hp), (4, 6, 8))
        self.assertEqual((self.actor.statuses["涡流"], self.actor.statuses["骰子等级降低"]), (2, 1))

    def test_one_vortex_is_spent_and_schedules_lower_level_on_any_holder(self):
        self.enemy.add_status("涡流", 1)
        self.new_turn()
        self.assertNotIn("涡流", self.enemy.statuses)
        self.assertEqual(self.enemy.statuses["骰子等级降低"], 1)
        self.new_turn()
        self.assertNotIn("骰子等级降低", self.enemy.statuses)

    def test_vortex_floor_changes_only_clash_and_only_annolin_ignores_level(self):
        self.actor.add_status("涡流", 14)
        self.enemy.add_status("涡流", 5)
        for character in (self.actor, self.enemy):
            character.add_status("骰子等级降低", 1)
        die = dict(type="slash", level=3)
        mine = self.place_fixture(self.actor, [die])
        theirs = self.place_fixture(self.enemy, [die])
        self.battle()
        left, right = mine.instantiated_dice[0], theirs.instantiated_dice[0]
        self.assertEqual((left.roll_max, left.final_score, left.clash_score), (8, 1, 10))
        self.assertEqual((right.roll_max, right.final_score, right.clash_score), (6, 1, 5))

    def test_failed_and_tied_evades_share_two_reactions_per_turn(self):
        dice = [dict(type=kind, level=2) for kind in ("slash", "evade", "evade", "evade")]
        opposing = [dict(type="slash", level=1, base_value=base) for base in (0, 0, 10, 10)]
        self.actor.hp = 3
        mine = self.place_fixture(self.actor, dice)
        theirs = self.place_fixture(self.enemy, opposing)
        self.battle()
        self.assertEqual((self.actor.hp, self.actor.statuses["涡流"]), (5, 2))
        self.new_turn()
        self.place(self.actor, mine.name)
        self.place(self.enemy, theirs.name)
        self.battle()
        self.assertEqual((self.actor.hp, self.actor.statuses["涡流"]), (7, 2))

    def test_skipped_evades_share_the_limit_with_ties_and_losses(self):
        reactions = []
        self.game.context.register_entries(self.actor, [{
            "trigger": "AFTER STATUS", "when": {"status": "涡流"},
            "operation": lambda ctx: reactions.append(ctx.event["die"].clash_result),
        }])
        self.actor.hp = 3
        evades = self.place_fixture(self.actor, [dict(type="evade", level=2)] * 3)
        self.place_fixture(self.enemy, [dict(type="block", level=2), dict(type="slash", level=2),
                                       dict(type="slash", level=2, base_value=10)])
        self.battle()
        self.assertEqual([die.clash_result for die in evades.instantiated_dice], ["skip", "draw", "lose"])
        self.assertEqual(reactions, ["skip", "draw"])
        self.assertEqual((self.actor.hp, self.actor.statuses["涡流"]), (5, 2))
        self.new_turn()
        self.place(self.actor, evades.name)
        self.battle()
        self.assertEqual(reactions, ["skip", "draw", "skip", "skip"])
        self.assertEqual((self.actor.hp, self.actor.statuses["涡流"]), (7, 2))

    def test_drifting_sword_hits_next_slot_then_returns_same_card_to_hand(self):
        next_foe = self.dummy(self.right, "下一交锋")
        mine = self.place(self.actor, "漂泊剑法")
        self.place_fixture(self.enemy, [dict(type="slash", level=1, base_value=-5)] * 4)
        self.place_fixture(next_foe, [dict(type="block", level=1)], slot=1)
        self.battle()
        self.assertEqual((self.enemy.hp, next_foe.hp), (29, 29))
        self.assertEqual(next_foe.statuses["骰子等级降低"], 1)
        self.assertNotIn("骰子等级降低", self.enemy.statuses)
        self.assertEqual(self.left.cardspace.hand.content.count(mine), 1)
        self.new_turn()
        self.assertIn(mine, self.left.cardspace.hand.content)
        self.assertNotIn(mine, self.left.cardspace.draw.content)

    def test_shielded_opener_arms_return_only_for_its_own_use(self):
        self.enemy.add_shield("normal", 2)
        mine = self.place(self.actor, "漂泊剑法")
        hits = []
        self.game.context.register_entries(self.actor, [{
            "trigger": "AFTER RESOLVE_HIT",
            "operation": lambda ctx: hits.append((ctx.event["die"].position, mine in self.left.cardspace.hand.content)),
        }])
        self.battle()
        self.assertEqual((self.enemy.hp, self.enemy.shield), (30, 1))
        self.assertEqual(hits, [(1, False), (2, False)])
        self.assertIn(mine, self.left.cardspace.hand.content)
        self.new_turn()
        self.place(self.actor, mine.name)
        self.place_fixture(self.enemy, [dict(type="slash", level=2, base_value=10)])
        self.battle()
        self.assertEqual(mine.instantiated_dice[0].clash_result, "lose")
        self.assertEqual(hits, [(1, False), (2, False), (2, False)])
        self.assertNotIn(mine, self.left.cardspace.hand.content)
        self.new_turn()
        self.assertIn(mine, self.left.cardspace.draw.content)

    def test_drifting_sword_tied_opener_does_not_return_after_later_hit(self):
        mine = self.place(self.actor, "漂泊剑法")
        self.place_fixture(self.enemy, [dict(type="slash", level=2)])
        self.battle()
        self.assertNotIn(mine, self.left.cardspace.hand.content)
        self.assertEqual(mine.instantiated_dice[0].clash_result, "draw")
        self.assertEqual(mine.instantiated_dice[-1].clash_result, "skip")
        self.assertEqual(self.enemy.hp, 30)
        self.assertNotIn("骰子等级降低", self.enemy.statuses)

    def test_drifting_sword_cancelled_opener_does_not_arm_return(self):
        self.game.context.register_entries(self.enemy, [{
            "trigger": "BEFORE RESOLVE_HIT", "subject": "target", "operation": "cancel",
            "turn_limit": {"key": "cancel_first", "count": 1},
        }])
        mine = self.place(self.actor, "漂泊剑法")
        self.battle()
        self.assertEqual(self.enemy.hp, 30)
        self.assertNotIn(mine, self.left.cardspace.hand.content)

    def test_drifting_sword_opener_target_dies_before_hit_and_next_die_retargets(self):
        other = self.dummy(self.right, "第二目标")
        self.game.context.register_entries(self.enemy, [{
            "trigger": "BEFORE RESOLVE_HIT", "subject": "target",
            "operation": {"op": "program", "code": ["$self", 30, "LOSE_HP"]},
        }])
        resolved = []
        self.game.context.register_entries(self.actor, [{
            "trigger": "AFTER RESOLVE_HIT",
            "operation": lambda ctx: resolved.append((ctx.event["die"].position, ctx.event["target"])),
        }])
        mine = self.place(self.actor, "漂泊剑法")
        self.place_fixture(self.enemy, [dict(type="slash", level=1, base_value=-5)])
        self.battle()
        self.assertFalse(self.enemy.is_alive)
        self.assertIn((2, other), resolved)
        self.assertNotIn(mine, self.left.cardspace.hand.content)

    def test_drifting_sword_lethal_opener_still_arms_return(self):
        self.dummy(self.right, "第二目标")
        self.enemy.hp = 1
        self.place_fixture(self.enemy, [dict(type="slash", level=1, base_value=-5)])
        mine = self.place(self.actor, "漂泊剑法")
        self.battle()
        self.assertFalse(self.enemy.is_alive)
        self.assertIn(mine, self.left.cardspace.hand.content)

    def test_vortex_sword_locks_target_and_loses_hp_through_shield(self):
        self.enemy.add_status("涡流", 1)
        self.actor.add_status("强壮", 1)
        self.actor.add_shield("normal", 2)
        self.place(self.actor, "剑携涡流")
        self.place_fixture(self.enemy, [dict(type="slash", level=1, base_value=-5)] * 3)
        self.battle()
        self.assertEqual((self.actor.hp, self.actor.shield, self.actor.statuses["涡流"]), (8, 3, 2))
        self.assertEqual(self.enemy.hp, 26)
        self.assertNotIn("涡流", self.enemy.statuses)

    def test_breeze_counts_actual_damage_only_during_its_duel_and_enables_zero_damage_die(self):
        self.actor.add_shield("normal", 1)
        self.place(self.actor, "流风习习")
        self.place_fixture(self.enemy, [
            dict(type="slash", level=1, base_value=10, entries=["1物理"]),
            dict(type="slash", level=1, base_value=10, entries=["1物理"]),
            dict(type="slash", level=1, base_value=-5),
            dict(type="slash", level=1, base_value=-5),
        ])
        self.place_fixture(self.enemy, [dict(type="slash", level=1, entries=["1物理"])], slot=1)
        self.battle()
        self.assertEqual((self.actor.hp, self.actor.statuses["涡流"]), (7, 3))
        self.assertEqual((self.enemy.hp, self.enemy.statuses["涡流"]), (28, 1))

    def test_burst_spends_before_primary_bonus_and_pays_hp_with_shields(self):
        other = self.dummy(self.right, "次目标")
        other.add_shield("normal", 2)
        self.actor.add_shield("normal", 3)
        self.actor.add_status("涡流", 8)
        mine = self.place(self.actor, "翠流迸发")
        self.battle()
        self.assertEqual((self.actor.hp, self.actor.shield, self.actor.statuses["涡流"]), (5, 3, 6))
        self.assertEqual(mine.instantiated_dice[1].final_bonus, 15)
        self.assertEqual((self.enemy.hp, other.hp), (23, 28))

    def test_burst_with_three_hp_drains_to_death_and_cancels_tail(self):
        self.actor.hp = 3
        self.actor.add_status("涡流", 1)
        self.actor.add_shield("normal", 9)
        self.place(self.actor, "翠流迸发")
        self.battle()
        self.assertFalse(self.actor.is_alive)
        self.assertEqual((self.actor.hp, self.enemy.hp), (0, 29))
        self.assertNotIn("涡流", self.actor.statuses)

    def test_burst_next_die_bonus_follows_a_repeat_and_is_consumed_on_loss(self):
        mine = self.place(self.actor, "翠流迸发")
        first, second = mine.dice
        repeat_once = {
            "trigger": "on_dice_hit",
            "operation": {"op": "program", "code": ["$repeat_count", 0, "EQ", ["$die", "REPEAT_DIE"], "WHEN"]},
        }
        mine.dice = [dict(first, entries=[*first["entries"], repeat_once]), second]
        self.place_fixture(self.enemy, [dict(type="slash", level=1, base_value=x) for x in (-5, 30, -5)])
        self.battle()
        self.assertEqual([die.final_bonus for die in mine.instantiated_dice], [0, 15, 0])
        self.assertEqual((self.actor.hp, self.enemy.hp), (5, 25))

    def test_drifting_wind_converts_all_stacks_and_schedules_each_enemy_once(self):
        other = self.dummy(self.right, "次目标")
        self.actor.add_status("骰子等级降低", 3)
        self.actor.add_status("涡流", 12)
        mine = self.place(self.actor, "飘流翠风")
        self.battle()
        self.assertEqual(self.actor.statuses["强壮"], 12)
        self.assertEqual(mine.instantiated_dice[0].clash_result, "skip")
        self.assertEqual(self.actor.statuses["涡流"], 1)
        self.assertEqual([die.roll_max for die in mine.instantiated_dice], [8, 12, 12, 20])
        self.assertEqual((self.enemy.hp, other.hp), (26, 28))
        self.new_turn()
        self.assertEqual((self.actor.statuses["强壮"], self.actor.statuses["涡流"]), (12, 2))
        self.assertNotIn("骰级免疫", self.actor.statuses)
        for foe in (self.enemy, other):
            self.assertEqual(foe.statuses["骰子等级降低"], 1)

    def test_drifting_wind_grants_level_immunity_without_vortex(self):
        self.actor.add_status("骰子等级降低", 2)
        mine = self.place(self.actor, "飘流翠风")
        self.place_fixture(self.enemy, [dict(type="slash", level=1, base_value=-5)])
        self.battle()
        self.assertNotIn("涡流", self.actor.statuses)
        self.assertNotIn("强壮", self.actor.statuses)
        self.assertEqual(self.actor.statuses["骰级免疫"], 1)
        self.assertEqual(mine.instantiated_dice[-1].roll_max, 20)
