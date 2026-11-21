"""赫里斯、李凌对东部四科双人队。运行 python -m tests.test_plan_b_duo_match --replay [种子]。"""

import io
import random
import sys
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from main import play_game
from models.character import Character
from replay_lightcore import ReplayPlayer, declare_attacks


def replay(seed=13):
    teams = (("赫里斯", "李凌"), ("莱克", "厄尔克斯"))
    players = [ReplayPlayer(1, "PlanB"), ReplayPlayer(2, "东部四科")]
    game = Game(players, rng=random.Random(seed))
    pool = {spec["name"]: spec for spec in load_characters_from_packs()}
    for player, team in zip(players, teams):
        for name in team:
            actor = Character(pool[name], player)
            player.characters.append(actor)
            actor.init_cards()
            actor.setup_deck()
        player.cardspace.draw.shuffle(game.rng)
    game.run_pre_reveal_declarations = lambda: declare_attacks(game)
    print(f"赫里斯、李凌 对 莱克、厄尔克斯　双人队伍战　种子 {seed}")
    play_game(game)
    print(f"第 {game.turn_number} 回合终局　" + "，".join(
        f"{c.name} {c.hp}/{c.max_hp}" for p in players for c in p.characters))
    return game


class PlanBDuoMatchTests(unittest.TestCase):
    def test_ignition_calls_the_hammer_and_the_pierce_chain_finishes_a_standard_match(self):
        with redirect_stdout(io.StringIO()) as log:
            game = replay()
        self.assertTrue(game.is_over)
        events = log.getvalue()
        self.assertIn("以「重锤！」进攻 莱克", events)
        self.assertIn("以「重锤！」进攻 厄尔克斯", events)
        self.assertIn("李凌 进行 1～20 判定", events)
        self.assertEqual((game.turn_number, game.winner.name), (5, "PlanB"))
        self.assertEqual([c.hp for player in game.players for c in player.characters], [4, 4, 0, 0])


if __name__ == "__main__":
    if sys.argv[1:2] == ["--replay"]:
        replay(*map(int, sys.argv[2:]))
    else:
        unittest.main()
