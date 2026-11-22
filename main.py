"""光点计划 III · 本地双人对局。"""

import argparse
import random

from game import Game
from loader import load_characters_from_packs
from displayer import special_seats, timing_label
from pipeline.pipeline_errors import PipelineFinished
from player.player import Player
from special_actions_cli import offer_actions
from terminal_bridge import TerminalBridge


def play_game(game, step=False, *, bridge=None):
    """Drive one match to victory. The host owns interaction between pipeline steps."""
    if bridge is None:
        bridge = TerminalBridge(game)
    while not game.is_over:
        try:
            action = bridge.advance()
        except PipelineFinished:
            if game.is_over:
                break
            game.pipeline.current_step_index = -1
            game.pipeline.is_finished = False
            continue
        timing = timing_label(action)
        if (timing or game.special.decision_owner is not None) and bridge.special_prompt and not game.is_over:
            if special_seats(game):
                print(f"〔{timing}〕")
                bridge.offer_special_actions()
        if step and not game.is_over:
            if input(f"{action}  [回车继续 / q 退出] ").strip().lower() == "q":
                return
    print(f"对局结束，{game.winner.name} 获胜。" if game.winner else "双方全灭，平局。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="光点计划 III · 本地双人卡牌交锋")
    parser.add_argument("--seed", type=int, help="使用指定随机种子")
    parser.add_argument("--step", action="store_true", help="逐个查看引擎节点并按回车推进")
    parser.add_argument("--packs", help="从指定目录读取角色卡包")
    args = parser.parse_args(argv)
    try:
        characters = load_characters_from_packs(args.packs)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if len(characters) < 2 and not any(c.get("mirror_allowed") for c in characters):
        parser.error("双人对局至少需要两名可选角色")
    try:
        print("光点计划 III · 本地双人对局")
        print("每方选择 1～3 名角色。双方扣置后先处理开牌前交锋，再统一开牌。消灭对方所有角色获胜。")
        game = Game([Player(1, "玩家一"), Player(2, "玩家二")], rng=random.Random(args.seed))
        bridge = TerminalBridge(game, special_prompt=offer_actions)
        bridge.select_character(characters)
        play_game(game, step=args.step, bridge=bridge)
    except (EOFError, KeyboardInterrupt):
        print("\n已退出对局。")


if __name__ == "__main__":
    main()
