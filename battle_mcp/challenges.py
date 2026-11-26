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
            human, opponent = ([team] if isinstance(team, str) else list(team) for team in roster)
            if (isinstance(human, list) and human and isinstance(opponent, list)
                    and tuple(opponent) == self.opponents and not any(c in self.opponents for c in human)):
                return [human, opponent]
        raise ValueError("挑战对手固定，请从其余角色中选择自己的阵容。")


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
