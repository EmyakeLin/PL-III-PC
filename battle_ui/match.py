"""Local two-player battle host for private declarations and public resolution."""

from collections import deque
import random
import time

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

    def run_pre_reveal_declarations(self):
        """The browser supplies each attack and interception separately."""


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
        self._pre_seat = None
        self._response_times = []
        self.revision = 0
        self._advance()

    def _legal_cards(self):
        player = self.game.placing
        return [card for card in player.cardspace.hand.content
                if card.character.is_alive and card.character.used_duels < card.character.max_duels]

    def snapshot(self):
        deciding = self.mode in ("placement", "pre_attack", "intercept")
        early = self.game.pre_reveal
        player = self._pre_seat or self.game.placing
        side = player.side if player and (deciding or self.mode == "handoff") else None
        private_pre = deciding and self._pre_seat is not None
        attacks = [c.id for c in early.attack_cards(player)] if private_pre else []
        intercepts = [c.id for c in early.intercept_cards(player)] if private_pre else []
        legal_cards = {"pre_attack": attacks, "intercept": intercepts}.get(self.mode, [])
        if self.mode == "placement":
            legal_cards = [c.id for c in self._legal_cards()]
        frame = self._views[side if deciding else None].snapshot()
        return {
            "mode": self.mode, "revision": self.revision, "active_side": side,
            "frame": frame,
            "catalog": self._views[None].catalog(), "choices": [dict(c) for c in self.choices],
            "legal_cards": legal_cards, "legal_attack_cards": attacks, "legal_intercept_cards": intercepts,
            "pending_responses": early.pending_for(player) if private_pre else [],
            "can_end_attack": private_pre and early.can_attack(player),
            "eligible_sides": frame["pre_reveal"]["eligible_sides"],
            "response_times": [dict(timing) for timing in self._response_times],
            "can_pass": self.mode == "placement" and self.game.placed_this_window > 0,
            "window_remaining": self._window_size - self.game.placed_this_window if self.mode == "placement" else 0,
            "history": list(self._history),
        }

    def act(self, action, revision, *, card_id=None, target=None, side=None, duel_number=None):
        if type(revision) is not int or revision != self.revision:
            raise StaleActionError("对局已经推进，请查看当前局面。")
        if self.mode == "handoff" and action == "ready":
            if self._pre_seat is not None:
                if side is not None:
                    self._pre_seat = self._choose_seat(side, self.game.pre_reveal.eligible_players())
                self.mode = self._pre_mode()
            else:
                if side is not None:
                    self._choose_seat(side, [self.game.placing])
                self.mode = "placement"
        elif self.mode in ("reveal", "combat", "turn_end") and action == "next":
            self._advance()
        elif self.mode == "placement" and action in ("place", "pass", "end"):
            self._place_action(action, card_id)
        elif self.mode in ("pre_attack", "intercept"):
            if action == "switch_side":
                others = [p for p in self.game.pre_reveal.eligible_players() if p is not self._pre_seat]
                if not others:
                    raise ValueError("当前只有一方可以操作。")
                self._pre_seat = self._choose_seat(side, others) if side is not None else others[0]
                self.mode = "handoff"
            else:
                self._pre_action(action, card_id, target, duel_number)
        else:
            raise ValueError("当前阶段无法执行这个操作。")
        self.revision += 1
        return self.snapshot()

    @staticmethod
    def _choose_seat(side, players):
        if type(side) is int:
            for player in players:
                if player.side == side:
                    return player
        raise ValueError("这一方当前无法接手。")

    def _pre_mode(self):
        phase = self.game.pre_reveal
        if phase.actor is self._pre_seat:
            return "pre_attack" if phase.phase == "attack" else "intercept"
        return "pre_attack" if phase.can_attack(self._pre_seat) else "intercept"

    def _pre_action(self, action, card_id, target, duel_number):
        phase = self.game.pre_reveal
        player = self._pre_seat
        card = next((c for c in player.cardspace.hand.content if c.id == card_id), None)
        if action == "end_attack":
            phase.end_attack(player)
            self._history.append(f"{player.name}结束主动进攻。")
        elif action in ("intercept", "let_through"):
            pending = phase.pending_for(player)
            if duel_number is None and len(pending) == 1:
                duel_number = pending[0]
            if type(duel_number) is not int or duel_number not in pending:
                raise ValueError("请选择仍待己方迎击的交锋编号。")
            if action == "let_through":
                phase.pass_intercept(duel_number, player=player)
                self._history.append(f"{player.name}放行开牌前交锋 {duel_number}。")
            else:
                if card is None:
                    raise ValueError("请选择自己的迎击手牌。")
                phase.intercept(card, duel_number)
                self._history.append(f"开牌前交锋 {duel_number} 转火到{player.name}的{card.name}。")
        elif action == "attack" and card is not None and isinstance(target, dict):
            if target.get("kind") == "character":
                enemy = next(p for p in self.game.players if p is not player)
                actor = next((c for c in enemy.characters if c.id == target.get("id") and c.is_alive), None)
                if actor is None:
                    raise ValueError("请选择存活的敌方角色。")
                phase.declare_attack(card, character=actor)
                label = actor.name
            elif target.get("kind") == "duel" and type(target.get("number")) is int:
                phase.declare_attack(card, duel_index=target["number"] - 1)
                label = f"常规交锋 {target['number']}"
            else:
                raise ValueError("请选择角色或常规交锋。")
            self._history.append(f"开牌前交锋 {len(phase.space.space)}　{card.name} → {label}。")
        else:
            raise ValueError("当前开牌前交锋无法执行这个操作。")
        self._record_response_times()
        self._pre_seat = phase.actor
        if self.game.is_over:
            self._finish()
        elif phase.actor is None:
            self._advance()
        else:
            self.mode = self._pre_mode() if phase.actor is player else "handoff"

    def _record_response_times(self):
        now = time.time_ns() // 1_000_000
        for index, slot in enumerate(self.game.pre_reveal.space.space):
            if index == len(self._response_times):
                self._response_times.append({"number": index + 1, "declared_at_ms": now,
                                             "answered_at_ms": None})
            timing = self._response_times[index]
            if slot.ready and timing["answered_at_ms"] is None:
                timing["answered_at_ms"] = max(now, timing["declared_at_ms"])

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
            elif node == "logic_before_reveal_declarations" and game.pre_reveal.actor is not None:
                self._pre_seat = game.pre_reveal.actor
                self.mode = "handoff"
                return
            elif node == "logic_reveal":
                self.mode = "reveal"
                count = len(game.duelspace.space)
                message = f"双方开牌，共 {count} 个常规交锋。" if count else "双方没有常规扣牌。"
                self._history.append(message)
                return
            elif node == "after_turn_end":
                self.mode = "turn_end"
                self._response_times.clear()
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
        checkpoints = ("logic_duel_start", "on_clash_win", "on_clash_draw", "on_clash_lose",
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
        early = combat["kind"] == "pre_reveal"
        if early and "logic_duel_start" in nodes:
            slot = game.pre_reveal.space.space[combat["duel_number"] - 1]
            if slot.target_duel_index is not None and slot.resolved_target is not None:
                position = slot.target_duel_index + 1
                if slot.pulled_card is not None:
                    actions.append(f"常规交锋 {position} 的{slot.pulled_card.name}被牵制")
                else:
                    actions.append(f"常规交锋 {position} 已空，转向原持牌人{slot.resolved_target.name}")
        scored = any(n in ("on_clash_win", "on_clash_draw", "on_clash_lose") for n in nodes)
        for node, side, player in zip(nodes, combat["sides"], game.players):
            character = player.characters[0]
            die = side["die"]
            if node == "logic_skill_use":
                pipe = game.pipeline.side_pipelines[player.side]
                verb = "使用" if pipe.paid else "未能支付"
                actions.append(f"{character.name}{verb} {pipe.card.name}")
                if pipe.paid and side["range_deficit"]:
                    actions.append(f"{pipe.card.name}处于 {side['range_deficit']} 级远程劣势")
            elif scored and die and die["result"] in ("win", "lose", "draw"):
                result = {"win": "胜", "draw": "平", "lose": "负"}[die["result"]]
                if die["win_branch_skipped"]:
                    result += "，跳过拼赢分支"
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
            prefix = "开牌前交锋" if combat["kind"] == "pre_reveal" else "常规交锋"
            self._history.append(f"{prefix} {combat['duel_number']}　" + "，".join(actions) + "。")
        return pause

    def _finish(self):
        self.mode = "finished"
        winner = self.game.winner
        fallen = [p.characters[0].name for p in self.game.players if not p.characters[0].is_alive]
        if fallen:
            self._history.append("、".join(fallen) + "阵亡。")
        self._history.append(f"{winner.name}获胜。" if winner else "双方全灭，平局。")
