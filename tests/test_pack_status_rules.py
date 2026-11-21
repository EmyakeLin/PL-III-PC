import io
import unittest
from contextlib import redirect_stdout

from displayer import Displayer
from game import Game
from models.character import Character
from models.opcode import OpCode
from player.player import Player


class PackStatusRules(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        left, right = Player(1, "甲方"), Player(2, "乙方")
        self.game = Game([left, right])
        self.rules = {
            "刻印": {"cap": 12, "overflow_batch": {"threshold": 6, "event": "on_mark_lock", "reduce_to": 6}},
            "加成来源": {"requires_status": "资源", "sustain": {"强壮": 2}},
            "限用": {"restrict_highest_hand_cost": True},
        }
        skills = [dict(id=name, name=name, cost=price, dice=[])
                  for name, price in (("甲", 4), ("乙", 4), ("丙", 3))]
        self.owner = Character(dict(id="a", name="甲", rank="NORMAL", max_hp=6, skills=skills,
                                    status_rules=self.rules, turn_end_statuses=["限用"]), left)
        self.other = Character(dict(id="b", name="乙", rank="NORMAL", max_hp=6, skills=skills), right)
        left.characters.append(self.owner)
        right.characters.append(self.other)
        self.game.first_player = left
        self.owner.init_cards()
        self.other.init_cards()

    def test_batch_freezes_targets_before_dispatch_and_reduces_after_all_passives(self):
        observed = []
        def listen(ctx):
            observed.append(tuple((c, c.statuses["刻印"]) for c in ctx.event["targets"]))
            for c in ctx.event["targets"]:
                c.add_status("刻印", 2)
        for actor in (self.owner, self.other):
            self.game.context.register_entries(actor, [{"trigger": "on_mark_lock", "operation": listen}])
        self.other.add_status("刻印", 11)
        self.other.add_status("刻印", 4)
        self.assertEqual(self.other.status_overflow, {"刻印": 3})
        self.game.finish_turn()
        self.assertEqual(observed, [])
        self.other.add_status("刻印", 3)
        self.owner.add_status("刻印", 30)
        self.game.context.dispatch_pipeline("before_turn_end")
        self.game.finish_turn()
        self.assertEqual(observed, [((self.owner, 12), (self.other, 12))] * 2)
        for actor in (self.owner, self.other):
            self.assertEqual((actor.statuses["刻印"], actor.status_overflow), (6, {}))

    def test_no_overflow_until_effective_delta_passes_cap(self):
        receipts = []
        ctx = self.game.context
        ctx.register_entries(self.other, [
            {"trigger": "BEFORE STATUS", "when": {"status": "刻印", "amount_at_least": 1},
             "operation": {"op": "program", "code": [1, "SUB"]}},
            {"trigger": "AFTER STATUS", "when": {"status": "刻印"},
             "operation": lambda vm: receipts.append((vm.event["previous_stacks"], vm.event["actual_delta"],
                                                      vm.event["status_overflow"]))},
        ])
        self.other.add_status("刻印", 12)
        self.other.add_status("刻印", 4)
        self.assertEqual(receipts, [(0, 11, 0), (11, 1, 2)])
        self.assertEqual(self.other.status_overflow, {"刻印": 2})

    def test_sustained_and_ordinary_stacks_have_independent_lifetimes(self):
        self.owner.add_status("加成来源", 1)
        self.assertNotIn("强壮", self.owner.statuses)
        self.owner.add_status("资源", 3)
        self.owner.add_status("强壮", 1)
        self.owner.add_status("加成来源", 1)
        self.assertEqual(self.owner.statuses["强壮"], 3)
        self.game.finish_turn()
        self.assertEqual(self.owner.statuses["强壮"], 2)
        self.owner.add_status("强壮", 3)
        self.game.context.eval_block([self.owner, "资源", 2, OpCode.SPEND_STATUS])
        self.assertEqual(self.owner.statuses["强壮"], 5)
        self.game.context.eval_block([self.owner, "资源", 3, OpCode.SPEND_STATUS])
        self.assertEqual(self.owner.statuses, {"强壮": 3})
        self.owner.add_status("资源", 1)
        self.assertNotIn("加成来源", self.owner.statuses)

    def test_restriction_keeps_hand_tie_order_and_protects_all_payment_modes(self):
        hand = self.owner.player.cardspace.hand
        first, second, cheap = self.owner.skills
        for card in (second, first, cheap):
            hand.add_card(card)
        self.game.start_turn()
        self.owner.add_status("限用", 1)
        self.assertTrue(self.owner.skill_restricted(second))
        self.assertFalse(self.owner.skill_restricted(first))
        self.assertTrue(self.game.place_in_duel(self.owner.player.side, second, 0))
        second.use_state["cost_prepaid"] = True
        self.assertFalse(self.owner.player.pay_skill_cost(second))
        self.assertEqual((self.owner.used_independent_cost, self.owner.player.used_cost), (0, 0))
        self.assertTrue(self.owner.skill_restricted(first))
        self.owner.clear_status("限用")
        self.assertTrue(self.owner.player.pay_skill_cost(second))

    def test_next_turn_cost_reductions_floor_replenishment_at_zero(self):
        self.game.context.eval_block([self.owner.player, -8, OpCode.NEXT_TURN_COST])
        self.game.start_turn()
        self.assertEqual(self.owner.player.available_cost, 0)
        self.assertEqual(self.owner.available_cost, 1)

    def test_public_overflow_and_private_hand_restrictions(self):
        for card in self.owner.skills:
            self.owner.player.cardspace.hand.add_card(card)
        self.owner.add_status("限用", 1)
        self.owner.add_status("刻印", 17)
        self.assertIn("刻印溢出 5/6", self.owner.combat_summary())
        for viewer in (None, 1, 2):
            frame = Displayer(self.game, viewer_side=viewer).snapshot()["players"][0]
            self.assertEqual(frame["characters"][0]["status_overflow"], {"刻印": {"amount": 5, "threshold": 6}})
            if viewer == 1:
                self.assertEqual([card["use_restricted"] for card in frame["hand"]], [True, False, False])
            else:
                self.assertIsNone(frame["hand"])
