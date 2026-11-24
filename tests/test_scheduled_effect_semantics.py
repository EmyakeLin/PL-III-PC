import json
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from context.context import Context
from entry.entry import Entry
from entry.compiler import compile_program
from models.card import Card
from models.character import Character
from models.dice import Dice
from pipeline.combat_steps import DICE
from pipeline.pipeline import CombatFrame, Pipeline


class ScheduledEffectTests(unittest.TestCase):
    def setUp(self):
        self.game = SimpleNamespace(turn_number=2, card_serial=0, resolving_duel=None, status_entries={},
                                    status_rules={}, ability_rules={}, turn_end_statuses=set(), is_over=False)
        self.game.context = self.ctx = Context(game=self.game)
        self.game.init_dice = lambda spec: Dice(spec, self.game)
        self.game.players = []
        for side in ("source", "recipient"):
            player = SimpleNamespace(side=side, game=self.game, register_faction_passives=lambda actor: None)
            player.characters = [Character(dict(id=side, name=side, rank="NORMAL", max_hp=6, skills=[]), player)]
            self.game.players.append(player)
        self.source, self.target = [p.characters[0] for p in self.game.players]

    def terms(self, body, **changes):
        return {"schedule": {"event": "sample", "source": "$self", "target": "$event.target",
                             "after_turns": 0, "through_turns": None, "uses": 1, "require_source_alive": False,
                             "require_target_alive": True, "then": body, **changes}}

    def run_entry(self, operation):
        entry = Entry.from_spec(self.source, {"trigger": "fixture", "operation": operation, "authority": 2})
        with self.ctx.binding(source=self.source, target=self.target):
            self.ctx._invoke(entry)

    def die(self, actor, spec=None):
        card = Card(actor.player, dict(id="fixture", name="测试技能", cost=0,
                                      dice=[spec or dict(type="slash", level=1)]), actor)
        return card.get_current_die(self.game, register=False)

    def emit_die(self, die):
        self.ctx.dispatch_pipeline("before_dice_use", source=die.card.character, die=die, card=die.card,
                                   side=die.card.player.side, valid=lambda: not die.destroyed)

    def test_real_weakness_promised_by_lin_qiu_survives_the_source_and_waits_for_next_turn(self):
        pack = Path(__file__).resolve().parents[1] / "_packs" / "xinxing_lin_qiu.json"
        skills = json.loads(pack.read_text(encoding="utf-8"))["characters"][0]["skills"]
        printed = next(s for s in skills if s["id"] == "lin_qiu_plume_sword")
        die = self.die(self.source, printed["dice"][1])
        die.register_entries()
        self.ctx.dispatch_pipeline("on_dice_hit", source=self.source, target=self.target, die=die,
                                   card=die.card, side=self.source.player.side)
        self.source.is_alive = False
        self.ctx.dispatch_pipeline("on_turn_prepared")
        self.assertNotIn("虚弱", self.target.statuses)
        self.game.turn_number += 1
        self.ctx.dispatch_pipeline("on_turn_prepared")
        self.ctx.dispatch_pipeline("on_turn_prepared")
        self.assertEqual(self.target.statuses["虚弱"], 1)
        self.assertEqual(self.ctx.scheduled_effects, [])

    def test_real_counterflow_debuff_waits_for_the_targets_actual_die(self):
        pack = Path(__file__).resolve().parents[1] / "_packs" / "xinxing_lin_qiu.json"
        skills = json.loads(pack.read_text(encoding="utf-8"))["characters"][0]["skills"]
        printed = next(s for s in skills if s["id"] == "lin_qiu_counterflow")
        original = self.die(self.source, printed["dice"][0])
        original.register_entries()
        self.ctx.dispatch_pipeline("on_dice_hit", source=self.source, target=self.target, die=original,
                                   card=original.card, side=self.source.player.side)
        self.emit_die(original)
        self.source.is_alive = False
        cancelled = self.die(self.target)
        cancelled.destroyed = True
        self.emit_die(cancelled)
        self.game.turn_number += 2
        actual = self.die(self.target)
        self.emit_die(actual)
        self.assertEqual([original.final_bonus, cancelled.final_bonus, actual.final_bonus], [0, 0, -4])
        self.assertEqual(self.ctx.scheduled_effects, [])

    def test_drifting_wind_remembers_the_amount_actually_spent_on_this_use(self):
        pack = Path(__file__).resolve().parents[1] / "_packs" / "wind_plan_b.json"
        skills = json.loads(pack.read_text(encoding="utf-8"))["characters"][0]["skills"]
        printed = next(s for s in skills if s["id"] == "annolin_drifting_wind")
        card = Card(self.source.player, printed, self.source)
        self.source.statuses["涡流"] = 3
        self.ctx.dispatch_pipeline("on_skill_use", source=self.source, card=card, side=self.source.player.side)
        self.assertEqual(self.source.statuses["强壮"], 3)
        self.source.statuses["涡流"] = 9
        self.game.turn_number += 1
        self.ctx.dispatch_pipeline("on_turn_prepared")
        self.assertEqual(self.source.statuses["强壮"], 6)

    def test_captured_local_is_frozen_and_the_closure_reads_the_triggering_events(self):
        spec = self.terms(["$event.scheduled.target", "采样", "$event.scheduled.capture.initial",
                           "$event.value", "ADD", "STATUS"], capture={"initial": "$local.amount"}, uses=2)
        self.run_entry({"op": "program", "code": [3, "amount", "STORE", spec, 99, "amount", "STORE"]})
        self.ctx.dispatch_pipeline("different", value=99)
        self.ctx.dispatch_pipeline("sample", value=1)
        self.ctx.dispatch_pipeline("sample", value=2)
        self.ctx.dispatch_pipeline("sample", value=30)
        self.assertEqual(self.target.statuses["采样"], 9)

    def test_dead_source_and_dead_target_are_separate_conditions(self):
        body = ["$event.scheduled.target", "答复", 1, "STATUS"]
        self.run_entry(self.terms(body, require_source_alive=True))
        self.run_entry(self.terms(body))
        self.source.is_alive = False
        self.ctx.dispatch_pipeline("sample")
        self.assertEqual(self.target.statuses["答复"], 1)
        self.source.is_alive = True
        self.run_entry(self.terms(body))
        self.target.is_alive = False
        self.ctx.dispatch_pipeline("sample")
        self.assertEqual(self.target.statuses["答复"], 1)
        self.assertEqual(self.ctx.scheduled_effects, [])

    def test_expiry_event_channel_and_unlimited_uses_are_independent(self):
        self.run_entry(self.terms(["$event.scheduled.target", "计数", 1, "STATUS"], event_type="event",
                                  after_turns=1, through_turns=1, uses=None))
        self.ctx.publish("sample", {})
        self.game.turn_number = 3
        self.ctx.dispatch_pipeline("sample")
        self.assertNotIn("计数", self.target.statuses)
        self.ctx.publish("sample", {})
        self.ctx.publish("sample", {})
        self.game.turn_number = 4
        self.ctx.publish("sample", {})
        self.assertEqual(self.target.statuses["计数"], 2)
        self.assertEqual(self.ctx.scheduled_effects, [])

    def test_event_participants_and_scheduled_authority_are_independently_observable(self):
        observed = []
        self.ctx.register_entries(None, [{"trigger": "AFTER STATUS", "operation": lambda vm: observed.append(
            (vm.event["source"], vm.event["target"], vm.event["authority"]))}])
        self.run_entry(self.terms(["$event.observed.source", "反馈", 1, "STATUS"]))
        self.ctx.dispatch_pipeline("sample", source=self.target, target=self.source)
        self.assertEqual(observed, [(self.source, self.target, 2)])

    def test_highest_authority_spend_uses_the_scheduled_source_and_initiative_at_delivery(self):
        self.ctx.register_entries(self.target, [dict(trigger="BEFORE SPEND_STATUS", subject="target",
            authority="最高话语权", operation={"op": "cancel"})])
        self.target.add_status("强壮", 2)
        for first, expected in ((self.target.player, 2), (self.source.player, 1)):
            with self.subTest(first=first.side):
                self.game.first_player = self.target.player if first is self.source.player else self.source.player
                self.run_entry(self.terms(["$event.target", "强壮", 1, "SPEND_STATUS"]))
                self.game.first_player = first
                self.ctx.dispatch_pipeline("sample", source=self.target)
                self.assertEqual(self.target.statuses["强壮"], expected)

    def test_a_nested_trigger_does_not_leak_the_callers_fields_into_its_reservation(self):
        for channel in ("pipeline", "event"):
            self.run_entry(self.terms(["$event.scheduled.target", "额外数值", "$event.unrelated",
                                       0, "COALESCE", "STATUS"], event_type=channel))
        with self.ctx.binding(unrelated=8):
            self.ctx.dispatch_pipeline("sample")
            self.ctx.publish("sample", {})
        self.assertNotIn("额外数值", self.target.statuses)

    def test_reservation_created_inside_a_delivery_waits_for_another_occurrence(self):
        later = self.terms(["$event.scheduled.target", "第二次", 1, "STATUS"], target="$event.scheduled.target")
        self.run_entry(self.terms([later]))
        self.ctx.dispatch_pipeline("sample")
        self.assertNotIn("第二次", self.target.statuses)
        self.assertEqual(len(self.ctx.scheduled_effects), 1)
        self.ctx.dispatch_pipeline("sample")
        self.assertEqual(self.target.statuses["第二次"], 1)

    def test_scheduled_body_uses_its_enclosing_compiler_and_recursion_guard(self):
        actions = {"CUSTOM": ["$event.scheduled.target", "自定义", 1, "STATUS"]}
        tokens = [self.terms(["CUSTOM"])]
        compiled = compile_program(tokens, expand=actions.get)
        self.run_entry({"op": "program", "code": compiled})
        self.ctx.dispatch_pipeline("sample")
        self.assertEqual(self.target.statuses["自定义"], 1)
        actions["CUSTOM"] = tokens
        with self.assertRaisesRegex(ValueError, "循环展开"):
            compile_program(["CUSTOM"], expand=actions.get)

    def test_destroyed_first_die_leaves_later_reservations_for_the_next_valid_event(self):
        condition = [{"left": "$event.die.card.character", "op": "eq", "right": "$event.scheduled.target"}]
        self.run_entry(self.terms(["$event.die", "DESTROY"], event="before_dice_use", when=condition))
        self.run_entry(self.terms(["$event.die", 7, "DIE_FINAL_ADD"], event="before_dice_use", when=condition))
        first = self.die(self.target)
        self.emit_die(first)
        self.assertTrue(first.destroyed)
        self.assertEqual(len(self.ctx.scheduled_effects), 1)
        second = self.die(self.target)
        self.emit_die(second)
        self.assertEqual(second.final_bonus, 7)
        self.assertEqual(self.ctx.scheduled_effects, [])

    def test_draw_phase_delivers_after_budget_rollover_and_before_either_player_draws(self):
        # These unbound turn methods need neither a live game nor its external rules.
        with patch.dict("sys.modules", {"gamerule": SimpleNamespace(GameRule=None),
                                        "loader": SimpleNamespace(base_effects=None)}):
            from game import Game
        game = self.game
        game.open_turn = MethodType(Game.open_turn, game)
        game.prepare_turn = MethodType(Game.prepare_turn, game)
        game._continue_drawing = MethodType(Game._continue_drawing, game)
        game.turn_count, game._prepared_turn, game.turn_history = 2, 1, []
        seen = []
        for player in game.players:
            player.next_turn_common_cost = 2
            player.draw_for_turn = lambda p=player: seen.append((p.side, self.target.statuses.get("回合数值")))
        self.run_entry(self.terms(["$event.scheduled.target", "回合数值", "$player.turn_common_cost_bonus", "STATUS"],
                                  event="on_turn_prepared", after_turns=1, through_turns=1))
        Game.draw_phase(game)
        game.prepare_turn()
        self.assertEqual(seen, [("source", 2), ("recipient", 2)])
        self.assertEqual(self.target.statuses["回合数值"], 2)

    def test_actual_die_node_supplies_current_card_and_rejects_withdrawn_uses(self):
        pipeline = self.game.pipeline = Pipeline(self.game)
        die = self.die(self.target)
        slot = SimpleNamespace(get_content=lambda side: [die.card], play_mode=lambda card: "regular")
        space = SimpleNamespace(game=self.game, space=[slot], current_duel_index=0)
        self.game.pre_reveal = SimpleNamespace(space=None)
        frame = CombatFrame(space, self.game.players, interrupt=False)
        pipeline._frames.append(frame)
        pipe = frame.sides[self.target.player.side]
        pipe.card, pipe.die = die.card, die
        self.run_entry(self.terms(["$event.die", 5, "DIE_FINAL_ADD"], event="before_dice_use",
                                  when=[{"left": "$event.card.character", "op": "eq",
                                         "right": "$event.scheduled.target"}]))
        pipe.withdrawn = True
        self.assertIsNone(pipeline._execute(DICE[0], pipe))
        self.assertEqual(len(self.ctx.scheduled_effects), 1)
        pipe.withdrawn = False
        self.assertEqual(pipeline._execute(DICE[0], pipe), "before_dice_use")
        self.assertEqual(die.final_bonus, 5)

    def test_all_authorized_printed_skills_forms_dice_and_status_entries_compile(self):
        directory = Path(__file__).resolve().parents[1] / "_packs"
        for filename in ("plan_b_heck.json", "plan_b_heris.json", "plan_b_li_ling.json",
                         "wind_plan_b.json", "xinxing_lin_qiu.json"):
            with self.subTest(pack=filename):
                pack = json.loads((directory / filename).read_text(encoding="utf-8"))
                for definitions in pack.get("status_entries", {}).values():
                    self.ctx.register_entries(self.source, definitions)
                self.ctx.register_status_programs(pack.get("status_rules", {}))
                for character in pack["characters"]:
                    self.ctx.register_entries(self.source, character.get("passive_skills", ()))
                    for spec in character["skills"]:
                        card = Card(self.source.player, spec, self.source)
                        for form in [None, *spec.get("forms", {})]:
                            card.set_form(form)
                            for die_spec in card.dice:
                                die = Dice(die_spec, self.game)
                                die.card = card
                                die.register_entries()
