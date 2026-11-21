import unittest
from unittest.mock import patch

from game import Game
from models.card import Card
from models.character import Character
from models.dice import Dice
from models.opcode import OpCode
from player.player import Player


def fighter(player, **rules):
    return Character(dict(id="fighter", name="测试角色", rank="NORMAL", max_hp=15, skills=[], **rules), player)


class SystemStatusPackTests(unittest.TestCase):
    def test_concentration_checks_changes_and_refreshes_once_per_holder_per_turn(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right])
        a, b = fighter(left), fighter(right)
        left.characters.append(a)
        right.characters.append(b)
        game.start_turn()
        a.add_status("能源", 3)
        a.add_status("凝聚", 3)
        self.assertEqual(a.statuses["能源"], 3)
        game.context.eval_block([a, "能源", 2, OpCode.SPEND_STATUS])
        self.assertEqual(a.statuses["能源"], 2)
        a.clear_status("凝聚")
        a.add_status("凝聚", 5)
        self.assertEqual(a.statuses["能源"], 2)
        b.add_status("凝聚", 4)
        self.assertEqual(b.statuses["能源"], 1)
        game.finish_turn()
        game.start_turn()
        self.assertEqual((a.statuses["能源"], b.statuses["能源"]), (3, 2))
        b.clear_status("能源")
        self.assertNotIn("能源", b.statuses)

    def test_ignite_credits_each_segment_and_rechecks_stacks_after_each_activation(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right])
        game.first_player = left
        a, b = fighter(left), fighter(right)
        left.characters.append(a)
        right.characters.append(b)
        game.start_turn()
        b.add_status("烧伤", 12)
        b.add_shield("normal", 10)
        card = Card(left, dict(id="igniter", name="引燃测试", cost=0, entries=[{
            "trigger": "AFTER ACTIVATE_STATUS", "subject": "source",
            "when": {"status": "烧伤", "activation_kind": "ignite", "result": True},
            "operation": {"op": "program", "code": [
                "$card", "已追加", "SKILL_STATE", "NOT", [
                    "$card", "已追加", 1, "SET_SKILL_STATE", {"op": "ignite"}
                ], "WHEN"]},
        }], dice=[
            dict(type="pierce", level=1, entries=["1穿甲", {
                "trigger": "AFTER RESOLVE_HIT", "when": {"result": True}, "subject": "source",
                "operation": {"op": "ignite", "multiplier": 2},
            }]),
            dict(type="slash", level=1, entries=["引燃"]),
        ]), a)
        a.skills.append(card)
        receipts = []
        game.context.register_entries(b, [dict(trigger="AFTER DAMAGE", subject="target", operation=lambda ctx:
            receipts.append(tuple(ctx.event[k] for k in
                                  ("source", "damage_die", "damage_card", "damage_status",
                                   "base_amount", "damage_amount"))))])
        game.place_in_duel(1, card, 0)
        game.reveal_cards()
        game.pipeline.start_duel_combat()
        for _ in range(400):
            if not game.pipeline.in_duel_phase:
                break
            game.next_step()
        self.assertFalse(game.pipeline.in_duel_phase)
        first, second = card.instantiated_dice
        self.assertEqual(receipts, [(a, first, card, None, 1, 1), (a, first, card, None, 3, 6),
                                    (a, None, card, None, 1, 1), (a, second, card, None, 1, 1)])
        self.assertEqual((b.statuses["烧伤"], b.hp), (1, 14))

        # A second status can call the same keyword and retain its own identity.
        game.status_entries["余烬"] = [dict(trigger="on_spark", operation="引燃")]
        a.add_status("余烬", 1)
        b.add_status("烧伤", 7)
        game.context.dispatch_pipeline("on_spark", source=a, target=b)
        self.assertEqual(receipts[-1], (a, None, None, "余烬", 2, 2))
        b.on_turn_end()
        self.assertEqual(receipts[-1], (b, None, None, "烧伤", 1, 1))
        self.assertEqual(game.context.stack, [])

    def test_detached_character_resolves_stacked_statuses_through_the_same_damage_events(self):
        actor = fighter(Player(1, "甲"))
        actor.add_status("burn", 8)
        actor.add_status("fatal_stagger", 2)
        actor.add_shield("normal", 4)
        actor.on_turn_end()
        self.assertEqual((actor.hp, actor.shield), (15, 0))
        self.assertEqual(actor.statuses, {"烧伤": 4, "致命失衡": 1})

        actor.add_status("bleed", 6)
        actor.after_damage_part()
        self.assertEqual((actor.hp, actor.statuses["裂血"], actor.bleed_burst), (13, 4, True))
        actor.begin_dice_round()
        actor.after_damage_part()
        actor.after_damage_part()
        self.assertEqual((actor.hp, actor.bleed_burst), (10, False))
        self.assertNotIn("裂血", actor.statuses)
        actor.after_damage_part()
        self.assertEqual(actor.hp, 10)

    def test_aliases_share_stacks_costs_checks_and_notifications_in_a_bare_game(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right])
        actor = fighter(left)
        observed = []
        game.context.register_entries(actor, [{
            "trigger": "AFTER STATUS", "when": {"status": "呼吸"},
            "operation": lambda ctx: observed.append(ctx.event["actual_delta"]),
        }])
        game.context.eval_block([actor, "呼吸法", 8, OpCode.STATUS])
        self.assertEqual(observed, [6])
        die = Dice(dict(type="slash", level=1))
        with patch.object(game.rng, "randint", return_value=6) as roll:
            self.assertTrue(actor.on_attack_hit(die, fighter(right)))
            self.assertEqual(game.context.eval_block([actor, "breath", 1, OpCode.SPEND_STATUS]), 1)
            self.assertFalse(actor.on_attack_hit(die, fighter(right)))
        self.assertEqual(roll.call_args.args, (1, 6))
        self.assertEqual(actor.statuses, {"呼吸": 5})

    def test_stagger_check_uses_the_pack_die_and_failure_from_zero(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right])
        actor = fighter(left)
        with patch.object(game.rng, "randint", return_value=20) as roll:
            self.assertFalse(actor.trigger_stagger())
            self.assertEqual(actor.statuses, {"失衡": 2})
            actor.add_status("stagger", 99)
            self.assertTrue(actor.trigger_stagger())
        self.assertEqual(roll.call_args.args, (1, 20))
        self.assertEqual(actor.statuses, {"失衡": 15, "致命失衡": 1})
