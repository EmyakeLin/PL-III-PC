"""Local two-player battle host for private declarations and public resolution."""

from collections import Counter, deque
import random
import time

from displayer import Displayer, _passives, _printed_skill, hand_key, special_seats, timing_label
from game import Game
from loader import PACKS, load_characters_from_packs
from models.character import Character
from models.dice import TYPE_NAMES
from pipeline.pipeline_errors import PipelineFinished
from player.player import Player

from .fx_compiler import discover_character_fx, discover_fx_scripts
from .table_bridge import TableBridge
from .status_icons import discover_status_visuals


class StaleActionError(ValueError):
    """The client submitted an action for an earlier position."""


def _normalize_roster(roster, pool, *, open_rosters=False):
    if roster is None:
        roster = ("plan_b_annolin", "plan_b_heck")
    if not isinstance(roster, (tuple, list)) or len(roster) != 2:
        raise ValueError("请为双方选择不同的出战角色。")
    if all(isinstance(item, str) for item in roster):
        teams = ([roster[0]], [roster[1]])
    elif all(isinstance(team, (tuple, list)) for team in roster):
        teams = (list(roster[0]), list(roster[1]))
    else:
        raise ValueError("请为双方选择有效的出战角色。")
    seen = set()
    for team in teams:
        if not team or (not open_rosters and len(team) > 3):
            if open_rosters:
                raise ValueError("双方都需要至少一名出战角色。")
            raise ValueError("每方须选择 1 至 3 名出战角色。")
        team_seen = set()
        for key in team:
            if not isinstance(key, str) or key not in pool:
                raise ValueError("出战角色不在本房间的卡包中。")
            if not open_rosters and (key in team_seen or (key in seen and not pool[key].get("mirror_allowed"))):
                raise ValueError("请为双方选择不同的有效出战角色。")
            team_seen.add(key)
            seen.add(key)
    return teams


_CHARACTER_RANDOM_COLOR_POOL = (
    "#1c946b", "#c95a2b", "#2478cc", "#c44558",
    "#5d8f2c", "#c98216", "#1e8a78", "#b5482e",
    "#2f85a8", "#9e5a28", "#3b8c52", "#b84363",
    "#7c8a2e", "#bd6820", "#22857a", "#a65632",
    "#448a6b", "#c26e1d",
)


def _parse_pack_color(raw):
    if isinstance(raw, int) and 0 <= raw <= 0xFFFFFF:
        return f"#{raw:06x}"
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text.startswith("0x"):
            text = text[2:]
        elif text.startswith("#"):
            text = text[1:]
        if len(text) == 6 and all(ch in "0123456789abcdef" for ch in text):
            return f"#{text}"
    return None


def _assign_character_colors(pool):
    """Use pack-configured `color`/`card_color` when present; randomly assign distinct colors otherwise."""
    rng = random.Random()
    configured = {}
    used = set()
    for cid, spec in pool.items():
        parsed = _parse_pack_color(spec.get("color") or spec.get("card_color"))
        if parsed:
            configured[cid] = parsed
            used.add(parsed)

    available = [c for c in _CHARACTER_RANDOM_COLOR_POOL if c not in used]
    rng.shuffle(available)
    fallback = list(_CHARACTER_RANDOM_COLOR_POOL)
    rng.shuffle(fallback)

    colors = dict(configured)
    idx = 0
    for cid in pool:
        if cid in colors:
            continue
        if available:
            colors[cid] = available.pop()
        else:
            colors[cid] = fallback[idx % len(fallback)]
            idx += 1
    return colors


