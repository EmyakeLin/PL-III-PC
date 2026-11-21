"""Local two-player battle host for private declarations and public resolution."""

from collections import deque
import random
import time

from context.context import Context
from displayer import Displayer, _passives, _printed_skill, hand_key, special_seats, timing_label
from entry.entry import Entry, character_of
from game import Game
from loader import load_characters_from_packs
from models.card import CardState
from models.character import Character, DAMAGE_GRADES
from models.dice import TYPE_NAMES
from pipeline.pipeline_errors import PipelineFinished
from player.player import Player


class StaleActionError(ValueError):
    """The client submitted an action for an earlier position."""


class _TableCharacter(Character):
    def apply_resolved_damage(self, incoming, grade):
        if not self.is_alive or incoming <= 0:
            return 0
        multiplier = self.damage_multiplier()
        before = (self.shield, self.reinforced_shield, self.concept_shield, self.hp)
        lost = super().apply_resolved_damage(incoming, grade)
        after = (self.shield, self.reinforced_shield, self.concept_shield, self.hp)
        d_norm = before[0] - after[0]
        d_reinf = before[1] - after[1]
        d_conc = before[2] - after[2]
        if grade == "concept":
            absorbed = {"normal": 0, "reinforced": 0, "concept": d_conc}
            eroded = {"normal": d_norm, "reinforced": d_reinf}
        elif grade == "pierce":
            absorbed = {"normal": 0, "reinforced": d_reinf, "concept": 0}
            eroded = {"normal": d_norm, "reinforced": 0}
        else:
            absorbed = {"normal": d_norm, "reinforced": d_reinf, "concept": 0}
            eroded = {"normal": 0, "reinforced": 0}
        if self.game and hasattr(self.game, "emit_fx"):
            cause = self.game.context.event.get("damage_cause") or "attack"
            self.game.emit_fx(
                "damage",
                target_side=self.player.side,
                target_id=self.id,
                target_name=self.name,
                cause=str(cause),
                grade=grade,
                incoming=incoming,
                multiplier=multiplier,
                absorbed=absorbed,
                eroded=eroded,
                hp_lost=lost,
                hp_after=self.hp,
                max_hp=self.max_hp,
            )
        return lost

    def heal(self, amount):
        actual = super().heal(amount)
        if actual > 0 and self.game and hasattr(self.game, "emit_fx"):
            self.game.emit_fx(
                "heal",
                target_side=self.player.side,
                target_id=self.id,
                target_name=self.name,
                amount=actual,
                hp_after=self.hp,
                max_hp=self.max_hp,
            )
        return actual

    def lose_hp(self, amount):
        lost = super().lose_hp(amount)
        if lost > 0 and self.game and hasattr(self.game, "emit_fx"):
            self.game.emit_fx(
                "lose_hp",
                target_side=self.player.side,
                target_id=self.id,
                target_name=self.name,
                amount=lost,
                hp_after=self.hp,
                max_hp=self.max_hp,
            )
        return lost

    def on_attack_hit(self, die, target):
        triggered = super().on_attack_hit(die, target)
        if triggered and self.game and hasattr(self.game, "emit_fx"):
            self.game.emit_fx(
                "breath_crit",
                side=self.player.side,
                character_id=self.id,
                target_id=target.id if target else None,
                stacks=self.statuses.get("呼吸", 0),
            )
        return triggered

    def trigger_stagger(self):
        before = self.statuses.get("失衡", 0)
        triggered = super().trigger_stagger()
        if self.game and hasattr(self.game, "emit_fx"):
            self.game.emit_fx(
                "stagger_check",
                target_side=self.player.side,
                target_id=self.id,
                stacks_before=before,
                triggered=triggered,
            )
        return triggered

    def add_shield(self, kind, amount):
        before = (self.shield, self.reinforced_shield, self.concept_shield)
        val = super().add_shield(kind, amount)
        after = (self.shield, self.reinforced_shield, self.concept_shield)
        if self.game and hasattr(self.game, "emit_fx"):
            deltas = (
                ("normal", after[0] - before[0], after[0]),
                ("reinforced", after[1] - before[1], after[1]),
                ("concept", after[2] - before[2], after[2]),
            )
            for k, d, tot in deltas:
                if d > 0:
                    self.game.emit_fx(
                        "shield_gain",
                        side=self.player.side,
                        character_id=self.id,
                        name=self.name,
                        shield_kind=k,
                        amount=d,
                        total=tot,
                    )
        return val

    def apply_status_delta(self, name, amount, *, notify=True):
        before = dict(self.statuses)
        val = super().apply_status_delta(name, amount, notify=notify)
        if self.game and hasattr(self.game, "emit_fx"):
            # Resolve canonical key that changed
            changed = None
            for k in set(before) | set(self.statuses):
                if before.get(k, 0) != self.statuses.get(k, 0):
                    changed = k
                    break
            if changed is not None:
                prev_v = before.get(changed, 0)
                cur_v = self.statuses.get(changed, 0)
                self.game.emit_fx(
                    "status_change",
                    side=self.player.side,
                    character_id=self.id,
                    character_name=self.name,
                    status=changed,
                    before=prev_v,
                    after=cur_v,
                    delta=cur_v - prev_v,
                    burst=(changed == "裂血" and self.bleed_burst),
                )
        return val

    def _die(self):
        was_alive = self.is_alive
        super()._die()
        if was_alive and self.game and hasattr(self.game, "emit_fx"):
            self.game.emit_fx(
                "character_death",
                side=self.player.side,
                character_id=self.id,
                name=self.name,
            )


