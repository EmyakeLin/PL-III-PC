"""Read-only, JSON-ready views of a live match. Read between engine steps."""

from game import Game
from models.card import CardState, allows_interception, describe_entry
from models.dice import Dice
from pipeline import pipeline_steps


_PHASES = {
    node.id: phase
    for phase, nodes in (
        ("turn_start", pipeline_steps.turn_start_steps),
        ("placement", pipeline_steps.placement_phase),
        ("reveal", pipeline_steps.reveal_phase),
        ("combat", [pipeline_steps.logic_start_duel_combat]),
        ("turn_end", pipeline_steps.turn_end_steps),
    )
    for node in nodes
}
for _node in pipeline_steps.reveal_phase:
    if _node.id == "logic_reveal":
        break
    _PHASES[_node.id] = "pre_reveal"


def _printed_die(spec):
    # An unbound printed die uses the engine's aliases, defaults and custom roll_max.
    die = Dice(spec)
    return {
        "type": die.type, "printed_level": die.printed_level.value,
        "roll_max": die.roll_max, "base_value": die.base_value,
        "multiplier": die.multiplier, "final_bonus": die.final_bonus, "formula": die.calc_formula,
        "entries": [describe_entry(entry) for entry in die.entries],
    }


def _printed_skill(data):
    return {
        "id": data["id"], "name": data["name"], "cost": data["cost"],
        "pre_reveal": data.get("pre_reveal", False),
        "anytime_play": list(data.get("anytime_play", [])),
        "anytime_replace": data.get("anytime_replace", False),
        "interceptable": allows_interception(data, pre_reveal=True),
        "instant_interceptable": allows_interception(data, pre_reveal=False),
        "range_level": data.get("range_level", 0), "ignore_range": data.get("ignore_range", 0),
        "starts_out_of_combat": bool(data.get("out_of_combat")),
        "dice": [_printed_die(spec) for spec in data.get("dice", ())],
        "entries": [describe_entry(entry) for entry in data.get("entries", ())],
    }


def _passives(specs):
    result = []
    for spec in specs:
        if isinstance(spec, dict) and "entries" in spec:
            result.append({
                "name": spec.get("name"), "description": spec.get("description"),
                "entries": [describe_entry(entry) for entry in spec["entries"]],
            })
        else:
            result.append({"name": None, "description": None, "entries": [describe_entry(spec)]})
    return result


def _visible_card(card):
    return {**_printed_skill(card.data), "character_id": card.character.id,
            "cost": card.cost, "state": card.state.name.lower()}


def _live_die(die):
    if die is None:
        return None
    resolved = die._resolved_level is not None
    return {
        "position": die.position, "type": die.type, "printed_level": die.printed_level.value,
        "level": die.level.value if resolved else None, "roll_max": die.roll_max if resolved else None,
        "base_value": die.base_value, "rolled_value": die.value or None,
        "final_score": die.final_score, "clash_score": die.clash_score,
        "result": die.clash_result, "win_branch_skipped": die.win_branch_skipped,
        "critical": die.critical, "destroyed": die.destroyed,
    }


_TIMINGS = {
    "turn_start": "回合开始", "draw_cards": "回合抽牌", "resolve_speed": "速度判定",
    "place": "常规置卡", "reveal": "统一开牌", "before_reveal_phase_start": "开牌前阶段开始",
    "before_reveal_phase_end": "开牌前阶段结束", "near_before_reveal": "即将开牌",
    "duel_start": "交锋开始", "skill_use": "技能使用", "dice_use": "用骰",
    "dice_clash": "拼点", "clash_win": "拼点胜利", "clash_lose": "拼点失败",
    "clash_draw": "拼点平局", "clash_skip": "跳过拼点", "dice_hit": "命中",
    "duel_end": "交锋结束", "turn_end": "回合结束",
}


_SPECIAL_TIMINGS = {
    "clash_scores_ready": "拼点点数已确定，尚未判胜负",
    "before_skill_choice": "技能使用前，可换卡", "near_before_reveal": "即将开牌",
    "logic_draw_cards": "回合抽牌后", "logic_resolve_speed": "速度判定后",
    "logic_skill_use": "费用结算后", "logic_dice_clash": "掷出骰面后",
    "logic_resolve_clash_result": "拼点结果确定后", "logic_dice_hit": "命中结算后",
}


def timing_label(nodes):
    """Name the step just reached; queue bookkeeping does not open a new decision."""
    labels = []
    for node in nodes if isinstance(nodes, tuple) else (nodes,):
        if not node:
            continue
        prefix, _, step = node.partition("_")
        if node in _SPECIAL_TIMINGS:
            label = _SPECIAL_TIMINGS[node]
        elif step in _TIMINGS and prefix in ("before", "on", "after"):
            label = _TIMINGS[step] + {"before": "前", "on": "时", "after": "后"}[prefix]
        else:
            continue
        if label not in labels:
            labels.append(label)
    return " / ".join(labels)


