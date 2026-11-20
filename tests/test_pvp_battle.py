"""Play one online match through the same ordinary HTTP endpoints as two browsers."""

import io
import threading
import unittest
from contextlib import redirect_stdout
from itertools import count

from battle_mcp.room import Room
from battle_mcp.transport import ArenaServer
from tests.test_mcp_transport import WireClient


class PlayerMatchTests(WireClient, unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        room = Room(("ember_wen_sheng", "waa_lake"), seed=37, selectable=True)
        self.server = self.enterContext(ArenaServer(room, port=0))
        worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(self.server.shutdown)
        self.requests = count()

    def observe(self, side=None, **arguments):
        status, result = self.request("/api/observe", arguments, side=side)
        self.assertEqual(status, 200, result)
        return result

    def command(self, side, operation, **arguments):
        args = {"revision": self.observe(side)["revision"], "request_id": str(next(self.requests)), **arguments}
        status, result = self.request("/api/" + operation, args, side=side)
        self.assertEqual(status, 200, result)
        return result

    def play(self, side, kind, **fields):
        move = next(m for m in self.observe(side)["options"] if m["kind"] == kind
                    and all(m.get(key) == value for key, value in fields.items()))
        return self.command(side, "act", option_id=move["id"])

    def test_browser_follows_own_private_events_without_waking_agents_or_opponents(self):
        cursors = {side: self.observe(side)["cursor"] for side in (1, 2, None)}
        self.command(1, "prepare", declaration={"mode": "reserve", "event": "scores_ready",
                                               "match": {"kind": "special_replace"}})
        own_poll = {"cursor": cursors[1], "timeout": 0}
        status, update = self.request("/api/follow", own_poll, side=1)
        self.assertEqual(status, 200, update)
        self.assertEqual([entry["kind"] for entry in update["events"]], ["prepare"])
        for side, path in ((1, "/api/wait"), (2, "/api/follow"), (None, "/api/follow")):
            with self.subTest(side=side, path=path):
                args = {"cursor": cursors[side], "timeout": 0}
                status, response = self.request(path, args, side=side)
                self.assertEqual(status, 200, response)
                self.assertEqual(response, {"side": side, "cursor": cursors[side], "timeout": True})

    def test_selection_is_seat_scoped_and_locks_on_ready(self):
        initial = self.observe()
        self.assertEqual(initial["lobby"]["picks"], {"1": "ember_wen_sheng", "2": "waa_lake"})
        choices = {c["id"] for c in initial["lobby"]["characters"]}
        self.assertTrue({"mistport_cen_yao", "plan_b_annolin"} <= choices)
        args = {"character_id": "mistport_cen_yao", "revision": self.observe(1)["revision"], "request_id": "pick"}
        self.assertEqual(self.request("/api/select_character", args)[0], 403)
        self.assertEqual(self.request("/api/select_character", {**args, "side": 2}, side=1)[0], 400)
        self.assertEqual(self.observe()["lobby"]["picks"], initial["lobby"]["picks"])
        status, chosen = self.request("/api/select_character", args, side=1)
        self.assertEqual(status, 200, chosen)
        self.assertEqual(self.request("/api/select_character", args, side=1)[1]["revision"], chosen["revision"])
        self.assertEqual(self.observe(2)["lobby"]["picks"], {"1": "mistport_cen_yao", "2": "waa_lake"})
        self.command(1, "ready")
        for side, char_id in ((1, "waa_grolina"), (2, "mistport_cen_yao")):
            error, _ = self.request("/api/select_character",
                                    {**args, "character_id": char_id, "revision": self.observe(side)["revision"],
                                     "request_id": "refused"}, side=side)
            self.assertIn(error, (400, 409))
        self.assertEqual(self.observe()["ready_sides"], [1])
        self.assertFalse(self.observe()["started"])
        self.command(2, "select_character", character_id="plan_b_annolin")
        self.assertTrue(self.command(2, "ready")["started"])

    def test_two_browsers_reconnect_with_pending_intercepts_and_finish(self):
        self.command(1, "select_character", character_id="mistport_cen_yao")
        self.command(2, "select_character", character_id="plan_b_annolin")
        self.command(1, "ready")
        self.command(2, "ready")
        face_down = self.play(1, "place", card_id="cen_yao_fold_rule")
        own_cards = face_down["frame"]["duels"][0]["sides"][0]["cards"]
        self.assertEqual(own_cards[0]["id"], "cen_yao_fold_rule")
        for viewer in (2, None):
            other = self.observe(viewer)
            self.assertIsNone(other["frame"]["players"][0]["hand"])
            self.assertEqual(other["frame"]["duels"][0]["sides"][0]["cards"], [{"hidden": True}])
        self.play(2, "place")
        self.play(2, "end")
        self.play(1, "end")
        self.play(1, "attack", card_id="cen_yao_sounding", duel_number=1)

        # The second browser closes on an unanswered attack. Its opponent keeps placing.
        cursor = self.observe(2)["cursor"]
        invite_token = self.server.tokens[2]
        self.play(1, "attack", card_id="cen_yao_transit", duel_number=1)
        new_browser = WireClient()
        new_browser.server = self.server
        status, resumed = new_browser.request("/api/observe", {"cursor": cursor},
                                               Authorization="Bearer " + invite_token)
        self.assertEqual(status, 200, resumed)
        self.assertEqual(resumed["side"], 2)
        self.assertGreater(resumed["cursor"], cursor)
        self.assertTrue(resumed["events"])
        duels = resumed["frame"]["pre_reveal"]["duels"]
        self.assertEqual([(d["number"], d["ready"]) for d in duels], [(1, False), (2, False)])
        block = next(m for m in resumed["options"] if m["kind"] == "intercept" and m["response_number"] == 2)
        args = {"revision": resumed["revision"], "request_id": "reconnected-block", "option_id": block["id"]}
        status, updated = new_browser.request("/api/act", args, Authorization="Bearer " + invite_token)
        self.assertEqual(status, 200, updated)
        self.assertEqual([d["ready"] for d in self.observe()["frame"]["pre_reveal"]["duels"]], [False, True])

        for _ in range(180):
            public = self.observe()
            if public["finished"]:
                winner = public["winner_side"]
                self.assertIn(winner, (1, 2))
                self.assertEqual([self.observe(side)["winner_side"] for side in (1, 2)], [winner, winner])
                self.assertFalse(public["options"])
                return
            for side in (1, 2):
                options = self.observe(side)["options"]
                if options:
                    self.command(side, "act", option_id=options[0]["id"])
                    break
            else:
                self.fail("对局尚未结束，但两位玩家都没有行动。")
        self.fail("两台浏览器未能在 180 次操作内打到终局。")
