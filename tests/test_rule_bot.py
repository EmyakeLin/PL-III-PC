"""A single player can start a local room and play through the computer's decisions."""

import io
import unittest
from contextlib import redirect_stdout
from itertools import count
from unittest.mock import patch

from battle_mcp.declarations import ORDINARY
from battle_mcp.room import Room


class RuleBotTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch("battle_mcp.room.threading.Timer"))
        self.room = Room(("ember_wen_sheng", "plan_b_annolin"), seed=8, bot=True)
        self.addCleanup(self.room.close)
        self.requests = count()

    def command(self, operation, **fields):
        view = self.room.observe(1)
        return getattr(self.room, operation)(1, revision=view["revision"],
                                             request_id=str(next(self.requests)), **fields)

    def test_host_picks_both_characters_then_locks_them_with_one_ready(self):
        with self.assertRaises(ValueError):
            self.command("select_character", target_side=2, character_id="ember_wen_sheng")
        self.assertEqual(self.room.observe(1)["lobby"]["picks"], {1: "ember_wen_sheng", 2: "plan_b_annolin"})
        self.command("select_character", character_id="blank_boss")
        lobby = self.command("select_character", target_side=2, character_id="blank_boss")
        self.assertFalse(lobby["started"])
        self.assertEqual(lobby["lobby"]["picks"], {1: "blank_boss", 2: "blank_boss"})
        with self.assertRaises(PermissionError):
            self.room.ready(2, self.room.observe(2)["revision"], "bot-seat")
        view = self.command("ready", human=True)
        self.assertTrue(view["started"])
        self.assertNotIn("lobby", view)
        self.assertEqual(view["bot_side"], 2)
        self.assertEqual(view["ready_sides"], [1, 2])
        with self.assertRaises(ValueError):
            self.command("select_character", target_side=2, character_id="nova_lin_qiu")
        self.command("pause")
        self.assertIsNone(self.room._beat_timer)
        self.assertIsNone(self.command("resume")["paused_by"])

    def test_bot_plays_to_terminal_result_and_resolves_its_skill_prompt(self):
        self.command("select_character", character_id="waa_lake")
        self.command("select_character", target_side=2, character_id="nova_lin_qiu")
        placement = ("place", "attack", "intercept", "let_through", "end_attack", "end")
        with patch.object(self.room.engine, "apply", wraps=self.room.engine.apply) as apply:
            self.command("ready", human=True)
            for _ in range(400):
                view = self.room.observe(1)
                self.assertIsNone(view["frame"]["players"][1]["hand"])
                if view["finished"]:
                    break
                options = [move for move in view["options"] if move["kind"] in ORDINARY]
                if options:
                    move = min(options, key=lambda m: placement.index(m["kind"]) if m["kind"] in placement else len(placement))
                    self.command("act", option_id=move["id"])
                else:
                    self.assertIsNotNone(self.room._beat_timer, view["frame"]["mode"])
                    with patch("battle_mcp.room.threading.current_thread", return_value=self.room._beat_timer):
                        self.room._advance_beat()
            else:
                self.fail("单人操作后，人机对局未抵达终局。")
        computer_moves = {move["kind"] for side, move in (call.args for call in apply.call_args_list) if side == 2}
        self.assertTrue({"place", "attack", "special_choose_card"} <= computer_moves)
        self.assertIn(view["winner_side"], (1, 2))
        reconnected = self.room.observe(1, cursor=0)
        self.assertTrue(reconnected["finished"])
        self.assertEqual(reconnected["winner_side"], view["winner_side"])
        self.assertFalse(reconnected["options"])
