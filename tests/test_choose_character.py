"""Semantic and bridge tests for OpCode.CHOOSE_CHARACTER."""
import io
import unittest
from contextlib import redirect_stdout

from battle_mcp.engine import ArenaEngine
from displayer import Displayer, seat_action_view
from entry.entry import Entry, TriggerType
from game import Game
from models.character import Character
from models.special_actions import SpecialAction
from player.player import Player
from tests.test_entry_execution_paths import TraceContext


class ChooseCharacterTests(unittest.TestCase):
    @staticmethod
    def _dummy_spec(cid, name, *, hp=12, actions=()):
        return {
            "id": cid,
            "name": name,
            "rank": "NORMAL",
            "max_hp": hp,
            "actions": list(actions),
            "skills": [
                {"id": f"{cid}_strike", "name": f"{name}斩击", "cost": 1, "dice": [{"type": "slash", "min": 1, "max": 6}]}
                for _ in range(3)
            ],
        }

    def _setup_game(self, *, left_specs, right_specs):
        self.enterContext(redirect_stdout(io.StringIO()))
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right])
        trace = TraceContext()
        trace.game = game
        game.context = trace
        game.first_player = left
        for side_player, specs in ((left, left_specs), (right, right_specs)):
            for spec in specs:
                char = Character(spec, side_player)
                side_player.characters.append(char)
                char.init_cards()
                char.setup_deck()
        game.start_turn()
        return game, left, right

    def test_chain_choose_option_to_choose_character_applies_to_selected_target_only(self):
        ability = {
            "id": "chain_select",
            "name": "重剑选敌",
            "window": "before_reveal",
            "target": "self",
            "per_turn": 1,
            "operation": {
                "op": "program",
                "code": [
                    {
                        "literal": {
                            "title": "选择战术",
                            "description": "选定目标方式",
                            "options": [
                                {
                                    "id": "mark",
                                    "label": "压制指定敌人",
                                    "description": "选择一名敌方角色施加烧伤与伤害",
                                    "then": {
                                        "op": "program",
                                        "code": [
                                            "$player", "OPPONENT", {"field": "characters"}, ["$event.item.is_alive"], "FILTER",
                                            {
                                                "literal": {
                                                    "title": "选择敌方目标",
                                                    "description": "选择一名存活敌方角色。",
                                                    "then": {
                                                        "op": "program",
                                                        "code": [
                                                            "$event.chosen_character", 2, "normal", "none", "DAMAGE",
                                                            "$event.chosen_character", "烧伤", 0, 3, "ADD", "STATUS",
                                                        ],
                                                    },
                                                }
                                            },
                                            "CHOOSE_CHARACTER",
                                        ],
                                    },
                                },
                                {
                                    "id": "shield",
                                    "label": "原地整备",
                                    "then": {"$self": {"shield": 2}},
                                },
                            ],
                        }
                    },
                    "CHOOSE_OPTION",
                ],
            },
        }
        game, left, right = self._setup_game(
            left_specs=[self._dummy_spec("actor", "贺敛", actions=[ability])],
            right_specs=[self._dummy_spec("e1", "甲敌", hp=12), self._dummy_spec("e2", "乙敌", hp=10)],
        )
        e1, e2 = right.characters

        opts = game.special.options(left)
        use_ability = next(o for o in opts if o.kind == "ability" and o.ability_id == "chain_select")
        self.assertTrue(game.special.apply(left, use_ability))
        self.assertEqual(game.next_step(), "wait_option_choice")

        self.assertTrue(game.special.apply(left, SpecialAction("choose_option", option_id="mark")))
        self.assertEqual(game.next_step(), "wait_character_choice")
        self.assertIs(game.special.decision_owner, left)
        self.assertEqual(game.special.options(right), [])

        char_opts = game.special.options(left)
        self.assertEqual([o.kind for o in char_opts], ["choose_character", "choose_character"])
        self.assertEqual([o.character for o in char_opts], [e1, e2])

        choice_view = Displayer(game, viewer_side=1).effect_choice()
        self.assertEqual(choice_view["selection"], "character")
        self.assertEqual(choice_view["description"], "选择一名存活敌方角色。")
        action_view = seat_action_view(char_opts[1], left)
        self.assertEqual(action_view["character_id"], "e2")
        self.assertEqual(action_view["description"], "生命 10/10")

        self.assertTrue(game.special.apply(left, char_opts[1]))
        self.assertIsNone(game.special.character_decision)
        self.assertIsNone(game.special.decision_owner)
        self.assertEqual(e2.hp, 8)
        self.assertEqual(e2.statuses.get("烧伤", 0), 3)
        self.assertEqual(e1.hp, 12)
        self.assertEqual(e1.statuses.get("烧伤", 0), 0)

    def test_optional_decline_and_dead_filtering(self):
        game, left, right = self._setup_game(
            left_specs=[self._dummy_spec("actor", "施术者")],
            right_specs=[self._dummy_spec("e1", "活敌"), self._dummy_spec("e2", "倒地敌")],
        )
        actor = left.characters[0]
        e1, e2 = right.characters
        e2._die()

        spec = {
            "optional": True,
            "title": "可选点名",
            "then": {"op": "program", "code": ["$event.chosen_character", 5, "normal", "none", "DAMAGE"]},
        }
        entry = Entry(actor, TriggerType.PIPELINE, "test_choose", {
            "op": "program",
            "code": ["$player", "OPPONENT", {"field": "characters"}, {"literal": spec}, "CHOOSE_CHARACTER"],
        })
        with game.context.binding(source=actor, side=1):
            game.context._invoke(entry)

        opts = game.special.options(left)
        self.assertEqual([(o.kind, o.character) for o in opts], [("choose_character", e1), ("decline_character", None)])
        self.assertTrue(game.special.apply(left, opts[1]))
        self.assertIsNone(game.special.character_decision)
        self.assertEqual(e1.hp, 12)

        with game.context.binding(source=actor, side=1):
            game.context._invoke(Entry(actor, TriggerType.PIPELINE, "test_choose_die", {
                "op": "program",
                "code": [
                    "$player", "OPPONENT", {"field": "characters"},
                    {"literal": {**spec, "optional": False}}, "CHOOSE_CHARACTER",
                ],
            }))
        self.assertIsNotNone(game.special.character_decision)
        e1._die()
        self.assertIsNone(game.special.character_decision)
        self.assertIsNone(game.special.decision_owner)

    def test_match_and_mcp_engine_submit_choose_character(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        engine = ArenaEngine(roster=("plan_b_annolin", "plan_b_heck"), seed=1)
        actor = engine.game.players[0].characters[0]
        target = engine.game.players[1].characters[0]
        hp_before = target.hp
        entry = Entry(actor, TriggerType.PIPELINE, "bridge_choose", {
            "op": "program",
            "code": [
                "$player", "OPPONENT", {"field": "characters"}, ["$event.item.is_alive"], "FILTER",
                {
                    "literal": {
                        "title": "桥梁选人",
                        "description": "选定对手角色造成 2 点伤害。",
                        "then": {"op": "program", "code": ["$event.chosen_character", 2, "normal", "none", "DAMAGE"]},
                    }
                },
                "CHOOSE_CHARACTER",
            ],
        })
        with engine.game.context.binding(source=actor, side=1):
            engine.game.context._invoke(entry)

        snap = engine.snapshot()
        self.assertTrue(snap["card_choice"])
        self.assertEqual(engine.required_sides(), [1])
        mcp_opts = engine.options(1)
        pick = next(o for o in mcp_opts if o["kind"] == "special_choose_character")
        self.assertIn("choice_key", pick)
        minimal = {"kind": pick["kind"], "character_id": pick["character_id"], "choice_key": pick["choice_key"]}
        self.assertIsNotNone(engine.current_move(1, minimal))

        engine.apply(1, minimal)
        self.assertIsNone(engine.game.special.character_decision)
        self.assertEqual(target.hp, hp_before - 2)


if __name__ == "__main__":
    unittest.main()
