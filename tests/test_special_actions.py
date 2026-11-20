import io
import unittest
from contextlib import redirect_stdout

from game import Game
from models.card import Card, CardState
from models.character import Character
from models.special_actions import SpecialAction
from player.player import Player


class SpecialActionsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right])
        self.game.first_player = self.left
        self.a = self.actor(self.left, "甲一")
        self.b = self.actor(self.right, "乙一")
        self.game.start_turn()
        self.actions = self.game.special

    def actor(self, player, name):
        actor = Character(dict(id=name, name=name, rank="NORMAL", max_hp=12, skills=[]), player)
        player.characters.append(actor)
        return actor

    def hand(self, owner, name, **data):
        card = Card(owner.player, dict(id=name, name=name, cost=1, dice=[], **data), owner)
        owner.skills.append(card)
        owner.player.cardspace.hand.add_card(card)
        return card

    def test_first_allied_empty_slot_and_cancelled_permission(self):
        other = self.hand(self.b, "敌方扣牌")
        self.game.place_in_duel(2, other, 0)
        new = self.hand(self.a, "补位")
        self.a.add_status("置卡机会", 1)
        choice = SpecialAction("place", new, duel_index=0)
        self.assertIn(choice, self.actions.options(self.left))
        guard, = self.game.context.register_entries(self.a, [dict(trigger="BEFORE PLACE", operation="Cancel")])
        self.assertFalse(self.actions.apply(self.left, choice))
        self.assertEqual(self.a.statuses["置卡机会"], 1)
        self.assertEqual(self.a.used_duels, 0)
        self.assertIn(new, self.left.cardspace.hand.content)
        self.game.context.entries.remove(guard)
        self.assertTrue(self.actions.apply(self.left, choice))
        self.assertEqual(self.game.duelspace.space[0].get_content(1), [new])
        self.assertEqual(self.game.duelspace.space[0].get_content(2), [other])
        self.assertIs(new.state, CardState.PLACED_FACE_DOWN)
        self.assertNotIn("置卡机会", self.a.statuses)
        self.assertEqual(self.a.used_duels, self.a.max_duels)
        with self.assertRaises(ValueError):
            self.actions.apply(self.left, choice)

    def test_full_character_cannot_spend_an_opportunity_or_use_printed_placement(self):
        ordinary = self.hand(self.a, "常规置卡")
        granted = self.hand(self.a, "机会补位")
        printed = self.hand(self.a, "两种打出方式", anytime_play=["place", "attack"])
        self.a.add_status("置卡机会", 1)
        self.assertTrue(self.game.auto_place_in_duel(1, ordinary))
        ally = self.actor(self.left, "队友")
        ally_card = self.hand(ally, "队友补位", anytime_play=["place"])
        choices = self.actions.options(self.left)
        self.assertEqual([action.card for action in choices if action.kind == "place"], [ally_card])
        self.assertIn(SpecialAction("attack", printed, character=self.b), choices)
        for card in (granted, printed):
            with self.assertRaises(ValueError):
                self.actions.apply(self.left, SpecialAction("place", card, duel_index=1))
            self.assertFalse(self.game.place_in_duel(1, card, 1, special=True))
        self.assertEqual(self.a.statuses["置卡机会"], 1)
        self.assertEqual(self.left.cardspace.hand.content, [granted, printed, ally_card])
        self.assertEqual(len(self.game.duelspace.space), 1)
        self.assertEqual(self.a.used_duels, self.a.max_duels)
        self.assertEqual(ally.used_duels, 0)

    def test_printed_special_placement_uses_quota_without_spending_the_optional_status(self):
        printed = self.hand(self.a, "随时补位", anytime_play=["place"])
        ordinary = self.hand(self.a, "常规置卡")
        self.a.add_status("置卡机会", 1)
        self.assertTrue(self.actions.apply(self.left, SpecialAction("place", printed, duel_index=0)))
        self.assertEqual(self.a.used_duels, self.a.max_duels)
        self.assertEqual(self.a.statuses["置卡机会"], 1)
        self.assertFalse(self.game.auto_place_in_duel(1, ordinary))

    def test_placement_before_initiative_stays_charged_after_turn_start(self):
        self.game.finish_turn()
        early = self.hand(self.a, "抽牌后补位", anytime_play=["place"])
        regular = self.hand(self.a, "稍后置卡")
        self.assertEqual(self.game.next_step(), "before_turn_start")
        self.assertEqual(self.game.next_step(), "logic_draw_cards")
        self.actions.apply(self.left, SpecialAction("place", early, duel_index=0))
        self.assertEqual(self.game.next_step(), "logic_resolve_speed")
        self.assertEqual(self.game.next_step(), "logic_turn_start")
        self.assertEqual(self.a.used_duels, 1)
        self.assertFalse(self.game.auto_place_in_duel(1, regular))
        self.game.finish_turn()
        self.assertEqual(self.a.used_duels, 0)

    def test_swap_in_place_preserves_hand_size_and_hidden_face(self):
        old = self.hand(self.a, "原牌")
        new = self.hand(self.a, "换入", anytime_replace=True)
        self.game.place_in_duel(1, old, 0)
        ally = self.actor(self.left, "甲二")
        wrong = self.hand(ally, "队友牌")
        self.game.place_in_duel(1, wrong, 1)
        counts = []
        self.game.context.register_entries(self.a, [dict(trigger="on_hand_changed",
            operation=lambda ctx: counts.append(ctx.event["hand_count"]))])
        self.assertNotIn(SpecialAction("replace", new, wrong), self.actions.options(self.left))
        self.assertTrue(self.actions.apply(self.left, SpecialAction("replace", new, old)))
        self.assertEqual(counts, [])
        self.assertEqual(self.left.cardspace.hand.content, [old])
        self.assertIs(new.state, CardState.PLACED_FACE_DOWN)
        self.assertEqual(self.game.duelspace.space[0].get_content(1), [new])
        self.assertEqual(self.a.used_independent_cost, 0)

    def test_off_turn_anytime_attack_preserves_number_and_original_attack_right(self):
        first = self.hand(self.a, "先发", pre_reveal=True)
        new = self.hand(self.b, "随时，可拦", anytime_play=["attack"], interceptable=True)
        intercept = self.hand(self.a, "迎击")
        phase = self.game.pre_reveal
        phase.start()
        phase.declare_attack(first, character=self.b)
        self.actions.apply(self.right, SpecialAction("attack", new, character=self.a))
        self.assertEqual(phase.pending_for(self.right), [1])
        self.assertEqual(phase.pending_for(self.left), [])
        self.assertIs(self.actions.pending_attack.attack_card, new)
        self.actions.apply(self.left, SpecialAction("intercept", intercept, response_number=1))
        while self.game.pipeline.in_duel_phase:
            self.game.next_step()
        phase.pass_intercept(1, self.right)
        self.assertEqual(phase.phase, "ready")

    def test_same_unmarked_anytime_skill_invites_interception_only_in_pre_reveal_series(self):
        first = self.hand(self.a, "开牌前进攻", anytime_play=["attack"])
        second = self.hand(self.a, "场内进攻", anytime_play=["attack"])
        defender = self.hand(self.b, "迎击")
        phase = self.game.pre_reveal
        phase.start()
        self.actions.apply(self.left, SpecialAction("attack", first, character=self.b))
        self.assertEqual(phase.pending_for(self.right), [1])
        phase.intercept(defender, 1)
        phase.end_attack(self.left)
        phase.begin_resolution()
        while self.game.pipeline.in_duel_phase:
            self.game.next_step()
        self.game.reveal_cards()
        self.actions.apply(self.left, SpecialAction("attack", second, character=self.b))
        self.assertIsNone(self.actions.pending_attack)
        self.assertTrue(self.actions.duels[-1].ready)
        with self.assertRaises(ValueError):
            self.actions.apply(self.right, SpecialAction("pass_intercept", response_number=1))
        while self.game.pipeline.in_duel_phase:
            self.game.next_step()
        self.assertEqual(self.game.used_cards.count(second), 1)

    def test_several_pending_attacks_keep_swaps_and_resolve_in_declaration_order(self):
        original = self.hand(self.a, "扣牌")
        swap = self.hand(self.a, "候补", anytime_replace=True)
        attacks = [self.hand(self.a, name, anytime_play=["attack"], interceptable=True)
                   for name in ("先打", "后打")]
        block = self.hand(self.b, "唯一迎击牌")
        self.game.place_in_duel(1, original, 0)
        for card in attacks:
            self.actions.apply(self.left, SpecialAction("attack", card, character=self.b))
        self.actions.apply(self.left, SpecialAction("replace", swap, original))
        self.actions.apply(self.right, SpecialAction("intercept", block, response_number=2))
        self.assertEqual(self.actions.pending_attacks, self.actions.duels[:1])
        self.assertEqual(self.game.next_step(), "wait_special_intercept")
        self.assertFalse(self.game.used_cards)
        self.actions.apply(self.right, SpecialAction("pass_intercept", response_number=1))
        while self.game.pipeline.in_duel_phase:
            self.game.next_step()
        self.assertEqual(self.game.used_cards, [attacks[0], attacks[1], block])

    def test_custom_anytime_text_is_pack_owned_and_leaves_no_duplicate(self):
        trick = self.hand(self.a, "按词条打出", anytime_play=["custom"], entries=[{
            "trigger": "on_anytime_play", "operation": {"op": "program", "code": [
                "$self", "normal", 2, "SHIELD", "$card", "out_of_combat", "MOVE_CARD"]}}])
        self.assertTrue(self.actions.apply(self.left, SpecialAction("custom", trick)))
        self.assertEqual(self.a.shield, 2)
        self.assertEqual(self.left.cardspace.out_of_combat.content, [trick])
        self.assertFalse(self.left.cardspace.delayed_discard.content)
        self.assertFalse(self.left.cardspace.hand.content)

    def test_separate_instant_attacks_use_public_numbers_for_first_duel_effects(self):
        numbers = []
        self.game.context.register_entries(self.a, [dict(trigger="on_skill_use",
            operation=lambda ctx: numbers.append(self.game.duel_position()[1] + 1))])
        for name in ("一", "二"):
            attack = self.hand(self.a, name, anytime_play=["attack"], interceptable=False)
            self.actions.apply(self.left, SpecialAction("attack", attack, character=self.b))
            while self.game.pipeline.in_duel_phase:
                self.game.next_step()
        self.assertEqual(numbers, [1, 2])

    def test_extra_card_placed_after_last_regular_slot_is_used_before_cleanup(self):
        late = self.hand(self.a, "收尾", anytime_play=["place"])
        self.game.reveal_cards()
        steps = self.game.pipeline.step_list
        self.game.pipeline.current_step_index = next(i for i, n in enumerate(steps) if n.id == "before_turn_end")
        self.actions.apply(self.left, SpecialAction("place", late, duel_index=0))
        self.assertIs(late.state, CardState.PLACED_FACE_UP)
        used = []
        self.game.context.register_entries(self.a, [dict(trigger="on_skill_use",
            operation=lambda ctx: used.append(ctx.event["card"]))])
        for _ in range(100):
            result = self.game.next_step()
            if result == "logic_turn_end":
                break
        self.assertEqual(result, "logic_turn_end")
        self.assertEqual(used, [late])
        self.assertFalse(self.game.used_cards)
        self.assertEqual(self.left.cardspace.draw.content, [late])
        self.assertEqual(self.actions.options(self.left), [])
