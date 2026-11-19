import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from game import Game
from loader import load_characters_from_packs
from models.character import Character
from models.opcode import OpCode
from player.player import Player


PACKS = Path(__file__).resolve().parents[1] / "_packs"


class WaaResources(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.start_match(load_characters_from_packs())

    def start_match(self, characters):
        left, right = Player(1, "东部"), Player(2, "对手")
        self.game = Game([left, right])
        self.ctx = self.game.context
        pool = {data["name"]: data for data in characters}

        def recruit(player, name):
            char = Character(pool[name], player)
            player.characters.append(char)
            char.init_cards()
            return char
        self.actor = recruit(left, "厄尔克斯")
        self.ally = recruit(left, "铁壁先锋")
        self.enemy = recruit(right, "绯红决斗者")

    def start_pack_variant(self, pack):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "waa_east_four.json").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            shutil.copyfile(PACKS / "sample_pack.json", path / "sample_pack.json")
            self.start_match(load_characters_from_packs(path))

    def gain(self, status, amount):
        return self.ctx.eval_block([self.actor, status, amount, OpCode.STATUS])

    def spend(self, status, amount):
        return self.ctx.eval_block([self.actor, status, amount, OpCode.SPEND_STATUS])

    def test_surcharged_cost_drains_the_balance_and_records_only_actual_spend(self):
        receipts = []

        def record(ctx):
            receipts.append((ctx.event["amount"], ctx.event["result"], ctx.event["paid_in_full"]))

        self.ctx.register_entries(self.actor, [{"trigger": "AFTER SPEND_STATUS", "operation": record}])
        self.gain("充能", 7)
        self.assertEqual(self.gain("纯能", 8), 5)
        self.assertEqual(self.gain("充能", 10), 7)
        with self.ctx.binding(card=self.actor.skills[2]):
            self.assertEqual(self.spend("充能", 2), 3)
            self.assertEqual(self.actor.statuses["充能"], 4)
            self.assertEqual(self.spend("充能", 4), 4)
        self.assertNotIn("充能", self.actor.statuses)
        self.assertEqual(receipts, [(3, 3, True), (5, 4, False)])
        self.assertEqual(self.actor.skills[2].use_state["spent_statuses"], {"充能": 7})
        self.assertEqual(self.ctx.stack, [])

    def test_partial_vortex_spend_only_gates_the_conditional_followup(self):
        self.game.start_turn()
        schedule = ["$self", "$self", "骰子等级降低", 1, "QUEUE_STATUS"]
        for owner, balance, followup in (
            (self.actor, 1, ["SPEND_STATUS", "POP", *schedule]),
            (self.ally, 1, ["SPEND_STATUS_IN_FULL", schedule, "WHEN"]),
            (self.enemy, 2, ["SPEND_STATUS_IN_FULL", schedule, "WHEN"]),
        ):
            owner.add_status("涡流", balance)
            self.ctx.register_entries(owner, [{
                "trigger": "on_turn_end",
                "operation": {"op": "program", "code": ["$self", "涡流", 2, *followup]},
            }])
        self.game.finish_turn()
        self.ctx.dispatch_pipeline("on_turn_end")
        for owner in (self.actor, self.ally, self.enemy):
            self.assertNotIn("涡流", owner.statuses)
            self.assertNotIn("骰子等级降低", owner.statuses)
        self.game.start_turn()
        self.assertEqual(self.actor.statuses["骰子等级降低"], 1)
        self.assertNotIn("骰子等级降低", self.ally.statuses)
        self.assertEqual(self.enemy.statuses["骰子等级降低"], 1)

    def test_partial_pure_spend_triggers_diffusion_and_preserves_its_own_receipt(self):
        self.gain("纯能", 1)
        self.gain("涡流", 1)
        self.ctx.register_entries(self.actor, [
            {"trigger": "AFTER SPEND_STATUS", "when": {"status": "纯能"},
             "operation": {"op": "program", "code": [
                 "$self", "涡流", 1, "SPEND_STATUS_IN_FULL", ["$self", "迅捷", 1, "STATUS"], "WHEN",
             ]}},
            {"trigger": "on_turn_start", "operation": {"op": "program", "code": [
                "$self", "纯能", 2, "SPEND_STATUS_IN_FULL", ["$self", "强壮", 1, "STATUS"], "WHEN",
            ]}},
        ])
        card = self.actor.skills[1]
        self.ctx.dispatch_pipeline("on_turn_start", source=self.actor, card=card)
        self.assertEqual(self.actor.statuses, {"充能": 1, "迅捷": 1})
        self.assertEqual(self.ally.statuses["充能"], 1)
        self.assertEqual(card.use_state["spent_statuses"], {"纯能": 1, "涡流": 1})
        self.assertEqual(self.ctx.stack, [])

    def test_gain_block_and_surcharge_can_be_removed_independently_in_the_pack(self):
        for removed_trigger, expected_charge, paid in (
            ("BEFORE STATUS", 6, 3),
            ("BEFORE SPEND_STATUS", 4, 2),
        ):
            with self.subTest(removed_trigger=removed_trigger):
                pack = json.loads((PACKS / "waa_east_four.json").read_text(encoding="utf-8-sig"))
                erkes = next(char for char in pack["characters"] if char["name"] == "厄尔克斯")
                weapon = next(passive for passive in erkes["passive_skills"] if passive["name"] == "自发增压武器")
                removed = next(entry for entry in weapon["entries"] if entry["trigger"] == removed_trigger)
                weapon["entries"].remove(removed)
                self.start_pack_variant(pack)

                self.actor.add_status("充能", 4)
                self.actor.add_status("纯能", 3)
                self.assertEqual(self.actor.add_status("充能", 2), expected_charge)
                self.assertEqual(self.spend("充能", 2), paid)
                self.assertEqual(self.actor.statuses.get("充能"), expected_charge - paid)

    def test_overcharge_does_not_surcharge_all_or_nonpositive_payments(self):
        self.gain("充能", 4)
        self.gain("纯能", 3)
        for amount in (0, -1):
            with self.subTest(amount=amount):
                self.assertEqual(self.spend("充能", amount), 0)
                self.assertEqual(self.actor.statuses["充能"], 4)
        self.assertEqual(self.spend("充能", "all"), 4)
        self.assertNotIn("充能", self.actor.statuses)

    def test_surcharge_uses_the_amount_left_by_an_earlier_card_entry(self):
        self.gain("充能", 7)
        self.gain("纯能", 3)
        card = self.actor.skills[0]
        self.ctx.register_entries(card, [{
            "trigger": "BEFORE SPEND_STATUS", "when": {"status": "充能"},
            "operation": {"op": "program", "code": [
                "DUP", "all", "EQ", ["POP", 2], ["POP", "all"], "IF_ELSE",
            ]},
        }])
        with self.ctx.binding(card=card):
            self.assertEqual(self.spend("充能", "all"), 3)
            self.assertEqual(self.spend("充能", 2), 4)
        self.assertEqual(card.use_state["spent_statuses"], {"充能": 7})

    def test_seal_on_other_faction_only_restricts_its_holder(self):
        self.enemy.add_status("纯能", 2)
        self.enemy.add_status("充能", 7)
        self.enemy.add_status("能源封印", 1)
        for resource in ("纯能", "充能"):
            self.assertEqual(self.ctx.eval_block([self.enemy, resource, 1, OpCode.SPEND_STATUS]), 0)
        self.actor.add_status("纯能", 1)
        self.assertEqual(self.spend("纯能", 1), 1)
        self.assertIn("能源封印", self.enemy.statuses)
        self.enemy.add_status("充能", 1)
        self.assertNotIn("能源封印", self.enemy.statuses)
        self.assertEqual(self.ctx.eval_block([self.enemy, "纯能", 1, OpCode.SPEND_STATUS]), 1)

    def test_seal_locked_resource_and_unlock_threshold_follow_pack_entries(self):
        pack = json.loads((PACKS / "waa_east_four.json").read_text(encoding="utf-8-sig"))
        seal_entries = pack["status_entries"]["能源封印"]
        pure_energy_lock = next(entry for entry in seal_entries
                                if entry["trigger"] == "BEFORE SPEND_STATUS" and entry["when"]["status"] == "纯能")
        pure_energy_lock["when"]["status"] = "备用电池"
        unlock = next(entry for entry in seal_entries if entry["trigger"] == "AFTER STATUS")
        unlock["when"]["result_at_least"] = 6
        self.start_pack_variant(pack)

        holder = self.enemy
        for resource in ("纯能", "备用电池", "能源封印"):
            holder.add_status(resource, 1)
        holder.add_status("充能", 5)
        self.assertEqual(self.ctx.eval_block([holder, "纯能", 1, OpCode.SPEND_STATUS]), 1)
        self.assertEqual(self.ctx.eval_block([holder, "备用电池", 1, OpCode.SPEND_STATUS]), 0)
        self.assertEqual(self.ctx.eval_block([holder, "充能", 1, OpCode.SPEND_STATUS]), 0)
        holder.add_status("充能", 1)
        self.assertNotIn("能源封印", holder.statuses)
        self.assertEqual(self.ctx.eval_block([holder, "备用电池", 1, OpCode.SPEND_STATUS]), 1)

    def test_diffusion_rechecks_pure_energy_after_payment_and_includes_other_factions(self):
        self.gain("纯能", 4)
        self.assertEqual(self.spend("纯能", 1), 1)
        self.assertEqual(self.ally.statuses["充能"], 1)
        self.assertNotIn("充能", self.actor.statuses)
        self.assertEqual(self.spend("纯能", 1), 1)
        self.assertEqual(self.ally.statuses["充能"], 2)
        self.assertEqual(self.actor.statuses["充能"], 1)
        self.assertNotIn("充能", self.enemy.statuses)
        self.assertNotIn("能源", self.actor.statuses)

    def test_seal_and_cancelled_payment_do_not_trigger_diffusion(self):
        self.gain("纯能", 2)
        self.gain("能源封印", 1)
        self.gain("充能", 7)
        self.assertEqual(self.spend("充能", "all"), 0)
        self.ctx.register_entries(self.actor, [{
            "trigger": "on_turn_start", "operation": {"op": "program", "code": [
                "$self", "纯能", 1, "SPEND_STATUS_IN_FULL", ["$self", "强壮", 1, "STATUS"], "WHEN",
            ]},
        }])
        self.ctx.dispatch_pipeline("on_turn_start", source=self.actor)
        self.assertEqual(self.actor.statuses["纯能"], 2)
        self.assertNotIn("强壮", self.actor.statuses)
        self.assertNotIn("充能", self.ally.statuses)
        self.gain("充能", 1)
        self.assertNotIn("能源封印", self.actor.statuses)
        self.ctx.register_entries(self.actor, [
            {"trigger": "BEFORE SPEND_STATUS", "operation": "Cancel"}
        ])
        self.assertIsNone(self.spend("纯能", 1))
        self.assertEqual(self.actor.statuses["纯能"], 2)
        self.assertNotIn("充能", self.ally.statuses)
