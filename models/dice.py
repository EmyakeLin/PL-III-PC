

from enum import Enum, auto

class DiceType(Enum):
    SLASH = auto()
    PIERCE = auto()
    BLUNT = auto()
    BLOCK = auto()
    EVADE = auto()

class DiceLevel(Enum):
    D4 = 1
    D6 = 2
    D8 = 3
    D12 = 4
    D16 = 5
    D20 = 6

dice_value_range = {
    DiceLevel.D4: [1,4],
    DiceLevel.D6: [1,6],
    DiceLevel.D8: [1,8],
    DiceLevel.D12: [1,12],
    DiceLevel.D16: [1,16],
    DiceLevel.D20: [1,20],
}

dice_type_map = {
    "slash": DiceType.SLASH,
    "pierce": DiceType.PIERCE,
    "blunt": DiceType.BLUNT,
    "block": DiceType.BLOCK,
    "evade": DiceType.EVADE,
}


class Dice():
    def __init__(self, data, game = None):
        self.game = game
        self.type = data["type"]
        self.level = DiceLevel(data["level"])
        self.base_value = data["base_value"]
        self.final_bonus = data["final_bonus"]
        self.multiplier = data["multiplier"]
        self.calc_formula = data.get("calc_formula") or data.get("calc_fomula", "+")
        self.entries = data["entries"]
        

        self.value = 0
        self.clash_result = None

        if self.calc_formula in ["+", "-"]:
            self.calc_formula = "(b + v) * m + f" # b = base_value, v = 1 ~ Max, m = multiplier, f = final_bonus

    @property
    def is_passive(self) -> bool:
        """防御型骰子为被动触发 (block/evade)；进攻型为主动触发 (slash/pierce/blunt)"""
        return self.type in (DiceType.BLOCK, DiceType.EVADE, "block", "evade")

    def get_value(self):
        b = self.base_value
        v = self.value
        m = self.multiplier
        f = self.final_bonus
        return eval(self.calc_formula)
    
    def roll(self):
        import random
        min = dice_value_range[self.level][0]
        max = dice_value_range[self.level][1]
        from entry.builtin_operations import parse_builtin_operation
        op = parse_builtin_operation(f"Dice-Roll: {min}, {max}, 0, {id(self)}", self)
        if self.game is not None:
            self.game.context.eval_block(op)