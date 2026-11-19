import io
import random
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from models.card import Card, CardState
from models.character import Character
from player.player import Player


class PreRevealTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "先手"), Player(2, "后手")
        self.game = Game([self.left, self.right], rng=random.Random(8))
        self.game.first_player = self.left
        self.a = self.recruit(self.left, "甲")
        self.b = self.recruit(self.right, "乙")
        self.c = self.recruit(self.right, "丙")
        self.game.start_turn()
        self.phase = self.game.pre_reveal

    def recruit(self, player, name):
        actor = Character(dict(id=name, name=name, rank="NORMAL", max_hp=20, skills=[]), player)
        player.characters.append(actor)
        return actor

    def card(self, actor, name, *, attack=False, damage=1, **spec):
        dice = [dict(type="pierce", level=1, entries=[str(damage)])] if damage else []
        card = Card(actor.player, dict(id=name, name=name, cost=1, pre_reveal=attack, dice=dice, **spec), actor)
        actor.skills.append(card)
        actor.player.cardspace.hand.add_card(card)
        return card

    def resolve(self):
        self.assertEqual(self.phase.phase, "ready")
        self.phase.begin_resolution()
        for _ in range(1500):
            if not self.game.pipeline.in_duel_phase:
                return
            self.game.next_step()
        self.fail("开牌前结算未能结束")

    def test_three_attacks_two_intercepts_then_opposite_attack_count_only_four(self):
        attacks = [self.card(self.a, str(i), attack=True) for i in range(3)]
        my_melee = self.card(self.a, "普通手牌")
        blocks = [self.card(self.b, str(i)) for i in range(2)]
        counter = self.card(self.b, "反击", attack=True)
        self.a.used_duels = self.a.max_duels
        self.phase.start()
        self.assertEqual(self.phase.legal_cards(), attacks)
        self.assertIs(self.phase.actor, self.left)
        self.phase.declare_attack(attacks[0], character=self.b)
        self.assertFalse(self.phase.space.space[0].ready)
        self.assertIs(self.phase.actor, self.right)
        self.assertEqual(self.phase.legal_cards(), [*blocks, counter])
        self.phase.intercept(blocks[0])
        self.assertTrue(self.phase.space.space[0].ready)
        self.phase.declare_attack(attacks[1], character=self.c)
        self.phase.intercept(blocks[1])
        self.phase.declare_attack(attacks[2], character=self.c)
        self.phase.pass_intercept()
        self.assertIs(self.phase.actor, self.right)
        self.phase.declare_attack(counter, character=self.a)
        self.assertEqual(self.phase.legal_cards(), [my_melee])
        self.phase.pass_intercept()
        self.assertEqual(self.phase.phase, "ready")
        slots = self.phase.space.space
        self.assertEqual([s.attacking_side for s in slots], [1, 1, 1, 2])
        self.assertEqual([s.intercept_card for s in slots], [*blocks, None, None])
        self.assertTrue(all(slot.ready for slot in slots))
        self.assertFalse(self.game.used_cards)
        self.assertEqual(self.left.used_cost + self.a.used_independent_cost, 0)

    def test_attacker_can_continue_while_defender_weighs_earlier_cards(self):
        shots = [self.card(self.a, f"进攻 {i}", attack=True) for i in range(3)]
        defense = self.card(self.b, "迎击")
        self.card(self.c, "保留在手")
        self.phase.start()
        for card in shots[:2]:
            self.phase.declare_attack(card, character=self.c)
        self.assertEqual(self.phase.pending_for(self.right), [1, 2])
        self.assertCountEqual(self.phase.eligible_players(), [self.left, self.right])
        self.assertEqual(self.phase.attack_cards(self.left), [shots[2]])
        for number in (None, True, 0, 3):
            with self.assertRaises(ValueError):
                self.phase.intercept(defense, number)
        self.assertIn(defense, self.right.cardspace.hand.content)
        self.assertEqual(self.phase.pending_for(self.right), [1, 2])
        self.phase.intercept(defense, 2)
        self.phase.declare_attack(shots[2], character=self.b)
        self.assertEqual(self.phase.pending_for(self.right), [1, 3])
        with self.assertRaises(ValueError):
            self.phase.pass_intercept(2, self.right)
        with self.assertRaises(ValueError):
            self.phase.pass_intercept(1, self.left)
        self.phase.pass_intercept(3, self.right)
        self.phase.pass_intercept(1, self.right)
        self.assertEqual(self.phase.phase, "ready")
        self.assertEqual([s.attack_card for s in self.phase.space.space], shots)
        self.assertEqual([s.intercept_card for s in self.phase.space.space], [None, defense, None])

    def test_new_attacker_can_still_choose_which_earlier_attack_to_answer(self):
        feint = self.card(self.a, "佯攻", attack=True)
        pin = self.card(self.a, "牵制", attack=True)
        kept = self.card(self.a, "留下防守", attack=True)
        reply = self.card(self.b, "后手主动", attack=True)
        defense = self.card(self.c, "后手被动")
        self.card(self.b, "手牌")
        hidden = self.card(self.b, "常规扣牌", damage=0)
        self.game.place_in_duel(2, hidden, 0)
        self.phase.start()
        self.phase.declare_attack(feint, duel_index=0)
        self.phase.declare_attack(pin, duel_index=0)
        self.phase.end_attack(self.left)
        self.assertTrue(self.phase.can_attack(self.right))
        self.assertFalse(self.phase.can_attack(self.left))
        self.phase.declare_attack(reply, character=self.a)
        self.assertEqual(self.phase.pending_for(self.left), [3])
        self.assertEqual(self.phase.pending_for(self.right), [1, 2])
        self.phase.end_attack(self.right)
        self.assertIsNone(self.phase.attacker)
        with self.assertRaises(ValueError):
            self.phase.declare_attack(kept, character=self.b)
        with self.assertRaises(ValueError):
            self.phase.begin_resolution()
        self.phase.intercept(defense, 2)
        self.phase.intercept(kept, 3)
        self.phase.pass_intercept(1, self.right)
        self.assertEqual(self.phase.phase, "ready")
        self.assertIs(hidden.state, CardState.PLACED_FACE_DOWN)
        self.assertEqual(self.game.duelspace.space[0].get_content(2), [hidden])
        self.resolve()
        slots = self.phase.space.space
        self.assertEqual([s.pulled_card for s in slots], [hidden, None, None])
        self.assertEqual([s.intercept_card for s in slots], [None, defense, kept])

    def test_spending_last_interception_card_leaves_other_slots_open_for_explicit_pass(self):
        shots = [self.card(self.a, f"进攻 {i}", attack=True) for i in range(2)]
        only = self.card(self.b, "仅剩的手牌", attack=True)
        self.phase.start()
        for shot in shots:
            self.phase.declare_attack(shot, character=self.b)
        self.phase.intercept(only, 2)
        self.assertEqual([s.ready for s in self.phase.space.space], [False, True])
        self.assertFalse(self.phase.intercept_cards(self.right))
        self.phase.end_attack(self.left)
        self.phase.end_attack(self.right)
        self.assertEqual(self.phase.eligible_players(), [self.right])
        with self.assertRaises(ValueError):
            self.phase.begin_resolution()
        self.phase.pass_intercept(1, self.right)
        self.assertEqual(self.phase.phase, "ready")

    def test_empty_handed_defender_can_draw_on_later_declaration_and_intercept_earlier_attack(self):
        attacks = [self.card(self.a, f"进攻 {i}", attack=True) for i in range(2)]
        defense = self.card(self.b, "增援")
        zones = self.right.cardspace
        zones.hand.move_card_to(defense, zones.draw)
        self.game.context.register_entries(self.b, [{
            "trigger": "on_pre_reveal_play", "subject": "any",
            "operation": {"op": "program", "code": [
                "$self", "$target", "EQ", ["$player", 1, "DRAW"], "WHEN"]},
        }])
        self.phase.start()
        first = self.phase.declare_attack(attacks[0], character=self.c)
        self.assertFalse(first.ready)
        self.assertFalse(self.phase.intercept_cards(self.right))
        self.assertIn(self.right, self.phase.eligible_players())
        self.phase.declare_attack(attacks[1], character=self.b)
        self.assertEqual(self.phase.pending_for(self.right), [1, 2])
        self.assertEqual(self.phase.intercept_cards(self.right), [defense])
        self.phase.intercept(defense, 1)
        self.phase.pass_intercept(2, self.right)
        self.assertIs(first.intercept_card, defense)
        self.assertEqual(self.phase.phase, "ready")

    def test_actual_pipeline_pulls_only_unintercepted_target_and_uses_cards_once(self):
        bait = self.card(self.a, "佯攻", attack=True)
        pin = self.card(self.a, "牵制", attack=True)
        repeat = self.card(self.a, "追击", attack=True, damage=3)
        intercept = self.card(self.c, "拦截", damage=0)
        pulled = self.card(self.b, "被牵制", damage=0)
        untouched = self.card(self.c, "无人牵制", damage=0)
        self.game.place_in_duel(2, pulled, 0)
        self.game.place_in_duel(2, untouched, 1)
        schedule = self.game.pipeline
        schedule.current_step_index = next(i for i, n in enumerate(schedule.step_list) if n.id == "before_reveal") - 1
        self.enterContext(patch.object(self.game, "run_pre_reveal_declarations"))
        self.enterContext(patch("builtins.input", side_effect=AssertionError("已指定目标")))
        while self.game.next_step() != "logic_before_reveal_declarations":
            pass
        cursor = schedule.current_step_index
        for _ in range(2):
            self.assertEqual(self.game.next_step(), "wait_before_reveal_combat")
            self.assertEqual(schedule.current_step_index, cursor)
        feint = self.phase.declare_attack(bait, duel_index=1)
        self.assertEqual(self.game.next_step(), "wait_before_reveal_combat")
        self.assertEqual(schedule.current_step_index, cursor)
        self.phase.intercept(intercept)
        actual = self.phase.declare_attack(pin, duel_index=0)
        follow = self.phase.declare_attack(repeat, duel_index=0)
        self.phase.pass_intercept(2, self.right)
        self.phase.pass_intercept(3, self.right)
        self.assertIsNone(actual.pulled_card)
        self.assertIs(pulled.state, CardState.PLACED_FACE_DOWN)
        self.assertEqual(self.game.duelspace.space[0].get_content(2), [pulled])
        self.assertIsNone(feint.target_duel_index)
        self.assertEqual(self.game.next_step(), "logic_before_reveal_combat")
        while self.game.active_duelspace.current_duel_index == 0:
            self.assertIsNone(actual.pulled_card)
            self.assertIs(pulled.state, CardState.PLACED_FACE_DOWN)
            self.game.next_step()
        while self.game.next_step() != "logic_reveal":
            self.assertFalse(self.game.cards_revealed)
            self.assertIs(untouched.state, CardState.PLACED_FACE_DOWN)
        self.assertIs(actual.pulled_card, pulled)
        self.assertIsNone(follow.pulled_card)
        self.assertIs(follow.resolved_target, self.b)
        self.assertEqual((self.b.hp, self.c.hp), (16, 19))
        self.assertEqual(self.game.duelspace.space[0].get_content(2), [])
        self.assertEqual(self.game.duelspace.space[1].get_content(2), [untouched])
        self.assertEqual(self.game.duelspace.current_duel_index, 0)
        while self.game.next_step() != "before_turn_end":
            pass
        self.assertCountEqual(self.game.used_cards, [bait, pin, repeat, intercept, pulled, untouched])
        self.assertEqual(self.left.used_cost + self.a.used_independent_cost, 3)
        self.game.finish_turn()
        self.assertCountEqual(self.left.cardspace.draw.content, [bait, pin, repeat])
        self.assertCountEqual(self.right.cardspace.draw.content, [intercept, pulled, untouched])

    def test_direct_target_dies_no_automatic_retarget_or_orphan_interceptor(self):
        lethal = self.card(self.a, "致命", attack=True, damage=20, interceptable=False)
        follow = self.card(self.a, "落空", attack=True, damage=10)
        reply = self.card(self.b, "阵亡者的反击", attack=True, damage=10)
        my_block = self.card(self.a, "多余的拦截", damage=10)
        self.phase.start()
        self.phase.declare_attack(lethal, character=self.b)
        self.assertIs(self.phase.actor, self.left)
        self.phase.declare_attack(follow, character=self.b)
        self.phase.pass_intercept()
        self.phase.declare_attack(reply, character=self.a)
        self.phase.intercept(my_block)
        self.resolve()
        self.assertEqual((self.a.hp, self.b.hp, self.c.hp), (20, 0, 20))
        self.assertEqual(self.game.used_cards, [lethal])
        self.assertIn(reply, self.right.cardspace.out_of_combat.content)
        self.assertNotIn(reply, self.phase.space.space[-1].get_content(2))
        self.game.finish_turn()
        self.assertIn(my_block, self.left.cardspace.draw.content)

    def test_unknown_empty_position_and_dead_pulled_owner_do_not_hit_a_substitute(self):
        opener = self.card(self.a, "致命牵制", attack=True, damage=20)
        follow = self.card(self.a, "原主已死", attack=True, damage=9)
        empty = self.card(self.a, "从未有敌方卡", attack=True, damage=9)
        pulled = self.card(self.b, "守位", damage=0)
        left_only = self.card(self.a, "己方占位", damage=0)
        self.game.place_in_duel(2, pulled, 0)
        self.game.place_in_duel(1, left_only, 1)
        self.phase.start()
        self.phase.declare_attack(opener, duel_index=0)
        self.phase.declare_attack(follow, duel_index=0)
        self.phase.declare_attack(empty, duel_index=1)
        for number in (1, 2, 3):
            self.phase.pass_intercept(number, self.right)
        self.resolve()
        self.assertEqual((self.b.hp, self.c.hp), (0, 20))
        self.assertNotIn(follow, self.game.used_cards)
        self.assertNotIn(empty, self.game.used_cards)

    def test_refused_actions_keep_state_and_end_attack_keeps_later_interception_right(self):
        early = self.card(self.a, "留作拦截", attack=True)
        late = self.card(self.b, "后手进攻", attack=True)
        self.phase.start()
        for target in (dict(character=self.a), dict(duel_index=-1), dict(duel_index=0),
                       dict(character=self.b, duel_index=0), {}):
            with self.assertRaises(ValueError):
                self.phase.declare_attack(early, **target)
        with self.assertRaises(ValueError):
            self.phase.declare_attack(late, character=self.a)
        self.assertEqual(self.left.cardspace.hand.content, [early])
        self.assertFalse(self.phase.space.space)
        self.phase.end_attack()
        self.phase.declare_attack(late, character=self.a)
        self.assertEqual(self.phase.legal_cards(), [early])
        self.phase.intercept(early)
        self.assertEqual(self.phase.phase, "ready")
        self.assertEqual(len(self.phase.space.space), 1)

    def test_unaffordable_attack_still_pulls_defender_and_only_paid_skill_runs(self):
        attack = self.card(self.a, "付不起的牵制", attack=True, damage=9)
        defense = self.card(self.b, "反打", damage=2)
        self.game.place_in_duel(2, defense, 0)
        self.left.used_cost = self.left.max_cost
        self.a.used_independent_cost = self.a.independent_cost
        self.phase.start()
        slot = self.phase.declare_attack(attack, duel_index=0)
        self.phase.pass_intercept()
        self.resolve()
        self.assertIs(slot.pulled_card, defense)
        self.assertEqual((self.a.hp, self.b.hp), (18, 20))
        self.assertEqual(self.game.used_cards, [defense])
        self.assertEqual(self.game.duelspace.space[0].get_content(2), [])

    def test_pass_seals_slot_and_preserves_own_attack_right(self):
        opener = self.card(self.a, "先手", attack=True)
        melee = self.card(self.b, "放弃拦截的牌")
        counter = self.card(self.b, "后手", attack=True)
        self.phase.start()
        slot = self.phase.declare_attack(opener, character=self.b)
        self.phase.pass_intercept()
        self.assertTrue(slot.ready)
        self.assertIs(self.phase.actor, self.right)
        self.assertEqual(self.phase.phase, "attack")
        with self.assertRaises(ValueError):
            self.phase.intercept(melee)
        self.assertFalse(self.game.auto_place_in_duel(2, melee))
        self.assertFalse(self.game.place_in_duel(2, melee, 0))
        self.phase.declare_attack(counter, character=self.a)
        self.phase.pass_intercept()
        self.assertEqual(self.phase.phase, "ready")
        self.assertIsNone(slot.intercept_card)
        self.assertEqual(self.right.cardspace.hand.content, [melee])

    def test_card_pack_reads_declared_and_resolved_play_modes(self):
        def probe(trigger, key):
            return {"trigger": trigger, "operation": {"op": "program", "code": [
                "$card", key, "$play_mode", "SET_SKILL_STATE"]}}
        entries = [probe("on_pre_reveal_play", "declare"), probe("on_skill_use", "use")]
        active = self.card(self.a, "主动", attack=True, entries=entries)
        pin = self.card(self.a, "主动牵制", attack=True, entries=entries)
        passive = self.card(self.b, "被动", entries=entries)
        pulled = self.card(self.c, "牵制", entries=entries)
        self.game.place_in_duel(2, pulled, 0)
        self.phase.start()
        self.phase.declare_attack(active, character=self.b)
        self.phase.intercept(passive)
        self.phase.declare_attack(pin, duel_index=0)
        self.phase.pass_intercept()
        self.assertEqual(active.use_state["declare"], "active")
        self.assertEqual(passive.use_state["declare"], "passive")
        self.assertEqual(pulled.use_state, {})
        self.resolve()
        self.assertEqual([c.use_state["use"] for c in (active, passive, pulled)], ["active", "passive", "pulled"])
        self.assertNotIn("declare", pulled.use_state)

    def test_routed_die_in_last_pre_reveal_duel_cannot_peek_into_regular_duels(self):
        route = {"trigger": "before_dice_pair", "operation": {"op": "program", "code": [
            "$die", "$next_duel_target", "ROUTE_DIE_ATTACK"]}}
        attack = self.card(self.a, "改打下一交锋", attack=True)
        attack.dice[0]["entries"].insert(0, route)
        hidden = self.card(self.b, "常规仍扣置", damage=0)
        self.game.place_in_duel(2, hidden, 0)
        self.phase.start()
        self.phase.declare_attack(attack, character=self.c)
        self.phase.pass_intercept()
        self.resolve()
        self.assertIs(hidden.state, CardState.PLACED_FACE_DOWN)
        self.assertEqual((self.b.hp, self.c.hp), (20, 20))
        die = attack.instantiated_dice[0]
        self.assertTrue(die.attack_redirected)
        self.assertIsNone(die.attack_target)

    def test_explicit_card_effect_can_still_insert_a_skill_during_resolution(self):
        reserve = self.card(self.a, "增援", damage=2)
        self.left.cardspace.hand.move_card_to(reserve, self.left.cardspace.out_of_combat)
        opener = self.card(self.a, "呼叫增援", attack=True, entries=[{
            "trigger": "on_skill_use", "operation": {"op": "place_skill", "card_id": reserve.id}
        }])
        self.phase.start()
        slot = self.phase.declare_attack(opener, character=self.b)
        self.phase.pass_intercept()
        self.assertTrue(slot.ready)
        self.resolve()
        self.assertEqual(self.game.used_cards, [opener, reserve])
        self.assertEqual(self.b.hp, 17)
        self.assertEqual(self.a.used_duels, 0)
        self.assertFalse(self.game.duelspace.space)
