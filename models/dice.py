import ast
import operator
from collections import deque
from enum import Enum, auto
from functools import lru_cache

from entry.effects import damage_part, independent_damage_part
from models.card import describe_entry, describe_range_traits, range_trait, validate_range_trait
from models.opcode import OpCode


class DiceType(Enum):
    SLASH = auto()
    PIERCE = auto()
    BLUNT = auto()
    BLOCK = auto()
    EVADE = auto()
    BLANK = auto()
    SKIP = auto()


class DiceLevel(Enum):
    D4 = 1
    D6 = 2
    D8 = 3
    D12 = 4
    D16 = 5
    D20 = 6


dice_value_range = {level: (1, int(level.name[1:])) for level in DiceLevel}
dice_type_map = {kind.name.lower(): kind for kind in DiceType}
dice_type_map["guard"] = DiceType.BLOCK
TYPE_NAMES = {"slash": "斩击", "pierce": "突刺", "blunt": "砸击",
              "block": "招架", "evade": "闪避", "blank": "空白骰", "skip": "跳过"}
ARITHMETIC = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}


@lru_cache(maxsize=128)
def _formula_tree(text):
    return ast.parse(text, mode="eval").body


def _evaluate(node, values):
    if isinstance(node, ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node, ast.Constant) and type(node.value) in (float, int):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in ARITHMETIC:
        return ARITHMETIC[type(node.op)](_evaluate(node.left, values), _evaluate(node.right, values))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand, values)
        return -value if isinstance(node.op, ast.USub) else value
    raise ValueError("骰子公式只支持数值、b/v/m/f 与算术运算")


