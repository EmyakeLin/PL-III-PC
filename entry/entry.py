from dataclasses import dataclass
from enum import Enum, auto

from models.opcode import OpCode


class TriggerType(Enum):
    PIPELINE = auto()
    OPCODE = auto()


AUTHORITY = {"常规": 0, "较高话语权": 1, "最高话语权": 2,
             "normal": 0, "high": 1, "highest": 2}


def character_of(entity):
    card = getattr(entity, "card", None)
    if card is not None:
        return getattr(card, "character", None)
    if hasattr(entity, "character"):
        return entity.character
    if hasattr(entity, "is_alive"):
        return entity
    return None


def kind_of(owner):
    if hasattr(owner, "card"):
        return "die"
    if hasattr(owner, "character"):
        return "card"
    if hasattr(owner, "is_alive"):
        return "character"
    return "global"


class Entry:
    """An instantiated rule. One owner may have several in card-pack order."""

    @property
    def owning_card(self):
        return self.owner if kind_of(self.owner) == "card" else getattr(self.owner, "card", None)

    @property
    def blanked(self):
        return (getattr(self.owner, "type", None) == "blank"
                or getattr(self.owning_card, "range_deficit", 0) >= 3)

    def __init__(self, owner, trigger_type, trigger, operation, timing="AFTER", *,
                 scope="global", subject="any", target=None, authority=0, when=None,
                 period=None, origin=None, turn_limit=None, damage_cause=None, status_name=None):
        self.owner = owner
        self.trigger_type = trigger_type
        self.trigger = trigger
        self.operation = operation
        self.timing = timing
        self.scope = scope
        self.subject = subject
        self.target = target
        self.authority = AUTHORITY.get(authority, authority)
        if self.authority not in (0, 1, 2):
            raise ValueError(f"未知的话语权 {authority!r}")
        self.when = when or {}
        self.period = period
        self.origin = origin or kind_of(owner)
        self.damage_cause = damage_cause
        self.status_name = status_name
        self.window_open = period is None
        self.next_armed = False
        self.next_card = None
        self.turn_active = False
        self.detached = False
        self.turn_limit = turn_limit

    @classmethod
    def from_spec(cls, owner, spec):
        trigger = spec["trigger"]
        kind = kind_of(owner)
        timing = str(spec.get("timing", "AFTER")).upper()
        if str(spec.get("trigger_type", "")).lower() == "opcode":
            trigger = OpCode[str(trigger).upper()]
        if isinstance(trigger, str):
            words = trigger.upper().split()
            if len(words) == 2 and words[0] in ("BEFORE", "AFTER"):
                timing, trigger = words[0], OpCode[words[1]]
        trigger_type = TriggerType.OPCODE if isinstance(trigger, OpCode) else TriggerType.PIPELINE
        scope = spec.get("scope", kind)
        subject = spec.get("subject", "owner" if kind != "global" else "any")
        return cls(owner, trigger_type, trigger, spec["operation"], timing,
                   scope=scope, subject=subject, target=spec.get("target"),
                   authority=spec.get("authority", 0), when=spec.get("when"),
                   period=spec.get("period"), origin=spec.get("origin", kind), turn_limit=spec.get("turn_limit"),
                   damage_cause=spec.get("damage_cause"), status_name=spec.get("status_name"))


@dataclass(eq=False)
class EntryExecution:
    entry: Entry
    cancelled: bool = False
