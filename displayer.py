"""Read-only, JSON-ready views of a live match. Read between engine steps."""

from game import Game
from models.card import CardState, allows_interception, describe_entry, describe_range_traits
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
        "type": die.type, "printed_level": None if die.type == "skip" else die.printed_level.value,
        "roll_max": None if die.type == "skip" else die.roll_max, "base_value": die.base_value,
        "range_traits": [*describe_range_traits(spec), *(["被动激活"] if spec.get("passive_activation") else [])],
        "resource_cost": dict(spec["resource_cost"]) if spec.get("resource_cost") else None,
        "multiplier": die.multiplier, "final_bonus": die.final_bonus, "formula": die.calc_formula,
        "entries": [describe_entry(entry) for entry in die.entries],
    }


def _printed_skill(data, *, include_forms=False):
    return {
        "id": data["id"], "name": data["name"], "cost": data["cost"],
        "pre_reveal": data.get("pre_reveal", False),
        "pre_reveal_requires_status": dict(data.get("pre_reveal_requires_status", {})),
        "before_duel_attack": data.get("before_duel_attack", False),
        "pre_reveal_target": data.get("pre_reveal_target"),
        "pre_reveal_bind": data.get("pre_reveal_bind", "slot"),
        "resource_cost": dict(data["resource_cost"]) if data.get("resource_cost") else None,
        "requires_status": dict(data.get("requires_status", {})),
        "forms": [_printed_skill({**data, **form}) for form in data.get("forms", {}).values()] if include_forms else [],
        "anytime_play": list(data.get("anytime_play", [])),
        "anytime_replace": data.get("anytime_replace", False),
        "interceptable": allows_interception(data, pre_reveal=True),
        "instant_interceptable": allows_interception(data, pre_reveal=False),
        "range_level": data.get("range_level", 0), "ignore_range": data.get("ignore_range", 0),
        "range_traits": describe_range_traits(data),
        "starts_out_of_combat": bool(data.get("out_of_combat")),
        "dice": [_printed_die(spec) for spec in data.get("dice", ())],
        "entries": [describe_entry(entry) for entry in data.get("entries", ())],
    }


def _passives(specs):
    result = []
    for spec in specs:
        if isinstance(spec, dict) and "entries" in spec:
            name = spec.get("name")
            description = spec.get("description")
            entries = [describe_entry(entry) for entry in spec["entries"]]
        else:
            name = description = None
            entries = [describe_entry(spec)]
        result.append({
            "name": name, "description": description, "entries": entries,
            "display_lines": [description] if description and description.strip() else entries,
        })
    return result


def _visible_card(card):
    details = _printed_skill({**card.data, "name": card.name, "dice": card.dice})
    destroyed = sorted({die.position for die in card.instantiated_dice or () if die and die.destroyed})
    return {**details, "pre_reveal": card.can_open_pre_reveal,
            "character_id": card.character.id, "borrowed": card.printed_owner is not card.character,
            "destroyed_die_positions": destroyed,
            "instance_id": card.instance_id, "cost": card.cost, "state": card.state.name.lower()}


def hand_key(card):
    """Legacy template IDs stay valid when they identify exactly one card in hand."""
    hand = card.player.cardspace.hand.content
    if sum(other.id == card.id for other in hand) > 1:
        return f"instance:{card.instance_id}"
    return card.id


