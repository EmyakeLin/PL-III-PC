"""Translate settled kernel facts into the public table's animation protocol."""
from collections import deque


SHIELDS = {"shield": "normal", "reinforced_shield": "reinforced", "concept_shield": "concept"}


class TableBridge:
    def __init__(self, context):
        self._pending = context.observe_facts()
        self._events = deque(maxlen=220)
        self._sequence = 0
        self._turn = 0
        self._rolls = {}
        self._teams = []
        self._speed_rolls = []

    @property
    def events(self):
        self.flush()
        return tuple(self._events)

    @property
    def speed_rolls(self):
        self.flush()
        return tuple(self._speed_rolls)

    def _append(self, kind, **payload):
        self._sequence += 1
        self._events.append({"seq": self._sequence, "kind": kind, "turn": self._turn, **payload})

    def emit(self, kind, **payload):
        self.flush()
        self._append(kind, **payload)

    def flush(self):
        while self._pending:
            self._project(*self._pending.popleft())

    def _project(self, kind, data):
        if kind == "turn_opened":
            self._turn = data["number"]
            self._speed_rolls.clear()
            self._teams.clear()
            self._rolls.clear()
        elif kind == "initiative_die":
            modifiers = data["modifiers"]
            self._rolls.setdefault(data["side"], []).append({
                "character_id": data["character_id"], "name": data["character_name"], "raw": data["raw"],
                "haste": modifiers.get("迅捷", 0), "bind": modifiers.get("束缚", 0), "speed": data["speed"],
            })
        elif kind == "team_speed":
            side = data["side"]
            self._teams.append({"side": side, "rolls": self._rolls.pop(side, []),
                                "dropped_id": data["dropped"], "team_speed": data["speed"]})
        elif kind in ("initiative", "speed_tied"):
            result = {"attempt": len(self._speed_rolls) + 1, "winner_side": data.get("side"), "sides": self._teams}
            self._teams = []
            self._speed_rolls.append(result)
            self._append("speed_roll", **result)
        elif kind in ("cards_revealed", "empty_board"):
            self._append("cards_reveal", duels=data.get("duels", []))
        elif kind == "turn_ended":
            self._append("turn_recycle", sides=data["recycled"])
        elif kind == "cards_drawn":
            self._append("draw", side=data["side"], count=data["count"])
        elif kind == "turn_budget":
            self._append("cost_refill", side=data["side"], common=data["common"],
                         personal=[{"character_id": key, "available": amount} for key, amount in data["personal"]])
        elif kind == "skill_payment":
            self._append("cost_pay", **data)
        elif kind == "entry_resolved":
            self._append("passive_trigger", side=data["side"], character_id=data["character_id"],
                         character_name=data["character_name"], passive_name=data["group"])
        elif kind == "stagger_resolved":
            self._append("stagger_check", target_side=data["side"], target_id=data["character_id"],
                         stacks_before=data["before"].get("失衡", 0), triggered=data["passed"])
        elif kind == "critical_resolved":
            self._append("breath_crit", side=data["side"], character_id=data["character_id"],
                         target_id=data["target_id"], stacks=data["balances"].get("呼吸", 0))
        elif kind == "character_died":
            self._append("character_death", side=data["side"], character_id=data["character_id"],
                         name=data["character_name"])
        elif kind == "shield_balance" and data["after"] > data["before"]:
            self._append("shield_gain", side=data["side"], character_id=data["character_id"],
                         name=data["character_name"], shield_kind=SHIELDS[data["field"]],
                         amount=data["after"] - data["before"], total=data["after"])
        elif kind == "status_balance":
            self._append("status_change", side=data["side"], character_id=data["character_id"],
                         character_name=data["character_name"], status=data["status"], before=data["before"],
                         after=data["after"], delta=data["after"] - data["before"],
                         burst=data["status"] == "裂血" and data["active"])
        elif kind in ("damage_settled", "health_lost", "health_recovered"):
            health = dict(target_side=data["side"], target_id=data["character_id"], target_name=data["character_name"],
                          hp_after=data["hp"], max_hp=data["maximum"])
            if kind == "damage_settled":
                self._append("damage", **health, grade=data["grade"], incoming=data["incoming"],
                             multiplier=data["multiplier"], hp_lost=data["hp_lost"], cause=data["cause"] or "attack",
                             absorbed={name: data["absorbed"].get(field, 0) for field, name in SHIELDS.items()},
                             eroded={name: data["eroded"].get(field, 0) for field, name in SHIELDS.items()
                                     if field != "concept_shield"})
            else:
                self._append("heal" if kind == "health_recovered" else "lose_hp", **health, amount=data["amount"])
        elif kind == "lightcore_healed":
            self._append(kind, target_side=data["side"], target_id=data["character_id"],
                         target_name=data["character_name"], amount=data["amount"],
                         lightcore_after=data["hp"], max_lightcore=data["maximum"])
        elif kind == "lightcore_damage":
            self._append(
                "lightcore_damage",
                target_side=data.get("side"),
                target_id=data.get("character_id"),
                target_name=data.get("character_name") or data.get("target"),
                amount=data.get("amount", 0),
                lost=data.get("lost", 0),
                lightcore_after=data.get("hp", 0),
                max_lightcore=data.get("maximum", 0),
            )
        elif kind == "lightcore_collapse":
            self._append(
                "lightcore_collapse",
                target_side=data.get("side"),
                target_id=data.get("character_id"),
                target_name=data.get("character_name") or data.get("target"),
            )
        elif kind == "lightcore_restored":
            self._append(
                "lightcore_restored",
                target_side=data.get("side"),
                target_id=data.get("character_id"),
                target_name=data.get("character_name") or data.get("target"),
                lightcore_after=data.get("hp", 0),
                max_lightcore=data.get("maximum", 0),
            )
        elif kind == "card_destroyed":
            self._append(
                "card_destroyed",
                side=data.get("side"),
                character_id=data.get("character_id"),
                character_name=data.get("character_name"),
                card_id=data.get("card_id"),
                instance_id=data.get("instance_id"),
                card_name=data.get("card"),
            )
        elif kind == "die_destroyed":
            self._append(
                "die_destroyed",
                side=data.get("side"),
                character_id=data.get("character_id"),
                character_name=data.get("character_name"),
                card_id=data.get("card_id"),
                card_name=data.get("card"),
                position=data.get("position"),
                die_type=data.get("die_type"),
            )
