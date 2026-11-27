import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from context.context import Context
from models.card import Card, describe_range_traits
from models.character import Character
from models.dice import Dice
from pipeline.pipeline import Pipeline, SidePipeline


PACKS = Path(__file__).resolve().parents[1] / "_packs"


class RangeAmountTests(unittest.TestCase):
    def setUp(self):
        self.game = SimpleNamespace(card_serial=0, status_entries={}, status_rules={}, ability_rules={},
                                    turn_end_statuses=set(), resolving_duel=None)
        self.game.context = Context(game=self.game)
        self.game.init_dice = lambda spec: Dice(spec, self.game)
        self.game.pipeline = Pipeline(self.game)
        self.player = SimpleNamespace(side="A", game=self.game, register_faction_passives=lambda actor: None)
        self.actor = Character(dict(id="actor", name="持有者", rank="NORMAL", max_hp=6, skills=[]), self.player)
        self.player.characters = [self.actor]
        self.game.players = [self.player]

    def printed_skill(self, pack, skill_id):
        character = json.loads((PACKS / pack).read_text(encoding="utf-8"))["characters"][0]
        spec = next(skill for skill in character["skills"] if skill["id"] == skill_id)
        return Card(self.player, spec, self.actor)

    def use(self, card):
        self.game.context.dispatch_pipeline("on_skill_use", source=self.actor, card=card, side=self.player.side)

    def test_reduction_precedes_pressure_and_only_competes_with_a_level_guard(self):
        def card(**fields):
            return Card(self.player, dict(id="sample", name="测试", cost=0, dice=[], **fields), self.actor)
        for protection, attack_rank, expected in ((False, "low", 0), (True, "normal", 3), (True, "high", 0)):
            with self.subTest(protection=protection, attack_rank=attack_rank):
                ranged = card(range_level=3, protect_range_level=protection)
                lowering = card(opponent_range_reduction=3, trait_authority={"opponent_range_reduction": attack_rank})
                for _ in range(2):
                    self.assertEqual(ranged.paired_ranges(lowering), (expected, 0))
                self.assertEqual(ranged.effective_range, 3)
        for protection, expected in (("low", 3), ("normal", 0), ("high", 0)):
            near = card(ignore_range=3, trait_authority={"ignore_range": protection})
            near.set_range_opponent(card(range_level=3))
            self.assertEqual(near.range_deficit, expected)

    def test_invalid_authority_is_rejected_on_printed_effects(self):
        from entry.entry import Entry
        for invalid in (-2, 3, True, [], "unknown"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Entry.from_spec(self.actor, dict(trigger="fixture", authority=invalid, operation={"op": "cancel"}))
            with self.assertRaises(ValueError):
                Dice(dict(type="slash", level=1, clash_order="lower", trait_authority={"clash_order": invalid}))
        with self.assertRaises(ValueError):
            Dice(dict(type="slash", level=1, trait_authority={"damage": 2}))

    def test_energy_analysis_second_die_reads_current_stacks_at_each_comparison(self):
        card = self.printed_skill("plan_b_heck.json", "heck_energy_analysis")
        card.advance_die()
        die = card.get_current_die(self.game, register=False)
        for count, expected in [(0, 0), (1, 1), (4, 3), (2, 2), (0, 0)]:
            self.actor.statuses["凝聚"] = count
            self.assertEqual(die.effective_ignore_range, expected)
            self.assertEqual(card.effective_ignore_range, 0)
        self.assertIn("至多3级", "".join(describe_range_traits(die.data)))

    def test_speed_gap_uses_the_current_opponent_and_handles_an_empty_slot(self):
        card = self.printed_skill("plan_b_li_ling.json", "li_ling_sky")
        self.actor.speed = 12
        enemy = SimpleNamespace(speed=8)
        for speed in (None, 9, 8, 0, 99):
            card.range_opponent = SimpleNamespace(character=enemy) if speed is not None else None
            enemy.speed = speed
            active = speed is not None and self.actor.speed - speed >= 4
            self.assertEqual((card.effective_range, card.effective_ignore_range), (1, 3) if active else (0, 0))

    def test_tunnel_and_repeat_are_independently_read_from_their_printed_sources(self):
        cut = self.printed_skill("xinxing_lin_qiu.json", "lin_qiu_void_cut")
        boundary = self.printed_skill("xinxing_lin_qiu.json", "lin_qiu_boundary")
        counter = self.printed_skill("xinxing_lin_qiu.json", "lin_qiu_counterflow")
        counter.advance_die()
        die = counter.get_current_die(self.game, register=False)
        for opened in (0, 1, 9):
            for marked in (False, True):
                self.actor.statuses["隧道开启"] = opened
                counter.use_state["ranged_repeat"] = marked
                self.assertEqual(cut.effective_range, 3 if opened else 1)
                self.assertEqual(boundary.effective_ignore_range, 3 if opened else 0)
                self.assertEqual(die.effective_range, int(marked))
        with self.assertRaises(ValueError):
            Dice({"type": "block", "level": 1, "range_level_when": {"speed_lead": 4, "amount": 1}})

    def test_heris_uses_current_stacks_before_use_and_the_recorded_value_afterward(self):
        card = self.printed_skill("plan_b_heris.json", "heris_crush")
        self.actor.statuses["凝聚"] = 2
        self.assertEqual(card.effective_ignore_range, 2)
        self.use(card)
        self.assertTrue(card.use_effects_resolved)
        self.assertEqual(card.use_state["使用时凝聚"], 2)
        self.actor.statuses["凝聚"] = 0
        self.assertEqual(card.effective_ignore_range, 2)
        card.reset_for_draw()
        self.assertFalse(card.use_effects_resolved)
        self.assertEqual(card.effective_ignore_range, 0)
        self.use(card)
        self.actor.statuses["凝聚"] = 3
        self.assertEqual(card.effective_ignore_range, 0)
        card.use_state.pop("使用时凝聚")
        self.assertEqual(card.effective_ignore_range, 0)

    def test_snapshot_follows_the_energy_spend_inside_the_same_use(self):
        card = self.printed_skill("plan_b_heris.json", "heris_crush")
        self.game.context.register_entries(self.actor, [{
            "trigger": "on_status_changed", "subject": "target",
            "when": [{"left": "$event.status", "op": "eq", "right": "能源"}],
            "operation": {"op": "program", "code": ["$self", "凝聚", 1, "STATUS"]},
        }])
        self.actor.statuses.update(凝聚=1, 能源=8)
        self.assertEqual(card.effective_ignore_range, 0)
        self.use(card)
        self.assertEqual(card.use_state["使用时凝聚"], 2)
        self.assertEqual(card.effective_ignore_range, 2)

    def test_pairing_uses_the_pre_use_value_before_collecting_fees(self):
        pipe = SidePipeline("A", self.game)
        pipe.card = self.printed_skill("plan_b_heris.json", "heris_crush")
        other = SidePipeline("B", self.game)
        other.card = Card(self.player, dict(id="far", name="远程", cost=0, dice=[], range_level=3), self.actor)
        self.actor.statuses["凝聚"] = 2
        observed = []

        def collect(participants, stop):
            if stop == "logic_skill_use":
                for side in participants:
                    observed.append((side.side, side.card.range_deficit))
                    side.paid = True
            return iter(())

        with patch.object(self.game.pipeline, "_card_live", return_value=True), patch.object(self.game.pipeline, "_run_to", collect):
            list(self.game.pipeline._start_skills([pipe, other], [pipe, other]))
        self.assertEqual(observed, [("B", 0), ("A", 1)])

    def test_the_expression_can_choose_a_different_rate_and_cap_on_a_card(self):
        card = Card(self.player, {
            "id": "bands", "name": "测试技能", "cost": 0, "dice": [],
            "range_level_amount": {"value": {
                "left": {"left": {"field": "$self.statuses", "key": "资源", "default": 0},
                         "op": "floor_div", "right": 2}, "op": "min", "right": 2}},
        }, self.actor)
        for layers, expected in [(1, 0), (2, 1), (4, 2), (9, 2)]:
            self.actor.statuses["资源"] = layers
            self.assertEqual(card.effective_range, expected)
