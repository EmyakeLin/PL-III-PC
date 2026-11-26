"""Mode selection, private invitations and simultaneous unified Room tables on one listener."""
import http.client
import io
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from urllib.parse import parse_qs, urljoin, urlsplit
from unittest.mock import patch

from battle_mcp.bot import choose_move
from battle_mcp.__main__ import serve_local_game
from battle_mcp.challenges import CHALLENGES, Challenge
from battle_mcp.room import Room
from battle_mcp.transport import ArenaServer
from tests.test_mcp_transport import WireClient


class LobbyTests(WireClient, unittest.TestCase):
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
        self.assertEqual(invite.path, prefix + "/canvas/")
        token, = parse_qs(invite.fragment)["token"]
        return prefix, {"Authorization": "Bearer " + token}

    def read_canvas(self, path, auth):
        return self.request(path + "/api/canvas/state", {}, **auth)

    def cmd(self, path, auth, cmd_name, *, revision=0, req_id="req-1", **kwargs):
        return self.request(path + "/api/canvas/cmd", {"cmd": cmd_name, "revision": revision, "request_id": req_id, **kwargs}, **auth)

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

    def test_direct_launch_uses_lobby_lineup_or_starts_a_room_table(self):
        for roster in (None, ["emyake_lin_yu", "lan_qing"]):
            with self.subTest(roster=roster), patch.object(ArenaServer, "serve_forever"), redirect_stdout(io.StringIO()) as log:
                serve_local_game("lan_qing", challenge=True, roster=roster, seed=37)
                link = urlsplit(log.getvalue().split("玩家 1 入口  ")[1].strip())
                if roster:
                    self.assertRegex(link.path, r"^/rooms/[a-f0-9]+/canvas/$")
                    self.assertIn("token", parse_qs(link.fragment))
                else:
                    self.assertEqual(link.path, "/lobby/")
                    self.assertEqual(parse_qs(link.query), {"mode": ["challenge"], "variant": ["lan_qing"]})

    def test_lineup_preview_has_printed_skills_presets_and_never_opens_a_room(self):
        with patch("battle_mcp.hosting.HostedRoom") as open_room:
            for mode, variant in (("regular", "online"), ("regular", "hotseat"), ("regular", "solo"), ("challenge", "carrier")):
                status, data = self.request(f"/api/lineup?mode={mode}&variant={variant}", method="GET")
                self.assertEqual(status, 200)
                by_id = {c["id"]: c for c in data["catalog"]}
                self.assertTrue(by_id["plan_b_annolin"]["skills"])
                self.assertIn("power", by_id["plan_b_annolin"])
                self.assertEqual("structured_carrier" in by_id, variant == "carrier")
                self.assertEqual(data["fixed_opponents"], ["structured_carrier"] if variant == "carrier" else [])
                self.assertEqual(data["hotseat"], variant == "hotseat")
                self.assertEqual(data["online"], variant == "online")
            self.assertEqual(self.request("/api/lineup?mode=limit_battle", method="GET")[0], 501)
            open_room.assert_not_called()

    def test_confirming_a_lineup_starts_exactly_the_selected_teams(self):
        for mode, variant, teams in (
                ("regular", "hotseat", [["plan_b_heck"], ["plan_b_annolin", "plan_b_heris"]]),
                ("regular", "solo", [["plan_b_heris", "plan_b_heris"], ["plan_b_heck"]]),
                ("challenge", "carrier", [["plan_b_annolin", "plan_b_heck"], ["structured_carrier"]])):
            path, key = self.create(mode, variant, roster=teams)
            status, state = self.read_canvas(path, key)
            self.assertEqual(status, 200)
            self.assertTrue(state["started"])
            self.assertEqual(state["bot_side"], None if variant == "hotseat" else 2)
            self.assertEqual([[c["printed_id"] for c in p["characters"]] for p in state["frame"]["players"]], teams)
        for teams in (([], ["structured_carrier"]), (["structured_carrier"], ["structured_carrier"]),
                      (["plan_b_annolin"], ["lan_qing"])):
            self.assertEqual(self.request("/api/rooms", {"mode": "challenge", "variant": "carrier",
                                                         "roster": teams})[0], 400)

    def test_catalog_reserved_modes_and_invalid_variants(self):
        status, modes = self.request("/api/modes", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual([m["name"] for m in modes], ["常规对战", "挑战模式", "界限战斗", "砺战合约"])
        self.assertEqual([v["id"] for v in modes[0]["variants"]], ["online", "solo", "hotseat"])
        self.assertEqual({v["id"] for v in modes[1]["variants"]}, set(CHALLENGES))
        for mode in modes[2:]:
            self.assertFalse(mode["available"])
            self.assertEqual(mode["variants"], [])
            self.assertEqual(self.request("/api/rooms", {"mode": mode["id"]})[0], 501)
        for spec in ([], {}, {"mode": "unknown"}, {"mode": "regular", "variant": "carrier"},
                     {"mode": "challenge", "variant": []}, {"mode": "challenge", "variant": "unknown"}):
            self.assertEqual(self.request("/api/rooms", spec)[0], 400)

    def test_simultaneous_hotseat_solo_and_challenges_keep_independent_games_and_seats(self):
        variants = (
            ("regular", "hotseat", [["plan_b_annolin"], ["plan_b_heck"]]),
            ("regular", "solo", [["plan_b_annolin"], ["plan_b_heck"]]),
            ("challenge", "carrier", [["plan_b_annolin"], ["structured_carrier"]]),
            ("challenge", "lan_qing", [["plan_b_annolin"], ["lan_qing"]]),
        )
        with ThreadPoolExecutor(max_workers=4) as executor:
            tables = list(executor.map(lambda item: self.create(item[0], item[1], roster=item[2]), variants))
        self.assertEqual(len({path for path, _ in tables}), 4)
        (table, key), (solo, solo_key), (boss, boss_key), (lan, lan_key) = tables
        self.assertEqual(self.read_canvas(boss, solo_key)[0], 403)
        _, initial = self.read_canvas(table, key)
        _, carrier = self.read_canvas(boss, boss_key)
        _, original_lan = self.read_canvas(lan, lan_key)
        self.assertEqual(original_lan["challenge"], "幽蓝残雪·澜清")
        status, rematched = self.cmd(
            boss, boss_key, "rematch",
            revision=carrier["revision"], req_id="rem-1",
            roster=[["plan_b_heck"], ["structured_carrier"]],
        )
        self.assertEqual((status, rematched["match_number"]), (200, 2))
        self.assertEqual(self.read_canvas(table, key)[1]["position"], initial["position"])
        self.assertEqual(self.read_canvas(lan, lan_key)[1]["position"], original_lan["position"])
        self.assertEqual(self.request("/api" + boss, method="DELETE", **solo_key)[0], 403)
        self.assertEqual(self.request("/api" + boss, method="DELETE", **boss_key)[0], 204)
        self.assertEqual(self.read_canvas(boss, boss_key)[0], 404)
        self.assertEqual(self.read_canvas(solo, solo_key)[1]["bot_side"], 2)

    def test_scripted_team_is_locked_in_order_on_rematch(self):
        team = Challenge("测试小队", "plan_b_annolin", choose_move, teammates=("lan_qing",))
        with patch.dict(CHALLENGES, test_team=team):
            path, key = self.create("challenge", "test_team", roster=[["plan_b_heck"], list(team.opponents)])
            _, state = self.read_canvas(path, key)
            for idx, opponent in enumerate((list(reversed(team.opponents)), ["lan_qing"])):
                code, _ = self.cmd(path, key, "rematch", revision=state["revision"], req_id=f"bad-{idx}", roster=[["plan_b_heck"], opponent])
                self.assertEqual(code, 400)
            status, again = self.cmd(path, key, "rematch", revision=state["revision"], req_id="ok-rem", roster=[["plan_b_heris"], list(team.opponents)])
            self.assertEqual((status, again["match_number"]), (200, 2))
            self.assertEqual([c["printed_id"] for c in again["frame"]["players"][1]["characters"]], list(team.opponents))

    def test_lan_qing_challenge_stages_and_unstages_on_unified_room(self):
        path, key = self.create("challenge", "lan_qing", roster=[["emyake_lin_yu"], ["lan_qing"]])
        _, state = self.read_canvas(path, key)
        for idx in range(50):
            if state["frame"]["mode"] == "placement" and any(m["kind"] == "end" for m in state["options"]):
                break
            _, state = self.cmd(path, key, "next", revision=state["revision"], req_id=f"n-{idx}")
        self.assertTrue(state["pre_reveal_eligible_cards"])
        card = state["pre_reveal_eligible_cards"][0]
        target = {"kind": "character", "id": "lan_qing"}
        _, state = self.cmd(path, key, "claim_pre_reveal", revision=state["revision"], req_id="claim-1")
        _, state = self.cmd(path, key, "stage_pre_reveal", revision=state["revision"], req_id="stage-1", card_id=card, target=target)
        self.assertEqual([(p["card_id"], p["target"]) for p in state["pre_reveal_plan"]], [(card, target)])
        place_ids = [m["card_id"] for m in state["options"] if m["kind"] == "place"]
        self.assertNotIn(card, place_ids)
        _, state = self.cmd(path, key, "unstage_pre_reveal", revision=state["revision"], req_id="unstage-1", card_id=card)
        self.assertEqual(state["pre_reveal_plan"], [])
        self.assertIn(card, state["pre_reveal_eligible_cards"])

    def test_play_and_rematch_all_scripted_challenges(self):
        for variant, challenge in CHALLENGES.items():
            with self.subTest(variant=variant):
                teams = [["emyake_lin_yu"], list(challenge.opponents)]
                room = Room(teams, seed=37, bot=True, challenge=challenge, start_immediately=True)
                for idx in range(1500):
                    state = room.canvas_state(1)
                    if state["frame"]["is_over"]:
                        break
                    self.assertIsNone(state["frame"]["players"][1]["hand"])
                    opts = state["options"]
                    if draw := state["frame"].get("draw_select"):
                        ids = [c["action_key"] for c in draw["candidates"][:draw["discard_count"]]]
                        room.draw_bottom(1, ids, state["revision"], f"db-{idx}")
                    elif opts:
                        preferred = (
                            next((m for m in opts if m["kind"] == "place"), None)
                            or next((m for m in opts if m["kind"] in ("let_through", "end_attack", "end", "special_pass_intercept", "decline")), None)
                            or opts[0]
                        )
                        room.act(1, preferred["id"], state["revision"], f"act-{idx}")
                    elif state["can_advance"]:
                        room.next_beat(1, state["revision"], f"nx-{idx}")
                    else:
                        break
                self.assertTrue(room.engine.game_over)
                rec = room.battle_record()
                self.assertEqual((rec["match_number"], rec["finished"]), (1, True))
                room.rematch(1, room.canvas_state(1)["revision"], "rem-1", roster=teams)
                self.assertEqual(room.canvas_state(1)["match_number"], 2)


if __name__ == "__main__":
    unittest.main()
