"""Exercise the desktop worker through the same pipes used by the tray."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class DesktopLaunchTests(unittest.TestCase):
    def test_busy_port_create_room_and_exit_on_owner_disconnect(self):
        entry = Path(__file__).resolve().parents[1] / "光点计划 III.pyw"
        with socket.socket() as busy:
            try:
                busy.bind(("127.0.0.1", 8766))
                busy.listen()
            except OSError:
                pass  # A running game can also occupy the default port.
            with subprocess.Popen([sys.executable, str(entry), "--serve"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True) as worker:
                try:
                    launch = urlsplit(worker.stdout.readline().strip())
                    self.assertRegex(launch.fragment, r"^desktop=[0-9a-f]{32}$")
                    self.assertNotEqual(launch.port, 8766)
                    origin = f"http://{launch.netloc}"
                    with urlopen(origin, timeout=5) as response:
                        self.assertIn(b"lobby.js", response.read())
                    for count in (0, 1):
                        worker.stdin.write("rooms\n")
                        worker.stdin.flush()
                        self.assertEqual(worker.stdout.readline().strip(), str(count))
                        if count == 0:
                            body = json.dumps({"mode": "regular", "variant": "solo"}).encode()
                            with urlopen(Request(origin + "/api/rooms", data=body, headers={
                                "Content-Type": "application/json"}), timeout=5) as response:
                                self.assertEqual(response.status, 201)
                    worker.stdin.close()
                    self.assertEqual(worker.wait(timeout=5), 0)
                    with self.assertRaises(OSError):
                        socket.create_connection(("127.0.0.1", launch.port), timeout=1)
                finally:
                    if worker.poll() is None:
                        worker.kill()
