"""A real TCP client per seat, using MCP and the browser JSON API together."""

import http.client
import io
import json
import threading
import unittest
from contextlib import redirect_stdout

from battle_mcp.transport import ArenaServer


class SeatEcho:
    """Observe which seat the server passes to the room, independently of game state."""

    def observe(self, side, cursor=None):
        return {"side": side, "hand": [f"seat-{side}-private"] if side else []}

    def ready(self, side, revision, request_id):
        return {"side": side, "request_id": request_id}

    def rules(self, topic=None):
        return {"topic": topic}

    def close(self):
        pass


class WireClient:
    def request(self, path, body=None, *, side=None, method="POST", **headers):
        fields = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if side:
            fields["Authorization"] = "Bearer " + self.server.tokens[side]
        fields.update(headers)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, None if body is None else json.dumps(body), fields)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            connection.close()

    def rpc(self, method, params=None, *, side=None, **headers):
        return self.request("/mcp", {"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}},
                            side=side, **headers)

    def call(self, name, arguments=None, *, side=None):
        return self.rpc("tools/call", {"name": name, "arguments": arguments or {}}, side=side)


class TransportTests(WireClient, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ArenaServer(SeatEcho(), port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def test_streamable_http_handshake_and_stateless_json_results(self):
        init = {"protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "match-player", "version": "1.0"}}
        status, reply = self.rpc("initialize", init, side=1)
        self.assertEqual(status, 200)
        self.assertEqual(reply["id"], 7)
        self.assertEqual(reply["result"]["protocolVersion"], "2025-11-25")
        self.assertIn("tools", reply["result"]["capabilities"])
        for topic in ("briefing", "full", "catalog"):
            self.assertIn(topic, reply["result"]["instructions"])
        self.assertEqual(self.request("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                      side=1), (202, None))
        self.assertEqual(self.request("/mcp", method="GET"), (405, None))
        self.assertEqual(self.rpc("ping")[1]["result"], {})
        self.assertEqual(self.rpc("tools/list", **{"MCP-Protocol-Version": "invalid"})[0], 400)
        private_tools = self.rpc("tools/list", side=1)[1]["result"]["tools"]
        public_tools = self.rpc("tools/list")[1]["result"]["tools"]
        self.assertEqual({t["name"] for t in private_tools}, {"observe", "ready", "prepare", "act", "wait", "rules"})
        self.assertEqual({t["name"] for t in public_tools}, {"observe", "wait", "rules"})
        descriptions = {t["name"]: t["description"] for t in private_tools}
        for topic in ("briefing", "full", "catalog"):
            self.assertIn(topic, descriptions["rules"])
            self.assertIn(topic, descriptions["ready"])
        self.assertEqual(self.rpc("missing")[1]["error"]["code"], -32601)

    def test_two_agents_and_spectator_only_receive_their_view(self):
        for side in (1, 2, None):
            with self.subTest(side=side):
                status, result = self.call("observe", side=side)
                self.assertEqual(status, 200)
                value = json.loads(result["result"]["content"][0]["text"])
                status, browser = self.request("/api/observe", {}, side=side)
                self.assertEqual((value, status), (browser, 200))
                self.assertEqual(value["side"], side)
                self.assertEqual(value["hand"], [f"seat-{side}-private"] if side else [])
        args = {"revision": 0, "request_id": "ready-at-0"}
        self.assertEqual(self.request("/api/ready", args)[0], 403)
        self.assertIn("error", self.call("ready", args)[1])
        self.assertEqual(self.request("/api/ready", args, side=2)[1]["side"], 2)
        self.assertEqual(self.request("/api/observe", {"side": 2}, side=1)[0], 400)
        self.assertEqual(self.call("observe", {"side": 2}, side=1)[1]["error"]["code"], -32602)

    def test_http_boundary_and_invalid_private_credentials(self):
        self.assertEqual(self.request("/api/observe", {}, Origin="http://unknown.invalid")[0], 403)
        self.assertEqual(self.request("/api/observe", {}, Host="unknown.invalid")[0], 403)
        self.assertEqual(self.request("/api/observe", {}, Authorization="Bearer wrong")[0], 403)
        status, error = self.request("/api/observe", Authorization="Bearer wrong",
                                     **{"Content-Type": "text/plain", "Content-Length": "65536"})
        self.assertEqual((status, error["error"]), (403, "席位凭据无效。"))
        self.assertEqual(self.request("/api/observe", **{"Content-Length": "65537"})[0], 413)
        self.assertEqual(self.request("/api/observe", [], side=1)[0], 400)
        self.assertEqual(self.request("/api/observe", {"cursor": True}, side=1)[0], 400)
        self.assertEqual(self.request("/api/ready", {"revision": 0}, side=1)[0], 400)
        self.assertEqual(self.request("/api/wait", {"cursor": 0, "timeout": 9999}, side=1)[0], 400)
        self.assertEqual(self.request("/mcp", {"method": "ping"})[1]["error"]["code"], -32600)


class MatchOverWireTests(WireClient, unittest.TestCase):
    def play(self, browser_seat):
        from battle_mcp.room import Room
        room = Room(["ember_wen_sheng", "plan_b_annolin"], seed=1125)
        with ArenaServer(room, port=0) as self.server, redirect_stdout(io.StringIO()):
            thread = threading.Thread(target=self.server.serve_forever,
                                      kwargs={"poll_interval": 0.01}, daemon=True)
            thread.start()
            try:
                return self.play_seats(browser_seat)
            finally:
                self.server.shutdown()
                thread.join(2)

    def play_seats(self, browser_seat):
        def invoke(seat, name, args=None):
            if seat == browser_seat:
                status, value = self.request("/api/" + name, args or {}, side=seat)
                self.assertEqual(status, 200, value)
                return value
            status, reply = self.call(name, args or {}, side=seat)
            self.assertEqual(status, 200, reply)
            self.assertNotIn("error", reply)
            self.assertFalse(reply["result"]["isError"], reply)
            return json.loads(reply["result"]["content"][0]["text"])

        briefing = invoke(1, "rules", {"topic": "briefing"})
        full = invoke(2, "rules", {"topic": "full"})
        self.assertEqual(briefing["version"], full["version"])
        self.assertIn(briefing["sections"][0]["text"], full["text"])
        self.assertEqual(briefing["catalog"], invoke(2, "rules", {"topic": "catalog"})["catalog"])
        for seat in (1, 2):
            state = invoke(seat, "observe")
            if seat == 1:
                declaration = {"mode": "reserve", "event": "scores_ready", "when": {"turn": 3},
                               "match": {"kind": "special_replace"}}
                state = invoke(seat, "prepare", {"declaration": declaration, "revision": state["revision"],
                                                 "request_id": "reserve-score-window"})
                self.assertEqual(state["declarations"][0]["event"], "scores_ready")
                self.assertFalse(invoke(2, "observe").get("declarations"))
            invoke(seat, "ready", {"request_id": f"ready-{seat}", "revision": state["revision"]})
        actions = {1: 0, 2: 0}
        for _ in range(160):
            for seat in (1, 2):
                state = invoke(seat, "observe")
                if state["finished"]:
                    public = self.request("/api/observe", {})[1]
                    self.assertTrue(public["finished"])
                    self.assertFalse(public["options"])
                    self.assertTrue(all(actions.values()))
                    return state["frame"]["winner_side"], actions
                moves = state["options"]
                if not moves:
                    continue
                preference = ("place", "attack", "intercept", "let_through", "end_attack", "end")
                move = min(moves, key=lambda m: preference.index(m["kind"]) if m["kind"] in preference else 99)
                args = {"option_id": move["id"], "revision": state["revision"],
                        "request_id": f"move-{seat}-{actions[seat]}"}
                reply = invoke(seat, "act", args)
                if not actions[seat]:
                    retry = invoke(seat, "act", args)
                    self.assertEqual(reply["revision"], retry["revision"])
                actions[seat] += 1
        self.fail("两席未能在 160 轮操作内打到终局。")

    def test_mcp_and_browser_or_two_mcp_clients_finish_same_seed(self):
        agents = self.play(browser_seat=None)
        human_api = self.play(browser_seat=1)
        self.assertEqual(agents, human_api)
        self.assertIn(agents[0], (1, 2))


if __name__ == "__main__":
    unittest.main()
