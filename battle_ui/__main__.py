"""Local hot-seat battle server. Run with python -m battle_ui."""

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .assets import SPRITES_DIR, STATIC_DIR, resolve_static as _resolve_static
from .session import BattleSession


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
            return
        resolved = _resolve_static(path)
        if resolved is not None:
            file_path, content_type = resolved
            self._send(HTTPStatus.OK, file_path.read_bytes(), content_type)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "未找到资源。"})

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
    parser = argparse.ArgumentParser(description="光点计划 III · 本机对战")
    parser.add_argument("--port", type=int, default=8765, help="本地端口，默认 8765")
    parser.add_argument("--seed", type=int, help="指定对局随机种子")
    parser.add_argument("--ai", action="store_true", help="启用人机对战（玩家一 vs 人机玩家二）")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), BattleHandler) as server:
        server.session = BattleSession(seed=args.seed, ai_side=2 if args.ai else None)
        mode_tag = "人机对战（P1 vs AI）" if args.ai else "本机双人热座"
        print(f"{mode_tag}已开放  http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
