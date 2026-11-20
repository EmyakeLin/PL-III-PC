"""A local, fixed-seat HTTP server with a stateless Streamable HTTP MCP endpoint."""

import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .decision_view import decision_view
from .declarations import EVENTS, KINDS
from .manual import ManualDesk


VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
STATIC_DIR = Path(__file__).with_name("static")
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css"), "/desk": ("desk.html", "text/html"),
          "/desk.js": ("desk.js", "text/javascript"), "/desk.css": ("desk.css", "text/css")}
REVISION = {"type": "integer", "minimum": 0, "description": "当前己方 observe 返回的 revision。"}
REQUEST_ID = {"type": "string", "minLength": 1, "maxLength": 128,
              "description": "每次新操作使用唯一 ID，重试发送相同 ID 和参数。"}
CURSOR = {"type": "integer", "minimum": 0}
STUDY_RULES = ('新席位在准备前先读 rules(topic="briefing")，获取正式条文和双方印刷牌面。'
               '希望通读的席位可读 rules(topic="full")，再读 rules(topic="catalog")。')


def object_schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def tool(name, description, properties, required=()):
    return {"name": name, "description": description, "inputSchema": object_schema(properties, required)}


TEXT = {"type": "string"}
NUMBER = {"type": "integer"}
DECLARATION = {"type": "object", "oneOf": [
    object_schema({
        "mode": enum("reserve", "execute"),
        "event": enum(*EVENTS),
        "match": object_schema({"kind": enum(*sorted(KINDS)), "card_id": TEXT, "target_card_id": TEXT,
                                "duel_number": NUMBER, "response_number": NUMBER, "character_id": TEXT}),
        "when": object_schema({"duel_kind": TEXT, "duel_number": NUMBER, "die_number": NUMBER,
                               "own_card_id": TEXT, "score": enum("lt", "eq", "gt"), "timing": TEXT,
                               "pending_number": NUMBER, "after_ms": NUMBER, "turn": NUMBER,
                               "action_kind": enum(*sorted(KINDS)), "actor_side": {"type": "integer", "enum": [1, 2]}}),
        "repeat": {"type": "boolean"},
    }, ("event", "mode")),
    object_schema({"cancel": TEXT}, ("cancel",)),
]}

TOOLS = [
    tool("observe", "查看本席位的当前局面、合法选择和 cursor 之后的可见事件。观战席只见公开信息。",
         {"cursor": CURSOR}),
    tool("rules", 'briefing 一次读取赛前条文及本局牌面，full 通读完整规则书，catalog 单查印刷牌面。'
         '省略 topic 查看目录和准备示例，也可用 "3.3" 等章节号查原文。',
         {"topic": TEXT}),
    tool("wait", "等到本席位有已预约的时机、决策或终局。默认持续等待，可传 timeout 秒数。等待不会放行迎击。",
         {"cursor": CURSOR, "timeout": {"type": "number", "minimum": 0, "maximum": 60}}, ("cursor",)),
    tool("prepare", "为未来的事件登记提前声明，可预约到点决定或条件满足时执行。用 rules 查看条件和动作示例。",
         {"declaration": DECLARATION, "revision": REVISION, "request_id": REQUEST_ID},
         ("declaration", "revision", "request_id")),
    tool("ready", STUDY_RULES + "用 prepare 提前预留所需特殊机会。ready 确认准备并预留常规置卡和开牌前攻防决定。",
         {"revision": REVISION, "request_id": REQUEST_ID}, ("revision", "request_id")),
    tool("act", "在已预约的决策窗口提交当前席位 options 提供的一个选项。",
         {"option_id": TEXT, "revision": REVISION, "request_id": REQUEST_ID},
         ("option_id", "revision", "request_id")),
]
BY_NAME = {item["name"]: item for item in TOOLS}
READ_ONLY = {"rules", "observe", "wait"}


class RequestError(ValueError):
    def __init__(self, status, message, rpc_code=-32600):
        super().__init__(message)
        self.status = status
        self.rpc_code = rpc_code


