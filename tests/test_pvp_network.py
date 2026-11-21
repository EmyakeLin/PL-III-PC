"""Invitations, interface selection and origin checks for the multiplayer room."""

import io
import re
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from battle_mcp.__main__ import main
from battle_mcp.network import allowed_origins, https_origin, ipv4_address, lan_address
from battle_mcp.transport import ArenaServer
from tests.test_mcp_transport import SeatEcho, WireClient


class NetworkTests(WireClient, unittest.TestCase):
    def test_network_address_validation_and_default_ports(self):
        for invalid in ("0.0.0.0", "224.0.0.1", "255.255.255.255", "wifi.local"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ipv4_address(invalid)
        for invalid in ("", "http://play.example", "https://user@play.example", "https://play.example/room",
                        "https://play.example?", "https://play.example#", "https://play.example:65536",
                        "https://play.example:", "https://*.example", "https://[::1]x", "https://[v1.face]",
                        "https://play.example\\room"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                https_origin(invalid)
        self.assertEqual(https_origin("https://PLAY.example:443/"), "https://play.example")
        self.assertEqual(https_origin("https://[::1]:8443"), "https://[::1]:8443")
        allow = allowed_origins("192.168.1.23", 80, "https://play.example")
        self.assertEqual(allow, {
            ("192.168.1.23", "http://192.168.1.23"), ("192.168.1.23:80", "http://192.168.1.23"),
            ("play.example", "https://play.example"), ("play.example:443", "https://play.example"),
        })

    def test_discovery_on_isolated_lan_or_loopback_only_host(self):
        with patch("battle_mcp.network.socket.socket") as factory, patch(
                "battle_mcp.network.socket.getaddrinfo") as resolve:
            factory.return_value.__enter__.return_value.connect.side_effect = OSError("no route")
            interfaces = [(2, 1, 6, "", ("127.0.0.1", 0))]
            resolve.return_value = interfaces
            with self.assertRaisesRegex(ValueError, "--address"):
                lan_address()
            interfaces.append((2, 1, 6, "", ("192.168.1.23", 0)))
            self.assertEqual(lan_address(), "192.168.1.23")
            factory.return_value.__enter__.return_value.bind.assert_called_with(("192.168.1.23", 0))
            route = factory.return_value.__enter__.return_value
            route.connect.side_effect = None
            route.getsockname.return_value = ("198.18.0.1", 31004)
            self.assertEqual(lan_address(), "192.168.1.23")

    def test_same_origin_forwarded_player_and_public_observer(self):
        with ArenaServer(SeatEcho(), port=0, public_url="https://play.example:8443") as self.server:
            worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
            worker.start()
            try:
                good = {"Host": "play.example:8443", "Origin": self.server.invite_url}
                for seat in (1, 2, None):
                    self.assertEqual(self.request("/api/observe", {}, side=seat, **good),
                                     (200, {"side": seat, "hand": [f"seat-{seat}-private"] if seat else []}))
                for bad in ({"Host": "play.example", "Origin": self.server.invite_url},
                            {**good, "Origin": "http://play.example:8443"},
                            {"Host": f"127.0.0.1:{self.server.server_port}", "Origin": self.server.invite_url},
                            {"Host": "foreign.example", "X-Forwarded-Host": good["Host"],
                             "X-Forwarded-Proto": "https"}):
                    with self.subTest(bad=bad):
                        self.assertEqual(self.request("/api/observe", {}, **bad)[0], 403)
            finally:
                self.server.shutdown()
                worker.join(2)

    def test_lan_cli_advertises_two_private_invites_at_actual_port(self):
        output = io.StringIO()
        with patch("sys.argv", ["battle_mcp", "--lan", "--port", "0"]), patch(
                "battle_mcp.__main__.lan_address", return_value="127.0.0.1"), patch.object(
                ArenaServer, "serve_forever"), redirect_stdout(output):
            main()
        invitations = re.findall(r"玩家 ([12]) 私人邀请  (http://127\.0\.0\.1:(\d+)/)#token=(\S+)",
                                 output.getvalue())
        self.assertEqual([seat for seat, *_ in invitations], ["1", "2"])
        (_, url, port, first), (_, other_url, _, second) = invitations
        self.assertEqual(url, other_url)
        self.assertGreater(int(port), 0)
        self.assertNotEqual(first, second)
        self.assertIn("观战页面  " + url, output.getvalue())
        self.assertNotIn("房主双席搬运台", output.getvalue())
