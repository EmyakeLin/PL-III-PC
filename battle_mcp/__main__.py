"""Start the mode lobby or a room with browser and MCP seats."""

import argparse

from loader import load_characters_from_packs
from .challenges import CHALLENGES
from .network import lan_address
from .transport import ArenaServer


def serve_local_game(variant, *, challenge=False, roster=None, port=0, seed=None):
    mode = "challenge" if challenge else "regular"
    with ArenaServer(port=port, seed=seed) as server:
        if roster:
            teams = [[key] if isinstance(key, str) else key for key in roster]
            game = server.lobby.create({"mode": mode, "variant": variant, "roster": teams})
            path = game["play_url"]
        else:
            path = f"/lobby/?mode={mode}&variant={variant}"
        print(f"对战大厅  {server.invite_url}/", flush=True)
        print(f"玩家 1 入口  {server.invite_url}{path}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description="光点计划 III · 对战服务端")
    parser.add_argument("--lobby", action="store_true", help="开启常驻对战大厅，可随时创建不同模式的房间")
    parser.add_argument("--roster", nargs=2, default=None,
                        metavar=("P1", "P2"), help="玩家一和玩家二的出战角色 ID")
    parser.add_argument("--port", type=int, default=8766, help="房间端口，0 表示自动分配")
    parser.add_argument("--bot", action="store_true", help="开启本机单角色 1v1 人机对战")
    parser.add_argument("--challenge", nargs="?", const="carrier", choices=CHALLENGES,
                        help="本机挑战：carrier 结构化载体（默认），lan_qing 幽兰残雪·澜清")
    parser.add_argument("--lan", action="store_true", help="在局域网网卡上创建玩家联机房间")
    parser.add_argument("--address", metavar="IP", help="在指定的本机 IPv4 网卡上创建联机房间")
    parser.add_argument("--public-url", metavar="HTTPS_URL", help="使用已有 HTTPS 反向代理的公开来源生成联机邀请")
    parser.add_argument("--seed", type=int, help="固定洗牌与掷骰种子")
    parser.add_argument("--list-characters", action="store_true", help="列出角色 ID 后退出")
    args = parser.parse_args()
    if args.list_characters:
        for char in load_characters_from_packs():
            print(f"{char['id']}  {char['name']}")
        return
    if not 0 <= args.port <= 65535:
        parser.error("端口必须在 0 到 65535 之间。")
    from .room import Room
    multiplayer = args.lan or args.address is not None or args.public_url is not None
    if args.lobby and (args.bot or args.challenge or args.roster):
        parser.error("大厅中的玩法和阵容在建房时选择。")
    if args.challenge and (args.bot or multiplayer):
        parser.error("--challenge 单独开启本机挑战房间。")
    if args.bot and multiplayer:
        parser.error("--bot 仅在本机运行，不能和联机参数同时使用。")
    try:
        if args.bot or args.challenge:
            return serve_local_game(args.challenge or "solo", challenge=bool(args.challenge),
                                    roster=args.roster, port=args.port, seed=args.seed)
        address = args.address if args.address is not None else (lan_address() if args.lan else "127.0.0.1")
        room = None if args.lobby else Room(
            args.roster, seed=args.seed, selectable=multiplayer)
        server = ArenaServer(room, args.port, address=address, public_url=args.public_url, seed=args.seed)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    with server:
        url = server.invite_url
        if server.lobby is not None:
            print(f"对战大厅  {url}/" + ("" if args.lobby else "lobby/"))
        if room is not None:
            print(f"观战页面  {url}/")
            print(f"Canvas 观战页面  {url}/canvas/")
            for seat, token in server.tokens.items():
                print(f"玩家 {seat} 私人邀请  {url}/#token={token}")
                print(f"玩家 {seat} Canvas 邀请  {url}/canvas/#token={token}")
            if multiplayer:
                print(f"房间监听  {server.server_address[0]}:{server.server_port}")
                print("房主打开玩家 1 的邀请，将玩家 2 的完整邀请发给对手。"
                      "双方选人、准备后开局。重连时打开原来的邀请。")
            else:
                print(f"MCP 端点  {url}/mcp")
                for seat, token in server.tokens.items():
                    print(f"席位 {seat} 模型回复搬运台  {url}/desk#token={token}")
                print(f"房主双席搬运台  {url}/desk#token={server.desk_token}")
                print("每席只领取自己的邀请。Agent 连接 MCP 时，取该席邀请中 token= 后的值，"
                      "作为 Authorization: Bearer <token> 请求头。")
        print("按 Ctrl+C 关闭服务。", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