def special_seats(game):
    """Only public rules and statuses determine whether to offer the shared table."""
    if game.is_over or not game.turn_number or game.turn_number <= game.turn_count:
        return []
    pending = game.special.pending_attack
    if pending is not None:
        return sorted(game.players, key=lambda p: p.side == pending.attacking_side)
    for player in game.players:
        for actor in player.characters:
            if not actor.is_alive:
                continue
            if (actor.statuses.get("置卡机会") or actor.statuses.get("换卡机会")
                    or any(s.get("anytime_play") or s.get("anytime_replace") for s in actor.skill_data)):
                return game.players.copy()
    return []


def special_action_label(action):
    if action.kind == "pass_intercept":
        return f"放行即时交锋 {action.response_number}"
    card = action.card
    skill = f"{card.name}（{card.cost} 费）"
    if action.kind == "place":
        return f"{skill}置入常规交锋 {action.duel_index + 1}"
    if action.kind == "replace":
        return f"用{skill}换下{action.target_card.name}"
    if action.kind == "attack":
        target = action.character.name if action.character else f"常规交锋 {action.duel_index + 1}"
        return f"用{skill}进攻{target}"
    if action.kind == "intercept":
        return f"用{skill}迎击即时交锋 {action.response_number}"
    return f"按牌面打出{skill}"


