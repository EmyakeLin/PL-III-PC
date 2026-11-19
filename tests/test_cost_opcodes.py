import io
import unittest
from contextlib import redirect_stdout

from game import Game
from models.character import Character
from models.opcode import OpCode
from player.player import Player


class CostOpcodeTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right])
        self.game.first_player = self.left
        self.ctx = self.game.context
        self.attacker = self.add_character(self.left, "先锋")
        self.defender = self.add_character(self.right, "守卫")

    def add_character(self, player, name):
        skills = [
            dict(id=f"{name}-{cost}", name=f"{name}-{cost}", cost=cost,
                 dice=[dict(type="slash", level=1, entries=["2"])])
            for cost in (3, 4, 0)
        ]
        char = Character(dict(id=name, name=name, rank="NORMAL", max_hp=12, skills=skills), player)
        player.characters.append(char)
        char.init_cards()
        char.setup_deck()
        return char

    def listen(self, owner, trigger, operation):
        self.ctx.register_entries(owner, [dict(trigger=trigger, operation=operation)])

    def test_turn_cost_add_can_exceed_refill_and_preserves_earlier_payments(self):
        self.game.start_turn()
        self.assertTrue(self.left.pay_skill_cost(self.attacker.skills[0]))
        self.assertEqual((self.left.available_cost, self.attacker.available_cost), (3, 0))
        previous_spend = self.left.used_cost
        self.ctx.eval_block([self.left, 4, OpCode.TURN_COST_ADD, self.attacker, 2, OpCode.TURN_COST_ADD])
        self.assertEqual((self.left.available_cost, self.attacker.available_cost), (7, 2))
        self.assertEqual((self.left.max_cost, self.left.used_cost), (5, previous_spend))
        self.assertTrue(self.left.pay_skill_cost(self.attacker.skills[1]))
        self.assertEqual((self.left.available_cost, self.attacker.available_cost), (5, 0))
        self.game.finish_turn()
        self.assertEqual((self.left.available_cost, self.attacker.available_cost), (0, 0))
        self.game.start_turn()
        self.assertEqual((self.left.available_cost, self.attacker.available_cost), (5, 1))

    def test_turn_start_and_end_emit_resets_for_each_players_own_team(self):
        teammate = self.add_character(self.left, "队友")
        self.game.gamerule.MAX_BASIC_COST = 4
        self.game.gamerule.CHAR_INDEPENDENT_COST = 2
        observations = {}
        for char in (self.attacker, teammate, self.defender):
            self.assertEqual((char.player.max_cost, char.independent_cost), (0, 0))
            observations[char] = []

            def record(ctx, owner=char):
                player = ctx.event["player"]
                self.assertIs(player, owner.player)
                self.assertEqual(ctx.event["side"], player.side)
                observations[owner].append((player.max_cost, player.used_cost,
                                            owner.independent_cost, owner.used_independent_cost))

            self.listen(char, "AFTER RESET_COST", record)
        self.game.start_turn()
        for char in observations:
            self.assertTrue(char.player.pay_skill_cost(char.skills[0]))
        self.game.finish_turn()
        for states in observations.values():
            self.assertEqual(states, [(4, 0, 2, 0), (0, 0, 0, 0)])

    def test_payment_returns_atomic_result_and_only_triggers_for_the_payer(self):
        teammate = self.add_character(self.left, "队友")
        first, expensive, free = self.attacker.skills
        receipts = []

        def receipt(ctx):
            event = ctx.event
            receipts.append((event["side"], event["source"], event["card"], event["result"],
                             self.attacker.used_independent_cost, self.left.used_cost))

        self.listen(self.attacker, "AFTER PAY_COST", receipt)

        def wrong_owner(ctx):
            self.fail("其他角色响应了付款角色的费用事件")

        for char in (teammate, self.defender):
            self.listen(char, "AFTER PAY_COST", wrong_owner)
        self.game.start_turn()
        self.ctx.eval_block([self.left, 1, 2, OpCode.RESET_COST])
        self.ctx.push("stack marker")
        self.assertIs(self.ctx.eval_block([expensive, expensive.cost, OpCode.PAY_COST]), False)
        self.assertIs(self.ctx.eval_block([first, first.cost, OpCode.PAY_COST]), True)
        self.assertIs(self.ctx.eval_block([free, free.cost, OpCode.PAY_COST]), True)
        self.assertEqual(self.ctx.stack, ["stack marker"])
        self.assertEqual(receipts, [
            (1, self.attacker, expensive, False, 0, 0),
            (1, self.attacker, first, True, 2, 1),
            (1, self.attacker, free, True, 2, 1),
        ])
        self.assertEqual((teammate.used_independent_cost, self.right.used_cost), (0, 0))

    def test_cancelled_payment_skips_skill_and_opponent_still_hits(self):
        mine, theirs = self.attacker.skills[0], self.defender.skills[0]
        charges = []
        self.listen(self.attacker, "BEFORE PAY_COST", "Cancel")
        self.listen(self.attacker, "AFTER PAY_COST", lambda ctx: self.fail("取消的支付仍进入 AFTER"))
        self.listen(self.defender, "AFTER PAY_COST", lambda ctx: charges.append(ctx.event["card"]))
        self.game.start_turn()
        for card in (mine, theirs):
            self.assertTrue(self.game.auto_place_in_duel(card.player.side, card))
        self.game.reveal_cards()
        self.assertEqual(charges, [])
        self.game.pipeline.start_duel_combat()
        for _ in range(200):
            if not self.game.pipeline.in_duel_phase:
                break
            self.game.next_step()
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertEqual(charges, [theirs])
        self.assertEqual(self.game.used_cards, [theirs])
        self.assertEqual((self.attacker.hp, self.defender.hp), (10, 12))
        self.assertEqual((self.attacker.used_independent_cost, self.left.used_cost), (0, 0))
        self.assertEqual((self.defender.used_independent_cost, self.right.used_cost), (1, 2))

    def test_before_hook_discounts_this_payment_without_changing_printed_cost(self):
        self.game.start_turn()
        card = self.attacker.skills[0]

        self.listen(card, "BEFORE PAY_COST", [2, OpCode.SUB])
        receipts = []

        def receipt(ctx):
            event = ctx.event
            receipts.append((event["amount"], event["personal_spent"], event["common_spent"]))

        self.listen(card, "AFTER PAY_COST", receipt)
        self.assertTrue(self.left.pay_skill_cost(card))
        self.assertEqual((self.attacker.used_independent_cost, self.left.used_cost), (1, 0))
        self.assertEqual(receipts, [(1, 1, 0)])
        self.assertEqual(card.cost, 3)
        self.assertEqual(self.ctx.stack, [])

    def test_reset_cancellation_preserves_spent_and_available_cost_only_on_own_side(self):
        self.game.start_turn()
        for actor in (self.attacker, self.defender):
            self.assertTrue(actor.player.pay_skill_cost(actor.skills[0]))
        self.listen(self.attacker, "BEFORE RESET_COST", "cancel")
        self.game.finish_turn()
        self.assertEqual((self.left.max_cost, self.left.used_cost), (5, 2))
        self.assertEqual((self.attacker.independent_cost, self.attacker.used_independent_cost), (1, 1))
        self.assertEqual((self.right.max_cost, self.right.used_cost), (0, 0))
        self.assertEqual((self.defender.independent_cost, self.defender.used_independent_cost), (0, 0))

    def test_destroying_card_in_before_payment_prevents_debit(self):
        self.game.start_turn()
        card = self.attacker.skills[0]
        self.listen(card, "BEFORE PAY_COST", {"op": "destroy", "target": "card"})
        self.assertFalse(self.left.pay_skill_cost(card))
        self.assertTrue(card.destroyed)
        self.assertEqual((self.attacker.used_independent_cost, self.left.used_cost), (0, 0))

    def test_conditional_program_can_cancel_the_pending_payment(self):
        self.game.start_turn()
        card = self.attacker.skills[0]
        self.listen(card, "BEFORE PAY_COST",
                    {"op": "program", "code": ["$full_hp", [{"op": "cancel"}], [2, "SUB"], "IF_ELSE"]})
        self.assertFalse(self.left.pay_skill_cost(card))
        self.assertEqual(self.ctx.stack, [])
        self.attacker.hp -= 1
        self.assertTrue(self.left.pay_skill_cost(card))
        self.assertEqual((self.attacker.used_independent_cost, self.left.used_cost), (1, 0))

    def test_first_turn_grant_is_interceptable_and_runs_in_initiative_order(self):
        self.game.first_player = self.right
        order = []
        for char in (self.attacker, self.defender):
            self.listen(char, "BEFORE RESET_COST", lambda ctx: order.append(ctx.event["side"]))
        self.listen(self.defender, "BEFORE RESET_COST", "Cancel")
        self.game.start_turn()
        self.assertEqual(order, [self.right.side, self.left.side])
        self.assertEqual((self.right.max_cost, self.defender.independent_cost), (0, 0))
        self.assertEqual((self.left.max_cost, self.attacker.independent_cost), (5, 1))
