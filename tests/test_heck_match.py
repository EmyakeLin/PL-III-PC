"""赫克对安诺琳的标准单人队伍战。python -m tests.test_heck_match --replay [种子]"""

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


class HeckPlayer(ReplayPlayer):
    def place_card(self, game):
        actor = self.characters[0]
        if actor.used_duels == actor.max_duels:
            return "ended"
        priorities = (("枪刃迸射", "开火", "贯彻之刺", "赤炎剑", "灼燃斩", "能源反解析")
                      if actor.statuses.get("全开") else ("装填", "能源反解析", "灼燃斩", "赤炎剑"))
        for name in priorities:
            for card in self.cardspace.hand.content:
                if card.name == name and card.meets_use_requirements() and self.affordable([card]):
                    if not game.auto_place_in_duel(self.side, card):
                        raise AssertionError(f"无法扣置{card.name}")
                    return "placed"
        return "ended"


def replay(seed=1):
    left, right = HeckPlayer(1, "赫克"), ReplayPlayer(2, "安诺琳")
    game = Game([left, right], rng=random.Random(seed))
    pool = {c["name"]: c for c in load_characters_from_packs()}
    for player in game.players:
        actor = Character(pool[player.name], player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        player.cardspace.draw.shuffle(game.rng)
    print(f"赫克对安诺琳　标准单人队伍　种子 {seed}")
    game.run_pre_reveal_declarations = lambda: declare_attacks(game)
    play_game(game)
    print(f"第 {game.turn_number} 回合，" + "，".join(
        f"{c.name} {c.hp}/{c.max_hp}" for p in game.players for c in p.characters))
    return game


class HeckMatchTests(unittest.TestCase):
    def test_starts_with_standard_decks_unlocks_decisive_skills_and_reaches_victory(self):
        with redirect_stdout(io.StringIO()) as log:
            game = replay()
        self.assertTrue(game.players[0].characters[0].rule_state.get("首次全开"))
        self.assertIn("赫克 使用「枪刃迸射」", log.getvalue())
        self.assertEqual((game.turn_number, game.winner.name), (4, "安诺琳"))
        self.assertEqual([p.characters[0].hp for p in game.players], [0, 8])


if __name__ == "__main__":
    if sys.argv[1:2] == ["--replay"]:
        replay(*map(int, sys.argv[2:]))
    else:
        unittest.main()
