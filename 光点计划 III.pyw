"""Windows desktop entry point and its local lobby worker."""

import base64
import ctypes
import errno
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parent


def serve():
    from battle_mcp.transport import ArenaServer

    class DesktopServer(ArenaServer):
        allow_reuse_address = False
        allow_reuse_port = False

        def server_bind(self):
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    try:
        server = DesktopServer(port=8766)
    except OSError as exc:
        if exc.errno not in (errno.EADDRINUSE, errno.EACCES):
            raise
        server = DesktopServer(port=0)

    with server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            print(f"{server.invite_url}/#desktop={secrets.token_hex(16)}", flush=True)
            for line in sys.stdin:
                if line.strip() == "rooms":
                    print(server.lobby.room_count, flush=True)
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    os.chdir(ROOT)
    if sys.argv[1:] == ["--serve"]:
        serve()
    else:
        try:
            script = (ROOT / "battle_mcp" / "desktop_tray.ps1").read_text(encoding="utf-8")
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-STA", "-EncodedCommand",
                 base64.b64encode(script.encode("utf-16le")).decode("ascii")],
                cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW,
                env={**os.environ, "PL3_PYTHON": str(Path(sys.executable).with_name("python.exe")),
                     "PL3_ENTRY": str(Path(__file__).resolve()), "PYTHONIOENCODING": "utf-8"},
            )
        except Exception as exc:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "光点计划 III · 启动失败", 16)