def _live_die(die):
    if die is None:
        return None
    resolved = die._resolved_level is not None and die.type != "skip"
    return {
        "position": die.position, "type": die.type, "printed_level": None if die.type == "skip" else die.printed_level.value,
        "level": die.level.value if resolved else None, "roll_max": die.roll_max if resolved else None,
        "base_value": die.base_value, "rolled_value": die.value or None,
        "final_score": die.final_score, "clash_score": die.clash_score,
        "result": die.clash_result, "win_branch_skipped": die.win_branch_skipped,
        "critical": die.critical, "destroyed": die.destroyed, "hit_index": die.hit_index,
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
    if game.is_over:
        return []
    pending = game.special.pending_attack
    if game.special.decision_owner is not None:
        return [game.special.decision_owner]
    if game.turn_number <= game.turn_count:
        return []
    if pending is not None:
        return sorted(game.players, key=lambda p: p.side == pending.attacking_side)
    for player in game.players:
        for actor in player.characters:
            if not actor.is_alive:
                continue
            if (actor.ability_permission("place") or actor.ability_permission("replace")
                    or any(game.special.window_open(a["window"]) for a in actor.action_specs())
                    or any(s.get("anytime_play") or s.get("anytime_replace") or s.get("replace_targets")
                           or s.get("before_duel_attack") and game.special.window_open("before_duel")
                           for s in actor.skill_data)):
                return game.players.copy()
    return []


_DUEL_NAMES = {"regular": "常规交锋", "pre_reveal": "开牌前交锋", "instant": "即时交锋"}


def board_location_label(target):
    return f"{_DUEL_NAMES[target['kind']]} {target['number']} · 第 {target['position']} 张"


def _card_choice_view(card, viewer):
    game = card.player.game
    hand = card.player.cardspace.hand.content
    if card in hand:
        position = hand.index(card) + 1
        target = {"zone": "hand", "side": card.player.side, "position": position}
        if viewer is not card.player:
            return {"effect_target": target, "label": f"对方第 {position} 张手牌"}
        target["card"] = _visible_card(card)
        borrowed = "（取自对手）" if card.printed_owner is not card.character else ""
        view = {"effect_target": target, "label": f"{card.name}{borrowed}（{card.cost} 费）"}
        choice = game.special.card_decision
        discount = None
        if choice and choice.player is viewer:
            preview = choice.specification.get("preview", {})
            key = preview.get("skill_discount")
            if key is not None:
                discount = choice.event["bindings"].get(key)
        if discount is not None:
            cost = max(0, card.cost - discount)
            extra = card.data.get("resource_cost")
            resource = {**extra, "available": card.character.statuses.get(extra["status"], 0)} if extra else None
            view["use_preview"] = {"base_cost": card.cost, "discount": discount, "cost": cost, "resource_cost": resource}
            label = f"{card.name}{borrowed} · 预计 {cost} 费"
            if resource:
                label += f" + {resource['amount']} {resource['status']}（现有 {resource['available']}）"
            view["label"] = label
        return view
    target = _board_card_target(card, viewer)
    name = card.name if "card" in target else "扣置技能"
    return {"effect_target": target, "label": f"{board_location_label(target)} · {name}"}


def _board_card_target(card, viewer):
    game = card.player.game
    for kind, slots in (("regular", game.duelspace.space), ("pre_reveal", game.pre_reveal.space.space),
                        ("instant", game.special.duels)):
        for number, slot in enumerate(slots, 1):
            cards = slot.get_content(card.player.side)
            if card in cards:
                position = cards.index(card) + 1
                target = {"zone": "board", "side": card.player.side, "kind": kind, "number": number, "position": position}
                visible = kind != "regular" or _board_visible_to(card, viewer)
                if visible:
                    target["card"] = _visible_card(card)
                return target
    raise ValueError("所选技能已离开候选区域。")


def _board_visible_to(card, viewer):
    return card.player is viewer or card.state == CardState.PLACED_FACE_UP or (
        card.player.game.cards_revealed and card.state != CardState.PLACED_FACE_DOWN)


def special_action_label(action):
    if action.label is not None:
        return action.label
    if action.kind == "decline_card":
        return "放弃此次选牌"
    if action.kind == "choose_slot":
        location = f"{_DUEL_NAMES[action.duel_kind]} {action.duel_index + 1}"
        return f"{action.card.name} · {location}" if action.card else location
    if action.kind == "choose_card":
        card = action.target_card
        chooser = card.player.game.special.decision_owner
        return _card_choice_view(card, chooser)["label"] if chooser else "选择技能"
    if action.kind == "ability":
        spec = next(s for s in action.character.action_specs() if s["id"] == action.ability_id)
        label = f"{action.character.name} · {spec['name']}"
        if action.duel_index is not None:
            cards = action.target_card.player.game.duelspace.space[action.duel_index].get_content(action.target_card.player.side)
            return f"{label} · 常规交锋 {action.duel_index + 1} 的第 {cards.index(action.target_card) + 1} 张扣牌"
        if action.target_card:
            borrowed = "（取自对手）" if action.target_card.printed_owner is not action.target_card.character else ""
            return f"{label} · {action.target_card.name}{borrowed}"
        return label
    if action.kind == "pass_intercept":
        return f"放行即时交锋 {action.response_number}"
    card = action.card
    skill = f"{card.name}（{card.cost} 费）"
    if card in card.player.cardspace.hand.content and card.character.skill_restricted(card):
        skill += "〔限制中〕"
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


def seat_action_view(action, player):
    """Describe one action offered to this seat, retaining concealed target identities."""
    target = action.target_card
    target_id = None
    if target and target.player is player:
        target_id = hand_key(target) if target in player.cardspace.hand.content else target.id
    details = _card_choice_view(target, player) if action.kind == "choose_card" else {"label": special_action_label(action)}
    if action.kind == "replace" or (action.kind == "ability" and action.duel_index is not None):
        details["effect_target"] = _board_card_target(target, player)
    if action.kind == "choose_slot":
        details["effect_target"] = {
            "zone": "board", "side": player.side, "kind": action.duel_kind, "number": action.duel_index + 1,
        }
    return {"kind": action.kind, **details,
            "card_id": hand_key(action.card) if action.card else None, "ability_id": action.ability_id,
            "target_card_id": target_id, "character_id": action.character.id if action.character else None,
            "duel_number": action.duel_index + 1 if action.duel_index is not None else None,
            "response_number": action.response_number}


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
        return [seat_action_view(a, self._viewer) for a in self._game.special.options(self._viewer)]

    def effect_choice(self):
        special = self._game.special
        if self._viewer is None or special.decision_owner is not self._viewer:
            return None
        card_choice = special.card_decision
        choice = card_choice or special.slot_decision
        selection = "slot"
        if card_choice:
            selection = "hand" if all(in_hand for _, in_hand in choice.origins.values()) else "board"
        entry = choice.invocation.entry
        source = entry.owning_card
        visible = source is None or source.player is self._viewer or source.state == CardState.PLACED_FACE_UP
        description = entry.choice_prompt if visible else None
        fallback = "选择要追加技能的交锋。" if selection == "slot" else "选择一张技能牌。"
        name = getattr(entry.owner, "name", "技能效果")
        if source:
            name = source.name if visible else "扣置技能"
        return {
            "selection": selection, "optional": getattr(choice, "optional", False),
            "description": description or fallback,
            "source_name": name,
            "source_card_id": source.id if source and visible else None,
            "die_position": getattr(entry.owner, "position", None) if visible else None,
        }

    def catalog(self) -> dict:
        """Public printed rules for the selected roster, independent of card locations."""
        actions = {action["id"]: action["name"] for p in self._game.players for c in p.characters
                   for action in c.data.get("actions", ())}
        actions.update({action["id"]: action["name"] for rule in self._game.ability_rules.values()
                        if (action := rule.get("action"))})
        statuses = {name: [describe_entry(e) for e in entries]
                    for name, entries in self._game.status_entries.items()}
        for name, rule in self._game.status_rules.items():
            if rule.get("description"):
                statuses.setdefault(name, []).insert(0, rule["description"])
        return {
            "players": [{
                "side": p.side,
                "characters": [{
                    "id": c.id, "name": c.name,
                    "passives": _passives(c.passive_skill_data),
                    "faction_passives": _passives(c.data.get("faction_passives", ())),
                    "skills": [_printed_skill(skill, include_forms=True) for skill in c.skill_data],
                } for c in p.characters],
            } for p in self._game.players],
            "statuses": statuses,
            "actions": actions,
            "ability_effects": {name: rule.get("description", "") for name, rule in self._game.ability_rules.items()},
        }

    def _player(self, player):
        own = player is self._viewer
        zones = player.cardspace
        return {
            "side": player.side, "name": player.name, "speed": player.speed,
            "team_statuses": dict(player.team_statuses),
            "cost": {"available": player.available_cost, "refill": player.max_cost, "spent": player.used_cost},
            "placement_ended": player in self._game.ended_player,
            "characters": [self._character(c, own) for c in player.characters],
            "draw_count": len(zones.draw.content), "hand_count": len(zones.hand.content),
            "decisive_count": len(zones.decisive.content) if any(c.deck_name == "decisive"
                for actor in player.characters for c in actor.skills) else None,
            "delayed_discard_count": len(zones.delayed_discard.content),
            "out_of_combat_count": len(zones.out_of_combat.content),
            "hand": [{**_visible_card(c), "action_key": hand_key(c), "use_restricted": c.character.skill_restricted(c)}
                     for c in zones.hand.content] if own else None,
            "delayed_discard": [_visible_card(c) for c in zones.delayed_discard.content] if own else None,
            "out_of_combat": [_visible_card(c) for c in zones.out_of_combat.content] if own else None,
        }

    def _character(self, c, own):
        return {
            "id": c.id, "printed_id": c.data["id"], "name": c.name, "title": c.data.get("title"), "faction": c.faction,
            "rank": c.rank.name, "alive": c.is_alive, "hp": c.hp, "max_hp": c.max_hp, "speed": c.speed,
            "lightcore_hp": c.lightcore_hp, "max_lightcore_hp": c.max_lightcore_hp,
            "shields": {"normal": c.shield, "reinforced": c.reinforced_shield, "concept": c.concept_shield},
            "statuses": {k: n for k, n in c.statuses.items() if k not in c.team_statuses},
            "bleed_burst": c.canonical_status_name("bleed") in c.active_statuses,
            "ability_effects": dict(c.ability_effects),
            "reserved_dice": [{"skill": reserve.template.card.name, "position": reserve.template.position,
                               "remaining": reserve.remaining}
                              for reserve in c.reserved_dice],
            "status_overflow": {name: {"amount": n, "threshold": c.status_rules.get(name, {}).get("overflow_threshold")}
                                for name, n in c.status_overflow.items()},
            "cost": {"available": c.available_cost, "refill": c.independent_cost, "spent": c.used_independent_cost},
            "duels": {"max": c.max_duels, "used": c.used_duels if own or self._game.cards_revealed else None},
        }

    def _board_visible(self, card):
        return _board_visible_to(card, self._viewer)

    def _board_card(self, card):
        return _visible_card(card) if self._board_visible(card) else {"hidden": True}

    def _suspended(self):
        game = self._game
        result = []
        for space, card, die, source in game.pipeline.suspended_uses():
            number = None
            if space is None:
                index = game.pipeline.current_step_index
                node = game.pipeline.step_list[index].id if index >= 0 else None
                kind = _PHASES.get(node, "turn_start")
            else:
                number = space.current_duel_index + 1
                if space is game.duelspace:
                    kind = "regular"
                elif space is game.pre_reveal.space:
                    kind = "pre_reveal"
                else:
                    kind = "instant"
                    number = game.special.duels.index(space.space[number - 1]) + 1
            visible = card is not None and self._board_visible(card)
            result.append({"kind": kind, "duel_number": number, "side": card.player.side if card else None,
                           "card_id": card.id if visible else None, "card_name": card.name if visible else None,
                           "die_position": die.position if die and visible else None, "source_name": source})
        return result

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
                "card_instance_id": card.instance_id if card is not None else None,
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
                "round_id": game.pipeline.round_id, "sides": sides, "suspended": self._suspended()}