class _TablePlayer(Player):
    def select_card(self, total_draw, draw_count):
        draw = self.cardspace.draw
        candidates = list(draw.content[:total_draw])
        keep = min(len(candidates), draw_count)
        discard_count = len(candidates) - keep
        if discard_count:
            self.game._pending_draws.append({
                "player": self,
                "candidates": candidates,
                "keep": keep,
                "discard_count": discard_count,
            })
        else:
            self.draw_card(keep)

    def choose_one_sided_target(self, enemy_player):
        return self.get_default_target(enemy_player)

    def draw_card(self, draw_count):
        before = len(self.cardspace.hand.content)
        super().draw_card(draw_count)
        added = len(self.cardspace.hand.content) - before
        if added > 0 and self.game and hasattr(self.game, "emit_fx"):
            self.game.emit_fx("draw", side=self.side, count=added)

    def reset_on_turn_start(self):
        super().reset_on_turn_start()
        if self.game and hasattr(self.game, "emit_fx"):
            self.game.emit_fx(
                "cost_refill",
                side=self.side,
                common=self.available_cost,
                personal=[{"character_id": c.id, "available": c.available_cost}
                          for c in self.characters if c.is_alive],
            )

    def pay_skill_cost(self, card):
        char = card.character
        p_before = char.available_cost if char else 0
        c_before = self.available_cost
        paid = super().pay_skill_cost(card)
        if self.game and hasattr(self.game, "emit_fx"):
            self.game.emit_fx(
                "cost_pay",
                side=self.side,
                character_id=char.id if char else None,
                card_id=card.id,
                card_name=card.name,
                cost=card.cost,
                personal_paid=max(0, p_before - (char.available_cost if char else 0)),
                common_paid=max(0, c_before - self.available_cost),
                paid=bool(paid),
            )
        return paid


class _TableContext(Context):
    def register_entries(self, owner, specs):
        if getattr(owner, "type", None) == "blank":
            return super().register_entries(owner, specs)
        registered = []
        for spec in specs or ():
            if isinstance(spec, dict) and "entries" in spec and "trigger" not in spec:
                group = super().register_entries(owner, spec["entries"])
                p_name = spec.get("name") or ""
                for entry in group:
                    entry._passive_name = p_name
                registered.extend(group)
            else:
                registered.extend(super().register_entries(owner, [spec]))
        return registered

    def _invoke(self, entry):
        p_name = getattr(entry, "_passive_name", None)
        char = character_of(entry.owner) if p_name else None
        if not p_name or char is None or not self.game or not hasattr(self.game, "emit_fx"):
            return super()._invoke(entry)

        seq_before = self.game._fx_seq
        player = getattr(char, "player", None)
        card = self.event.get("card")
        vref = self.event.get("value_ref")
        hm = self.event.get("hit_modifiers")
        before = (
            char.turn_duel_bonus,
            char.next_turn_duels,
            char.turn_cost_adjustment,
            player.turn_cost_adjustment if player else 0,
            len(player.cardspace.hand.content) if player else 0,
            (getattr(card, "final_bonus", 0), getattr(card, "level_bonus", 0), len(getattr(card, "use_state", {}))) if card else None,
            (getattr(vref, "floor", None), getattr(vref, "ceiling", None)) if vref else None,
            len(hm) if isinstance(hm, list) else 0,
            len(self.game.next_turn_statuses),
        )
        res = super()._invoke(entry)
        after = (
            char.turn_duel_bonus,
            char.next_turn_duels,
            char.turn_cost_adjustment,
            player.turn_cost_adjustment if player else 0,
            len(player.cardspace.hand.content) if player else 0,
            (getattr(card, "final_bonus", 0), getattr(card, "level_bonus", 0), len(getattr(card, "use_state", {}))) if card else None,
            (getattr(vref, "floor", None), getattr(vref, "ceiling", None)) if vref else None,
            len(hm) if isinstance(hm, list) else 0,
            len(self.game.next_turn_statuses),
        )
        # Skip noisy value_ref floor/ceiling pin when no level debuff was actually active
        only_vref_changed = (
            self.game._fx_seq == seq_before
            and before[:6] == after[:6]
            and before[7:] == after[7:]
            and before[6] != after[6]
        )
        if self.game._fx_seq > seq_before or (before != after and not (only_vref_changed and not char.statuses.get("骰子等级降低", 0))):
            self.game.emit_fx(
                "passive_trigger",
                side=player.side if player else None,
                character_id=char.id,
                character_name=char.name,
                passive_name=p_name,
            )
        return res


