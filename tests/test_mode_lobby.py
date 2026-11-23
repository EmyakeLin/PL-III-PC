"""Mode selection, private invitations and simultaneous tables on one listener."""
import http.client
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urljoin, urlsplit
from unittest.mock import patch

from battle_mcp.bot import choose_move
from battle_mcp.challenges import CHALLENGES, Challenge
from battle_mcp.transport import ArenaServer
from tests.test_carrier_challenge import PlaysChallenge
from tests.test_mcp_transport import WireClient


class LobbyTests(PlaysChallenge, WireClient, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ArenaServer(port=0, seed=37)
        worker = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(worker.join)
        cls.addClassCleanup(cls.server.shutdown)

    def create(self, mode, variant, **setup):
        status, created = self.request("/api/rooms", {"mode": mode, "variant": variant, **setup})
        self.assertEqual(status, 201, created)
        invite = urlsplit(created["play_url"])
        prefix = "/rooms/" + created["id"]
        self.assertEqual(invite.path, prefix + ("/table/" if variant == "hotseat" else "/canvas/"))
        token, = parse_qs(invite.fragment)["token"]
        return prefix, {"Authorization": "Bearer " + token}

    def test_lobby_entry_serves_game_canvas_and_shared_picker(self):
        def asset(path, content_type):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(response.status, 200, path)
                self.assertEqual(response.getheader("Content-Type").split(";")[0], content_type, path)
                return response.read()
            finally:
                connection.close()

        root = asset("/", "text/html")
        self.assertEqual(root, asset("/lobby/", "text/html"))
        self.assertIn(b'<canvas id="pixi-canvas"', root)
        self.assertIn(b'src="/lobby/engine/lobby.js"', root)
        menu = asset("/lobby/engine/lobby.js", "text/javascript")
        for module in ("./table_overlays.js", "./card_print.js", "./stage_actors.js",
                       "./lobby_rooms.js", "../vendor/pixi.min.mjs"):
            self.assertIn(module.encode(), menu)
            self.assertTrue(asset(urljoin("/lobby/engine/lobby.js", module), "text/javascript"))

    def test_lineup_preview_has_printed_skills_and_never_opens_a_room(self):
        with patch("battle_mcp.hosting.HostedRoom") as open_room:
            for mode, variant in (("regular", "hotseat"), ("regular", "solo"), ("challenge", "carrier")):
                status, data = self.request(f"/api/lineup?mode={mode}&variant={variant}", method="GET")
                self.assertEqual(status, 200)
                by_id = {c["id"]: c for c in data["catalog"]}
                self.assertTrue(by_id["plan_b_annolin"]["skills"])
                self.assertEqual("structured_carrier" in by_id, variant == "carrier")
                self.assertEqual(data["fixed_opponents"], ["structured_carrier"] if variant == "carrier" else [])
                self.assertEqual(data["hotseat"], variant == "hotseat")
            self.assertEqual(self.request("/api/lineup?mode=limit_battle", method="GET")[0], 501)
            open_room.assert_not_called()

    def test_confirming_a_lineup_starts_exactly_the_selected_teams(self):
        for mode, variant, teams in (
                ("regular", "hotseat", [["plan_b_heck"], ["plan_b_annolin", "plan_b_heris"]]),
                ("regular", "solo", [["plan_b_heris", "plan_b_heris"], ["plan_b_heck"]]),
                ("challenge", "carrier", [["plan_b_annolin", "plan_b_heck"], ["structured_carrier"]])):
            path, key = self.create(mode, variant, roster=teams)
            if variant == "hotseat":
                _, state = self.request(path + "/api/state", method="GET", **key)
            else:
                _, state = self.request(path + "/api/canvas/state", {}, **key)
                self.assertTrue(state["started"])
            self.assertEqual([[c["printed_id"] for c in p["characters"]] for p in state["frame"]["players"]], teams)
        for teams in (([], ["structured_carrier"]), (["structured_carrier"], ["structured_carrier"]),
                      (["plan_b_annolin"], ["lan_qing"])):
            self.assertEqual(self.request("/api/rooms", {"mode": "challenge", "variant": "carrier",
                                                         "roster": teams})[0], 400)

    def test_catalog_reserved_modes_and_invalid_variants(self):
        status, modes = self.request("/api/modes", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual([m["name"] for m in modes], ["常规对战", "挑战模式", "界限战斗", "砺战合约"])
        self.assertEqual([v["id"] for v in modes[0]["variants"]], ["hotseat", "solo"])
        self.assertEqual({v["id"] for v in modes[1]["variants"]}, set(CHALLENGES))
        for mode in modes[2:]:
            self.assertFalse(mode["available"])
            self.assertEqual(mode["variants"], [])
            self.assertEqual(self.request("/api/rooms", {"mode": mode["id"]})[0], 501)
        for spec in ([], {}, {"mode": "unknown"}, {"mode": "regular", "variant": "carrier"},
                     {"mode": "challenge", "variant": []}, {"mode": "challenge", "variant": "unknown"}):
            self.assertEqual(self.request("/api/rooms", spec)[0], 400)

    def test_simultaneous_hotseat_solo_and_challenges_keep_independent_games_and_seats(self):
        variants = (("regular", "hotseat"), ("regular", "solo"), ("challenge", "carrier"), ("challenge", "lan_qing"))
        with ThreadPoolExecutor(max_workers=4) as executor:
            tables = list(executor.map(lambda pair: self.create(*pair), variants))
        self.assertEqual(len({path for path, _ in tables}), 4)
        (table, key), (solo, solo_key), (boss, boss_key), (lan, lan_key) = tables
        state = "/api/canvas/state"
        start = "/api/canvas/ready"
        self.assertEqual(self.request(table + "/api/state", method="GET")[0], 403)
        status, initial = self.request(table + "/api/state", method="GET", **key)
        self.assertEqual(status, 200)
        play = {"action": "place", "card_id": initial["legal_cards"][0], "revision": initial["revision"]}
        status, handoff = self.request(table + "/api/action", play, **key)
        self.assertEqual((status, handoff["mode"]), (200, "handoff"))
        self.assertTrue(all(p["hand"] is None for p in handoff["frame"]["players"]))
        self.assertEqual(self.request(boss + state, {}, **solo_key)[0], 403)
        self.assertEqual(self.request(boss + state, {})[1]["side"], None)
        self.assertEqual(self.request(solo + state, {}, **solo_key)[1]["challenge"], None)
        args = {"revision": 0, "request_id": "ready", "roster": [["plan_b_annolin"], ["structured_carrier"]]}
        self.assertEqual(self.request(boss + start, args, **boss_key)[0], 200)
        self.assertTrue(self.request(boss + state, {}, **boss_key)[1]["started"])
        self.assertFalse(self.request(lan + state, {}, **lan_key)[1]["started"])
        self.assertEqual(self.request(table + "/api/state", method="GET", **key)[1], handoff)
        close = "/api" + boss
        self.assertEqual(self.request(close, method="DELETE", **solo_key)[0], 403)
        self.assertEqual(self.request(close, method="DELETE", **boss_key)[0], 204)
        self.assertEqual(self.request(boss + state, {}, **boss_key)[0], 404)
        self.assertEqual(self.request(lan + state, {}, **lan_key)[1]["challenge"], "幽兰残雪·澜清")
        self.assertEqual(self.request(solo + start, {**args, "roster": [["plan_b_annolin"], ["plan_b_heck"]]},
                                      **solo_key)[0], 200)

    def test_scripted_team_is_locked_in_order_through_ready_and_rematch(self):
        team = Challenge("测试小队", "plan_b_annolin", choose_move, teammates=("lan_qing",))
        with patch.dict(CHALLENGES, test_team=team):
            path, key = self.create("challenge", "test_team")
        state = self.request(path + "/api/canvas/state", {}, **key)[1]
        players = state["frame"]["players"]
        self.assertEqual([c["printed_id"] for c in players[1]["characters"]], list(team.opponents))
        self.assertNotIn(players[0]["characters"][0]["printed_id"], team.opponents)
        args = {"revision": state["revision"], "request_id": "start"}
        for opponent in (list(reversed(team.opponents)), ["lan_qing"]):
            self.assertEqual(self.request(path + "/api/canvas/ready",
                             {**args, "roster": [["plan_b_heck"], opponent]}, **key)[0], 400)
        self.assertEqual(self.request(path + "/api/canvas/ready",
                         {**args, "roster": [["plan_b_heck"], list(team.opponents)]}, **key)[0], 200)
        state = self.request(path + "/api/canvas/state", {}, **key)[1]
        again = {"revision": state["revision"], "request_id": "restart"}
        self.assertEqual(self.request(path + "/api/canvas/rematch",
                         {**again, "roster": [["plan_b_heck"], ["lan_qing"]]}, **key)[0], 400)
        self.assertEqual(self.request(path + "/api/canvas/rematch", again, **key)[0], 200)
        state = self.request(path + "/api/canvas/state", {}, **key)[1]
        self.assertEqual(state["match_number"], 2)
        self.assertEqual([c["printed_id"] for c in state["frame"]["players"][1]["characters"]], list(team.opponents))

    def test_play_and_rematch_both_scripted_challenges_from_their_own_invitations(self):
        for variant, challenge in CHALLENGES.items():
            with self.subTest(variant=variant):
                path, key = self.create("challenge", variant)
                self.play(challenge, ["plan_b_annolin", "plan_b_heris"], prefix=path, credentials=key)
