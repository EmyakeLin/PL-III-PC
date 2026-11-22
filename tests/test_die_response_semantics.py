import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from context.context import Context
from models.card import Card
from models.character import Character
from models.dice import Dice
from models.die_response import SkillDieTemplate
from models.opcode import OpCode
from pipeline.pipeline import BEFORE_ONE_SIDED_ATTACK, CombatFrame, Pipeline


class DieResponseTests(unittest.TestCase):
    def setUp(self):
        self.game = SimpleNamespace(turn_number=3, card_serial=0, resolving_duel=None, status_entries={}, status_rules={},
                                    ability_rules={}, turn_end_statuses=set())
        self.game.context = Context(game=self.game)
        self.game.init_dice = lambda data: Dice(data, self.game)
        self.game.pipeline = self.pipeline = Pipeline(self.game)
        self.game.players = []
        for side in ("attacker", "defender"):
            player = SimpleNamespace(side=side, game=self.game, register_faction_passives=lambda actor: None)
            player.characters = [Character(dict(id=side, name=side, rank="ELITE", max_hp=12, skills=[]), player)]
            self.game.players.append(player)
        self.attacker, self.holder = [p.characters[0] for p in self.game.players]
        self.frame = CombatFrame(SimpleNamespace(game=self.game), self.game.players, interrupt=False)
        self.pipeline._frames.append(self.frame)
        self.attack = self.frame.sides["attacker"]
        self.attack.card = self.card(self.attacker, [dict(type="slash", level=1)])
        self.attack.die = self.attack.card.get_current_die(self.game, register=False)
        self.attack.target = self.holder

    def card(self, actor, dice):
        return Card(actor.player, dict(id="fixture", name="测试用技能", cost=0, dice=dice), actor)

    def grant(self, card, *, position=1, count=2, trigger=BEFORE_ONE_SIDED_ATTACK,
              deadline=3, spend_on="use", cost=1):
        return self.game.context.eval_block([self.holder, card, position, OpCode.CAPTURE_SKILL_DIE,
                                             count, trigger, deadline, spend_on, cost, OpCode.GRANT_DIE_RESPONSE])

    def test_heck_printed_entry_saves_first_die_and_consumes_one_per_actual_clash(self):
        path = Path(__file__).resolve().parents[1] / "_packs" / "plan_b_heck.json"
        skills = json.loads(path.read_text(encoding="utf-8"))["characters"][0]["skills"]
        data = next(skill for skill in skills if skill["id"] == "heck_burning_slash")
        card = Card(self.holder.player, data, self.holder)
        self.holder.statuses["凝聚"] = 2
        self.game.context.dispatch_pipeline("on_skill_use", card=card, source=self.holder, side="defender")
        self.assertEqual(len(self.holder.reserved_dice), 1)
        response, = self.holder.reserved_dice
        self.assertEqual((response.remaining, response.through_turn, response.template.position), (2, 3, 1))
        self.holder.statuses["凝聚"] = 0
        self.assertEqual(self.pipeline._pending_response_die(self.attack).position, 1)
        self.assertFalse(self.pipeline._pending_response_die(self.attack).entries_registered)
        self.assertEqual(response.remaining, 2)
        previous_defender = self.frame.sides["defender"]

        def inspect_clash(pipes):
            reply = next(pipe for pipe in pipes if pipe.is_response)
            self.assertIs(self.frame.active_cards["defender"], reply.card)
            self.assertIs(self.frame.pair.dice_dict["defender"], reply.die)
            self.assertTrue(reply.die.entries_registered)
            self.assertIsNot(reply.card, card)
            self.assertIs(self.attack.opposing_card, reply.card)
            return iter(())

        with patch.object(self.pipeline, "_run_to", return_value=()), patch.object(self.pipeline, "_clash", inspect_clash):
            for remaining in (1, 0):
                self.assertEqual(list(self.pipeline._contest_solo(self.attack, self.holder)), [])
                self.assertEqual(response.remaining, remaining)
                self.assertIs(self.frame.sides["defender"], previous_defender)
                self.assertIsNone(self.attack.opposing_card)
        self.assertIsNone(self.pipeline._pending_response_die(self.attack))
        self.assertEqual(card.current_dice_index, 0)

    def test_capturing_dice_neither_grants_an_opportunity_nor_mutates_the_source(self):
        card = self.card(self.attacker, [dict(type="slash", level=1), dict(type="block", level=3)])
        template = SkillDieTemplate.capture(card, 2)
        card.dice[1]["level"] = 1
        first, second = (template.create_die(self.game, self.holder) for _ in range(2))
        self.assertEqual((first.position, first.modified_level), (2, 3))
        self.assertIs(first.card.character, self.holder)
        self.assertIsNot(first, second)
        self.assertIsNot(first.card, second.card)
        self.assertIsNone(card.instantiated_dice)
        self.assertEqual(self.holder.reserved_dice, [])
        self.assertIsNone(SkillDieTemplate.capture(card, 0))

    def test_trigger_and_turn_deadline_are_independent(self):
        card = self.card(self.holder, [dict(type="block", level=1)])
        self.assertTrue(self.grant(card, trigger="other_window", deadline=None))
        self.assertTrue(self.grant(card, deadline=4))
        self.assertTrue(self.grant(card, deadline=3))
        other, later, now = self.holder.reserved_dice
        self.assertEqual(self.holder.available_die_responses(BEFORE_ONE_SIDED_ATTACK, 3), [later, now])
        self.holder.expire_die_responses(3)
        self.assertEqual(self.holder.reserved_dice, [other, later])
        self.assertEqual(self.holder.available_die_responses(BEFORE_ONE_SIDED_ATTACK, 5), [])
        self.holder.expire_die_responses(4)
        self.assertEqual(self.holder.available_die_responses("other_window", 20), [other])
        self.assertIsNone(self.pipeline._pending_response_die(self.attack))

    def test_snapshot_keeps_the_original_use_balances_and_combatant_identity_after_a_transfer(self):
        physical = self.card(self.attacker, [dict(type="block", level=1)])
        physical.use_state.update(spent_statuses={"能源": 4}, marked=self.holder)
        template = SkillDieTemplate.capture(physical, 1)
        physical.set_controller(self.holder)
        physical.use_state["spent_statuses"]["能源"] = 8
        first = template.create_die(self.game, self.attacker)
        self.assertIs(first.card.character, self.attacker)
        self.assertIs(first.card.use_state["marked"], self.holder)
        self.assertEqual(first.card.use_state["spent_statuses"]["能源"], 4)
        first.card.use_state["spent_statuses"]["能源"] += 2
        self.assertEqual(template.create_die(self.game, self.attacker).card.use_state["spent_statuses"]["能源"], 4)

    def test_blocked_unpaid_and_successful_responses_apply_their_own_charge(self):
        card = self.card(self.holder, [dict(type="block", level=1, requires_skill_state="enabled"),
                                      dict(type="block", level=2, resource_cost=dict(status="弹药", amount=1)),
                                      dict(type="evade", level=3)])
        self.grant(card)
        self.grant(card, position=2, count=4, spend_on="attempt", cost=2)
        self.grant(card, position=3, count=2, cost=2)
        gated, unaffordable, successful = self.holder.reserved_dice
        self.assertEqual(self.pipeline._pending_response_die(self.attack).position, 2)
        self.assertEqual([r.remaining for r in self.holder.reserved_dice], [2, 4, 2])
        result = self.pipeline._accept_die_response(self.attack, self.holder, BEFORE_ONE_SIDED_ATTACK)
        self.assertEqual(result.position, 3)
        self.assertEqual([gated.remaining, unaffordable.remaining, successful.remaining], [2, 2, 0])
        self.assertEqual(self.holder.reserved_dice, [gated, unaffordable])

    def test_failed_payment_can_be_retried_without_spending_a_use(self):
        card = self.card(self.holder, [dict(type="block", level=2, resource_cost=dict(status="弹药", amount=1))])
        self.grant(card, count=1)
        self.assertIsNone(self.pipeline._accept_die_response(self.attack, self.holder, BEFORE_ONE_SIDED_ATTACK))
        self.assertEqual(self.holder.reserved_dice[0].remaining, 1)
        self.holder.statuses["弹药"] = 1
        die = self.pipeline._accept_die_response(self.attack, self.holder, BEFORE_ONE_SIDED_ATTACK)
        self.assertTrue(die.resource_paid)
        self.assertEqual(self.holder.reserved_dice, [])

    def test_a_printed_price_can_be_discounted_when_the_die_is_actually_used(self):
        card = self.card(self.holder, [dict(type="block", level=2, resource_cost=dict(status="弹药", amount=2))])
        self.holder.statuses["弹药"] = 1
        self.game.context.register_entries(self.holder, [{"trigger": "BEFORE SPEND_STATUS", "subject": "target",
            "operation": {"op": "program", "code": [1, "SUB"]}}])
        self.grant(card, count=1)
        self.assertIsNotNone(self.pipeline._pending_response_die(self.attack))
        self.assertEqual(self.holder.statuses["弹药"], 1)
        used = self.pipeline._accept_die_response(self.attack, self.holder, BEFORE_ONE_SIDED_ATTACK)
        self.assertTrue(used.resource_paid)
        self.assertEqual(self.holder.statuses.get("弹药", 0), 0)

    def test_zero_stacks_or_missing_position_grants_nothing(self):
        card = self.card(self.holder, [dict(type="block", level=1)])
        self.assertFalse(self.grant(card, count=0))
        self.assertFalse(self.grant(card, position=2))
        self.assertEqual(self.holder.reserved_dice, [])

    def test_a_second_check_in_one_attack_can_use_a_new_grant_without_charging_the_first_again(self):
        card = self.card(self.holder, [dict(type="block", level=1, requires_skill_state="enabled"),
                                      dict(type="evade", level=2)])
        self.grant(card, count=3, spend_on="attempt")
        first, = self.holder.reserved_dice
        attempted = set()
        self.assertIsNone(self.pipeline._accept_die_response(self.attack, self.holder, BEFORE_ONE_SIDED_ATTACK,
                                                             attempted=attempted))
        self.grant(card, position=2, count=1)
        die = self.pipeline._accept_die_response(self.attack, self.holder, BEFORE_ONE_SIDED_ATTACK,
                                                 attempted=attempted)
        self.assertEqual(die.position, 2)
        self.assertEqual(first.remaining, 2)