class _TableGame(Game):
    def __init__(self, players, rng=None):
        super().__init__(players, rng=rng)
        self.context = _TableContext(game=self)
        self.fx_events = deque(maxlen=220)
        self._fx_seq = 0
        self._pending_draws = []
        self.last_speed_rolls = []

    def emit_fx(self, kind, **payload):
        self._fx_seq += 1
        self.fx_events.append({
            "seq": self._fx_seq,
            "kind": kind,
            "turn": self.turn_number,
            **payload,
        })

    def determine_first_player(self):
        self.prepare_turn()
        self.close_private_view()
        self.last_speed_rolls = []
        left, right = self.players
        attempt = 0
        while True:
            attempt += 1
            sides_info = []
            for player in self.players:
                player.calculate_speed()
                rolls = []
                for char in player.characters:
                    if not char.is_alive:
                        continue
                    haste = char.statuses.get("迅捷", 0)
                    bind = char.statuses.get("束缚", 0)
                    raw = char.speed - haste + bind
                    rolls.append({
                        "character_id": char.id,
                        "name": char.name,
                        "raw": raw,
                        "haste": haste,
                        "bind": bind,
                        "speed": char.speed,
                    })
                dropped_id = None
                if len(rolls) > 1:
                    lowest = min(rolls, key=lambda item: item["speed"])
                    dropped_id = lowest["character_id"]
                sides_info.append({
                    "side": player.side,
                    "rolls": rolls,
                    "dropped_id": dropped_id,
                    "team_speed": player.speed,
                })
            winner = None
            if left.speed != right.speed:
                self.first_player = left if left.speed > right.speed else right
                winner = self.first_player.side
            record = {"attempt": attempt, "sides": sides_info, "winner_side": winner}
            self.last_speed_rolls.append(record)
            self.emit_fx("speed_roll", **record)
            if winner is not None:
                return

    def reveal_cards(self):
        duel_cards = [
            {
                "number": num,
                "sides": {
                    p.side: [c.id for c in slot.get_content(p.side) if c.state == CardState.PLACED_FACE_DOWN]
                    for p in self.players
                },
            }
            for num, slot in enumerate(self.duelspace.space, 1)
        ]
        super().reveal_cards()
        self.emit_fx("cards_reveal", duels=duel_cards)

    def finish_turn(self):
        on_board = [card for slot in self.board_slots() for cards in slot.content.values()
                    for card in cards]
        used_set = set()
        per_side = {p.side: {"side": p.side, "used_count": 0, "board_count": 0,
                             "discard_count": len(p.cardspace.delayed_discard.content)}
                    for p in self.players}
        remaining = set(on_board)
        for card in self.used_cards:
            if card in remaining and card.character.is_alive:
                remaining.remove(card)
                used_set.add(card)
                per_side[card.player.side]["used_count"] += 1
        for card in on_board:
            if card in remaining and card.character.is_alive:
                remaining.remove(card)
                per_side[card.player.side]["board_count"] += 1
        super().finish_turn()
        self.emit_fx("turn_recycle", sides=list(per_side.values()))

    def run_placement(self):
        """Open the first placement window. The client supplies each decision."""
        self.placing = self.first_player
        self.placed_this_window = 0

    def run_pre_reveal_declarations(self):
        """The client supplies each attack and interception separately."""


def _normalize_roster(roster, pool):
    if roster is None:
        return (["plan_b_annolin"], ["waa_lake"])
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
        if not 1 <= len(team) <= 3:
            raise ValueError("每方须选择 1 至 3 名出战角色。")
        team_seen = set()
        for key in team:
            if (not isinstance(key, str) or key not in pool or key in team_seen
                    or (key in seen and not pool[key].get("mirror_allowed"))):
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


