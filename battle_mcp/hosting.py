"""The mode catalog, 6-character room codes, and isolated Room instances hosted by one arena process."""

import secrets
from functools import partial
from threading import Lock

from battle_ui.fx_compiler import discover_character_fx, discover_fx_scripts
from battle_ui.match import roster_art
from battle_ui.status_icons import discover_status_visuals
from loader import load_characters_from_packs
from .challenges import CHALLENGES
from .manual import ManualDesk
from .room import Room
from .ruleset import ROOM_RULE_BOUNDS, build_opponent_presets, default_ruleset, generate_room_code


def mode_definitions():
    """All modes run on the unified real-time Room engine."""
    return {
        "regular": ("常规对战", {
            "online": ("联机开黑", partial(Room, selectable=True)),
            "solo": ("单人演练", partial(Room, bot=True, selectable=True)),
            "hotseat": ("同屏双人", partial(Room, hotseat=True, selectable=True)),
        }),
        "challenge": ("挑战模式", {
            key: (c.name, partial(Room, bot=True, challenge=c, selectable=True))
            for key, c in CHALLENGES.items()
        }),
        "limit_battle": ("界限战斗", {}),
        "combat_contract": ("砺战合约", {}),
    }


def mode_catalog():
    return [
        {
            "id": key,
            "name": name,
            "available": bool(variants),
            "variants": [{"id": vid, "name": label} for vid, (label, _) in variants.items()],
        }
        for key, (name, variants) in mode_definitions().items()
    ]


class RequestError(ValueError):
    def __init__(self, status, message, rpc_code=-32600):
        super().__init__(message)
        self.status = status
        self.rpc_code = rpc_code


