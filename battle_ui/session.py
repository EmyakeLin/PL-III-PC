"""The hot-seat table and its revision-checked commands."""

import secrets
from http import HTTPStatus
from threading import Lock

from .match import BattleMatch


class BattleSession:
    """A single table shared by the browsers connected to this local process."""

    def __init__(self, seed=None, *, roster=None):
        self.seed = seed
        self.match = BattleMatch(roster, seed=seed, initial_handoff=roster is not None)
        self.revision = secrets.randbits(40)
        self.match_number = 1
        self.lock = Lock()

    def state(self):
        with self.lock:
            return {**self.match.snapshot(), "revision": self.revision, "match_number": self.match_number}

    def command(self, request):
        if not isinstance(request, dict) or type(request.get("revision")) is not int:
            raise ValueError("操作缺少有效的对局版本。")
        with self.lock:
            if request["revision"] != self.revision:
                return HTTPStatus.CONFLICT, {**self.match.snapshot(), "revision": self.revision, "match_number": self.match_number}
            action = request.get("action")
            if action == "new":
                roster = request.get("roster")
                self.match = BattleMatch(roster, seed=self.seed, initial_handoff=True)
                self.match_number += 1
                frame = self.match.snapshot()
            else:
                if action not in ("place", "end", "pass", "ready", "next",
                                  "attack", "end_attack", "intercept", "let_through", "switch_side",
                                  "open_special", "leave_special", "use_special",
                                  "draw_bottom", "set_default_target"):
                    raise ValueError("未知的对战操作。")
                frame = self.match.act(
                    action,
                    self.match.revision,
                    card_id=request.get("card_id"),
                    card_ids=request.get("card_ids"),
                    target=request.get("target"),
                    side=request.get("side"),
                    duel_number=request.get("duel_number"),
                    option=request.get("option"),
                    character_id=request.get("character_id"),
                )
            self.revision += 1
            return HTTPStatus.OK, {**frame, "revision": self.revision, "match_number": self.match_number}
