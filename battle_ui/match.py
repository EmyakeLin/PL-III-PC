"""Local two-player battle host. Only human placement waits cross HTTP requests."""

from collections import deque
import random

from displayer import Displayer
from game import Game
from loader import load_characters_from_packs
from models.character import Character
from models.dice import TYPE_NAMES
from pipeline.pipeline_errors import PipelineFinished
from player.player import Player


class StaleActionError(ValueError):
    """The client submitted an action for an earlier position."""


class _TableGame(Game):
    def run_placement(self):
        """Open the first placement window. The browser supplies each decision."""
        self.placing = self.first_player
        self.placed_this_window = 0


class BattleMatch:
    """Drive the normal pipeline up to its next decision or public combat result."""

    def __init__(self, roster=None, *, seed=None, initial_handoff=False):
        pool = {spec["id"]: spec for spec in load_characters_from_packs()}
        if roster is None:
            roster = ("plan_b_annolin", "waa_lake")
        if (not isinstance(roster, (tuple, list)) or len(roster) != 2
                or any(not isinstance(key, str) or key not in pool for key in roster)
                or roster[0] == roster[1]):
            raise ValueError("请为双方选择两名不同的出战角色。")
        self.choices = [
            {key: spec.get(key) for key in ("id", "name", "title", "rank", "max_hp", "faction")}
            for spec in pool.values()
        ]
        players = [Player(1, "玩家一"), Player(2, "玩家二")]
        self.game = _TableGame(players, rng=random.Random(seed))
        for key, player in zip(roster, players):
            character = Character(pool[key], player)
            player.characters.append(character)
            character.init_cards()
            character.setup_deck()
            player.cardspace.draw.shuffle(self.game.rng)
        self._views = {side: Displayer(self.game, viewer_side=side) for side in (None, 1, 2)}
        self._history = deque(maxlen=100)
        self._window_size = 1
        self._require_handoff = initial_handoff
        self.revision = 0
        self._advance()

    def _legal_cards(self):
        player = self.game.placing
        return [card for card in player.cardspace.hand.content
                if card.character.is_alive and card.character.used_duels < card.character.max_duels]

    def snapshot(self):
        placing = self.game.placing
        side = placing.side if placing and self.mode in ("handoff", "placement") else None
        private = self.mode == "placement"
        return {
            "mode": self.mode, "revision": self.revision, "active_side": side,
            "frame": self._views[side if private else None].snapshot(),
            "catalog": self._views[None].catalog(), "choices": [dict(c) for c in self.choices],
            "legal_cards": [c.id for c in self._legal_cards()] if private else [],
            "can_pass": private and self.game.placed_this_window > 0,
            "window_remaining": self._window_size - self.game.placed_this_window if private else 0,
            "history": list(self._history),
        }

    def act(self, action, revision, *, card_id=None):
        if type(revision) is not int or revision != self.revision:
            raise StaleActionError("对局已经推进，请查看当前局面。")
        if self.mode == "handoff" and action == "ready":
            self.mode = "placement"
        elif self.mode in ("reveal", "combat", "turn_end") and action == "next":
            self._advance()
        elif self.mode == "placement" and action in ("place", "pass", "end"):
            self._place_action(action, card_id)
        else:
            raise ValueError("当前阶段无法执行这个操作。")
        self.revision += 1
        return self.snapshot()

    def _place_action(self, action, card_id):
        game = self.game
        player = game.placing
        if action == "place":
            card = next((c for c in self._legal_cards() if c.id == card_id), None)
            if card is None:
                raise ValueError("这张手牌当前无法扣置。")
            if game.auto_place_in_duel(player.side, card):
                game.placed_this_window += 1
                if game.is_over:
                    self._finish()
                    return
                if game.placed_this_window < self._window_size:
                    if self._legal_cards():
                        return
                    game.ended_player.append(player)
            # An intercepted placement passes the window just as the terminal does.
        elif action == "pass":
            if not game.placed_this_window:
                raise ValueError("本次至少扣置一张后可以交权。")
        else:
            game.ended_player.append(player)
        if game.is_over:
            self._finish()
            return
        game.switch_place_right()
        self._window_size = game.gamerule.PLACE_CAPACITY
        game.placed_this_window = 0
        self._open_window(previous=player)
        if game.placing is None:
            self._advance()

    def _open_window(self, previous=None):
        game = self.game
        # The terminal automatically ends a player's placement when no card fits.
        while game.placing is not None and not self._legal_cards():
            game.ended_player.append(game.placing)
            game.switch_place_right()
            self._window_size = game.gamerule.PLACE_CAPACITY
        if game.placing is not None:
            switching = previous is not None and game.placing is not previous
            self.mode = "handoff" if self._require_handoff or switching else "placement"
            self._require_handoff = False

    def _advance(self):
        game = self.game
        while not game.is_over:
            try:
                node = game.next_step()
            except PipelineFinished:
                game.pipeline.current_step_index = -1
                game.pipeline.is_finished = False
                continue
            if game.is_over:
                break
            if node == "logic_start_placement":
                self._window_size = 1
                self._history.append(f"第 {game.turn_number} 回合，{game.first_player.name}先手。")
                self._open_window()
                if game.placing is not None:
                    return
            elif node == "logic_reveal":
                self.mode = "reveal"
                count = len(game.duelspace.space)
                message = f"双方开牌，共 {count} 个交锋。" if count else "双方空过。"
                self._history.append(message)
                return
            elif node == "after_turn_end":
                self.mode = "turn_end"
                self._require_handoff = True
                self._history.append(f"第 {game.turn_count} 回合结束。")
                return
            elif isinstance(node, tuple) and self._combat_stop(node):
                self.mode = "combat"
                return
        self._finish()

    def _combat_stop(self, nodes):
        # next_step returns one executed node per side, even when the other side
        # is parked on an earlier node. Use this tick to avoid replaying old hits.
        checkpoints = ("on_clash_win", "on_clash_draw", "on_clash_lose",
                       "on_clash_skip", "after_dice_hit", "logic_skill_use")
        if not any(node in checkpoints for node in nodes):
            return False
        game = self.game
        combat = self._views[None].snapshot()["combat"]
        if combat is None:
            return False
        actions = []
        scores = []
        pause = False
        for node, side, player in zip(nodes, combat["sides"], game.players):
            character = player.characters[0]
            die = side["die"]
            if node == "logic_skill_use":
                pipe = game.pipeline.side_pipelines[player.side]
                verb = "使用" if pipe.paid else "未能支付"
                actions.append(f"{character.name}{verb} {pipe.card.name}")
            elif node in ("on_clash_win", "on_clash_draw", "on_clash_lose") and die:
                result = {"win": "胜", "draw": "平", "lose": "负"}[die["result"]]
                scores.append(f"{character.name} {die['clash_score']}（{result}）")
                pause = True
            elif node == "on_clash_skip" and die:
                actions.append(f"{character.name}的{TYPE_NAMES[die['type']]}跳过拼点")
                pause = True
            elif node == "after_dice_hit" and die:
                enemy = next(p.characters[0] for p in game.players if p is not player)
                attack = "单方面攻击" if die["result"] is None else "进攻"
                actions.append(f"{character.name}{attack}，{enemy.name}生命 {enemy.hp}/{enemy.max_hp}")
                pause = True
        if scores:
            actions.append("拼点 " + " · ".join(scores))
        if actions:
            self._history.append(f"交锋 {combat['duel_number']}　" + "，".join(actions) + "。")
        return pause

    def _finish(self):
        self.mode = "finished"
        winner = self.game.winner
        fallen = [p.characters[0].name for p in self.game.players if not p.characters[0].is_alive]
        if fallen:
            self._history.append("、".join(fallen) + "阵亡。")
        self._history.append(f"{winner.name}获胜。" if winner else "双方全灭，平局。")
