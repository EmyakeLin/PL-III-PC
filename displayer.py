"""Read-only, JSON-ready views of a live match. Read between engine steps."""

from game import Game
from models.card import CardState, describe_entry
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
        "result": die.clash_result, "critical": die.critical, "destroyed": die.destroyed,
    }


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
            "combat": self._combat() if pipe.in_duel_phase and game.cards_revealed and not game.is_over else None,
        }

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
        index = game.duelspace.current_duel_index
        pipes = game.pipeline.side_pipelines
        if any(pipe.card is not None and not self._board_visible(pipe.card) for pipe in pipes.values()):
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
                "character_id": card.character.id if card is not None else None,
                "target_id": target.id if target is not None and card is not None else None,
                "die_number": card.current_dice_index + 1 if die is not None else None,
                "die": _live_die(die),
            })
        return {"duel_number": index + 1 if 0 <= index < len(game.duelspace.space) else None,
                "round_id": game.pipeline.round_id, "sides": sides}
