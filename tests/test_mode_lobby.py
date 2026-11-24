"""Mode selection, private invitations and simultaneous tables on one listener."""
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
from battle_mcp.transport import ArenaServer
from battle_ui.session import BattleSession
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
        self.assertEqual(invite.path, prefix + "/table/")
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

    def test_direct_launch_uses_lobby_lineup_or_starts_a_local_table(self):
        for roster in (None, ["emyake_lin_yu", "lan_qing"]):
            with self.subTest(roster=roster), patch.object(ArenaServer, "serve_forever"), redirect_stdout(io.StringIO()) as log:
                serve_local_game("lan_qing", challenge=True, roster=roster, seed=37)
                link = urlsplit(log.getvalue().split("玩家 1 入口  ")[1].strip())
                if roster:
                    self.assertRegex(link.path, r"^/rooms/[a-f0-9]+/table/$")
                    self.assertIn("token", parse_qs(link.fragment))
                else:
                    self.assertEqual(link.path, "/lobby/")
                    self.assertEqual(parse_qs(link.query), {"mode": ["challenge"], "variant": ["lan_qing"]})

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
            status, state = self.request(path + "/api/state", method="GET", **key)
            self.assertEqual(status, 200)
            self.assertEqual(state["ai_side"], None if variant == "hotseat" else 2)
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
        def read(path, auth):
            return self.request(path + "/api/state", method="GET", **auth)
        self.assertEqual(read(table, {})[0], 403)
        self.assertEqual(read(boss, solo_key)[0], 403)
        self.assertEqual(read(boss, {})[0], 403)
        _, initial = read(table, key)
        _, carrier = read(boss, boss_key)
        _, original_lan = read(lan, lan_key)
        self.assertEqual(original_lan["challenge"], "幽兰残雪·澜清")
        args = {"revision": carrier["revision"], "action": "new", "roster": [["plan_b_annolin"], ["structured_carrier"]]}
        self.assertEqual(self.request(boss + "/api/action", args, **boss_key)[1]["match_number"], 2)
        self.assertEqual(read(table, key)[1], initial)
        self.assertEqual(read(lan, lan_key)[1], original_lan)
        self.assertEqual(self.request("/api" + boss, method="DELETE", **solo_key)[0], 403)
        self.assertEqual(self.request("/api" + boss, method="DELETE", **boss_key)[0], 204)
        self.assertEqual(read(boss, boss_key)[0], 404)
        self.assertEqual(read(solo, solo_key)[1]["ai_side"], 2)

    def test_scripted_team_is_locked_in_order_on_new_game(self):
        team = Challenge("测试小队", "plan_b_annolin", choose_move, teammates=("lan_qing",))
        with patch.dict(CHALLENGES, test_team=team):
            path, key = self.create("challenge", "test_team")
        _, state = self.request(path + "/api/state", method="GET", **key)
        players = state["frame"]["players"]
        self.assertNotIn(players[0]["characters"][0]["printed_id"], team.opponents)
        self.assertEqual([c["printed_id"] for c in players[1]["characters"]], list(team.opponents))
        args = {"revision": state["revision"], "action": "new"}
        for opponent in (list(reversed(team.opponents)), ["lan_qing"]):
            self.assertEqual(self.request(path + "/api/action", {**args, "roster": [["plan_b_heck"], opponent]}, **key)[0], 400)
        status, again = self.request(path + "/api/action", {**args, "roster": [["plan_b_heck"], list(team.opponents)]}, **key)
        self.assertEqual((status, again["match_number"]), (200, 2))
        self.assertEqual([c["printed_id"] for c in again["frame"]["players"][1]["characters"]], list(team.opponents))

    def test_lobby_solo_uses_the_standalone_ai_table_and_actions(self):
        teams = [["emyake_lin_yu"], ["lan_qing"]]
        path, key = self.create("regular", "solo", roster=teams)
        reference = BattleSession(seed=37, ai_side=2, roster=teams)
        _, live = self.request(path + "/api/state", method="GET", **key)
        direct = reference.state()
        for _ in range(50):
            for field in ("mode", "active_side", "legal_cards", "pre_reveal_claimed", "pre_reveal_eligible_cards",
                          "pre_reveal_stage_targets", "card_owners"):
                self.assertEqual(live[field], direct[field], field)
            if live["mode"] == "placement":
                break
            _, live = self.request(path + "/api/action", {"action": "next", "revision": live["revision"]}, **key)
            _, direct = reference.command({"action": "next", "revision": direct["revision"]})
        self.assertEqual(live["mode"], "placement")
        self.assertTrue(live["pre_reveal_eligible_cards"])

    def test_lan_qing_challenge_stages_and_unstages_on_the_local_table(self):
        path, key = self.create("challenge", "lan_qing", roster=[["emyake_lin_yu"], ["lan_qing"]])
        _, state = self.request(path + "/api/state", method="GET", **key)
        def act(action, **kwargs):
            code, result = self.request(path + "/api/action", {"revision": state["revision"], "action": action, **kwargs}, **key)
            self.assertEqual(code, 200, result)
            return result
        for _ in range(50):
            if state["mode"] == "placement":
                break
            state = act("next")
        card = state["pre_reveal_eligible_cards"][0]
        target = {"kind": "character", "id": "lan_qing"}
        state = act("claim_pre_reveal")
        state = act("stage_pre_reveal", card_id=card, target=target)
        self.assertEqual([(p["card_id"], p["target"]) for p in state["pre_reveal_plan"]], [(card, target)])
        self.assertNotIn(card, state["legal_cards"])
        state = act("unstage_pre_reveal", card_id=card)
        self.assertEqual(state["pre_reveal_plan"], [])
        self.assertIn(card, state["pre_reveal_eligible_cards"])

    def test_ai_answers_the_specific_interception_and_pending_special(self):
        table = BattleSession(ai_side=2, seed=37)
        snap = {"active_side": 2, "mode": "intercept", "pending_responses": [1, 2],
                "legal_intercept_cards": ["late"], "intercepts_by_number": {1: [], 2: ["late"]},
                "frame": {"players": [{"side": 2, "hand": [{"id": "late", "cost": 0}]}]}}
        with patch.object(table.match, "act") as act:
            self.assertTrue(table._ai_step(snap))
            act.assert_called_once_with("let_through", table.match.revision, duel_number=1)
            self.assertTrue(table._ai_step({"active_side": 2, "mode": "special", "special_pending": True,
                                           "special_options": [{"kind": "intercept"}, {"kind": "pass_intercept"}]}))
            act.assert_called_with("use_special", table.match.revision, option=1)

    def test_play_and_rematch_both_scripted_challenges_from_their_own_invitations(self):
        for variant, challenge in CHALLENGES.items():
            with self.subTest(variant=variant):
                teams = [["emyake_lin_yu"], list(challenge.opponents)]
                path, key = self.create("challenge", variant, roster=teams)
                session = self.server.lobby.get(path.split("/")[-1]).room
                state = session.state()
                for _ in range(2000):
                    mode = state["mode"]
                    self.assertNotEqual(state["active_side"], 2)
                    self.assertIsNone(state["frame"]["players"][1]["hand"])
                    if mode == "finished":
                        break
                    if mode == "placement":
                        cards = state["legal_cards"]
                        command = {"action": "place", "card_id": cards[0]} if cards else {"action": "end"}
                    elif mode == "intercept":
                        command = {"action": "let_through", "duel_number": state["pending_responses"][0]}
                    elif mode == "pre_attack":
                        command = {"action": "end_attack"}
                    elif mode == "special":
                        command = {"action": "use_special", "option": 0} if state["special_pending"] else {"action": "leave_special"}
                    else:
                        command = {"action": "next"}
                    _, state = session.command({**command, "revision": state["revision"]})
                self.assertEqual(state["mode"], "finished")
                self.assertEqual(self.request(path + "/api/battle_record", method="GET")[0], 403)
                status, record = self.request(path + "/api/battle_record", method="GET", **key)
                self.assertEqual((status, record["match_number"], record["finished"]), (200, 1, True))
                self.assertEqual(record["history"][-100:], state["history"])
                status, again = self.request(path + "/api/action", {"action": "new", "roster": teams, "revision": state["revision"]}, **key)
                self.assertEqual((status, again["match_number"], again["challenge"]), (200, 2, challenge.name))
