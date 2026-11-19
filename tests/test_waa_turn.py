import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from loader import load_characters_from_packs
from models.character import Character
from models.opcode import OpCode
from player.player import Player


class WaaTurnRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = {card["name"]: card for card in load_characters_from_packs()}

    def setUp(self):
        self.output = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right])
        self.lake = self.recruit(self.left, "莱克")
        self.enemy = self.recruit(self.right, "铁壁先锋")

    def recruit(self, player, name):
        character = Character(self.roster[name], player)
        player.characters.append(character)
        character.init_cards()
        character.setup_deck()
        return character

    def test_mixed_team_gains_charge_once_per_upward_hand_crossing(self):
        partner = self.recruit(self.left, "格罗琳娜")
        common = self.recruit(self.left, "演练斥候")
        self.left.draw_card(2)
        self.assertNotIn("充能", self.lake.statuses)
        self.left.draw_card(1)
        self.left.draw_card(1)
        self.assertEqual([c.statuses["充能"] for c in (self.lake, partner, common)], [1, 1, 1])
        self.game.start_turn()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual([c.statuses["充能"] for c in (self.lake, partner, common)], [1, 1, 1])
        self.assertTrue(self.game.auto_place_in_duel(self.left.side, self.lake.skills[0]))
        self.game.context.eval_block([self.left, 1, OpCode.DISCARD])
        self.assertEqual(len(self.left.cardspace.hand.content), 2)
        self.left.draw_card(2)
        self.assertEqual([c.statuses["充能"] for c in (self.lake, partner, common)], [2, 2, 2])
        self.assertNotIn("充能", self.enemy.statuses)

    def test_faction_passive_continues_only_while_a_member_is_alive(self):
        partner = self.recruit(self.left, "格罗琳娜")
        common = self.recruit(self.left, "演练斥候")
        self.left.draw_card(3)
        self.lake.take_damage(self.lake.max_hp)
        self.assertEqual(self.left.cardspace.hand.content, [])
        self.left.draw_card(3)
        self.assertEqual((partner.statuses["充能"], common.statuses["充能"]), (2, 2))
        partner.take_damage(partner.max_hp)
        self.left.draw_card(3)
        self.assertEqual(common.statuses["充能"], 2)

    def test_hand_changes_report_moves_and_bulk_retirement_with_settled_zones(self):
        partner = self.recruit(self.left, "格罗琳娜")
        zones = self.left.cardspace
        changes = []

        def record(ctx):
            self.assertIs(ctx.event["player"], self.left)
            self.assertEqual(ctx.event["hand_count"], len(zones.hand.content))
            changes.append((ctx.event["previous_count"], ctx.event["hand_count"]))
            if changes[-1] == (4, 3):
                self.assertIn(partner.skills[0], self.game.duelspace.space[0].content[self.left.side])
            if changes[-1] == (3, 2):
                self.assertIn(self.lake.skills[1], zones.delayed_discard.content)
            if changes[-1] == (3, 0):
                self.assertTrue(all(card in zones.out_of_combat.content for card in self.lake.skills))

        self.game.context.register_entries(partner, [{"trigger": "on_hand_changed", "operation": record}])
        self.right.draw_card(1)
        self.left.draw_card(4)
        zones.hand.move_card_to(0, zones.hand)
        self.assertTrue(self.game.auto_place_in_duel(self.left.side, partner.skills[0]))
        self.game.context.eval_block([self.left, 1, OpCode.DISCARD])
        zones.delayed_discard.move_card_to(0, zones.hand)
        self.lake.take_damage(self.lake.max_hp)
        self.assertEqual(changes, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 3), (3, 2), (2, 3), (3, 0)])

    def test_pack_can_use_another_threshold_and_read_a_stable_hand_snapshot(self):
        self.game.context.register_entries(self.lake, [
            {"trigger": "on_hand_changed", "when": {"previous_count": 1, "hand_count": 2},
             "operation": {"op": "discard", "amount": 1}},
            {"trigger": "on_hand_changed", "operation": {"op": "program", "code": [
                "$previous_hand_count", 2, "LT", "$current_hand_count", 2, "GE", "AND",
                ["$self", "试验", 1, "STATUS"], "WHEN",
            ]}},
        ])
        self.left.draw_card(2)
        self.assertEqual(len(self.left.cardspace.hand.content), 1)
        self.assertEqual(self.lake.statuses.get("试验"), 1)

    def test_full_faction_opens_match_with_one_charge_on_each_member(self):
        self.recruit(self.left, "格罗琳娜")
        self.recruit(self.left, "厄尔克斯")
        with patch("builtins.input", return_value="1 2"), \
                patch.object(self.game.rng, "randint", side_effect=[1, 3, 4, 2]):
            for _ in range(8):
                if self.game.next_step() == "on_turn_start":
                    break
            else:
                self.fail("没有推进到回合开始")
        self.assertEqual(len(self.left.cardspace.hand.content), 3)
        self.assertEqual([c.statuses["充能"] for c in self.left.characters], [1, 1, 1])
        self.assertNotIn("充能", self.enemy.statuses)

    def test_speed_rolls_each_living_character_discards_one_minimum_and_rerolls_all_on_tie(self):
        second = self.recruit(self.left, "格罗琳娜")
        third = self.recruit(self.left, "厄尔克斯")
        self.game.start_turn()
        # Three equal rolls retain two equal members after dropping one minimum.
        with patch.object(self.game.rng, "randint", side_effect=[3, 3, 3, 3, 1, 3, 4, 3]) as rolls:
            self.game.determine_first_player()
        self.assertEqual(rolls.call_count, 8)
        self.assertEqual((self.lake.speed, second.speed, third.speed, self.enemy.speed), (1, 3, 4, 3))
        self.assertEqual((self.left.speed, self.right.speed), (3.5, 3))
        self.assertIs(self.game.first_player, self.left)
        self.lake.add_status("束缚", 2)
        with patch.object(self.game.rng, "randint", side_effect=[1, 3, 4]):
            self.assertEqual(self.left.calculate_speed(), 3.5)
        third.take_damage(third.max_hp)
        with patch.object(self.game.rng, "randint", side_effect=[4, 3]) as rolls:
            self.assertEqual(self.left.calculate_speed(), 3)
        self.assertEqual(rolls.call_count, 2)

    def test_speed_roll_opcode_identifies_the_individual_character(self):
        rolls = []
        for actor in (self.lake, self.enemy):
            def record(ctx, owner=actor):
                self.assertIs(ctx.event["source"], owner)
                self.assertEqual(ctx.event["side"], owner.player.side)
                rolls.append(owner)
            self.game.context.register_entries(actor, [{
                "trigger": "BEFORE ROLL", "when": {"roll_kind": "speed"}, "operation": record
            }])
        with patch.object(self.game.rng, "randint", side_effect=[4, 2]):
            self.game.determine_first_player()
        self.assertEqual(rolls, [self.lake, self.enemy])

    def test_delayed_statuses_bonuses_and_clash_history_follow_turn_boundaries(self):
        self.game.start_turn()
        self.game.record_clash_result(self.lake, "win")
        self.game.record_clash_result(self.enemy, "lose")
        self.game.duelspace.current_duel_index = 1
        self.assertTrue(self.right.lost_clash_in_previous_duel())
        self.assertTrue(self.lake.won_clash_this_turn)
        self.lake.add_status("强壮", 2)
        self.lake.queue_status("迅捷", 1)
        self.enemy.queue_status("虚弱", 2, source=self.lake)
        self.lake.queue_status("充能", 2)
        self.lake.next_turn_duels += 2
        self.left.next_turn_common_cost += 1
        self.assertNotIn("虚弱", self.enemy.statuses)
        self.game.finish_turn()
        self.assertNotIn("强壮", self.lake.statuses)
        self.game.draw_phase()
        with patch.object(self.game.rng, "randint", side_effect=[1, 2, 1, 3]):
            self.game.determine_first_player()
        self.assertEqual((self.left.speed, self.right.speed), (2, 3))
        self.game.start_turn()
        self.assertEqual((self.lake.statuses["迅捷"], self.enemy.statuses["虚弱"]), (1, 2))
        self.assertEqual((self.lake.max_duels, self.left.max_cost), (3, 6))
        self.assertFalse(self.lake.won_clash_this_turn)
        self.game.duelspace.current_duel_index = 1
        self.assertFalse(self.right.lost_clash_in_previous_duel())
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual((self.lake.max_duels, self.left.max_cost), (1, 5))
        self.assertNotIn("迅捷", self.lake.statuses)
        self.assertNotIn("虚弱", self.enemy.statuses)
        self.assertEqual(self.lake.statuses["充能"], 2)

    def test_delayed_status_skips_a_target_who_died_before_the_next_turn(self):
        doomed = self.recruit(self.right, "格罗琳娜")
        self.game.start_turn()
        doomed.queue_status("虚弱", 2, source=self.lake)
        self.enemy.queue_status("虚弱", 1, source=self.lake)
        seen = []
        self.game.context.register_entries(self.lake, [{
            "trigger": "AFTER STATUS", "subject": "source", "when": {"status": "虚弱"},
            "operation": lambda ctx: seen.append(ctx.event["target"]),
        }])
        doomed.take_damage(doomed.max_hp)
        self.game.finish_turn()
        self.game.start_turn()
        self.assertEqual(seen, [self.enemy])
        self.assertNotIn("虚弱", doomed.statuses)
        self.assertEqual(self.enemy.statuses["虚弱"], 1)

    def test_one_turn_status_still_expires_on_a_fallen_character(self):
        ally = self.recruit(self.left, "格罗琳娜")
        ally.add_status("虚弱", 1)
        ally.take_damage(ally.max_hp)
        self.game.finish_turn()
        self.assertNotIn("虚弱", ally.statuses)