class HostedRoom:
    def __init__(self, room, *, code=None):
        self.room = room
        self.local_table = False
        self.code = code or getattr(room, "room_code", None)
        self.hotseat = bool(getattr(room, "hotseat", False))
        if self.hotseat:
            tok = secrets.token_urlsafe(32)
            self.tokens = {1: tok}
            self.hotseat_token = tok
            self.seat2_claimed = True
        else:
            self.hotseat_token = None
            seats = (1, 2)
            self.tokens = {s: secrets.token_urlsafe(32) for s in seats if s != getattr(room, "bot_side", None)}
            self.seat2_claimed = bool(getattr(room, "bot_side", None) is not None)
        self.desk = ManualDesk(room) if hasattr(room, "cv") else None
        self.desk_token = secrets.token_urlsafe(32)

    def close(self):
        self.room.close()

    def resolve_token(self, token):
        """Return `(side, is_hotseat)` for a raw bearer/ws token string, or raise 403."""
        if not token:
            return None, False
        if not isinstance(token, str) or not token.isascii():
            raise RequestError(403, "席位凭据无效。")
        if self.hotseat_token and secrets.compare_digest(self.hotseat_token, token):
            return 1, True
        for seat, secret in self.tokens.items():
            if secrets.compare_digest(secret, token):
                if seat == 2:
                    self.seat2_claimed = True
                return seat, False
        raise RequestError(403, "席位凭据无效。")

    def authorized_seats(self, authorization, *, desk=False):
        if authorization is None:
            return ()
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token and token.isascii():
            if desk and secrets.compare_digest(self.desk_token, token):
                return (1, 2) if self.hotseat else tuple(self.tokens)
            if self.hotseat_token and secrets.compare_digest(self.hotseat_token, token):
                return (1, 2)
            for seat, secret in self.tokens.items():
                if secrets.compare_digest(secret, token):
                    if seat == 2:
                        self.seat2_claimed = True
                    return (seat,)
        raise RequestError(403, "席位凭据无效。")

    def auth_context(self, authorization):
        """Return `(side, is_hotseat)` from an HTTP Authorization header."""
        if authorization is None:
            return None, False
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return self.resolve_token(token)
        raise RequestError(403, "席位凭据无效。")

    def side_for(self, authorization):
        side, _ = self.auth_context(authorization)
        return side

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
        self._by_code = {}
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
        colors, sprites, catalog = roster_art(pool)
        is_online = mode == "regular" and variant == "online"
        return {
            "catalog": catalog,
            "character_colors": colors,
            "character_sprites": sprites,
            "character_fx": discover_character_fx(pool, colors),
            "fx_scripts": discover_fx_scripts(),
            "status_visuals": discover_status_visuals(pool),
            "fixed_opponents": list(challenge.opponents) if challenge else [],
            "opponent_presets": [] if (challenge or is_online) else build_opponent_presets(pool),
            "default_ruleset": default_ruleset(online=is_online),
            "rule_bounds": dict(ROOM_RULE_BOUNDS),
            "hotseat": mode == "regular" and variant == "hotseat",
            "online": is_online,
        }

    def create(self, spec):
        if not isinstance(spec, dict) or spec.keys() - {"mode", "variant", "roster", "ruleset"}:
            raise RequestError(400, "请指定对战模式及玩法。")
        mode, variant = spec.get("mode"), spec.get("variant")
        _, factory = self.variant(mode, variant)
        args = {"seed": self.seed}
        if "ruleset" in spec and spec["ruleset"] is not None:
            args["ruleset"] = spec["ruleset"]
        has_roster = "roster" in spec and spec["roster"] is not None
        if has_roster:
            roster = spec["roster"]
            if not isinstance(roster, list) or len(roster) != 2 or not all(
                    isinstance(team, list) and team and all(isinstance(c, str) for c in team) for team in roster):
                raise RequestError(400, "请为双方各选至少一名角色。")
            args["roster"] = roster
            args["start_immediately"] = (variant != "online")

        with self._lock:
            if self._closed:
                raise RequestError(503, "服务正在关闭。")
            code = generate_room_code(self._by_code.keys())
        args["room_code"] = code
        try:
            room = factory(**args)
        except ValueError as exc:
            raise RequestError(400, str(exc)) from None
        hosted = HostedRoom(room, code=code)
        room_id = secrets.token_hex(16)
        with self._lock:
            if self._closed:
                hosted.close()
                raise RequestError(503, "服务正在关闭。")
            self._rooms[room_id] = hosted
            self._by_code[code] = room_id
        resp = {
            "id": room_id,
            "code": code,
            "mode": mode,
            "variant": variant,
            "play_url": f"/rooms/{room_id}/canvas/#token={hosted.tokens[1]}",
            "spectate_url": f"/rooms/{room_id}/canvas/",
        }
        if 2 in hosted.tokens:
            resp["guest_url"] = f"/rooms/{room_id}/canvas/#token={hosted.tokens[2]}"
        return resp

    def join(self, body):
        if not isinstance(body, dict) or not isinstance(body.get("code"), str):
            raise RequestError(400, "请输入 6 位房间码。")
        code = body["code"].strip().upper()
        with self._lock:
            room_id = self._by_code.get(code)
            hosted = self._rooms.get(room_id) if room_id else None
            if hosted is None:
                raise RequestError(404, "未找到该房间码，请确认房间是否仍在运行。")
            if not hosted.seat2_claimed and 2 in hosted.tokens:
                hosted.seat2_claimed = True
                return {
                    "id": room_id,
                    "code": code,
                    "role": "player",
                    "side": 2,
                    "play_url": f"/rooms/{room_id}/canvas/#token={hosted.tokens[2]}",
                }
            return {
                "id": room_id,
                "code": code,
                "role": "spectator",
                "side": None,
                "play_url": f"/rooms/{room_id}/canvas/",
            }

    def get(self, room_id):
        with self._lock:
            hosted = self._rooms.get(room_id)
        if hosted is None:
            raise RequestError(404, "房间不存在或已关闭。")
        return hosted

    def remove(self, room_id, authorization):
        hosted = self.get(room_id)
        if hosted.side_for(authorization) != 1:
            raise RequestError(403, "关闭房间需要房主的私人邀请。")
        with self._lock:
            removed = self._rooms.pop(room_id, None)
            if removed and removed.code:
                self._by_code.pop(removed.code, None)
        if removed is not None:
            removed.close()

    def close(self):
        with self._lock:
            self._closed = True
            rooms, self._rooms = self._rooms, {}
            self._by_code.clear()
        for hosted in rooms.values():
            hosted.close()