def _discover_character_sprites(pool, sprites_dir=None):
    """Auto-discover convention-based `_packs/sprites/<char_id>.svg` (or optional `sprite_svg`)."""
    root = (sprites_dir if sprites_dir is not None else (PACKS / "sprites")).resolve()
    if not root.is_dir():
        return {}
    found = {}
    for cid, spec in pool.items():
        candidates = []
        explicit = spec.get("sprite_svg")
        if isinstance(explicit, str) and explicit.strip():
            candidates.append(explicit.strip().lstrip("/"))
        candidates.append(f"{cid}.svg")
        for rel in candidates:
            if "\\" in rel or ".." in rel.split("/") or not rel.lower().endswith(".svg"):
                continue
            target = (root / rel).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                continue
            if target.is_file():
                found[cid] = f"/sprites/{target.relative_to(root).as_posix()}"
                break
    return found


def _roster_preview(spec, color=None, sprite_url=None):
    return {
        "id": spec["id"],
        "name": spec["name"],
        "title": spec.get("title"),
        "rank": spec["rank"],
        "max_hp": spec["max_hp"],
        "base_duels": Character.base_duels(spec),
        "mirror_allowed": bool(spec.get("mirror_allowed")),
        "faction": spec.get("faction", ""),
        "color": color,
        "sprite_url": sprite_url,
        "passives": _passives(spec.get("passive_skills", ())),
        "faction_passives": _passives(spec.get("faction_passives", ())),
        "skills": [_printed_skill(skill) for skill in spec.get("skills", ())],
    }


def roster_art(pool):
    colors = _assign_character_colors(pool)
    sprites = _discover_character_sprites(pool)
    catalog = [_roster_preview(spec, colors.get(cid), sprites.get(cid)) for cid, spec in pool.items()]
    return colors, sprites, catalog


