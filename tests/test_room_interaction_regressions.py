import io
import json
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from battle_mcp.challenges import CHALLENGES
from battle_mcp.declarations import select_moves, validate
from battle_mcp.room import Room, RoomConflict
from battle_mcp.transport import ArenaServer, invoke
from battle_mcp.ws import SimpleWebSocketClient
from tests.test_mcp_transport import WireClient


class RoomInteractionTests(WireClient, unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))

    def room(self, *args, **kwargs):
        room = Room(*args, **kwargs)
        self.addCleanup(room.close)
        return room

    def serve(self, room):
        self.server = ArenaServer(room, port=0)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.shutdown)

    def test_challenge_limits_player_and_failed_start_can_be_retried(self):
        room = self.room(challenge=CHALLENGES["carrier"], selectable=True, seed=1)
        room.update_rules(1, {"power_cap": 1}, 0, "cap")
        with self.assertRaisesRegex(ValueError, "超出"):
            room.ready(1, 0, "ready", team=["plan_b_heck"])
        self.assertFalse(room.started)
        self.assertEqual(room.seated, set())
        with patch.object(room, "_build_engine", side_effect=ValueError("不能开局")):
            with self.assertRaisesRegex(ValueError, "不能开局"):
                room.ready(1, 0, "ready", team=["plan_b_heris"], human=True, canvas=True)
        self.assertFalse(room.seated or room.human_seats or room.canvas_seats)
        room.ready(1, 0, "ready", team=["plan_b_heris"], human=True, canvas=True)
        state = room.canvas_state(1)
        self.assertTrue(state["started"])
        self.assertEqual(state["frame"]["turn"], 1)
        self.assertEqual(state["frame"]["players"][1]["characters"][0]["id"], "structured_carrier")

    def test_current_rosters_respect_visibility_and_ready_keeps_private_plans(self):
        room = self.room(["plan_b_annolin", "plan_b_heris"], selectable=True, seed=1)
        room.prepare(1, {"event": "turn_end", "mode": "reserve", "when": {"turn": 2}}, 0, "plan")
        room.ready(1, 0, "first")
        room.update_team(2, ["plan_b_heck"], 0, "pick")

        def roster(topic, side):
            players = invoke(room, "rules", side, {"topic": topic})["catalog"]["players"]
            return [[c["id"] for c in p["characters"]] for p in players]
        self.assertEqual(roster("briefing", 1), [["plan_b_annolin"], []])
        self.assertEqual(roster("catalog", 2), [[], ["plan_b_heck"]])
        room.update_rules(1, {"pick_mode": "open"}, 0, "public")
        self.assertEqual(roster("briefing", None), [["plan_b_annolin"], ["plan_b_heck"]])
        room.ready(2, 0, "second")
        self.assertEqual([p["id"] for p in room.observe(1)["declarations"]], ["p1"])
        self.assertFalse(room.observe(2)["declarations"])

    def test_hotseat_public_action_requires_handoff_to_only_eligible_player(self):
        room = self.room(["plan_b_annolin", "cang_feng_ji_lan"], seed=1, hotseat=True, start_immediately=True)
        for i in range(4):
            state = room.canvas_state(1, hotseat=True)
            if side := state["hotseat_handoff_side"]:
                room.hotseat_ready(side, state["revision"], str(i))
            else:
                end = next(m for m in state["options"] if m["kind"] == "end")
                room.act(1, end["id"], state["revision"], str(i), hotseat=True)
        public = room.canvas_state(1, hotseat=True)
        self.assertEqual(public["eligible_sides"], [2])
        curtain = room.pause(1, public["revision"], "pause", hotseat=True)
        self.assertIsNone(curtain["frame"]["viewer_side"])
        self.assertEqual(curtain["hotseat_handoff_side"], 2)
        self.assertFalse(any(p.get("hand") for p in curtain["frame"]["players"]))
        with self.assertRaises(ValueError):
            room.hotseat_ready(1, curtain["revision"], "wrong")
        private = room.hotseat_ready(2, curtain["revision"], "take")
        self.assertEqual(private["frame"]["viewer_side"], 2)
        self.assertTrue(private["frame"]["players"][1]["hand"])
        self.assertFalse(private["frame"]["players"][0].get("hand"))
        self.assertIsNone(room.resume(1, private["revision"], "resume", hotseat=True)["frame"]["viewer_side"])

    def test_mcp_draw_candidates_are_private_and_submit_once(self):
        room = self.room([["plan_b_annolin", "plan_b_heris"], ["plan_b_heck"]], seed=1)
        self.serve(room)

        def call(name, side, args):
            status, reply = self.call(name, args, side=side)
            self.assertEqual(status, 200)
            result = reply["result"]
            self.assertFalse(result["isError"], result)
            return json.loads(result["content"][0]["text"])

        for side in (1, 2):
            call("ready", side, {"revision": 0, "request_id": "start"})
        side, = room.engine.required_sides()
        view = call("observe", side, {})
        draw = view["frame"]["draw_select"]
        self.assertNotIn("draw_select", call("observe", 3 - side, {})["frame"])
        self.assertFalse(room.wait(side, 0, timeout=0).get("timeout"))
        args = dict(card_ids=[], revision=view["revision"], request_id="bottom")
        with self.assertRaises(ValueError):
            invoke(room, "draw_bottom", side, args)
        args["card_ids"] = [c["action_key"] for c in draw["candidates"][:draw["discard_count"]]]
        call("draw_bottom", side, args)
        after = call("draw_bottom", side, args)
        self.assertNotIn("draw_select", after["frame"])

    def test_delayed_concession_cannot_end_the_rematch(self):
        room = self.room(["plan_b_annolin", "plan_b_heck"], bot=True, seed=1, start_immediately=True)
        old = room.canvas_state(1)
        room.rematch(1, old["revision"], "again")
        for number in (None, old["match_number"]):
            with self.assertRaises(RoomConflict):
                room.concede(1, old["revision"], "late", match_number=number)
        self.assertFalse(room.engine.game_over)
        current = room.canvas_state(1)
        room.concede(1, current["revision"], "current", match_number=current["match_number"])
        self.assertTrue(room.engine.game_over)

    def test_deferred_replacement_only_matches_the_selected_copy(self):
        def move(instance):
            return {"kind": "special_replace", "card_id": "hand", "target_card_id": "board",
                    "effect_target": {"card": {"instance_id": instance}}}
        first, second = move(21), move(22)
        plan = validate({"event": "timing", "mode": "execute", "match": {
            "kind": "special_replace", "card_id": "hand", "target_card_id": "board", "target_instance_id": 22}})
        self.assertEqual(select_moves([first, second], plan["match"]), [second])
        self.assertEqual(select_moves([first], plan["match"]), [])

    def test_update_between_welcome_snapshot_and_push_worker_reaches_client(self):
        room = self.room(["plan_b_annolin", "plan_b_heris"], selectable=True, ruleset={"pick_mode": "open"})
        self.serve(room)
        snapshot = room.canvas_state

        def during_welcome(*args, **kwargs):
            initial = snapshot(*args, **kwargs)
            room.update_team(2, ["plan_b_heck"], 0, "pick")
            return initial

        with patch.object(room, "canvas_state", side_effect=during_welcome):
            client = SimpleWebSocketClient("127.0.0.1", self.server.server_port, "/ws")
            self.addCleanup(client.close)
            client.send_json({"type": "auth", "token": self.server.tokens[1]})
            first = client.recv_json()
            self.assertEqual(first["state"]["lobby_state"]["picks"]["2"], ["plan_b_heris"])
            second = client.recv_json()
            self.assertEqual(second["type"], "state")
            self.assertEqual(second["state"]["lobby_state"]["picks"]["2"], ["plan_b_heck"])
