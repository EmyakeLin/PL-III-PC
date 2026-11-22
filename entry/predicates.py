"""Read-only comparisons evaluated before ordering listeners and again before invocation."""

from dataclasses import dataclass

from entry.entry import character_of
from entry.references import read_path
from models.conditions import COMPARISONS
from models.opcode import OpCode


@dataclass(frozen=True)
class Reference:
    path: tuple
    key: object = None
    default: object = None
    size: bool = False

    def read(self, owner, event):
        root, *fields = self.path
        value = read_path(owner if root == "self" else event, fields, missing=None)
        if self.key is not None:
            value = value.get(self.key, self.default) if isinstance(value, dict) else self.default
        if value is None:
            return self.default
        return len(value) if self.size else value


@dataclass(frozen=True)
class Rank:
    subject: Reference
    collection: Reference
    key: Reference
    conditions: tuple
    descending: bool

    def read(self, owner, event):
        subject = self.subject.read(owner, event)
        candidates = []
        for item in self.collection.read(owner, event):
            item_event = dict(event, item=item)
            if all(condition.evaluate(owner, item_event) for condition in self.conditions):
                candidates.append((self.key.read(owner, item_event), item))
        candidates.sort(key=lambda pair: pair[0], reverse=self.descending)
        return next((index for index, (_, item) in enumerate(candidates, 1) if item == subject), None)


@dataclass(frozen=True)
class Operand:
    offset: int


@dataclass(frozen=True)
class Comparison:
    left: object
    op: str
    right: object
    numeric: bool = False

    def matches(self, ctx, entry, ordering):
        if ordering and (isinstance(self.left, Operand) or isinstance(self.right, Operand)):
            return True
        return self.evaluate(character_of(entry.owner), ctx.event, ctx.peek)

    def evaluate(self, owner, event, peek=None):
        def read(value):
            if isinstance(value, (Reference, Rank)):
                return value.read(owner, event)
            return peek(value.offset) if isinstance(value, Operand) else value
        left, right = read(self.left), read(self.right)
        if self.numeric and not isinstance(left, (int, float)):
            return False
        try:
            return COMPARISONS[self.op](left, right)
        except TypeError:
            return False


def compile_value(value, operands=()):
    options = value if isinstance(value, dict) else {}
    if "rank_of" in options:
        descending = options.get("descending", False)
        fields = [compile_value(options[key]) for key in ("rank_of", "in", "by")]
        if type(descending) is not bool or not all(isinstance(ref, Reference) for ref in fields):
            raise ValueError("排名需要对象、集合、排序字段和布尔方向")
        return Rank(*fields, compile_when(options.get("where", []), None, None), descending)
    if "literal" in options:
        return options["literal"]
    field = options.get("field", value)
    if not isinstance(field, str) or not field.startswith("$"):
        return value
    root, *parts = field[1:].split(".")
    if root == "pending" and len(parts) == 1 and parts[0] in operands:
        return Operand(len(operands) - operands.index(parts[0]) - 1)
    if root not in ("self", "event") or any(not key.isidentifier() or key.startswith("_") for key in parts):
        raise ValueError(f"无效的条件字段 {field!r}")
    return Reference((root, *parts), options.get("key"), options.get("default"), options.get("size", False))


def compile_when(when, trigger, timing):
    from models.opcodes import OPERANDS

    operands = OPERANDS.get(trigger, ()) if timing == "BEFORE" else ()

    if isinstance(when, list):
        result = []
        for clause in when:
            if not isinstance(clause, dict) or not {"left", "op", "right"} <= clause.keys() or clause["op"] not in COMPARISONS:
                raise ValueError(f"无效的词条条件 {clause!r}")
            result.append(Comparison(compile_value(clause["left"], operands), clause["op"], compile_value(clause["right"], operands)))
        return tuple(result)

    result = []
    for name, value in when.items():
        if name == "die_type":
            result.append(Comparison(Reference(("event", "die", "type")), "eq", value))
        elif name in ("owner_status_at_least", "target_status_at_least", "owner_status_below_status"):
            path = ("event", "target", "statuses") if name.startswith("target") else ("self", "statuses")
            for status, limit in value.items():
                current = Reference(path, status, 0)
                if name == "owner_status_below_status":
                    result.append(Comparison(current, "lt", Reference(path, limit, 0)))
                else:
                    result.append(Comparison(current, "ge", limit))
        elif name in ("owner_hp_at_most", "target_hp_at_most"):
            path = ("self", "hp") if name.startswith("owner") else ("event", "target", "hp")
            result.append(Comparison(Reference(path), "le", value))
        elif name in ("amount_at_least", "result_at_least", "hp_lost_at_least", "damage_amount_at_least"):
            field = name.removesuffix("_at_least")
            pending = field == "amount" or field == "damage_amount" and trigger == OpCode.RESOLVE_DAMAGE
            left = compile_value("$pending.amount", operands) if pending and "amount" in operands else Reference(("event", field))
            result.append(Comparison(left, "ge", value, numeric=True))
        else:
            result.append(Comparison(Reference(("event",), name), "eq", value))
    return tuple(result)
