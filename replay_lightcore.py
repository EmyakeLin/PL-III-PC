"""光点 Boss 实战。例：python replay_lightcore.py duel --seed 40 --log"""

import argparse
from collections import Counter
from contextlib import redirect_stdout
from itertools import combinations
import io
import random

from game import Game
from loader import load_characters_from_packs
from main import play_game
from models.character import Character
from models.dice import Dice
from player.player import Player


BELL = ("bellfounder_que_ming",)
SHIP = ("shipbreaker_shen_li",)
DUO = ("plan_b_annolin", "waa_lake")
TRIO = ("waa_lake", "waa_grolina", "waa_erkes")
MATCHUPS = {
    "bell-duo": (BELL, DUO), "bell-trio": (BELL, TRIO),
    "ship-duo": (SHIP, DUO), "ship-trio": (SHIP, TRIO), "duel": (BELL, SHIP),
}


def card_value(card):
    """固定估价只看印刷面。进攻骰、骰面、费用及射程影响置牌优先级。"""
    value = 3 * card.cost + 3 * card.range_level
    for spec in card.data["dice"]:
        die = Dice(spec)
        value += (die.roll_max + 1) / 2 + die.base_value + die.final_bonus
        value += 2 if die.is_attack else 0
    return value


class ReplayPlayer(Player):
    def select_card(self, total_draw, draw_count):
        draw = self.cardspace.draw
        candidates = draw.content[:total_draw]
        discard = max(0, len(candidates) - draw_count)
        for card in sorted(candidates, key=card_value)[:discard]:
            draw.move_card_to(card, draw)
        self.draw_card(min(draw_count, len(candidates)))

    def affordable(self, cards):
        committed = Counter()
        for slot in self.game.board_slots():
            for card in slot.get_content(self.side):
                committed[card.character] += card.cost
        for card in cards:
            committed[card.character] += card.cost
        common = sum(max(0, total - actor.available_cost) for actor, total in committed.items())
        return common <= self.available_cost

    def place_card(self, game):
        hand = [c for c in self.cardspace.hand.content if c.character.is_alive]
        best, best_score = (), 0
        values = {c: card_value(c) for c in hand}
        for size in range(1, len(hand) + 1):
            for selection in combinations(hand, size):
                regular = Counter(c.character for c in selection if not c.data.get("pre_reveal"))
                if any(n + actor.used_duels > actor.max_duels for actor, n in regular.items()):
                    continue
                score = sum(values[c] for c in selection)
                if score > best_score and self.affordable(selection):
                    best, best_score = selection, score
        regular = [c for c in best if not c.data.get("pre_reveal")]
        if not regular:
            return "ended"
        card = max(regular, key=values.get)
        if not game.auto_place_in_duel(self.side, card):
            raise RuntimeError(f"{self.name} 无法扣置「{card.name}」。")
        return "placed"

    def choose_one_sided_target(self, enemy_player):
        alive = (c for c in enemy_player.characters if c.is_alive)
        return min(alive, key=lambda c: (c.hp, c.lightcore_hp), default=None)


def declare_attacks(game):
    phase = game.pre_reveal
    while phase.actor is not None:
        actor = phase.attacker
        if actor is not None:
            attacks = [c for c in phase.attack_cards(actor) if actor.affordable([c])]
            if attacks:
                card = max(attacks, key=card_value)
                target = actor.choose_one_sided_target(phase.opponent(actor))
                legal = phase.attack_targets(card)
                character, index = (target, None) if (target, None) in legal else legal[0]
                phase.declare_attack(card, character=character, duel_index=index)
            else:
                phase.end_attack(actor)
        for player in game.players:
            for number in phase.pending_for(player):
                cards = [c for c in phase.intercept_cards(player) if player.affordable([c])]
                if cards:
                    phase.intercept(max(cards, key=card_value), number)
                else:
                    phase.pass_intercept(number, player)


def simulate(matchup, seed, pool):
    rosters = MATCHUPS[matchup]
    players = [ReplayPlayer(i, "＋".join(pool[key]["name"] for key in roster))
               for i, roster in enumerate(rosters, 1)]
    game = Game(players, rng=random.Random(seed))
    for player, roster in zip(players, rosters):
        for key in roster:
            character = Character(pool[key], player)
            player.characters.append(character)
            character.init_cards()
            character.setup_deck()
        player.cardspace.draw.shuffle(game.rng)
    game.run_pre_reveal_declarations = lambda: declare_attacks(game)
    play_game(game)
    return game


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matchup", nargs="?", choices=["all", *MATCHUPS], default="all")
    parser.add_argument("--seed", type=int, default=40)
    parser.add_argument("--runs", type=int, default=1, help="从 seed 起连续运行的种子个数")
    parser.add_argument("--log", action="store_true", help="逐行打印引擎的完整战斗日志")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs 必须大于 0")
    pool = {c["id"]: c for c in load_characters_from_packs()}
    for matchup in MATCHUPS if args.matchup == "all" else (args.matchup,):
        results = Counter()
        for seed in range(args.seed, args.seed + args.runs):
            output = io.StringIO()
            with redirect_stdout(output):
                game = simulate(matchup, seed, pool)
            if args.log:
                print(f"\n〔{matchup} · 种子 {seed}〕")
                print(output.getvalue(), end="")
            winner = game.winner.name if game.winner else "平局"
            results[winner] += 1
            result = winner + "胜" if game.winner else winner
            states = [f"{c.name} 生命 {c.hp}/{c.max_hp}，完整度 {c.lightcore_hp}/{c.max_lightcore_hp}"
                      for p in game.players for c in p.characters]
            print(f"{matchup} · 种子 {seed} · 第 {game.turn_number} 回合 · {result}　" + "；".join(states))
        if args.runs > 1:
            print(f"{matchup} 共 {args.runs} 场　" + "，".join(f"{key} {n} 场" for key, n in results.items()))


if __name__ == "__main__":
    main()
