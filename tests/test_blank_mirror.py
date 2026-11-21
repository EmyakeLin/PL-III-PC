"""空白镜像标准对局。运行 python -m tests.test_blank_mirror --replay 输出战报。"""

import io
import random
import sys
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.character import Character
from pipeline.pipeline_errors import PipelineFinished
from player.player import Player


class MirrorPlayer(Player):
    def cost_left(self, game):
        committed = sum(card.cost for slot in game.board_slots() for card in slot.get_content(self.side))
        return self.available_cost + self.characters[0].available_cost - committed

    def place_card(self, game):
        actor = self.characters[0]
        energy = actor.statuses.get("能源", 0)
        # Leave an attack in hand when we can afford to declare it after placement.
        cards = [card for card in self.cardspace.hand.content if card.cost <= self.cost_left(game)
                 and not card.data.get("pre_reveal") and (energy >= 2 or not card.data.get("resource_cost"))]
        if actor.used_duels >= actor.max_duels or not cards:
            return "ended"
        card = max(cards, key=lambda c: c.cost)
        if not game.auto_place_in_duel(self.side, card):
            raise AssertionError("无法完成常规置卡")
        print(f"〔决策〕{self.name}扣置第 {actor.used_duels} 张技能。")
        return "placed"


def mirror_match(seed=40):
    players = [MirrorPlayer(1, "先登"), MirrorPlayer(2, "望衡")]
    game = Game(players, rng=random.Random(seed))
    data = next(c for c in load_characters_from_packs() if c["id"] == "blank_boss")
    for player in players:
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        player.cardspace.draw.shuffle(game.rng)

    def choose_actions(game):
        for player in players:
            options = game.special.options(player)
            actor = player.characters[0]
            for action in options:
                if action.kind == "ability":
                    spec = next(s for s in actor.action_specs() if s["id"] == action.ability_id)
                    if spec["target"] == "own_hand" and (len(player.cardspace.hand.content) < 2
                            or actor.statuses.get("能源", 0) >= 6 or action.target_card.cost > 2):
                        continue
                elif action.kind == "attack":
                    if not action.character or action.card.cost > player.cost_left(game):
                        continue
                elif action.kind != "choose_slot":
                    continue
                if not game.special.apply(player, action):
                    raise AssertionError(f"合法行动未能执行 {action}")
                break

    def declare():
        phase = game.pre_reveal
        while phase.actor is not None:
            actor = phase.attacker
            if actor:
                cards = [c for c in phase.attack_cards(actor) if c.cost <= actor.cost_left(game)
                         and (not c.data.get("resource_cost") or actor.characters[0].statuses.get("能源", 0) >= 2)]
                if cards:
                    card = cards[0]
                    enemy, slot = phase.attack_targets(card)[0]
                    phase.declare_attack(card, character=enemy, duel_index=slot)
                else:
                    phase.end_attack(actor)
            for player in players:
                for number in phase.pending_for(player):
                    answers = [c for c in phase.intercept_cards(player) if c.cost <= player.cost_left(game)]
                    if answers:
                        phase.intercept(answers[0], number)
                    else:
                        phase.pass_intercept(number, player)

    game.special_prompt = choose_actions
    game.run_pre_reveal_declarations = declare
    print(f"空白镜像 · 先登 对 望衡 · 种子 {seed}")
    for _ in range(45000):
        if game.is_over:
            print(f"〔终局〕第 {game.turn_number} 回合，{game.winner.name if game.winner else '平局'}。"
                  + "　".join(f"{p.name} {p.characters[0].hp}/15" for p in players))
            return game
        try:
            node = game.next_step()
        except PipelineFinished:
            game.pipeline.current_step_index = -1
            game.pipeline.is_finished = False
            continue
        if game.special.placement_owner or node in ("on_turn_start", "before_reveal") or (
                isinstance(node, tuple) and "before_duel_start" in node):
            choose_actions(game)
    raise AssertionError("空白镜像对局未能在步数预算内结束")


class MirrorMatchTests(unittest.TestCase):
    def test_two_standard_decks_finish_a_seeded_match(self):
        with redirect_stdout(io.StringIO()) as log:
            game = mirror_match()
        self.assertIn("从对方手中抽取", log.getvalue())
        self.assertIn("锁定位置", log.getvalue())
        self.assertEqual([p.characters[0].statuses.get("空白已发动") for p in game.players], [1, 1])
        self.assertEqual(game.winner.name, "望衡")
        self.assertEqual(sum(p.characters[0].is_alive for p in game.players), 1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--replay"]:
        mirror_match(*map(int, sys.argv[2:]))
    else:
        unittest.main()
