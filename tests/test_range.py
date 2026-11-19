import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from models.card import Card
from models.character import Character
from models.duel import DuelSlot
from player.player import Player


def die(kind="slash", base=0, entries=()):
    return dict(type=kind, level=1, base_value=base, entries=list(entries))


def program(trigger, code, **fields):
    return dict(trigger=trigger, operation=dict(op="program", code=code), **fields)


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.players = [Player(1, "左"), Player(2, "右")]
        self.game = Game(self.players, rng=random.Random(2))
        self.game.first_player = self.players[0]
        self.left, self.right = (self.actor(player, player.name) for player in self.players)
        self.game.start_turn()

    def actor(self, player, name):
        actor = Character(dict(id=name, name=name, rank="ELITE", max_hp=30, skills=[]), player)
        player.characters.append(actor)
        return actor

    def skill(self, actor, name, dice, level=0, **fields):
        card = Card(actor.player, dict(id=name, name=name, cost=fields.pop("cost", 0),
                                       dice=dice, range_level=level, **fields), actor)
        actor.skills.append(card)
        return card

    def slot(self, left, right):
        slot = DuelSlot(self.game)
        for cards in (left, right):
            for card in cards:
                slot.add_content(card.player.side, card)
        self.game.duelspace.append_new_duel(slot)

    def play(self):
        pipe = self.game.pipeline
        pipe.start_duel_combat()
        while pipe.in_duel_phase:
            pipe.step_duel_combat()
        self.assertEqual(self.game.context.stack, [])

    def test_level_one_can_win_but_cannot_land_any_hit_or_affect_ranged_caster(self):
        use = program("on_skill_use", ["$target", "标记", 1, "STATUS", "$self", "准备", 1, "STATUS"])
        after = program("after_skill_use", ["$self", "$target", "明日标记", 1, "QUEUE_STATUS"])
        hit = program("on_dice_hit", ["$self", "命中", 1, "STATUS"])
        weak = self.skill(self.left, "近战", [die(base=10, entries=["4", hit])] * 2, entries=[use, after])
        strong = self.skill(self.right, "远射", [die()], 1)
        self.slot([weak], [strong])
        self.play()
        self.assertTrue(self.left.won_clash_this_turn)
        self.assertEqual(self.left.statuses, {"准备": 1})
        self.assertEqual(self.right.hp, self.right.max_hp)
        self.assertNotIn("标记", self.right.statuses)
        self.assertEqual(self.game.next_turn_statuses, [])

    def test_level_two_scores_still_recorded_solo_attack_blanks_but_own_entries_work(self):
        self.left.hp = 20
        action = program("on_dice_use", ["$self", "用骰", 1, "STATUS"])
        win = program("on_clash_win", ["$self", "胜利词条", 1, "STATUS"])
        weak = self.skill(self.left, "还击", [die(base=12, entries=[action, win, "3"])] * 2,
                          entries=[program("on_skill_use", ["$self", 2, "HEAL"])])
        strong = self.skill(self.right, "强化", [die(base=1)], 2)
        self.game.context.register_entries(self.right, [
            program("on_clash_lose", ["$self", "败者", 1, "STATUS"]),
            program("before_clash_win", ["$self", "准备", 1, "STATUS"], subject="any"),
            program("after_clash_win", ["$self", "收尾", 1, "STATUS"], subject="any")])
        self.slot([weak], [strong])
        self.play()
        first, tail = weak.instantiated_dice
        self.assertGreater(first.clash_score, strong.instantiated_dice[0].clash_score)
        self.assertEqual(first.clash_result, "win")
        self.assertTrue(first.win_branch_skipped)
        self.assertTrue(self.left.won_clash_this_turn)
        self.assertEqual(strong.instantiated_dice[0].clash_result, "lose")
        self.assertEqual((tail.type, tail.clash_result), ("blank", "skip"))
        self.assertEqual(self.left.statuses, {"用骰": 1})
        self.assertEqual(self.right.statuses, {"败者": 1})
        self.assertEqual(self.left.hp, 22)

    def test_level_three_blanks_whole_skill_before_use_dice_and_after_use_but_base_fee_and_passive_work(self):
        mark = ["$self", "发动", 1, "STATUS"]
        weak = self.skill(self.left, "还击", [die(base=10, entries=[program("on_dice_use", mark)])],
                          entries=[program(t, mark) for t in ("before_skill_use", "on_skill_use", "after_skill_use")],
                          cost=1)
        self.game.context.register_entries(self.left, [program("on_skill_use", ["$self", "被动", 1, "STATUS"])])
        self.slot([weak], [self.skill(self.right, "极限", [die()], 3)])
        self.play()
        self.assertEqual(weak.instantiated_dice[0].type, "blank")
        self.assertIsNotNone(weak.instantiated_dice[0].clash_score)
        self.assertTrue(weak.instantiated_dice[0].win_branch_skipped)
        self.assertIn(weak, self.game.used_cards)
        self.assertEqual(self.left.statuses, {"被动": 1})
        self.assertEqual(self.left.used_independent_cost + self.left.player.used_cost, 1)
        weak.reset_for_draw()
        self.assertEqual(weak.get_current_die(self.game).type, "slash")

    def test_equal_range_and_ignore_cancel_without_erasing_printed_levels(self):
        for index, (left, right, ignored) in enumerate([(2, 2, 0), (1, 3, 2), (0, 3, 3)]):
            weak = self.skill(self.left, f"弱{index}", [die(base=10, entries=["1"])], left, ignore_range=ignored)
            strong = self.skill(self.right, f"强{index}", [die()], right)
            self.slot([weak], [strong])
        self.play()
        self.assertEqual(self.right.hp, 27)

    def test_partial_cancellation_only_leaves_level_one(self):
        win = program("on_clash_win", ["$self", "胜利", 1, "STATUS"])
        weak = self.skill(self.left, "普通", [die(base=12, entries=["3", win])], 1, ignore_range=1)
        self.slot([weak], [self.skill(self.right, "极限", [die()], 3)])
        self.play()
        self.assertEqual(self.left.statuses, {"胜利": 1})
        self.assertEqual(self.right.hp, self.right.max_hp)
        self.assertFalse(weak.instantiated_dice[0].win_branch_skipped)

    def test_range_blocks_even_a_hit_redirected_to_a_different_caster(self):
        second = self.actor(self.right.player, "队友")
        route = program("before_dice_pair", ["$die", "$next_duel_target", "ROUTE_DIE_ATTACK"])
        weak = self.skill(self.left, "改道", [die(entries=["3", route])])
        self.slot([weak], [self.skill(self.right, "普通", [die("block")], 1)])
        self.slot([], [self.skill(second, "普通招架", [die("block")])])
        self.play()
        self.assertIs(weak.instantiated_dice[0].attack_target, second)
        self.assertEqual((self.right.hp, second.hp), (30, 30))

    def test_conditional_ignore_and_changing_opponent_recompute_range(self):
        self.left.add_status("测距", 1)
        self.game.context.register_entries(self.left, [program("BEFORE RESOLVE_RANGE_DEFICIT",
                ["$value_ref", 0, "VALUE_CEILING"], when={"owner_status_at_least": {"测距": 1}})])
        weak = self.skill(self.left, "两骰", [die(base=12, entries=["2"])] * 2)
        self.slot([weak], [self.skill(self.right, "极限", [die()], 3), self.skill(self.right, "接续", [die()])])
        self.play()
        self.assertEqual(self.right.hp, 26)
        self.assertEqual([d.type for d in weak.instantiated_dice], ["slash", "slash"])

    def test_new_opponent_releases_previous_range_disadvantage(self):
        weak = self.skill(self.left, "两骰", [die(base=12, entries=["2"])] * 2)
        self.slot([weak], [self.skill(self.right, "极限", [die()], 3), self.skill(self.right, "接续", [die()])])
        self.play()
        self.assertEqual(self.right.hp, 28)
        self.assertEqual([d.type for d in weak.instantiated_dice], ["blank", "slash"])

    def test_enemy_and_friendly_reactions_use_source_of_entry_not_current_event(self):
        protected = self.skill(self.right, "强化", [die(entries=["1"])], 2)
        # The disadvantaged card cannot lower an enemy roll or damage their
        # caster, but a character passive observing the same event still can.
        lower = program("BEFORE RESOLVE_FINAL_SCORE", [50, "SUB"], subject="enemy")
        weak = self.skill(self.left, "反应", [die()], entries=[lower])
        self.game.context.register_entries(self.left, [program("on_skill_use",
                ["$target", "被动命中", 1, "STATUS"])])
        self.slot([weak], [protected])
        self.play()
        self.assertEqual(self.right.statuses.get("被动命中"), 1)
        self.assertGreater(protected.instantiated_dice[0].final_score, 0)

    def test_unaffordable_range_cannot_blank_opponent(self):
        weak = self.skill(self.left, "近战", [die(entries=["3"])], cost=99, entries=[
            program("before_skill_use", ["$self", "准备", 1, "STATUS"]), program("BEFORE PAY_COST", [99, "SUB"])])
        self.slot([weak], [self.skill(self.right, "无法支付", [die()], 3, cost=99)])
        self.play()
        self.assertEqual(self.right.hp, 27)
        self.assertEqual(self.left.statuses, {"准备": 1})
        self.assertEqual(weak.instantiated_dice[0].type, "slash")

    def test_range_activation_obeys_actual_discounted_or_cancelled_price(self):
        self.game.context.register_entries(self.right, [dict(trigger="BEFORE PAY_COST", operation="cancel",
                turn_limit={"key": "cancel_first", "count": 1})])
        for i in range(2):
            cheap = program("BEFORE PAY_COST", [99, "SUB"])
            self.slot([self.skill(self.left, f"还击{i}", [die(base=12, entries=["2"])], entries=[
                program("before_skill_use", ["$self", "准备", 1, "STATUS"])])],
                      [self.skill(self.right, f"极限{i}", [die()], 3, cost=99, entries=[cheap])])
        self.play()
        self.assertEqual(self.right.hp, 28)
        self.assertEqual(self.left.statuses, {"准备": 1})
        self.assertEqual([c.name for c in self.game.used_cards], ["还击0", "极限1", "还击1"])
