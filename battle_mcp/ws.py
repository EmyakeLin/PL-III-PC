"""Zero-dependency RFC 6455 WebSocket server & test-client framing on standard-library sockets."""

import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WebSocketClosed(OSError):
    """Raised when the peer closes or resets the WebSocket stream."""


def is_websocket_upgrade(headers):
    upgrade = (headers.get("Upgrade") or "").strip().lower()
    conn = (headers.get("Connection") or "").lower()
    return upgrade == "websocket" and "upgrade" in conn


def compute_accept_key(sec_key):
    raw = (sec_key.strip() + _WS_GUID).encode("ascii")
    return base64.b64encode(hashlib.sha1(raw).digest()).decode("ascii")


def encode_frame(opcode, payload=b"", *, mask=False):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    length = len(payload)
    b0 = 0x80 | (opcode & 0x0F)
    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header = struct.pack("!BB", b0, mask_bit | length)
    elif length < 65536:
        header = struct.pack("!BBH", b0, mask_bit | 126, length)
    else:
        header = struct.pack("!BBQ", b0, mask_bit | 127, length)
    if not mask:
        return header + payload
    mask_key = os.urandom(4)
    repeated = mask_key * (length // 4 + 1)
    masked_bytes = bytes(a ^ b for a, b in zip(payload, repeated))
    return header + mask_key + masked_bytes


def _read_exact(rfile, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = rfile.read(n - len(buf))
        if not chunk:
            raise WebSocketClosed("WebSocket 连接已关闭。")
        buf.extend(chunk)
    return bytes(buf)


def decode_one_frame(rfile, *, require_masked=True, max_bytes=262144):
    head = _read_exact(rfile, 2)
    b0, b1 = head[0], head[1]
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    if require_masked and not masked:
        raise WebSocketClosed("客户端帧必须携带掩码。")
    length = b1 & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", _read_exact(rfile, 2))
    elif length == 127:
        (length,) = struct.unpack("!Q", _read_exact(rfile, 8))
    if length > max_bytes:
        raise WebSocketClosed("WebSocket 帧超出大小限制。")
    mask_key = _read_exact(rfile, 4) if masked else None
    payload = _read_exact(rfile, length) if length else b""
    if mask_key and payload:
        repeated = mask_key * (length // 4 + 1)
        payload = bytes(a ^ b for a, b in zip(payload, repeated))
    return fin, opcode, payload


class WebSocketConnection:
    """Thread-safe full-duplex RFC 6455 WebSocket wrapper around a BaseHTTPRequestHandler socket."""

    def __init__(self, sock, rfile):
        self.sock = sock
        self.rfile = rfile
        self._write_lock = threading.Lock()
        self.closed = False
        self.last_seen_mono = time.monotonic()

    @classmethod
    def accept(cls, handler):
        version = (handler.headers.get("Sec-WebSocket-Version") or "").strip()
        key = (handler.headers.get("Sec-WebSocket-Key") or "").strip()
        if version != "13" or not key:
            return None
        accept_val = compute_accept_key(key)
        handler.close_connection = True
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_val}\r\n"
            "\r\n"
        ).encode("ascii")
        handler.wfile.write(response)
        handler.wfile.flush()
        handler.connection.settimeout(45.0)
        return cls(handler.connection, handler.rfile)

    def _send_raw(self, data):
        with self._write_lock:
            if self.closed:
                return False
            try:
                self.sock.sendall(data)
                return True
            except OSError:
                self.closed = True
                return False

    def send_json(self, data):
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return self._send_raw(encode_frame(OP_TEXT, text, mask=False))

    def send_ping(self, payload=b"hb"):
        return self._send_raw(encode_frame(OP_PING, payload, mask=False))

    def send_pong(self, payload=b""):
        return self._send_raw(encode_frame(OP_PONG, payload, mask=False))

    def close(self, code=1000):
        with self._write_lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.sock.sendall(encode_frame(OP_CLOSE, struct.pack("!H", code), mask=False))
            except OSError:
                pass
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def recv_json(self, *, max_bytes=262144):
        """Read the next complete JSON message; transparently answer Pings and track heartbeats."""
        fragments = []
        total = 0
        while not self.closed:
            try:
                fin, opcode, payload = decode_one_frame(self.rfile, require_masked=True, max_bytes=max_bytes)
            except socket.timeout:
                if not self.send_ping():
                    raise WebSocketClosed("WebSocket 心跳发送失败。") from None
                continue
            except OSError as exc:
                self.closed = True
                raise WebSocketClosed(str(exc)) from exc

            self.last_seen_mono = time.monotonic()
            if opcode == OP_PING:
                self.send_pong(payload[:125])
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                self.close()
                return None
            if opcode in (OP_TEXT, OP_BINARY):
                fragments = [payload]
                total = len(payload)
                if fin:
                    raw = b"".join(fragments)
                    return json.loads(raw.decode("utf-8"))
            elif opcode == OP_CONT and fragments:
                total += len(payload)
                if total > max_bytes:
                    self.close(1009)
                    raise WebSocketClosed("分片消息过大。")
                fragments.append(payload)
                if fin:
                    raw = b"".join(fragments)
                    return json.loads(raw.decode("utf-8"))
            else:
                self.close(1002)
                raise WebSocketClosed("无效的 WebSocket 帧序列。")
        return None


class SimpleWebSocketClient:
    """Lightweight RFC 6455 client for deterministic integration tests."""

    def __init__(self, host, port, path="/ws", *, headers=None, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req_headers = {
            "Host": f"{host}:{port}",
            "Origin": f"http://{host}:{port}",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": key,
            "Sec-WebSocket-Version": "13",
        }
        if headers:
            req_headers.update(headers)
        lines = [f"GET {path} HTTP/1.1"] + [f"{k}: {v}" for k, v in req_headers.items()] + ["", ""]
        self.sock.sendall("\r\n".join(lines).encode("utf-8"))
        self.rfile = self.sock.makefile("rb")
        status_line = self.rfile.readline().decode("latin1").strip()
        if not status_line.startswith("HTTP/1.1 101"):
            code = int(status_line.split()[1]) if len(status_line.split()) >= 2 and status_line.split()[1].isdigit() else 500
            self.close()
            raise ConnectionRefusedError(f"WebSocket handshake failed: {code} ({status_line})")
        resp_accept = None
        while True:
            line = self.rfile.readline().decode("latin1")
            if line in ("\r\n", "\n", ""):
                break
            k, _, v = line.partition(":")
            if k.strip().lower() == "sec-websocket-accept":
                resp_accept = v.strip()
        if resp_accept != compute_accept_key(key):
            self.close()
            raise ValueError("Invalid Sec-WebSocket-Accept")

    def send_json(self, obj):
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.sock.sendall(encode_frame(OP_TEXT, raw, mask=True))

    def recv_json(self, *, max_bytes=8388608):
        while True:
            fin, opcode, payload = decode_one_frame(self.rfile, require_masked=False, max_bytes=max_bytes)
            if opcode == OP_PING:
                self.sock.sendall(encode_frame(OP_PONG, payload[:125], mask=True))
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                return None
            if opcode == OP_TEXT and fin:
                return json.loads(payload.decode("utf-8"))

    def close(self):
        try:
            self.sock.sendall(encode_frame(OP_CLOSE, struct.pack("!H", 1000), mask=True))
        except OSError:
            pass
        try:
            self.rfile.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