class Dice:
    def __init__(self, data, game=None):
        self.game = game
        self.card = None
        for key in ("range_level", "ignore_range"):
            validate_range_trait(data, key)
        self.data = data
        if type(data.get("passive_activation", False)) is not bool:
            raise ValueError("被动激活须为布尔值")
        if data.get("clash_order", "higher") not in ("higher", "lower"):
            raise ValueError("拼点胜利条件须为 higher 或 lower")
        if type(data.get("fixed_level", False)) is not bool:
            raise ValueError("固定印刷骰级须为布尔值")
        kind = data["type"]
        if isinstance(kind, DiceType):
            kind = kind.name.lower()
        self.type = dice_type_map[kind].name.lower()
        self._printed_level = DiceLevel(1 if self.type == "skip" else data["level"])
        self._printed_roll_max = data.get("roll_max", dice_value_range[self._printed_level][1])
        if type(self._printed_roll_max) is not int or self._printed_roll_max < 1:
            raise ValueError("变动点数上限必须是正整数")
        self._level_bonus = 0
        self._resolved_level = None
        self.position = None
        self.repeat_requested = False
        self.repeat_materialized = False
        self.entries_registered = False
        self.resource_paid = False
        self.is_repeat = False
        self.queued_hits = deque()
        self.hit_mode = None
        self.hit_origin = None
        self.hit_target = None
        self.hit_index = 0
        self.landed_hits = 0
        self.did_deal_damage = False
        self.use_state = {}
        self.attack_redirected = False
        self.attack_target = None
        self.base_value = data.get("base_value", 0)
        self.final_bonus = data.get("final_bonus", 0)
        self.multiplier = data.get("multiplier", 1)
        self.calc_formula = data.get("calc_formula") or data.get("calc_fomula", "+")
        self.entries = data.get("entries", [])
        self._value = 0
        self.final_score = None
        self.clash_score = None
        self.clash_result = None
        self.win_branch_skipped = False
        self.destroyed = False
        self.keep_position = False
        self.critical = False

    @property
    def is_passive(self):
        return self.type in ("block", "evade")

    @property
    def can_attack_alone(self):
        return self.is_attack and not self.data.get("passive_activation", False)

    def pay_use_cost(self):
        """Pay once, after insertions have resolved and before this use is paired."""
        cost = self.data.get("resource_cost")
        if not cost or self.resource_paid or self.card.range_deficit >= 3:
            return True
        actor = self.card.character
        ctx = self.game.context
        with ctx.binding(source=actor, side=actor.player.side, card=self.card, die=self):
            ctx.stack.extend((actor, cost["status"], cost["amount"]))
            self.resource_paid = ctx.pay_status_cost()
        return self.resource_paid

    def can_afford_use(self):
        cost = self.data.get("resource_cost")
        return (not cost or self.resource_paid or self.card.range_deficit >= 3
                or self.card.character.spendable_status(cost["status"]) >= cost["amount"])

    def register_entries(self):
        if not self.destroyed and not self.entries_registered:
            self.game.context.register_entries(self, self.entries)
            self.entries_registered = True

    @property
    def is_attack(self):
        return self.type in ("slash", "pierce", "blunt")

    @property
    def effective_range(self):
        return max(self.card.effective_range if self.card else 0, range_trait(self.data, "range_level", self.card))

    @property
    def effective_ignore_range(self):
        return max(self.card.effective_ignore_range if self.card else 0, range_trait(self.data, "ignore_range", self.card))

    @property
    def paired_range(self):
        opponent = self.card.range_opponent if self.card else None
        if opponent is None:
            return self.effective_range
        opposing_die = self.game.context.active_dice.get(opponent.player.side)
        opposing_range = (opposing_die.effective_range if getattr(opposing_die, "card", None) is opponent
                          else opponent.effective_range)
        return self.card.paired_ranges(opponent, self.effective_range, opposing_range)[0]

    @property
    def has_damage_part(self):
        return any(damage_part(entry) is not None or independent_damage_part(entry) is not None or (
            isinstance(entry, dict) and isinstance(entry.get("operation"), dict)
            and entry["operation"].get("damage_part")) for entry in self.entries)

    def make_blank(self):
        """Only this use changes. The printed die remains available on redraw."""
        self.type = "blank"
        self.entries = []
        self.repeat_requested = False
        self.queued_hits.clear()
        self.attack_redirected = False
        self.attack_target = None

    @property
    def printed_level(self):
        return self._printed_level

    @property
    def modified_level(self):
        return self._printed_level.value + self._level_bonus + (self.card.level_bonus if self.card else 0)

    @property
    def level(self):
        if self.data.get("fixed_level"):
            return self._printed_level
        value = self.modified_level if self._resolved_level is None else self._resolved_level
        return DiceLevel(min(DiceLevel.D20.value, max(DiceLevel.D4.value, value)))

    def resolve_value(self, opcode, initial, **fields):
        if self.game is None:
            return self.record_value(opcode, initial)
        with self.game.context.binding(**fields):
            return self.game.context.eval_block([self, initial, opcode])

    def record_value(self, opcode, value):
        if opcode == OpCode.RESOLVE_DIE_LEVEL:
            self._resolved_level = value
            return self.level.value
        if opcode == OpCode.RESOLVE_FINAL_SCORE:
            self.final_score = value
        else:
            self.clash_score = value
        return value

    def resolve_level(self):
        self._resolved_level = None
        return self.resolve_value(OpCode.RESOLVE_DIE_LEVEL, self.modified_level)

    @property
    def roll_max(self):
        level = self.level
        if level == self._printed_level:
            return self._printed_roll_max
        return dice_value_range[level][1]

    def add_levels(self, amount):
        self._level_bonus += amount
        self.refresh_resolved_level()

    def refresh_resolved_level(self):
        if self._resolved_level is not None:
            self.resolve_level()

    def request_repeat(self):
        if self.destroyed or self.repeat_requested:
            return False
        self.repeat_requested = True
        return True

    @property
    def value(self):
        return min(self._value, self.roll_max)

    @value.setter
    def value(self, value):
        self._value = min(self.roll_max, max(1, value))

    def get_value(self):
        if self.final_score is not None:
            return self.final_score
        return self.calculate_final_score()

    def calculate_final_score(self):
        if self.calc_formula in ("+", "-", "(b + v) * m + f"):
            value = (self.base_value + self.value) * self.multiplier + self.final_bonus
        else:
            value = _evaluate(_formula_tree(self.calc_formula), {
                "b": self.base_value, "v": self.value, "m": self.multiplier, "f": self.final_bonus,
            })
        if self.card is not None:
            value += self.card.final_bonus
            if self.card.character is not None and self.type != "blank":
                value += self.card.character.status_modifier("final_score")
        return value

    def roll(self, *, clash=False):
        self.final_score = self.clash_score = None
        self.resolve_level()
        if self.game is None:
            import random
            self.value = random.randint(1, self.roll_max)
        else:
            with self.game.context.binding(clash_roll=clash):
                self.game.context.eval_block([1, self.roll_max, 0, self, OpCode.ROLL])
        return self.get_value()


def describe_die(data):
    die = Dice(data)
    name = TYPE_NAMES[die.type]
    if die.type == "skip":
        return "SKIP（跳过本轮）"
    die.value = 1
    first = die.get_value()
    die.value = die.roll_max
    last = die.get_value()
    traits = describe_range_traits(data)
    if data.get("clash_order") == "lower":
        traits.append("拼点逆转")
    if data.get("fixed_level"):
        traits.append("固定骰面范围，忽略骰级升降")
    if data.get("passive_activation"):
        traits.append("被动激活")
    if cost := data.get("resource_cost"):
        traits.append(f"使用本骰须消耗{cost['amount']}{cost['status']}")
    effects = "；".join([*traits, *(describe_entry(entry) for entry in die.entries)])
    return f"{name} {die.level.name.lower()}（{first}～{last}）" + (f"〔{effects}〕" if effects else "")
