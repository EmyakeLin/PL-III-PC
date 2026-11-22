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

    def test_energy_analysis_second_die_reads_current_stacks_at_each_comparison(self):
        card = self.printed_skill("plan_b_heck.json", "heck_energy_analysis")
        card.advance_die()
        die = card.get_current_die(self.game, register=False)
        for count, expected in [(0, 0), (1, 1), (4, 3), (2, 2), (0, 0)]:
            self.actor.statuses["凝聚"] = count
            self.assertEqual(die.effective_ignore_range, expected)
            self.assertEqual(card.effective_ignore_range, 0)
        self.assertIn("至多3级", "".join(describe_range_traits(die.data)))

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