def _roster_preview(spec, color=None):
    return {
        "id": spec["id"],
        "name": spec["name"],
        "title": spec.get("title"),
        "rank": spec["rank"],
        "max_hp": spec["max_hp"],
        "base_duels": Character.base_duels(spec),
        "faction": spec.get("faction", ""),
        "color": color,
        "passives": _passives(spec.get("passive_skills", ())),
        "faction_passives": _passives(spec.get("faction_passives", ())),
        "skills": [_printed_skill(skill) for skill in spec.get("skills", ())],
    }


class BattleMatch:
    """Drive the normal pipeline up to its next decision or public combat result."""

    def __init__(self, roster=None, *, seed=None, initial_handoff=False):
        pool = {spec["id"]: spec for spec in load_characters_from_packs()}
        teams = _normalize_roster(roster, pool)
        self._character_colors = _assign_character_colors(pool)
        self.choices = [
            {
                **{key: spec.get(key) for key in ("id", "name", "title", "rank", "max_hp", "faction", "mirror_allowed")},
                "max_lightcore_hp": Character.initial_lightcore_max(spec["max_hp"]),
                "color": self._character_colors.get(spec["id"]),
            }
            for spec in pool.values()
        ]
        self._roster_catalog = [
            _roster_preview(spec, self._character_colors.get(spec["id"]))
            for spec in pool.values()
        ]
        players = [_TablePlayer(1, "玩家一"), _TablePlayer(2, "玩家二")]
        self.game = _TableGame(players, rng=random.Random(seed))
        for team, player in zip(teams, players):
            for key in team:
                character = _TableCharacter(pool[key], player)
                player.characters.append(character)
                character.init_cards()
                character.setup_deck()
            player.cardspace.draw.shuffle(self.game.rng)
        self._views = {side: Displayer(self.game, viewer_side=side) for side in (None, 1, 2)}
        self._history = deque(maxlen=100)
        self._window_size = 1
        self._require_handoff = initial_handoff
        self._pre_seat = None
        self._draw_seat = None
        self._response_times = []
        self._special_open = False
        self._special_seat = None
        self._interrupt_return = None
        self._timing = ""
        self.revision = 0
        self._advance()

    def _legal_cards(self):
        player = self.game.placing
        return [card for card in player.cardspace.hand.content
                if card.character.is_alive and card.character.used_duels < card.character.max_duels
                and card.meets_use_requirements()]

    def _current_draw_prompt(self):
        if not self.game._pending_draws:
            return None
        pending = self.game._pending_draws[0]
        if self.mode != "draw_select" or self._draw_seat is not pending["player"]:
            return None
        return {
            "side": pending["player"].side,
            "keep": pending["keep"],
            "discard_count": pending["discard_count"],
            "candidates": [
                {
                    **_printed_skill(c.data),
                    "character_id": c.character.id,
                    "character_name": c.character.name,
                    "cost": c.cost,
                }
                for c in pending["candidates"]
            ],
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
            "queued_placement": self.game.special.placement_owner is not None,
            "special_timing": self._timing,
            "draw_select": self._current_draw_prompt(),
            "speed_rolls": list(self.game.last_speed_rolls),
            "character_colors": dict(self._character_colors),
            "card_owners": card_owners,
            "default_targets": {
                str(p.side): p.default_target_character.id
                if p.default_target_character and p.default_target_character.is_alive else None
                for p in self.game.players
            },
            "fx_events": list(self.game.fx_events),
            "frame": frame,
            "catalog": self._views[None].catalog(),
            "roster_catalog": self._roster_catalog,
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
            self._special_open = True
            self._special_seat = None
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
        self.revision += 1
        return self.snapshot()

    def _draw_bottom_action(self, card_ids):
        if not self.game._pending_draws:
            raise ValueError("当前没有待挑选的抽牌候选。")
        pending = self.game._pending_draws[0]
        player = pending["player"]
        candidates = pending["candidates"]
        discard_count = pending["discard_count"]
        if (not isinstance(card_ids, list) or len(card_ids) != discard_count
                or len(set(card_ids)) != discard_count):
            raise ValueError(f"请选择 {discard_count} 张不同的牌置于抽牌堆底。")
        by_id = {c.id: c for c in candidates}
        if any(cid not in by_id for cid in card_ids):
            raise ValueError("所选置底牌不在当前候选范围内。")
        draw = player.cardspace.draw
        for cid in card_ids:
            draw.move_card_to(by_id[cid], draw)
        self.game.emit_fx("draw_bottom", side=player.side, count=discard_count)
        player.draw_card(pending["keep"])
        self._history.append(f"{player.name}看顶选 {discard_count} 张置底，保留 {pending['keep']} 张手牌。")
        self.game._pending_draws.pop(0)
        if self.game._pending_draws:
            self._draw_seat = self.game._pending_draws[0]["player"]
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
            self._return_from_special()
            return
        if action == "switch_side" and self._special_seat is not None:
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
        succeeded = game.special.apply(player, move)
        # Face-down placements and replacements must remain hidden in the public log.
        if move.kind == "place":
            message = "特殊置卡"
        elif move.kind == "replace":
            message = "替换技能"
            if succeeded is not False:
                game.emit_fx(
                    "card_replace",
                    side=player.side,
                    old_card_id=move.target_card.id if move.target_card else None,
                    new_card_id=move.card.id if move.card else None,
                )
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
        elif game.pipeline.interrupt_space is not old_space:
            self._special_open = False
            if self._interrupt_return is None:
                self._interrupt_return = self.mode, self._timing, old_space
            self._advance()
        else:
            self._return_from_special()

    def _return_from_special(self):
        self._special_open = False
        self._special_seat = None
        if self.game.pre_reveal.actor is not None and self.game.pipeline.interrupt_space is None:
            self._pre_seat = self.game.pre_reveal.actor
            self.mode = "handoff"
        elif self.mode in ("placement", "handoff") and self._pre_seat is None:
            self._require_handoff = True
            self._open_window()
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
            if game.auto_place_in_duel(player.side, card):
                game.placed_this_window += 1
                if game.is_over:
                    self._finish()
                    return
                if game.placed_this_window < self._window_size:
                    if self._legal_cards():
                        return
                    game.ended_player.append(player)
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
        while (game.placing is not None and not self._legal_cards()
               and not game.special.ability_options(game.placing)):
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
            if game.special.decision_owner is not None:
                self._special_open = True
                self._special_seat = None
                self._timing = "选择技能" if game.special.card_decision else "选择交锋"
                self.mode = "combat"
                return
            if self._interrupt_return is not None:
                previous_mode, timing, space = self._interrupt_return
                if game.pipeline.interrupt_space is space:
                    self.mode, self._timing = previous_mode, timing
                    self._interrupt_return = None
                    self._return_from_special()
                    return
            self._timing = timing_label(node)
            if node == "logic_draw_cards" and game._pending_draws:
                self._draw_seat = game._pending_draws[0]["player"]
                self.mode = "handoff" if self._require_handoff else "draw_select"
                self._require_handoff = False
                return
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
            elif self._timing and self._pause_at_timing():
                self.mode = "timing"
                return
        self._finish()

    def _pause_at_timing(self):
        return bool(special_seats(self.game))

    def _combat_stop(self, nodes):
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
                    game.emit_fx(
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
                verb = "使用" if pipe.paid else "未能支付"
                actions.append(f"{character.combat_name}{verb} {pipe.card.name}")
                game.emit_fx(
                    "cost_pay",
                    side=player.side,
                    character_id=character.id,
                    card_id=pipe.card.id,
                    card_name=pipe.card.name,
                    cost=pipe.card.cost,
                    personal_paid=character.used_independent_cost if pipe.paid else 0,
                    common_paid=max(0, pipe.card.cost - (character.used_independent_cost if pipe.paid else 0)) if pipe.paid else 0,
                    paid=bool(pipe.paid),
                )
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
                    "range_deficit": side["range_deficit"],
                    "skipped": True,
                    **die,
                })
                pause = True
            elif node == "after_dice_hit" and die:
                target = pipe.target or next((c for c in next(
                    p for p in game.players if p is not player).characters if c.is_alive), None)
                attack = "单方面攻击" if die["result"] is None else "进攻"
                if target is not None:
                    actions.append(
                        f"{character.combat_name}{attack}，{target.combat_name}生命 {target.hp}/{target.max_hp}，"
                        f"完整度 {target.lightcore_hp}/{target.max_lightcore_hp}"
                    )
                    game.emit_fx(
                        "combat_strike",
                        attacker_side=player.side,
                        attacker_id=character.id,
                        attacker_name=character.name,
                        target_side=target.player.side,
                        target_id=target.id,
                        target_name=target.name,
                        die_type=die["type"],
                        one_sided=die["result"] is None,
                        card_id=side["card_id"],
                    )
                else:
                    actions.append(f"{character.combat_name}{attack}")
                pause = True
        if clash_sides:
            game.emit_fx(
                "dice_clash",
                duel_kind=combat["kind"],
                duel_number=combat["duel_number"],
                round_id=combat["round_id"],
                blank_round=scored and len(game.pipeline.current_clash_results) == 1,
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
