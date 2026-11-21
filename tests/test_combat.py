import io
import random
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from models.card import Card, CardState
from models.character import Character
from models.dice import Dice
from models.duel import DuelSlot
from pipeline.pipeline import Pipeline
from pipeline.pipeline_base import PipelineNode
from player.player import Player


class CombatTests(unittest.TestCase):
    def setUp(self):
        self.players = [Player(1, "A"), Player(2, "B")]
        self.game = Game(self.players, rng=random.Random(7))
        self.game.first_player = self.players[1]
        self.a = self.character(self.players[0], "先锋")
        self.b = self.character(self.players[1], "决斗者")
        self.game.start_turn()

    def character(self, player, name):
        actor = Character({"id": name, "name": name, "rank": "ELITE",
                           "max_hp": 50, "skills": []}, player)
        player.characters.append(actor)
        return actor

    def skill(self, actor, name, dice, *, cost=0, entries=()):
        card = Card(actor.player, {"id": name, "name": name, "cost": cost, "entries": entries,
                                   "dice": [{"type": t, "level": 1, "base_value": b, "entries": e}
                                            for t, b, e in dice]}, actor)
        card.state = CardState.PLACED_FACE_UP
        actor.skills.append(card)
        return card

    def slot(self, a, b):
        slot = DuelSlot(self.game)
        for side, cards in enumerate((a, b), 1):
            for card in cards:
                slot.add_content(side, card)
        self.game.duelspace.append_new_duel(slot)
        return slot

    def play(self):
        events = []
        with redirect_stdout(io.StringIO()):
            self.game.pipeline.start_duel_combat()
            for _ in range(600):
                events.append(self.game.pipeline.step_duel_combat())
                if not self.game.pipeline.in_duel_phase:
                    return events
        self.fail("交锋队列未完成")

    def test_three_dice_against_two_skills_and_next_slot(self):
        first = self.skill(self.a, "三连", [("slash", 20, ["1"])] * 3)
        guard = self.skill(self.b, "双盾", [("block", 0, [])] * 2)
        riposte = self.skill(self.b, "架刺", [("block", 0, []), ("pierce", 1, ["2"])])
        final = self.skill(self.a, "追击", [("blunt", 0, ["1"])])
        self.slot([first], [guard, riposte])
        self.slot([final], [])
        with patch.object(self.game.rng, "randint", wraps=self.game.rng.randint) as rng:
            events = self.play()
        self.assertEqual(rng.call_count, 6)
        self.assertEqual((self.a.hp, self.b.hp), (48, 46))
        self.assertEqual(self.game.used_cards, [guard, first, riposte, final])
        self.assertEqual(self.game.duelspace.current_duel_index, 2)
        self.assertEqual(events.count(("after_dice_clash", "after_dice_clash")), 3)
        self.assertEqual(events.count(("wait_can_hit_check", None)), 3)
        self.assertTrue(all(b is None for a, b in events if a == "logic_dice_hit"))
        self.assertEqual(sum(b == "on_clash_win" for a, b in events), 0)
        self.assertEqual(sum(b == "logic_dice_hit" for a, b in events), 1)

    def test_unopposed_target_chosen_once_for_whole_skill(self):
        c = self.character(self.players[0], "第二位")
        hit = self.skill(self.b, "双击", [("pierce", 0, ["2"])] * 2)
        self.slot([], [hit])
        with patch("builtins.input", return_value="2") as select:
            events = self.play()
        self.assertEqual(select.call_count, 1)
        self.assertEqual((self.a.hp, self.b.hp, c.hp), (50, 50, 46))
        self.assertFalse(any("on_clash_win" in pair for pair in events))

    def test_extra_hit_runs_all_hit_stages_under_one_clash_result(self):
        repeat = dict(trigger="before_dice_hit", when={"hit_index": 1, "clash_result": "win"},
                      operation=dict(op="program", code=["$die", "full", "QUEUE_HIT"]))
        mark = dict(trigger="on_dice_hit", operation="Shield: 1")
        attack = self.skill(self.a, "连中", [("slash", 20, [repeat, mark, "2"])])
        defense = self.skill(self.b, "阻挡", [("block", 0, [])])
        self.slot([attack], [defense])
        events = self.play()
        self.assertEqual((self.b.hp, self.a.shield), (46, 2))
        self.assertEqual(sum(a == "on_clash_win" for a, _ in events), 1)
        self.assertEqual(sum(a == "before_dice_use" for a, _ in events), 1)
        for step in ("before_dice_hit", "logic_dice_hit", "on_dice_hit", "after_dice_hit"):
            self.assertEqual(sum(a == step for a, _ in events), 2)

    def test_losing_hit_can_request_only_printed_damage(self):
        resident = dict(trigger="on_clash_lose",
                        operation=dict(op="program", code=["$die", "damage_only", "QUEUE_HIT"]))
        attack = self.skill(self.a, "驻留", [("slash", 0, ["2穿甲", "Shield: 4", resident,
                             dict(trigger="on_dice_hit", operation="Shield: 3")])])
        counter = self.skill(self.b, "还击", [("slash", 20, ["1"])])
        self.slot([attack], [counter])
        self.play()
        self.assertEqual((self.a.hp, self.b.hp, self.a.shield), (49, 48, 0))
        self.assertEqual(attack.instantiated_dice[0].clash_result, "lose")
        self.assertFalse(self.a.won_clash_this_turn)

    def test_cancelled_first_hit_drops_extra_hit_and_its_effects(self):
        first = dict(trigger="before_dice_hit", when={"hit_index": 1},
                     operation=dict(op="program", code=["$die", "full", "QUEUE_HIT"]))
        attack = self.skill(self.a, "追加", [("slash", 20, ["3", first,
                            dict(trigger="on_dice_hit", operation="Shield: 2")])])
        self.game.context.register_entries(self.b, [dict(
            trigger="BEFORE RESOLVE_HIT", subject="target", operation="cancel")])
        self.slot([attack], [])
        events = self.play()
        self.assertEqual(attack.instantiated_dice[0].landed_hits, 0)
        self.assertEqual((self.a.shield, self.b.hp), (0, 50))
        self.assertEqual(sum(a == "before_dice_hit" for a, _ in events), 1)

    def test_resident_hit_cannot_retarget_after_winner_dies(self):
        ally = self.character(self.players[1], "幸存者")
        resident = dict(trigger="on_clash_lose",
                        operation=dict(op="program", code=["$die", "damage_only", "QUEUE_HIT"]))
        self_damage = dict(trigger="on_dice_hit", operation=dict(op="program", code=["$self", 80, "LOSE_HP"]))
        losing = self.skill(self.a, "驻留", [("slash", 0, ["4", resident])])
        winning = self.skill(self.b, "决死", [("slash", 20, ["1", self_damage])])
        self.slot([losing], [winning])
        self.play()
        self.assertFalse(self.b.is_alive)
        self.assertEqual(ally.hp, ally.max_hp)
        self.assertEqual(losing.instantiated_dice[0].landed_hits, 0)

    def test_two_hits_destroy_future_repeat_and_next_die_before_pairing(self):
        shatter = dict(trigger="on_dice_hit", operation=dict(op="program", code=["$target_next_die", "DESTROY"]))
        extra = dict(trigger="before_dice_hit", when={"hit_index": 1},
                     operation=dict(op="program", code=["$die", "full", "QUEUE_HIT"]))
        again = dict(trigger="on_dice_use", operation=dict(op="program",
                     code=["$is_repeat", "NOT", ["$die", "REPEAT_DIE"], "WHEN"]))
        a = self.skill(self.a, "双击", [("slash", 20, [extra, shatter]), ("slash", 20, ["1"])])
        b = self.skill(self.b, "原骰与重复骰", [("slash", 0, [again]), ("slash", 0, [])])
        self.slot([a], [b])
        events = self.play()
        self.assertEqual([(d.is_repeat, d.destroyed) for d in b.instantiated_dice],
                         [(False, False), (True, True), (False, True)])
        self.assertEqual([d.clash_result for d in b.instantiated_dice], ["lose", None, None])
        self.assertEqual(a.instantiated_dice[1].landed_hits, 1)
        self.assertIsNone(a.instantiated_dice[1].clash_result)
        self.assertEqual(sum(a == "on_clash_win" for a, _ in events), 1)

    def test_future_die_selector_uses_only_board_cards_of_target_and_does_not_arm_entries(self):
        shatter = dict(trigger="on_dice_hit", operation=dict(op="program", code=["$target_next_die", "DESTROY"]))
        a = self.skill(self.a, "断后", [("slash", 20, [shatter])])
        b = self.skill(self.b, "当前", [("block", 0, [])])
        ally = self.character(self.players[1], "队友")
        other = self.skill(ally, "先到的队友", [("slash", 1, [])])
        future = self.skill(self.b, "后来者", [("slash", 30, [
            dict(trigger="AFTER DESTROY", subject="any", scope="global", operation="Shield: 8")])])
        self.slot([a], [b])
        self.slot([], [other, future])
        self.play()
        self.assertTrue(future.instantiated_dice[0].destroyed)
        self.assertFalse(future.instantiated_dice[0].entries_registered)
        self.assertFalse(other.instantiated_dice[0].destroyed)
        self.assertEqual(self.b.shield, 0)
        self.assertIsNone(self.game.pipeline.next_planned_die(self.b))

    def test_transferred_tail_keeps_pending_repeat_and_cannot_revive_destroyed_use(self):
        donor = self.skill(self.b, "被接管", [("slash", 1, []), ("blunt", 2, [])])
        receiver = self.skill(self.a, "接管", [("pierce", 1, [])])
        current = donor.get_current_die(self.game)
        current.request_repeat()
        repeat, end = donor.planned_dice(self.game, after_current=True)
        end.destroyed = True
        receiver.take_remaining_dice(donor)
        donor.advance_die()
        receiver.advance_die()
        transferred = receiver.get_current_die(self.game)
        self.assertTrue(repeat.is_repeat and transferred.is_repeat)
        self.assertEqual(transferred.type, "slash")
        receiver.advance_die()
        self.assertIsNone(receiver.get_current_die(self.game))
        self.assertIsNone(donor.get_current_die(self.game))

    def test_printed_skip_and_prospective_skip_advance_both_dice_without_a_hit(self):
        skip = dict(trigger="before_clash_result", when={"prospective_result": "lose"},
                    operation=dict(op="program", code=["$die", "SKIP_ROUND"]))
        marker = dict(trigger="on_clash_skip", operation="Shield: 1")
        a = self.skill(self.a, "避锋", [("slash", 0, []), ("slash", 0, [skip]), ("slash", 20, ["1"])])
        a.dice[0] = {"type": "skip"}
        b = self.skill(self.b, "三击", [("slash", 10, ["4", marker])] * 3)
        self.slot([a], [b])
        self.play()
        self.assertEqual([d.clash_result for d in a.instantiated_dice], ["skip", "skip", "win"])
        self.assertEqual([d.clash_result for d in b.instantiated_dice], ["skip", "skip", "lose"])
        self.assertEqual((self.a.hp, self.b.shield), (50, 1))
        self.assertIsNone(a.instantiated_dice[0].clash_score)
        self.assertIsNotNone(a.instantiated_dice[1].clash_score)

    def test_skill_target_reuses_choice_from_use_for_its_solo_dice(self):
        target = self.character(self.players[0], "选中者")
        lock = {"trigger": "on_skill_use", "operation": {"op": "program", "code": [
            "$card", "chosen", "$skill_target", "SET_SKILL_STATE"]}}
        attack = self.skill(self.b, "锁定", [("pierce", 0, ["1"])] * 2, entries=[lock])
        self.slot([], [attack])
        with patch("builtins.input", return_value="2") as select:
            self.play()
        self.assertIs(attack.use_state["chosen"], target)
        self.assertEqual(select.call_count, 1)
        self.assertEqual((self.a.hp, target.hp), (50, 48))

    def test_returned_card_resets_once_and_successor_still_plays(self):
        restore = {"trigger": "after_skill_use", "operation": {"op": "program", "code": [
            "$card", "hand", "MOVE_CARD"]}}
        first = self.skill(self.a, "回手", [("slash", 0, ["1"])] * 2, entries=[restore])
        following = self.skill(self.a, "后继", [("blunt", 0, ["2"])])
        slot = self.slot([first, following], [])
        self.play()
        self.assertEqual(self.b.hp, 46)
        self.assertEqual(self.game.used_cards, [first, following])
        self.assertEqual(slot.get_content(1), [following])
        self.assertEqual(first.current_dice_index, 0)
        with redirect_stdout(io.StringIO()):
            self.game.finish_turn()
        self.assertEqual(self.players[0].cardspace.hand.content, [first])
        self.assertEqual(self.players[0].cardspace.draw.content, [following])

    def test_redirected_and_opposing_attacks_resolve_independently(self):
        target = self.character(self.players[1], "下一交锋")
        route = {"trigger": "before_dice_pair", "operation": {"op": "program", "code": [
            "$die", "$next_duel_target", "ROUTE_DIE_ATTACK"]}}
        first = self.skill(self.a, "改道", [("slash", 0, [route, "3"]), ("pierce", 0, ["1"])])
        second = self.skill(self.b, "反向攻击", [("blunt", 0, ["2"])])
        guard = self.skill(target, "下交锋防御", [("guard", 0, [])])
        self.slot([first], [second])
        self.slot([], [guard])
        events = self.play()
        self.assertEqual((self.a.hp, self.b.hp, target.hp), (48, 49, 47))
        self.assertFalse(any("on_dice_clash" in pair for pair in events))
        self.assertEqual(guard.current_dice_index, 1)
        self.assertEqual(sum(pair.count("logic_dice_hit") for pair in events), 3)

    def test_redirect_with_no_next_enemy_skips_guard_use_but_opposing_attack_still_hits(self):
        route = {"trigger": "before_dice_pair", "operation": {"op": "program", "code": [
            "$die", "$next_duel_target", "ROUTE_DIE_ATTACK"]}}
        guard_use = {"trigger": "on_dice_use", "operation": "Shield: 1"}
        self.slot([self.skill(self.a, "改道", [("slash", 0, [route, "3"])] * 2)],
                  [self.skill(self.b, "先守后攻", [("guard", 0, [guard_use]), ("slash", 0, ["2"])])])
        events = self.play()
        self.assertEqual(events.count(("on_clash_skip", "on_clash_skip")), 1)
        self.assertFalse(any(left == "before_dice_use" for left, _ in events))
        self.assertEqual(sum(right == "before_dice_use" for _, right in events), 1)
        self.assertEqual((self.a.hp, self.b.hp), (48, 50))

    def test_group_damage_and_delayed_status_share_the_original_primary(self):
        primary = self.character(self.players[1], "主目标")
        applied = []
        self.game.context.register_entries(self.a, [{
            "trigger": "AFTER DAMAGE", "subject": "source",
            "operation": lambda ctx: applied.append((ctx.event["target"], ctx.event["result"]))}])
        hit_bonus = {"trigger": "before_dice_hit", "operation": "Damage_add: 1"}
        group = {"trigger": "AFTER RESOLVE_HIT", "operation": {"op": "program", "damage_part": True, "code": [
            "$enemies", ["$target", 4, "$is_primary_target", [2, "ADD"], "WHEN", "normal", "slash", "DAMAGE",
                         "$self", "$target", "降级", 1, "QUEUE_STATUS"], "FOR_EACH_TARGET"]}}
        attacker = self.skill(self.a, "群攻", [("slash", 20, [hit_bonus, group])])
        self.slot([attacker], [self.skill(primary, "定位", [("guard", 0, [])])])
        events = self.play()
        self.assertEqual(applied, [(primary, 7), (self.b, 5)])
        self.assertEqual(sum(pair.count("logic_dice_hit") for pair in events), 1)
        with redirect_stdout(io.StringIO()):
            self.game.finish_turn()
            self.game.start_turn()
        self.assertEqual([member.statuses["降级"] for member in (primary, self.b)], [1, 1])

    def test_cancelled_group_deals_nothing_and_primary_death_does_not_end_next_group(self):
        primary = self.character(self.players[1], "主目标")
        primary.hp = 3
        self.game.context.register_entries(primary, [{
            "trigger": "BEFORE RESOLVE_HIT", "subject": "target", "operation": "cancel",
            "turn_limit": {"key": "cancel_one", "count": 1}}])
        group = {"trigger": "AFTER RESOLVE_HIT", "operation": {"op": "program", "damage_part": True, "code": [
            "$enemies", ["$target", 4, "normal", "slash", "DAMAGE"], "FOR_EACH_TARGET"]}}
        attacker = self.skill(self.a, "两次群攻", [("slash", 20, [group])] * 2)
        self.slot([attacker], [self.skill(primary, "定位", [("guard", 0, [])] * 2)])
        events = self.play()
        self.assertEqual(sum(pair.count("logic_dice_hit") for pair in events), 2)
        self.assertEqual((primary.hp, self.b.hp), (0, 46))

    def test_passives_only_trigger_skip(self):
        self.slot([self.skill(self.a, "架", [("guard", 0, ["3"])])],
                  [self.skill(self.b, "闪", [("evade", 0, ["3"])])])
        self.slot([], [self.skill(self.b, "防", [("block", 0, ["3"])])])
        with patch.object(Dice, "roll", side_effect=AssertionError("被动骰不应单独掷骰")):
            events = self.play()
        self.assertEqual(events.count(("on_clash_skip", "on_clash_skip")), 1)
        self.assertEqual(events.count((None, "on_clash_skip")), 1)
        self.assertFalse(any(node in ("before_dice_use", "on_dice_hit") for pair in events for node in pair))
        self.assertEqual((self.a.hp, self.b.hp), (50, 50))

    def test_unaffordable_card_does_not_hold_the_other_side(self):
        expensive = self.skill(self.a, "不可支付", [("slash", 0, ["10"])], cost=20)
        affordable = self.skill(self.b, "可支付", [("blunt", 0, ["3"])], cost=3)
        self.slot([expensive], [affordable])
        self.play()
        self.assertEqual(self.game.used_cards, [affordable])
        self.assertEqual((self.a.used_independent_cost, self.players[0].used_cost), (0, 0))
        self.assertEqual((self.b.used_independent_cost, self.players[1].used_cost), (1, 2))
        self.assertEqual((self.a.hp, self.b.hp), (47, 50))

    def test_death_does_not_skip_next_ally_in_the_same_slot(self):
        ally = self.character(self.players[1], "接手")
        self.b.hp = 1
        attacker = self.skill(self.a, "连击", [("blunt", 20, ["2"])] * 2)
        fallen = self.skill(self.b, "战败", [("slash", 0, [])])
        replacement = self.skill(ally, "接手技", [("block", 0, [])])
        self.slot([attacker], [fallen, replacement])
        self.play()
        self.assertEqual(ally.hp, 48)
        self.assertFalse(self.b.is_alive)
        self.assertIn(fallen, self.players[1].cardspace.out_of_combat.content)
        self.assertEqual(self.game.used_cards, [fallen, attacker, replacement])

    def test_draw_and_winning_defense_do_not_hit(self):
        self.slot([self.skill(self.a, "攻", [("slash", 0, ["3"])] * 2)],
                  [self.skill(self.b, "守", [("block", 0, ["3"]), ("block", 20, ["3"])])])
        with patch.object(self.game.rng, "randint", return_value=1):
            events = self.play()
        self.assertIn(("on_clash_draw", "on_clash_draw"), events)
        self.assertIn(("on_clash_lose", "on_clash_win"), events)
        self.assertEqual((self.a.hp, self.b.hp), (50, 50))

    def test_skill_appended_by_effect_joins_before_the_first_die(self):
        inserted = self.skill(self.b, "增援", [("pierce", 20, ["2"])])
        self.players[1].cardspace.out_of_combat.add_card(inserted)
        place = {"trigger": "on_skill_use",
                 "operation": lambda ctx: self.game.place_in_duel(2, inserted, 0)}
        opening = self.skill(self.a, "开局", [("slash", 0, ["1"])], entries=[place])
        self.slot([opening], [])
        self.game.cards_revealed = True
        events = self.play()
        self.assertIn(("on_clash_lose", "on_clash_win"), events)
        self.assertEqual((self.a.hp, self.b.hp), (48, 50))
        self.assertEqual(self.game.used_cards, [opening, inserted])

    def test_destroyed_die_stops_responding_on_the_same_tick(self):
        smash = {"trigger": "before_dice_use", "operation": {"op": "destroy", "target": "opponent_die"}}
        attacker = self.skill(self.b, "摧毁", [("pierce", 0, ["2", smash])])
        defender = self.skill(self.a, "消失", [("slash", 20, ["3"])])
        self.slot([defender], [attacker])
        events = self.play()
        self.assertNotIn(("before_dice_use", "before_dice_use"), events)
        self.assertFalse(any("on_dice_clash" in pair for pair in events))
        self.assertIn((None, "on_clash_win"), events)
        self.assertEqual((self.a.hp, self.b.hp), (48, 50))
        self.assertEqual(self.game.context.active_dice, {})

    def test_defender_losing_its_paired_opponent_wins_the_blank_round(self):
        negate = {"trigger": "before_dice_clash", "operation": {"op": "destroy", "target": "opponent_die"}}
        defender = self.skill(self.b, "消解", [("evade", 0, [negate])])
        attacker = self.skill(self.a, "斩", [("slash", 0, ["3"])])
        self.slot([attacker], [defender])
        with patch.object(Dice, "roll", side_effect=AssertionError("对手被摧毁后不应再拼点")):
            events = self.play()
        self.assertIn((None, "on_clash_win"), events)
        self.assertFalse(any("on_clash_skip" in pair or "on_clash_lose" in pair for pair in events))
        self.assertEqual((self.a.hp, self.b.hp), (50, 50))

    def test_duel_start_bleed_uses_initiative_and_ends_match_immediately(self):
        self.a.hp = self.b.hp = 1
        self.a.add_status("裂血", 3)
        self.b.add_status("裂血", 3)
        self.slot([self.skill(self.a, "左", [])], [self.skill(self.b, "右", [])])
        events = self.play()
        self.assertIs(self.game.first_player, self.players[1])
        self.assertEqual((self.a.hp, self.b.hp), (1, 0))
        self.assertIs(self.game.winner, self.players[0])
        self.assertFalse(any("before_skill_use" in pair for pair in events))

    def test_cancelling_shared_clash_does_not_dispatch_a_result(self):
        cancel = {"trigger": "BEFORE CLASH", "scope": "card", "operation": "cancel"}
        self.slot([self.skill(self.a, "取消拼点", [("slash", 20, ["3"])], entries=[cancel])],
                  [self.skill(self.b, "交锋", [("slash", 0, ["2"])])])
        events = self.play()
        self.assertIn(("on_dice_clash", "on_dice_clash"), events)
        self.assertIn(("after_dice_clash", "after_dice_clash"), events)
        self.assertFalse(any("on_clash_win" in pair or "on_dice_hit" in pair for pair in events))
        self.assertEqual((self.a.hp, self.b.hp), (50, 50))


class RoundPipelineTests(unittest.TestCase):
    def test_each_match_binds_its_own_nodes_and_interactive_eof_reaches_caller(self):
        def prompt(node):
            input("继续？")

        template = PipelineNode("decision", prompt, period_args={"marks": []})
        first_game, second_game = object(), object()
        first = Pipeline(first_game, [template])
        second = Pipeline(second_game, [template])
        self.assertIs(first.step_list[0].game, first_game)
        self.assertIs(second.step_list[0].game, second_game)
        self.assertIsNone(template.game)
        first.step_list[0].period_args["marks"].append("test")
        self.assertEqual(second.step_list[0].period_args["marks"], [])
        with patch("builtins.input", side_effect=EOFError), self.assertRaises(EOFError):
            first.next_step()
