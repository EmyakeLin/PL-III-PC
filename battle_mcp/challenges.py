"""Playable local encounters. Each encounter owns its opponent and seat policy."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from bots.lan_qing import choose_move as lan_qing_move
from loader import PACKS


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
    "lan_qing": Challenge("幽兰残雪·澜清", "lan_qing", lan_qing_move),
}
