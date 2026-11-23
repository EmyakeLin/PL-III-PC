"""Read-only comparisons evaluated before ordering listeners and again before invocation."""

from collections.abc import Mapping
from dataclasses import dataclass
import operator

from entry.entry import character_of
from entry.references import read_path
from models.conditions import COMPARISONS


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
            value = value.get(self.key, self.default) if isinstance(value, Mapping) else self.default
        if value is None:
            return self.default
        return len(value) if self.size else value


@dataclass(frozen=True)
class Count:
    collection: Reference
    conditions: tuple

    def read(self, owner, event):
        items = (dict(event, item=item) for item in self.collection.read(owner, event))
        return sum(all(condition.evaluate(owner, item) for condition in self.conditions) for item in items)


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
class Calculation:
    operation: object
    left: object
    right: object

    def read(self, owner, event):
        return self.operation(read_value(self.left, owner, event), read_value(self.right, owner, event))


@dataclass(frozen=True)
class Conditional:
    condition: object
    yes: object
    no: object

    def read(self, owner, event):
        branch = self.yes if read_value(self.condition, owner, event) else self.no
        return read_value(branch, owner, event)


def read_value(value, owner, event):
    return value.read(owner, event) if isinstance(value, (Reference, Rank, Count, Calculation, Conditional)) else value


_VALUE_OPERATIONS = {**COMPARISONS, "add": operator.add, "sub": operator.sub, "mul": operator.mul,
                     "floor_div": operator.floordiv, "min": min, "max": max}


@dataclass(frozen=True)
class Comparison:
    left: object
    op: str
    right: object

    def matches(self, ctx, entry, ordering):
        if ordering and (isinstance(self.left, Operand) or isinstance(self.right, Operand)):
            return True
        return self.evaluate(character_of(entry.owner), ctx.event, ctx.peek)

    def evaluate(self, owner, event, peek=None):
        def read(value):
            return peek(value.offset) if isinstance(value, Operand) else read_value(value, owner, event)
        left, right = read(self.left), read(self.right)
        try:
            return COMPARISONS[self.op](left, right)
        except TypeError:
            return False


def compile_value(value, operands=()):
    options = value if isinstance(value, dict) else {}
    if "if" in options:
        if set(options) != {"if", "then", "else"}:
            raise ValueError("条件取值需要 if、then 和 else")
        return Conditional(*(compile_value(options[key]) for key in ("if", "then", "else")))
    if "op" in options:
        if set(options) != {"op", "left", "right"} or options["op"] not in _VALUE_OPERATIONS:
            raise ValueError(f"无效的只读取值表达式 {options!r}")
        return Calculation(_VALUE_OPERATIONS[options["op"]], compile_value(options["left"]), compile_value(options["right"]))
    if "rank_of" in options:
        descending = options.get("descending", False)
        fields = [compile_value(options[key]) for key in ("rank_of", "in", "by")]
        if type(descending) is not bool or not all(isinstance(ref, Reference) for ref in fields):
            raise ValueError("排名需要对象、集合、排序字段和布尔方向")
        return Rank(*fields, compile_when(options.get("where", []), None, None), descending)
    if "count_in" in options:
        collection = compile_value(options["count_in"])
        if set(options) - {"count_in", "where"} or not isinstance(collection, Reference):
            raise ValueError("计数需要集合引用和可选的筛选条件")
        return Count(collection, compile_when(options.get("where", []), None, None))
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

    if not isinstance(when, list):
        raise ValueError("when 需要由 left、op、right 组成的条件列表")
    result = []
    for clause in when:
        if not isinstance(clause, dict) or set(clause) != {"left", "op", "right"} or clause["op"] not in COMPARISONS:
            raise ValueError(f"无效的词条条件 {clause!r}")
        result.append(Comparison(compile_value(clause["left"], operands), clause["op"],
                                 compile_value(clause["right"], operands)))
    return tuple(result)
