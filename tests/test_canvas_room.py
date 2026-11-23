"""The Canvas client uses the shared room and its fixed-seat visibility."""

import http.client
import io
import threading
import unittest
from contextlib import redirect_stdout
from itertools import count
from unittest.mock import patch

from battle_mcp.declarations import ORDINARY
from battle_mcp.room import Room
from battle_mcp.transport import ArenaServer
from tests.test_mcp_transport import WireClient


class CanvasRoomTests(WireClient, unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch("battle_mcp.room.threading.Timer"))
        self.room = Room(("ember_wen_sheng", "plan_b_annolin"), seed=8, bot=True)
        self.server = self.enterContext(ArenaServer(self.room, port=0))
        worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(self.server.shutdown)
        self.requests = count()

    def canvas(self, side=None, **args):
        status, view = self.request("/api/canvas/state", args, side=side)
        self.assertEqual(status, 200, view)
        return view

    def command(self, operation, view, **fields):
        args = {"revision": view["revision"], "request_id": str(next(self.requests)), **fields}
        status, result = self.request("/api/" + operation, args, side=1)
        self.assertEqual(status, 200, result)
        return result

    def test_canvas_bot_match_draws_private_hands_and_reports_the_terminal_result(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request("GET", "/canvas/")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'id="pixi-canvas"', response.read())
            connection.request("GET", "/canvas/engine/transport.js")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b"class RoomSeatTransport", response.read())
        finally:
            connection.close()
        status, assets = self.request("/api/canvas/assets", {}, side=1)
        self.assertEqual(status, 200, assets)
        self.assertTrue(assets["roster_catalog"])
        lobby = self.canvas(1)
        self.assertFalse(lobby["started"])
        self.assertEqual(lobby["bot_side"], 2)
        ready = self.command("canvas/ready", lobby, roster=["waa_lake", "nova_lin_qiu"])
        self.assertTrue(ready["started"])

        view, saw_hidden_card = self.play_to_finish()
        self.assertTrue(saw_hidden_card)
        self.assertTrue({"cards_reveal", "dice_clash"} <= {event["kind"] for event in view["fx_events"]})
        spectator = self.canvas()
        self.assertEqual(spectator["frame"]["winner_side"], view["frame"]["winner_side"])
        self.assertFalse(spectator["options"])
        self.assertTrue(all(player["hand"] is None for player in spectator["frame"]["players"]))

    def test_rematch_reuses_invitation_and_can_replace_the_roster_after_the_next_game(self):
        token = self.server.tokens[1]
        lobby = self.canvas(1)
        args = {"revision": lobby["revision"], "request_id": "early"}
        self.assertEqual(self.request("/api/canvas/rematch", args)[0], 403)
        self.assertEqual(self.request("/api/canvas/rematch", args, side=1)[0], 400)
        self.command("canvas/ready", lobby, roster=["waa_lake", "nova_lin_qiu"])
        self.command("prepare", self.canvas(1), declaration={
            "event": "scores_ready", "mode": "reserve", "when": {"turn": 99}, "repeat": True,
        })
        first, _ = self.play_to_finish()
        self.assertTrue(first["can_rematch"])
        self.assertFalse(self.canvas()["can_rematch"])
        self.assertTrue(self.room.observe(1)["declarations"])

        args = {"revision": first["revision"], "request_id": "again"}
        bad_roster = {**args, "roster": ["waa_lake", "waa_lake"]}
        self.assertEqual(self.request("/api/canvas/rematch", bad_roster, side=1)[0], 400)
        self.assertTrue(self.canvas(1)["frame"]["is_over"])
        self.assertEqual(self.request("/api/canvas/rematch", args, side=1)[0], 200)
        second = self.canvas(1, after=first["position"])
        self.assertEqual(second["match_number"], 2)
        self.assertEqual(self.server.tokens[1], token)
        self.assertTrue(second["started"])
        self.assertFalse(second["frame"]["is_over"])
        self.assertEqual(second["history"][0], "第 2 局开始。")
        self.assertFalse(second["fx_events"])
        self.assertFalse(self.room.observe(1)["declarations"])
        self.assertEqual(self.roster(second), self.roster(first))
        self.assertGreater(second["revision"], first["revision"])
        self.assertEqual(self.request("/api/canvas/rematch", args, side=1)[0], 200)
        self.assertEqual(self.canvas(1)["match_number"], 2)

        second, _ = self.play_to_finish()
        self.command("canvas/rematch", second, roster=["blank_boss", "blank_boss"])
        third = self.canvas(1, after=second["position"])
        self.assertEqual(third["match_number"], 3)
        self.assertEqual(self.roster(third), ["blank_boss", "blank_boss"])
        self.assertEqual(self.canvas()["match_number"], 3)

    @staticmethod
    def roster(view):
        return [player["characters"][0]["id"] for player in view["frame"]["players"]]

    def test_asymmetric_duplicate_rosters_draw_play_and_rematch_in_the_same_room(self):
        lobby = self.canvas(1)
        self.command("canvas/ready", lobby, roster=[["waa_lake"], ["iron_qi_zheng"] * 5])
        opening = self.canvas(1)
        squad = opening["frame"]["players"][1]["characters"]
        self.assertEqual([c["printed_id"] for c in squad], ["iron_qi_zheng"] * 5)
        self.assertEqual(len({c["id"] for c in squad}), 5)
        self.command("canvas/target", opening, character_id=squad[-1]["id"])
        self.assertEqual(self.canvas(1)["default_targets"], {"1": squad[-1]["id"]})
        self.assertEqual(self.canvas()["default_targets"], {})
        first, _ = self.play_to_finish(max_steps=1600)
        draws = [event for event in first["fx_events"] if event["kind"] == "draw_bottom"]
        self.assertTrue(any(event["side"] == 2 and event["count"] == 4 for event in draws))

        self.command("canvas/rematch", first, roster=[["waa_lake"] * 7, ["iron_qi_zheng"]])
        for _ in range(20):
            opening = self.canvas(1)
            if draw := opening["frame"].get("draw_select"):
                break
            self.advance_beat(opening["frame"])
        else:
            self.fail("多人队伍未出现抽牌选择。")
        self.assertEqual((draw["keep"], draw["discard_count"]), (3, 6))
        second, _ = self.play_to_finish(max_steps=1600)
        self.assertEqual(second["match_number"], 2)
        players = second["frame"]["players"]
        self.assertEqual([len(p["characters"]) for p in players], [7, 1])

    def test_clones_keep_their_own_health_cards_and_identity(self):
        self.command("canvas/ready", self.canvas(1), roster=[["blank_boss"] * 7, ["blank_boss"] * 3])
        game = self.room.engine.game
        team = game.players[0].characters
        first, second = team[:2]
        self.assertIsNot(first, second)
        self.assertNotEqual(first.skills[0].instance_id, second.skills[0].instance_id)
        self.assertEqual(first.skills[0].id, second.skills[0].id)
        first.lose_hp(first.hp)
        self.assertFalse(first.is_alive)
        self.assertTrue(second.is_alive)
        self.assertEqual(second.hp, second.max_hp)
        self.assertFalse(game.is_over)

    def advance_beat(self, frame):
        self.assertIsNotNone(self.room._beat_timer, frame["mode"])
        with patch("battle_mcp.room.threading.current_thread", return_value=self.room._beat_timer):
            self.room._advance_beat()

    def play_to_finish(self, max_steps=400):
        priority = ("place", "attack", "intercept", "let_through", "end_attack", "end")
        saw_hidden_card = False
        for _ in range(max_steps):
            view = self.canvas(1)
            frame = view["frame"]
            self.assertEqual(frame["viewer_side"], 1)
            self.assertIsNone(frame["players"][1]["hand"])
            self.assertNotIn("card_owners", view)
            if not frame["cards_revealed"]:
                saw_hidden_card |= any(card.get("hidden") for slot in frame["duels"] for card in slot["sides"][1]["cards"])
            if frame["is_over"]:
                break
            if draw := frame.get("draw_select"):
                self.assertIsNone(self.canvas()["frame"].get("draw_select"))
                keys = [card["action_key"] for card in draw["candidates"]]
                self.assertEqual(len(keys), len(set(keys)))
                self.command("canvas/draw_bottom", view, card_ids=keys[:draw["discard_count"]])
                continue
            options = [move for move in view["options"] if move["kind"] in ORDINARY]
            if options:
                move = min(options, key=lambda m: priority.index(m["kind"]) if m["kind"] in priority else len(priority))
                self.command("act", view, option_id=move["id"])
            else:
                self.advance_beat(frame)
        else:
            self.fail("Canvas 房间未到终局。")

        return view, saw_hidden_card