class BattleMatch:
    """Drive the normal pipeline up to its next decision or public combat result."""

    def __init__(self, roster=None, *, seed=None, initial_handoff=False, open_rosters=False, extra_packs=()):
        pool = {spec["id"]: spec for spec in load_characters_from_packs(extra_packs=extra_packs)}
        teams = _normalize_roster(roster, pool, open_rosters=open_rosters)
        self._character_colors, self._character_sprites, self._roster_catalog = roster_art(pool)
        self._character_fx = discover_character_fx(pool, self._character_colors)
        self._fx_scripts = discover_fx_scripts()
        self._status_visuals = discover_status_visuals(pool)
        self.choices = [
            {
                **{key: spec.get(key) for key in ("id", "name", "title", "rank", "max_hp", "faction", "mirror_allowed")},
                "max_lightcore_hp": Character.initial_lightcore_max(spec["max_hp"]),
                "color": self._character_colors.get(spec["id"]),
                "sprite_url": self._character_sprites.get(spec["id"]),
            }
            for spec in pool.values()
        ]
        players = [Player(1, "玩家一"), Player(2, "玩家二")]
        self.game = Game(players, rng=random.Random(seed))
        self.presentation = TableBridge(self.game.context)
        self.game.deploy_rosters([[pool[key] for key in team] for team in teams])
        if open_rosters:
            counts = Counter(key for team in teams for key in team)
            for team, player in zip(teams, players):
                teammates = Counter(team)
                for position, (key, character) in enumerate(zip(team, player.characters), 1):
                    if counts[key] > 1:
                        character.id = f"@{player.side}.{position}:{key}"
                        if teammates[key] > 1:
                            character.name += f"（{position}号）"
        self._views = {side: Displayer(self.game, viewer_side=side) for side in (None, 1, 2)}
        self._history = deque(maxlen=100)
        self._require_handoff = initial_handoff
        self._pre_seat = None
        self._draw_seat = None
        self._response_times = []
        self._special_open = False
        self._special_seat = None
        self._interrupt_returns = []
        self._emitted_dice_rolls = set()
        self.game.pipeline.pause_on_clash_scores = True
        self._timing = ""
        self.revision = 0
        self._advance()

    @property
    def _window_size(self):
        return self.game.placement_capacity

    def _legal_cards(self):
        return self.game.legal_placements()

    def _current_draw_prompt(self, *, viewer_side=None):
        if self.game.pending_draw is None:
            return None
        pending = self.game.pending_draw
        if self._draw_seat is not pending.player:
            return None
        if (self.mode != "draw_select" if viewer_side is None else self._draw_seat.side != viewer_side):
            return None
        return {
            "side": pending.player.side,
            "keep": pending.keep,
            "discard_count": pending.discard_count,
            "candidates": [
                {
                    **_printed_skill(c.data),
                    "action_key": key,
                    "character_id": c.character.id,
                    "character_name": c.character.name,
                    "cost": c.cost,
                }
                for key, c in self._draw_candidate_keys(pending).items()
            ],
        }

    def table_assets(self):
        return {
            "character_colors": dict(self._character_colors),
            "character_sprites": dict(self._character_sprites),
            "character_fx": dict(self._character_fx),
            "fx_scripts": dict(self._fx_scripts),
            "status_visuals": dict(self._status_visuals),
            "roster_catalog": self._roster_catalog,
        }

    def snapshot(self):
        deciding = self.mode in ("placement", "pre_attack", "intercept", "draw_select")
        early = self.game.pre_reveal
        player = self._draw_seat or self._pre_seat or self.game.placing
        side = player.side if player and (deciding or self.mode == "handoff") else None
        private_pre = self.mode in ("pre_attack", "intercept") and self._pre_seat is not None
        attack_cards = early.attack_cards(player) if private_pre else []
        attacks = [hand_key(c) for c in attack_cards]
        intercepts = [hand_key(c) for c in early.intercept_cards(player)] if private_pre else []
        legal_cards = {"pre_attack": attacks, "intercept": intercepts}.get(self.mode, [])
        if self.mode == "placement":
            legal_cards = [hand_key(c) for c in self._legal_cards()]
        mode = self.mode
        seats = special_seats(self.game)
        special_options = []
        if self._special_open:
            deciding = self._special_seat is not None
            mode = "special" if deciding else "special_handoff"
            side = self._special_seat.side if deciding else seats[0].side if seats else None
            private_pre = False
            legal_cards, attacks, intercepts = [], [], []
            if deciding:
                special_options = self._views[side].special_actions()
        frame = self._views[side if deciding else None].snapshot()
        card_owners = {
            "duels": {
                f"{num}:{p.side}": [
                    {
                        "character_id": c.character.id,
                        "character_name": c.character.name,
                        "character_color": self._character_colors.get(c.character.id),
                    }
                    for c in slot.get_content(p.side)
                ]
                for num, slot in enumerate(self.game.duelspace.space, 1)
                for p in self.game.players
            },
            "pre_reveal": {
                f"{num}:{p.side}": [
                    {
                        "character_id": c.character.id,
                        "character_name": c.character.name,
                        "character_color": self._character_colors.get(c.character.id),
                    }
                    for c in slot.get_content(p.side)
                ]
                for num, slot in enumerate(self.game.pre_reveal.space.space, 1)
                for p in self.game.players
            },
        }
        return {
            "mode": mode, "revision": self.revision, "active_side": side,
            "special_available": bool(seats) and self.mode != "draw_select",
            "special_options": special_options,
            "special_pending": self.game.special.pending_attack is not None or self.game.special.decision_owner is not None,
            "card_choice": self.game.special.card_decision is not None,
            "effect_choice": self._views[side].effect_choice() if mode == "special" else None,
            "queued_placement": self.game.special.placement_owner is not None,
            "special_timing": self._timing,
            "draw_select": self._current_draw_prompt(),
            "speed_rolls": list(self.presentation.speed_rolls),
            **self.table_assets(),
            "card_owners": card_owners,
            "default_targets": {
                str(p.side): p.default_target_character.id
                if p.default_target_character and p.default_target_character.is_alive else None
                for p in self.game.players
            },
            "fx_events": list(self.presentation.events),
            "frame": frame,
            "catalog": self._views[None].catalog(),
            "choices": [dict(c) for c in self.choices],
            "legal_cards": legal_cards, "legal_attack_cards": attacks, "legal_intercept_cards": intercepts,
            "attack_targets": {hand_key(c): [{"kind": "character", "id": actor.id} if actor is not None
                              else {"kind": "duel", "number": i + 1} for actor, i in early.attack_targets(c)]
                               for c in attack_cards} if private_pre else {},
            "pending_responses": early.pending_for(player) if private_pre else [],
            "can_end_attack": private_pre and early.can_attack(player),
            "eligible_sides": [p.side for p in seats] if self._special_open else frame["pre_reveal"]["eligible_sides"],
            "response_times": [dict(timing) for timing in self._response_times],
            "can_pass": self.mode == "placement" and self.game.placed_this_window > 0,
            "window_remaining": self._window_size - self.game.placed_this_window if self.mode == "placement" else 0,
            "history": list(self._history),
        }

    def act(self, action, revision, *, card_id=None, card_ids=None, target=None, side=None,
            duel_number=None, option=None, character_id=None):
        if type(revision) is not int or revision != self.revision:
            raise StaleActionError("对局已经推进，请查看当前局面。")
        if action == "set_default_target":
            owner = self._choose_seat(side, self.game.players)
            enemy = next(p for p in self.game.players if p is not owner)
            actor = next((c for c in enemy.characters if c.id == character_id and c.is_alive), None)
            if actor is None:
                raise ValueError("请选择存活的敌方角色作为集火目标。")
            owner.set_default_target(actor)
            self.revision += 1
            return self.snapshot()
        if self._special_open:
            self._special_action(action, side, option)
        elif action == "open_special" and special_seats(self.game) and self.mode != "draw_select":
            viewer = None
            if side is not None:
                private = self.game.placing if self.mode == "placement" else (
                    self._pre_seat if self.mode in ("pre_attack", "intercept") else None)
                if private is None or private not in special_seats(self.game):
                    raise ValueError("请先由行动方接手。")
                viewer = self._choose_seat(side, [private])
            self._special_open = True
            self._special_seat = viewer
        elif self.mode == "handoff" and action == "ready":
            if self._draw_seat is not None:
                if side is not None:
                    self._choose_seat(side, [self._draw_seat])
                self.mode = "draw_select"
            elif self._pre_seat is not None:
                if side is not None:
                    self._pre_seat = self._choose_seat(side, self.game.pre_reveal.eligible_players())
                self.mode = self._pre_mode()
            else:
                if side is not None:
                    self._choose_seat(side, [self.game.placing])
                self.mode = "placement"
        elif self.mode == "draw_select" and action == "draw_bottom":
            self._draw_bottom_action(card_ids)
        elif self.mode in ("reveal", "combat", "turn_end", "timing") and action == "next":
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
        # An action during placement or declarations can itself request a choice
        # without advancing the public pipeline to another node.
        owner = self.game.special.decision_owner
        if owner is not None and not self._special_open:
            self._special_open = True
            self._special_seat = None
        self.revision += 1
        return self.snapshot()

    @staticmethod
    def _draw_candidate_keys(pending):
        cards = pending.candidates
        counts = Counter(card.id for card in cards)
        return {card.id if counts[card.id] == 1 else f"instance:{card.instance_id}": card for card in cards}

    def _draw_bottom_action(self, card_ids):
        if self.game.pending_draw is None:
            raise ValueError("当前没有待挑选的抽牌候选。")
        pending = self.game.pending_draw
        player = pending.player
        discard_count = pending.discard_count
        if (not isinstance(card_ids, list) or len(card_ids) != discard_count
                or not all(isinstance(key, str) for key in card_ids)
                or len(set(card_ids)) != discard_count):
            raise ValueError(f"请选择 {discard_count} 张不同的牌置于抽牌堆底。")
        by_id = self._draw_candidate_keys(pending)
        if any(cid not in by_id for cid in card_ids):
            raise ValueError("所选置底牌不在当前候选范围内。")
        self.presentation.emit("draw_bottom", side=player.side, count=discard_count)
        self.game.complete_draw(pending, [by_id[cid] for cid in card_ids])
        self._history.append(f"{player.name}看顶选 {discard_count} 张置底，保留 {pending.keep} 张手牌。")
        if self.game.pending_draw:
            self._draw_seat = self.game.pending_draw.player
            self.mode = "handoff"
        else:
            last_drawer = self._draw_seat
            self._draw_seat = None
            self._require_handoff = True
            self._advance()
            if self.mode == "handoff" and self.game.placing is last_drawer:
                self.mode = "placement"

    def _special_action(self, action, side, option):
        game = self.game
        seats = special_seats(game)
        if action == "ready" and self._special_seat is None:
            self._special_seat = self._choose_seat(side if side is not None else seats[0].side, seats)
            return
        if action == "leave_special" and game.special.pending_attack is None and game.special.decision_owner is None:
            self._return_from_special(self._special_seat)
            return
        if action == "switch_side" and self._special_seat is not None and len(seats) > 1:
            self._special_seat = None
            return
        if action != "use_special" or self._special_seat is None:
            raise ValueError("请接手特殊行动，选择合法的操作。")
        player = self._special_seat
        options = game.special.options(player)
        if type(option) is not int or not 0 <= option < len(options):
            raise ValueError("该选项不在当前的特殊行动中。")
        move = options[option]
        if move.kind == "ability":
            ability_name = next(s["name"] for s in move.character.action_specs() if s["id"] == move.ability_id)
        old_space = game.pipeline.interrupt_space
        public_replacement = move.kind == "replace" and self._views[None]._board_visible(move.target_card)
        succeeded = game.special.apply(player, move)
        # Face-down placements and replacements must remain hidden in the public log.
        if move.kind == "place":
            message = "特殊置卡"
        elif move.kind == "replace":
            message = "替换技能"
            if succeeded is not False:
                public_cards = {"old_card_id": move.target_card.id, "new_card_id": move.card.id} if public_replacement else {}
                self.presentation.emit("card_replace", side=player.side, **public_cards)
        elif move.kind == "pass_intercept":
            message = f"放行即时交锋 {move.response_number}"
        elif move.kind == "intercept":
            message = f"用{move.card.name}迎击即时交锋 {move.response_number}"
        elif move.kind == "ability":
            message = f"使用{ability_name}"
            if move.duel_index is not None and move.target_card.state.name == "PLACED_FACE_UP":
                message += f"，翻正常规交锋 {move.duel_index + 1} 的{move.target_card.name}"
        elif move.kind == "choose_slot":
            message = "依词条选择交锋"
        elif move.kind in ("choose_card", "decline_card"):
            message = "依词条选择技能" if move.kind == "choose_card" else "放弃此次选牌"
        else:
            message = f"打出{move.card.name}"
        suffix = "受阻" if succeeded is False else ""
        self._history.append(f"{player.name}{message}{suffix}。")
        self._record_response_times()
        self._special_seat = None
        if game.is_over:
            self._finish()
        elif game.special.pending_attack is not None or game.special.decision_owner is not None:
            self._special_open = True
            if game.special.decision_owner is player:
                self._special_seat = player
        elif game.pipeline.interrupt_space is not old_space:
            self._special_open = False
            self._interrupt_returns.append((self.mode, self._timing, old_space))
            self._advance()
        elif move.kind in ("choose_card", "choose_slot", "decline_card") and self.mode == "combat":
            self._special_open = False
            self._advance()
        else:
            self._return_from_special(player)

    def _return_from_special(self, viewer=None):
        self._special_open = False
        self._special_seat = None
        if self.game.pre_reveal.actor is not None and self.game.pipeline.interrupt_space is None:
            self._pre_seat = self.game.pre_reveal.actor
            self.mode = self._pre_mode() if self._pre_seat is viewer else "handoff"
        elif self.mode in ("placement", "handoff") and self._pre_seat is None:
            self._require_handoff = self.game.placing is not viewer
            self._open_window(previous=viewer)
            if self.game.placing is None:
                self._advance()
        elif self.mode in ("pre_attack", "intercept", "handoff"):
            self._pre_seat = self.game.pre_reveal.actor
            if self._pre_seat is None:
                self._advance()
            else:
                self.mode = "handoff"

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
        card = next((c for c in player.cardspace.hand.content if hand_key(c) == card_id), None)
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
            card = next((c for c in self._legal_cards() if hand_key(c) == card_id), None)
            if card is None:
                raise ValueError("这张手牌当前无法扣置。")
            game.submit_placement(player, card)
        else:
            game.submit_placement(player, after=action)
        if game.is_over:
            self._finish()
            return
        if game.placing is player and game.placed_this_window and self._legal_cards():
            return
        self._open_window(previous=player)
        if game.placing is None:
            self._advance()

    def _open_window(self, previous=None):
        game = self.game
        # The terminal automatically ends a player's placement when no card fits.
        while (game.placing is not None and not self._legal_cards()
               and not game.special.ability_options(game.placing)):
            game.submit_placement(game.placing, after="end")
        if game.placing is not None:
            switching = previous is not None and game.placing is not previous
            self.mode = "handoff" if self._require_handoff or switching else "placement"
            self._require_handoff = False

    def _advance(self):
        game = self.game
        while not game.is_over:
            previous_interrupt = game.pipeline.interrupt_space
            try:
                node = game.next_step()
            except PipelineFinished:
                game.pipeline.current_step_index = -1
                game.pipeline.is_finished = False
                continue
            if game.is_over:
                break
            if game.special.decision_owner is not None:
                self._special_open = True
                self._special_seat = None
                self._timing = "选择技能" if game.special.card_decision else "选择交锋"
                self.mode = "combat"
                return
            if self._interrupt_returns:
                previous_mode, timing, space = self._interrupt_returns[-1]
                if game.pipeline.interrupt_space is space:
                    self.mode, self._timing = previous_mode, timing
                    self._interrupt_returns.pop()
                    self._return_from_special()
                    return
            if (previous_interrupt is not None and previous_interrupt is not game.pipeline.interrupt_space
                    and node == ("FINISHED", "FINISHED") and game.pipeline.in_duel_phase):
                # A rule-triggered pursuit ends before the next hit of the paused play.
                self.mode = "combat"
                self._timing = "返回原交锋"
                return
            self._timing = timing_label(node)
            if node == "logic_draw_cards" and game.pending_draw:
                self._draw_seat = game.pending_draw.player
                self.mode = "handoff" if self._require_handoff else "draw_select"
                self._require_handoff = False
                return
            if node == "logic_start_placement":
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
            elif self._timing and self._pause_at_timing():
                if game.pipeline.in_duel_phase:
                    combat = self._views[None].snapshot()["combat"]
                    if combat is not None:
                        self._emit_unannounced_rolls(combat)
                self.mode = "timing"
                return
        self._finish()

    def _pause_at_timing(self):
        return bool(special_seats(self.game))

    def _roll_key(self, combat, side_num, die_number):
        return (self.game.turn_number, combat["kind"], combat["duel_number"], combat["round_id"], side_num, die_number)

    def _emit_unannounced_rolls(self, combat, *, sides_filter=None):
        game = self.game
        rolled_sides = []
        for side, player in zip(combat["sides"], game.players):
            if sides_filter is not None and player.side not in sides_filter:
                continue
            die = side["die"]
            if not die or die.get("rolled_value") is None:
                continue
            die_num = side.get("die_number") or die.get("position")
            key = self._roll_key(combat, player.side, die_num)
            if key in self._emitted_dice_rolls:
                continue
            pipe = game.pipeline.side_pipelines[player.side]
            character = pipe.card.character if pipe.card else next(
                (c for c in player.characters if c.is_alive), player.characters[0])
            self._emitted_dice_rolls.add(key)
            rolled_sides.append({
                "side": player.side,
                "character_id": character.id,
                "character_name": character.name,
                "card_id": side["card_id"],
                "die_number": die_num,
                "range_deficit": side["range_deficit"],
                **die,
            })
        if rolled_sides:
            self.presentation.emit(
                "dice_roll",
                duel_kind=combat["kind"],
                duel_number=combat["duel_number"],
                round_id=combat["round_id"],
                one_sided=len(rolled_sides) == 1 and rolled_sides[0].get("result") is None,
                sides=rolled_sides,
            )
        return rolled_sides

    def _combat_stop(self, nodes):
        checkpoints = ("logic_duel_start", "logic_dice_clash", "before_dice_hit",
                       "on_clash_win", "on_clash_draw", "on_clash_lose",
                       "on_clash_skip", "after_dice_hit", "logic_skill_use")
        if not any(node in checkpoints for node in nodes):
            return False
        game = self.game
        combat = self._views[None].snapshot()["combat"]
        if combat is None:
            return False
        # Roll-first gate: pause strictly AFTER rolling and BEFORE clash resolution or hit damage!
        if "logic_dice_clash" in nodes or "before_dice_hit" in nodes:
            rolled = self._emit_unannounced_rolls(combat)
            if rolled:
                prefix = {"pre_reveal": "开牌前交锋", "regular": "常规交锋", "instant": "即时交锋"}[combat["kind"]]
                roll_summary = " · ".join(f"{sd['character_name']} 掷出 {sd['rolled_value']}" for sd in rolled)
                self._history.append(f"{prefix} {combat['duel_number']}　{roll_summary}。")
                return True
            if not any(n in ("logic_duel_start", "on_clash_win", "on_clash_draw", "on_clash_lose",
                             "on_clash_skip", "after_dice_hit", "logic_skill_use") for n in nodes):
                return False
        actions = []
        scores = []
        pause = "logic_skill_use" in nodes and bool(combat["suspended"])
        early = combat["kind"] == "pre_reveal"
        if early and "logic_duel_start" in nodes:
            slot = game.pre_reveal.space.space[combat["duel_number"] - 1]
            if slot.target_duel_index is not None and slot.resolved_target is not None:
                position = slot.target_duel_index + 1
                if slot.pulled_card is not None:
                    actions.append(f"常规交锋 {position} 的{slot.pulled_card.name}被牵制")
                    self.presentation.emit(
                        "card_pull",
                        from_duel=position,
                        to_pre_reveal=combat["duel_number"],
                        defender_side=slot.pulled_card.player.side,
                        card_id=slot.pulled_card.id,
                        card_name=slot.pulled_card.name,
                    )
                else:
                    actions.append(f"常规交锋 {position} 已空，转向原持牌人{slot.resolved_target.name}")
        scored = any(n in ("on_clash_win", "on_clash_draw", "on_clash_lose") for n in nodes)
        clash_sides = []
        for node, side, player in zip(nodes, combat["sides"], game.players):
            pipe = game.pipeline.side_pipelines[player.side]
            character = pipe.card.character if pipe.card else next(
                (c for c in player.characters if c.is_alive), player.characters[0])
            die = side["die"]
            if node == "logic_skill_use":
                payment = pipe.payment
                if pipe.paid:
                    price = f"{payment['cost']} 费"
                    if resource := payment["resource_paid"]:
                        price += f"、{resource['amount']} {resource['status']}"
                    actions.append(f"{character.combat_name}使用 {pipe.card.name}（实付 {price}）")
                else:
                    actions.append(f"{character.combat_name}跳过「{pipe.card.name}」，{payment['failure_reason']}")
                    pause = True
                if pipe.paid and side["range_deficit"]:
                    actions.append(f"{pipe.card.name}处于 {side['range_deficit']} 级远程劣势")
            elif scored and die and die["result"] in ("win", "lose", "draw"):
                result = {"win": "胜", "draw": "平", "lose": "负"}[die["result"]]
                if die["win_branch_skipped"]:
                    result += "，跳过拼赢分支"
                if len(game.pipeline.current_clash_results) == 1:
                    scores.append(f"空白轮，{character.combat_name}（{result}）")
                else:
                    scores.append(f"{character.combat_name} {die['clash_score']}（{result}）")
                clash_sides.append({
                    "side": player.side,
                    "character_id": character.id,
                    "character_name": character.name,
                    "card_id": side["card_id"],
                    "die_number": side.get("die_number") or die.get("position"),
                    "range_deficit": side["range_deficit"],
                    **die,
                })
                pause = True
            elif node == "on_clash_skip" and die:
                actions.append(f"{character.combat_name}的{TYPE_NAMES[die['type']]}跳过拼点")
                clash_sides.append({
                    "side": player.side,
                    "character_id": character.id,
                    "character_name": character.name,
                    "card_id": side["card_id"],
                    "die_number": side.get("die_number") or die.get("position"),
                    "range_deficit": side["range_deficit"],
                    "skipped": True,
                    **die,
                })
                pause = True
            elif node == "after_dice_hit" and die:
                self._emit_unannounced_rolls(combat, sides_filter={player.side})
                target = pipe.target or next((c for c in next(
                    p for p in game.players if p is not player).characters if c.is_alive), None)
                attack = "单方面攻击" if die["result"] is None else "进攻"
                if target is not None:
                    actions.append(
                        f"{character.combat_name}{attack}，{target.combat_name}生命 {target.hp}/{target.max_hp}，"
                        f"完整度 {target.lightcore_hp}/{target.max_lightcore_hp}"
                    )
                    self.presentation.emit(
                        "combat_strike",
                        attacker_side=player.side,
                        attacker_id=character.id,
                        attacker_name=character.name,
                        target_side=target.player.side,
                        target_id=target.id,
                        target_name=target.name,
                        die_type=die["type"],
                        die_number=side.get("die_number"),
                        one_sided=die["result"] is None,
                        card_id=side["card_id"],
                        card_name=pipe.card.name if pipe.card else None,
                    )
                else:
                    actions.append(f"{character.combat_name}{attack}")
                pause = True
        if clash_sides:
            rolled_keys = [
                self._roll_key(combat, sd["side"], sd.get("die_number") or sd.get("position"))
                for sd in clash_sides
                if not sd.get("skipped") and sd.get("rolled_value") is not None
            ]
            already_rolled = bool(rolled_keys) and all(k in self._emitted_dice_rolls for k in rolled_keys)
            self._emitted_dice_rolls.update(rolled_keys)
            self.presentation.emit(
                "dice_clash",
                duel_kind=combat["kind"],
                duel_number=combat["duel_number"],
                round_id=combat["round_id"],
                blank_round=scored and len(game.pipeline.current_clash_results) == 1,
                already_rolled=already_rolled,
                sides=clash_sides,
            )
        if scores:
            actions.append("拼点 " + " · ".join(scores))
        if actions:
            prefix = {"pre_reveal": "开牌前交锋", "regular": "常规交锋", "instant": "即时交锋"}[combat["kind"]]
            self._history.append(f"{prefix} {combat['duel_number']}　" + "，".join(actions) + "。")
        return pause

    def _finish(self):
        self._special_open = False
        self._special_seat = None
        self._draw_seat = None
        self.mode = "finished"
        winner = self.game.winner
        fallen = [c.combat_name for p in self.game.players for c in p.characters if not c.is_alive]
        if fallen:
            self._history.append("、".join(fallen) + "阵亡。")
        self._history.append(f"{winner.name}获胜。" if winner else "双方全灭，平局。")
