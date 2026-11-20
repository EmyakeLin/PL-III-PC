"""Local hot-seat battle server. Run with python -m battle_ui."""

import argparse
import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from .match import BattleMatch


ASSETS = {
    "/": ("index.html", "text/html"),
    "/style.css": ("style.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}
STATIC_DIR = Path(__file__).with_name("static")


class BattleSession:
    """A single table shared by the browsers connected to this local process."""

    def __init__(self, seed=None):
        self.seed = seed
        self.match = BattleMatch(seed=seed)
        self.revision = secrets.randbits(40)
        self.lock = Lock()

    def state(self):
        with self.lock:
            return {**self.match.snapshot(), "revision": self.revision}

    def command(self, request):
        if not isinstance(request, dict) or type(request.get("revision")) is not int:
            raise ValueError("操作缺少有效的对局版本。")
        with self.lock:
            if request["revision"] != self.revision:
                return HTTPStatus.CONFLICT, {**self.match.snapshot(), "revision": self.revision}
            action = request.get("action")
            if action == "new":
                roster = request.get("roster")
                if (not isinstance(roster, list) or len(roster) != 2
                        or not all(isinstance(item, str) for item in roster)):
                    raise ValueError("请为两位玩家选择出战角色。")
                self.match = BattleMatch(roster, seed=self.seed, initial_handoff=True)
                frame = self.match.snapshot()
            else:
                if action not in ("place", "end", "pass", "ready", "next",
                                  "attack", "end_attack", "intercept", "let_through", "switch_side",
                                  "open_special", "leave_special", "use_special"):
                    raise ValueError("未知的对战操作。")
                frame = self.match.act(action, self.match.revision, card_id=request.get("card_id"),
                                       target=request.get("target"), side=request.get("side"),
                                       duel_number=request.get("duel_number"), option=request.get("option"))
            self.revision += 1
            return HTTPStatus.OK, {**frame, "revision": self.revision}


class BattleHandler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                   "application/json")

    def _local_request(self):
        port = self.server.server_port
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        if port == 80:
            hosts.update(("localhost", "127.0.0.1"))
        host = self.headers.get("Host", "").lower()
        origin = self.headers.get("Origin")
        if host in hosts and (origin is None or origin == f"http://{host}"):
            return True
        self._json(HTTPStatus.FORBIDDEN, {"error": "请从本机对战页面访问。"})
        return False

    def do_GET(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/state":
            self._json(HTTPStatus.OK, self.server.session.state())
        elif path in ASSETS:
            name, content_type = ASSETS[path]
            self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), content_type)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "未找到页面。"})

    def do_POST(self):
        if not self._local_request():
            return
        if urlsplit(self.path).path != "/api/action":
            self._json(HTTPStatus.NOT_FOUND, {"error": "未找到操作。"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "操作需要使用 JSON。"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise ValueError("操作长度无效。")
            request = json.loads(self.rfile.read(size).decode("utf-8"))
            status, frame = self.server.session.command(request)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "操作数据格式无效。"})
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        else:
            self._json(status, frame)


def main():
    parser = argparse.ArgumentParser(description="光点计划 III · 本机双人对战")
    parser.add_argument("--port", type=int, default=8765, help="本地端口，默认 8765")
    parser.add_argument("--seed", type=int, help="指定对局随机种子")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), BattleHandler) as server:
        server.session = BattleSession(seed=args.seed)
        print(f"本机对战已开放  http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