def check_arguments(name, arguments):
    schema = BY_NAME[name]["inputSchema"]
    if not isinstance(arguments, dict) or set(arguments) - schema["properties"].keys():
        raise RequestError(400, "工具参数包含未知字段。", -32602)
    if not set(schema["required"]) <= arguments.keys():
        raise RequestError(400, "工具缺少必要参数。", -32602)
    for key, value in arguments.items():
        if key in ("revision", "cursor") and (type(value) is not int or value < 0):
            raise RequestError(400, f"{key} 必须是非负整数。", -32602)
        if key in ("topic", "option_id", "request_id") and (
                not isinstance(value, str) or not 0 < len(value) <= (128 if key == "request_id" else 1024)):
            raise RequestError(400, f"{key} 必须是有效文字。", -32602)
        if key == "timeout" and (type(value) not in (int, float) or not 0 <= value <= 60):
            raise RequestError(400, "等待时间必须在 0 至 60 秒之间。", -32602)
        if key == "declaration" and not isinstance(value, dict):
            raise RequestError(400, "declaration 必须是对象。", -32602)


class ArenaServer(ThreadingHTTPServer):
    """One engine and two independent seat credentials per listening socket."""

    def __init__(self, room, port=8766):
        self.room = room
        self.tokens = {seat: secrets.token_urlsafe(32) for seat in (1, 2)}
        self.desk = ManualDesk(room)
        self.desk_token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), ArenaHandler)

    def server_close(self):
        self.room.close()
        super().server_close()

    def authorized_seats(self, authorization, *, desk=False):
        if authorization is None:
            return ()
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token and token.isascii():
            if desk and secrets.compare_digest(self.desk_token, token):
                return tuple(self.tokens)
            for seat, secret in self.tokens.items():
                if secrets.compare_digest(secret, token):
                    return (seat,)
        raise RequestError(403, "席位凭据无效。")

    def side_for(self, authorization):
        seats = self.authorized_seats(authorization)
        return seats[0] if seats else None

    def desk_command(self, name, seats, body):
        if name == "status" and body == {}:
            return self.desk.status(seats)
        if name not in ("export", "submit", "status"):
            raise RequestError(404, "搬运台操作不存在。")
        if not isinstance(body, dict) or name == "status" or type(body.get("side")) is not int:
            raise RequestError(400, "搬运台参数无效。")
        side = body["side"]
        if side not in seats:
            raise RequestError(403, "本邀请不能操作该席位。")
        if name == "submit" and set(body) == {"side", "reply"} and isinstance(body["reply"], str):
            return self.desk.import_reply(side, body["reply"])
        if (name == "export" and body.keys() <= {"side", "kind", "cursor"}
                and body.get("kind") in ("intro", "turn")):
            return self.desk.export(side, briefing=body["kind"] == "intro", cursor=body.get("cursor"))
        raise RequestError(400, "请指定有效的导出类型或待解析的回复。")

    def invoke(self, name, side, arguments):
        if not isinstance(name, str) or name not in BY_NAME:
            raise RequestError(404, "未知工具。", -32602)
        if side is None and name not in READ_ONLY:
            raise RequestError(403, "观众只能查看公开对局。")
        check_arguments(name, arguments)
        if name == "rules":
            return self.room.rules(**arguments)
        return getattr(self.room, name)(side, **arguments)


def rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def text_result(value, *, failed=False):
    # Only one representation of the payload goes into the agent's context.
    data = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return {"content": [{"type": "text", "text": data}], "isError": failed}


