"""Playable local encounters. Each encounter owns its opponent and seat policy."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from bots.lan_qing import choose_move as lan_qing_move
from bots.witness_residue import choose_move as witness_move
from loader import PACKS, load_characters_from_packs
from .bot import avoid_restricted_plays, choose_draw_bottom


@dataclass(frozen=True)
class Challenge:
    name: str
    character_id: str
    choose_move: Callable
    packs: tuple[Path, ...] = ()
    teammates: tuple[str, ...] = ()

    @property
    def opponents(self):
        return (self.character_id, *self.teammates)

    def validate_roster(self, roster):
        if roster is None:
            human = "plan_b_annolin"
            if human in self.opponents:
                human = next((c["id"] for c in load_characters_from_packs(extra_packs=self.packs)
                              if c["id"] not in self.opponents), None)
                if human is None:
                    raise ValueError("挑战需要至少一名可选的玩家角色。")
            return [[human], list(self.opponents)]
        if isinstance(roster, (list, tuple)) and len(roster) == 2:
            human, opponent = ([team] if isinstance(team, str) else team for team in roster)
            if (isinstance(human, (list, tuple)) and isinstance(opponent, (list, tuple))
                    and tuple(opponent) == self.opponents and not any(c in self.opponents for c in human)):
                return [human, opponent]
        raise ValueError("挑战对手固定，请从其余角色中选择自己的阵容。")

    def table_action(self, snap):
        """Let the encounter policy select among the current local table's legal commands."""
        mode = snap["mode"]
        if mode == "draw_select":
            return "draw_bottom", {"card_ids": choose_draw_bottom(snap["draw_select"])}
        choices = []
        if mode == "placement":
            choices.extend({"kind": "place", "card_id": key} for key in snap["legal_cards"])
            if snap["can_pass"]:
                choices.append({"kind": "pass"})
            choices.append({"kind": "end"})
        elif mode == "pre_attack":
            for key, targets in snap["attack_targets"].items():
                for target in targets:
                    field = {"character_id": target["id"]} if target["kind"] == "character" else {"duel_number": target["number"]}
                    choices.append({"kind": "attack", "card_id": key, **field})
            choices.append({"kind": "end_attack"})
        elif mode == "intercept":
            for number in snap["pending_responses"]:
                choices.extend({"kind": "intercept", "card_id": key, "response_number": number}
                               for key in snap["intercepts_by_number"][number])
                choices.append({"kind": "let_through", "response_number": number})
        elif mode == "special" and snap["special_pending"]:
            choices = [{**option, "kind": "special_" + option["kind"]} for option in snap["special_options"]]
        if not choices:
            return None
        frame_mode = {"pre_attack": "pre_reveal", "intercept": "pre_reveal",
                      "special": "skill_choice" if snap["effect_choice"] else "instant_response"}.get(mode, mode)
        move = self.choose_move({**snap["frame"], "mode": frame_mode}, choices)
        if move is None:
            return None
        if mode == "special":
            return "use_special", {"option": choices.index(move)}
        if move["kind"] == "attack":
            target = ({"kind": "character", "id": move["character_id"]} if "character_id" in move
                      else {"kind": "duel", "number": move["duel_number"]})
            return "attack", {"card_id": move["card_id"], "target": target}
        args = {"card_id": move["card_id"]} if "card_id" in move else {}
        if "response_number" in move:
            args["duel_number"] = move["response_number"]
        return move["kind"], args


@avoid_restricted_plays
def carrier_move(frame, moves):
    # Its card entries place the template and declare its attacks. Ordinary
    # prompts still have to yield initiative to the human seat.
    for kind in ("let_through", "special_pass_intercept", "end_attack", "end"):
        if move := next((m for m in moves if m["kind"] == kind), None):
            return move
    return next(iter(moves), None)


CHALLENGES = {
    "carrier": Challenge("结构化载体", "structured_carrier", carrier_move,
                         (PACKS / "challenges" / "structured_carrier.json",)),
    "lan_qing": Challenge("幽蓝残雪·澜清", "lan_qing", lan_qing_move),
    "witness_residue": Challenge("“目击残差”", "witness_residue", witness_move),
}
