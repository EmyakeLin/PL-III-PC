"""The mode catalog and the isolated tables hosted by one arena process."""

import secrets
from functools import partial
from threading import Lock

from battle_ui.session import BattleSession
from battle_ui.match import roster_art
from loader import load_characters_from_packs
from .challenges import CHALLENGES
from .manual import ManualDesk


def mode_definitions():
    """Each playable variant supplies a label and a factory accepting seed=."""
    return {
        "regular": ("常规对战", {"hotseat": ("热座", BattleSession),
                             "solo": ("单人模式", partial(BattleSession, ai_side=2, open_rosters=True))}),
        "challenge": ("挑战模式", {key: (c.name, partial(BattleSession, ai_side=2, open_rosters=True, challenge=c))
                               for key, c in CHALLENGES.items()}),
        "limit_battle": ("界限战斗", {}),
        "combat_contract": ("砺战合约", {}),
    }


def mode_catalog():
    return [{"id": key, "name": name, "available": bool(variants),
             "variants": [{"id": vid, "name": label} for vid, (label, _) in variants.items()]}
            for key, (name, variants) in mode_definitions().items()]


class RequestError(ValueError):
    def __init__(self, status, message, rpc_code=-32600):
        super().__init__(message)
        self.status = status
        self.rpc_code = rpc_code


class HostedRoom:
    def __init__(self, room):
        self.room = room
        self.local_table = isinstance(room, BattleSession)
        seats = (1,) if self.local_table else (1, 2)
        self.tokens = {s: secrets.token_urlsafe(32) for s in seats if s != getattr(room, "bot_side", None)}
        self.desk = None if self.local_table else ManualDesk(room)
        self.desk_token = secrets.token_urlsafe(32)

    def close(self):
        if not self.local_table:
            self.room.close()

    def authorized_seats(self, authorization, *, desk=False):
        if authorization is None:
            return ()
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token and token.isascii():
            if desk and secrets.compare_digest(self.desk_token, token):
                return tuple(self.tokens)
            for seat, secret in self.tokens.items():
                if secrets.compare_digest(secret, token):
                    return (seat,)
        raise RequestError(403, "席位凭据无效。")

    def side_for(self, authorization):
        seats = self.authorized_seats(authorization)
        return seats[0] if seats else None

    def desk_command(self, name, seats, body):
        if name == "status" and body == {}:
            return self.desk.status(seats)
        if name not in ("export", "submit", "status"):
            raise RequestError(404, "搬运台操作不存在。")
        if not isinstance(body, dict) or name == "status" or type(body.get("side")) is not int:
            raise RequestError(400, "搬运台参数无效。")
        side = body["side"]
        if side not in seats:
            raise RequestError(403, "本邀请不能操作该席位。")
        if name == "submit" and set(body) == {"side", "reply"} and isinstance(body["reply"], str):
            return self.desk.import_reply(side, body["reply"])
        if (name == "export" and body.keys() <= {"side", "kind", "cursor"}
                and body.get("kind") in ("intro", "turn")):
            return self.desk.export(side, briefing=body["kind"] == "intro", cursor=body.get("cursor"))
        raise RequestError(400, "请指定有效的导出类型或待解析的回复。")


class Lobby:
    def __init__(self, seed=None):
        self.seed = seed
        self._rooms = {}
        self._lock = Lock()
        self._closed = False

    @property
    def room_count(self):
        with self._lock:
            return len(self._rooms)

    @staticmethod
    def variant(mode, variant):
        modes = mode_definitions()
        if not isinstance(mode, str) or mode not in modes:
            raise RequestError(400, "未知对战模式。")
        label, variants = modes[mode]
        if not variants:
            raise RequestError(501, f"{label}尚未开放。")
        if not isinstance(variant, str) or variant not in variants:
            raise RequestError(400, f"请选择{label}中已开放的玩法。")
        return variants[variant]

    def lineup(self, mode, variant):
        self.variant(mode, variant)
        challenge = CHALLENGES[variant] if mode == "challenge" else None
        pool = {c["id"]: c for c in load_characters_from_packs(extra_packs=challenge.packs if challenge else ())}
        _, sprites, catalog = roster_art(pool)
        return {"catalog": catalog, "character_sprites": sprites,
                "fixed_opponents": list(challenge.opponents) if challenge else [],
                "hotseat": mode == "regular" and variant == "hotseat"}

    def create(self, spec):
        if not isinstance(spec, dict) or spec.keys() - {"mode", "variant", "roster"}:
            raise RequestError(400, "请指定对战模式及玩法。")
        mode, variant = spec.get("mode"), spec.get("variant")
        _, factory = self.variant(mode, variant)
        args = {"seed": self.seed}
        if "roster" in spec:
            roster = spec["roster"]
            if not isinstance(roster, list) or len(roster) != 2 or not all(
                    isinstance(team, list) and team and all(isinstance(c, str) for c in team) for team in roster):
                raise RequestError(400, "请为双方各选至少一名角色。")
            args["roster"] = roster
        hosted = HostedRoom(factory(**args))
        room_id = secrets.token_hex(16)
        with self._lock:
            if self._closed:
                hosted.close()
                raise RequestError(503, "服务正在关闭。")
            self._rooms[room_id] = hosted
        return {"id": room_id, "mode": mode, "variant": variant,
                "play_url": f"/rooms/{room_id}/table/#token={hosted.tokens[1]}"}

    def get(self, room_id):
        with self._lock:
            hosted = self._rooms.get(room_id)
        if hosted is None:
            raise RequestError(404, "房间不存在或已关闭。")
        return hosted

    def remove(self, room_id, authorization):
        hosted = self.get(room_id)
        if hosted.side_for(authorization) != 1:
            raise RequestError(403, "关闭房间需要创建时的私人邀请。")
        with self._lock:
            removed = self._rooms.pop(room_id, None)
        if removed is not None:
            removed.close()

    def close(self):
        with self._lock:
            self._closed = True
            rooms, self._rooms = self._rooms, {}
        for hosted in rooms.values():
            hosted.close()
