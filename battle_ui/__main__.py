"""Local tabletop launcher powered by the unified WebSocket Room engine. Run with python -m battle_ui."""

import argparse

from battle_mcp.room import Room
from battle_mcp.transport import ArenaServer


def main():
    parser = argparse.ArgumentParser(description="光点计划 III · 本机对战")
    parser.add_argument("--port", type=int, default=8765, help="本地端口，默认 8765")
    parser.add_argument("--seed", type=int, help="指定对局随机种子")
    parser.add_argument("--ai", action="store_true", help="启用人机对战（玩家一 vs 人机玩家二）")
    args = parser.parse_args()
    room = Room(seed=args.seed, bot=args.ai, hotseat=not args.ai, selectable=True)
    with ArenaServer(room, port=args.port) as server:
        mode_tag = "单人演练（P1 vs AI）" if args.ai else "同屏双人热座"
        token = server.tokens[1]
        print(f"{mode_tag}已开放  {server.invite_url}/canvas/#token={token}", flush=True)
        print(f"对战大厅已开放  {server.invite_url}/lobby/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