class ArenaHandler(BaseHTTPRequestHandler):
    server_version = "BattleRoom/1.0"

    def log_request(self, code="-", size="-"):
        # The CLI prints invitations once. Discard HTTP access logs (including raw URLs).
        pass

    def _send(self, status, value=None, content_type="application/json"):
        if isinstance(value, bytes):
            data = value
        elif value is None:
            data = b""
        else:
            data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        if status == 405:
            self.send_header("Allow", "POST")
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _check_origin(self):
        port = self.server.server_port
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        if port == 80:
            hosts.update(("localhost", "127.0.0.1"))
        host = self.headers.get("Host", "").lower()
        origin = self.headers.get("Origin")
        if host not in hosts or (origin is not None and origin != f"http://{host}"):
            raise RequestError(403, "请从本机房间访问。")

    def _content_length(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise RequestError(411, "需要 Content-Length。") from None
        if not 0 <= length <= 65536:
            raise RequestError(413, "请求过大。")
        return length

    def _json_body(self):
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "请求需要 application/json。")
        body = self.rfile.read(self._content_length())
        self._body_received = True
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            raise RequestError(400, "无效的 JSON。", -32700) from None

    def _drain_rejected_body(self):
        # Closing with unread request bytes can reset the response on Windows.
        # The rejection has already been sent. Only discard a small, declared body.
        self.close_connection = True
        try:
            remaining = self._content_length()
            deadline = time.monotonic() + 0.25
            while remaining:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                self.connection.settimeout(timeout)
                chunk = self.rfile.read1(remaining)
                if not chunk:
                    break
                remaining -= len(chunk)
        except (RequestError, OSError):
            pass

    def do_GET(self):
        try:
            self._check_origin()
            path = urlsplit(self.path).path
            if path == "/mcp":
                # This server uses JSON results and does not offer an SSE stream.
                self._send(405)
            elif path in ASSETS:
                filename, mime = ASSETS[path]
                self._send(200, (STATIC_DIR / filename).read_bytes(), mime)
            else:
                self._send(404, {"error": "页面不存在。"})
        except RequestError as exc:
            self._send(exc.status, {"error": str(exc)})

    def _rpc(self, message, side):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise RequestError(400, "需要单条 JSON-RPC 2.0 消息。")
        request_id = message.get("id")
        method = message.get("method")
        if method is None and "id" in message and ("result" in message or "error" in message):
            return self._send(202)
        if not isinstance(method, str):
            raise RequestError(400, "JSON-RPC method 无效。")
        if "id" not in message:
            # Notifications cannot perform player actions.
            return self._send(202)
        if type(request_id) not in (str, int):
            raise RequestError(400, "JSON-RPC id 无效。")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return self._send(200, rpc_error(request_id, -32602, "params 必须是对象。"))
        if method == "initialize":
            if not isinstance(params.get("protocolVersion"), str):
                return self._send(200, rpc_error(request_id, -32602, "协议版本无效。"))
            version = params["protocolVersion"]
            result = {"protocolVersion": version if version in VERSIONS else VERSIONS[0],
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "pl-iii-arena", "version": "1.0"},
                      "instructions": STUDY_RULES + "再 observe 查看本席局面，按需 prepare 后 ready。"
                                      "用 act 提交本席选项，用 wait 等待下一处决策。"}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [t for t in TOOLS if side is not None or t["name"] in READ_ONLY]}
        elif method == "tools/call":
            try:
                name = params.get("name")
                data = self.server.invoke(name, side, params.get("arguments", {}))
                if name != "rules" and "frame" in data:
                    data = decision_view(data)
                result = text_result(data)
            except RequestError as exc:
                return self._send(200, rpc_error(request_id, exc.rpc_code, str(exc)))
            except (ValueError, PermissionError) as exc:
                result = text_result(str(exc), failed=True)
        else:
            return self._send(200, rpc_error(request_id, -32601, "未知 MCP 方法。"))
        self._send(200, {"jsonrpc": "2.0", "id": request_id, "result": result})

    def do_POST(self):
        path = urlsplit(self.path).path
        self._body_received = False
        try:
            self._check_origin()
            authorization = self.headers.get("Authorization")
            if path.startswith("/api/desk/"):
                seats = self.server.authorized_seats(authorization, desk=True)
                if not seats:
                    raise RequestError(403, "请使用私人席位或双席搬运台邀请。")
                value = self.server.desk_command(path.removeprefix("/api/desk/"), seats, self._json_body())
                return self._send(200, value)
            side = self.server.side_for(authorization)
            if path == "/mcp":
                version = self.headers.get("MCP-Protocol-Version", "2025-03-26")
                if version not in VERSIONS:
                    raise RequestError(400, "不支持的 MCP 协议版本。")
                return self._rpc(self._json_body(), side)
            if not path.startswith("/api/"):
                raise RequestError(404, "接口不存在。")
            value = self.server.invoke(path[5:], side, self._json_body())
            self._send(200, value)
        except RequestError as exc:
            data = rpc_error(None, exc.rpc_code, str(exc)) if path == "/mcp" else {"error": str(exc)}
            self._send(exc.status, data)
            if not self._body_received:
                self._drain_rejected_body()
        except PermissionError as exc:
            self._send(403, {"error": str(exc)})
        except ValueError as exc:
            from .room import RoomConflict
            self._send(409 if isinstance(exc, RoomConflict) else 400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