class Displayer:
    """Use one instance per audience. None is public, a side sees its private zones."""

    def __init__(self, game: Game, *, viewer_side=None):
        self._game = game
        self._viewer = None
        if viewer_side is not None:
            self._viewer = next((p for p in game.players
                                 if type(p.side) is type(viewer_side) and p.side == viewer_side), None)
            if self._viewer is None:
                raise ValueError(f"未知的玩家阵营 {viewer_side!r}")

    def snapshot(self) -> dict:
        """Return a detached frame made entirely of JSON values."""
        game = self._game
        pipe = game.pipeline
        index = pipe.current_step_index
        node = pipe.step_list[index].id if 0 <= index < len(pipe.step_list) else None
        if game.is_over:
            phase = "finished"
        elif game.pre_reveal.phase in ("attack", "intercept", "ready", "resolving"):
            phase = "pre_reveal"
        elif pipe.in_duel_phase:
            phase = "combat"
        elif node is not None:
            phase = _PHASES.get(node, "other")
        elif game.cards_revealed:
            phase = "reveal"
        elif game.placing is not None:
            phase = "placement"
        else:
            phase = "turn_start" if game.turn_number else "setup"

        return {
            "turn": game.turn_number, "phase": phase, "node": node,
            "viewer_side": self._viewer.side if self._viewer is not None else None,
            "first_side": game.first_player.side if game.first_player is not None else None,
            "placing_side": game.placing.side if game.placing is not None else None,
            "cards_revealed": game.cards_revealed, "is_over": game.is_over,
            "winner_side": game.winner.side if game.winner is not None else None,
            "players": [self._player(p) for p in game.players],
            "duels": [
                {"number": number, "sides": [
                    {"side": p.side, "cards": [self._board_card(c) for c in slot.get_content(p.side)]}
                    for p in game.players
                ]}
                for number, slot in enumerate(game.duelspace.space, 1)
            ],
            "pre_reveal": self._pre_reveal(),
            "special_duels": [self._declared_slot(n, slot) for n, slot in enumerate(game.special.duels, 1)],
            "combat": self._combat() if pipe.in_duel_phase and not game.is_over else None,
        }

    def _pre_reveal(self):
        phase = self._game.pre_reveal
        duels = [self._declared_slot(n, slot) for n, slot in enumerate(phase.space.space, 1)]
        return {"phase": phase.phase, "duels": duels,
                "eligible_sides": [p.side for p in phase.eligible_players()],
                "actor_side": phase.actor.side if phase.actor else None,
                "attacking_side": phase.attacker.side if phase.attacker else None}

    def _declared_slot(self, number, slot):
        if slot.intercept_card is not None:
            target = {"kind": "intercept", "name": slot.intercept_card.name}
        elif slot.target_duel_index is not None:
            target = {"kind": "duel", "number": slot.target_duel_index + 1}
        else:
            target = {"kind": "character", "name": slot.target_character.name}
        return {
            "number": number, "ready": slot.ready, "interceptable": slot.interceptable,
            "attacking_side": slot.attacking_side, "target": target,
            "attack_card_id": slot.attack_card.id,
            "pulled_card_id": slot.pulled_card.id if slot.pulled_card else None,
            "resolved_target_id": slot.resolved_target.id if slot.resolved_target else None,
            "sides": [{"side": p.side, "cards": [
                {**_visible_card(c), "play_mode": slot.play_mode(c)} for c in slot.get_content(p.side)]}
                      for p in self._game.players],
        }

    def special_actions(self):
        """Private choices, in the same order as this revision's engine options."""
        if self._viewer is None:
            return []
        return [{"kind": a.kind, "label": special_action_label(a),
                 "card_id": a.card.id if a.card else None,
                 "target_card_id": a.target_card.id if a.target_card else None,
                 "character_id": a.character.id if a.character else None,
                 "duel_number": a.duel_index + 1 if a.duel_index is not None else None,
                 "response_number": a.response_number}
                for a in self._game.special.options(self._viewer)]

    def catalog(self) -> dict:
        """Public printed rules for the selected roster, independent of card locations."""
        return {
            "players": [{
                "side": p.side,
                "characters": [{
                    "id": c.id, "name": c.name,
                    "passives": _passives(c.passive_skill_data),
                    "faction_passives": _passives(c.data.get("faction_passives", ())),
                    "skills": [_printed_skill(skill) for skill in c.skill_data],
                } for c in p.characters],
            } for p in self._game.players],
            "statuses": {name: [describe_entry(e) for e in entries]
                         for name, entries in self._game.status_entries.items()},
        }

    def _player(self, player):
        own = player is self._viewer
        zones = player.cardspace
        return {
            "side": player.side, "name": player.name, "speed": player.speed,
            "cost": {"available": player.available_cost, "refill": player.max_cost, "spent": player.used_cost},
            "placement_ended": player in self._game.ended_player,
            "characters": [self._character(c, own) for c in player.characters],
            "draw_count": len(zones.draw.content), "hand_count": len(zones.hand.content),
            "delayed_discard_count": len(zones.delayed_discard.content),
            "out_of_combat_count": len(zones.out_of_combat.content),
            "hand": [_visible_card(c) for c in zones.hand.content] if own else None,
            "delayed_discard": [_visible_card(c) for c in zones.delayed_discard.content] if own else None,
            "out_of_combat": [_visible_card(c) for c in zones.out_of_combat.content] if own else None,
        }

    def _character(self, c, own):
        return {
            "id": c.id, "name": c.name, "title": c.data.get("title"), "faction": c.faction,
            "rank": c.rank.name, "alive": c.is_alive, "hp": c.hp, "max_hp": c.max_hp, "speed": c.speed,
            "shields": {"normal": c.shield, "reinforced": c.reinforced_shield, "concept": c.concept_shield},
            "statuses": dict(c.statuses), "bleed_burst": c.bleed_burst,
            "cost": {"available": c.available_cost, "refill": c.independent_cost, "spent": c.used_independent_cost},
            "duels": {"max": c.max_duels, "used": c.used_duels if own or self._game.cards_revealed else None},
        }

    def _board_visible(self, card):
        return card.player is self._viewer or (
            self._game.cards_revealed and card.state != CardState.PLACED_FACE_DOWN)

    def _board_card(self, card):
        return _visible_card(card) if self._board_visible(card) else {"hidden": True}

    def _combat(self):
        game = self._game
        space = game.active_duelspace
        index = space.current_duel_index
        early = space is game.pre_reveal.space
        instant = space is game.pipeline.interrupt_space
        pipes = game.pipeline.side_pipelines
        if not early and not instant and (not game.cards_revealed or any(
                pipe.card is not None and not self._board_visible(pipe.card) for pipe in pipes.values())):
            return None
        sides = []
        for player in game.players:
            pipe = pipes[player.side]
            card, die = pipe.card, pipe.die
            target = die.attack_target if die is not None and die.attack_redirected else pipe.target
            sides.append({
                "side": player.side, "node": pipe.current_node.id if pipe.current_node else None,
                "waiting_at": pipe.blocked_at.id if pipe.blocked_at else None,
                "card_id": card.id if card is not None else None,
                "play_mode": space.space[index].play_mode(card) if (early or instant) and card is not None else None,
                "range_deficit": card.range_deficit if card is not None else 0,
                "character_id": card.character.id if card is not None else None,
                "target_id": target.id if target is not None and card is not None else None,
                "die_number": card.current_dice_index + 1 if die is not None else None,
                "die": _live_die(die),
            })
        number = index + 1 if 0 <= index < len(space.space) else None
        if instant and number is not None:
            slot = space.space[index]
            if slot in game.special.duels:
                number = game.special.duels.index(slot) + 1
        return {"kind": "instant" if instant else "pre_reveal" if early else "regular", "duel_number": number,
                "round_id": game.pipeline.round_id, "sides": sides}
