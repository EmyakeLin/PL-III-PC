

from enum import Enum, auto
class CardState(Enum):
    DEFAULT = auto()            # 常规状态
    PLACED_FACE_UP = auto()     # 明置（于交锋）
    PLACED_FACE_DOWN = auto()   # 扣置（于交锋）
    NEGATED = auto()            # 被无效化


"""
arg = {

"id" = "id",
"name" = "card_name",
"cost" = cost,


"entries" = [
"PLScript",
]

"dice" = [
"type" = "type"
"level" = dice_level (1~6),
"base_value" = base_value,
"final_bonus" = final_bonus,
"multiplier" = multiplier(1),

"calc_formula" = "+"/"-"/custom ("(b+v)*m+f")

"entries" = [
"PLScript"
]

]
}

"""

# 骰子是以对象形式存储的，其触发时再实例化

class Card():
    def __init__(self, player, data, character = None):
        self.player = player
        self.character = character
        self.data = data

        self.id = data["id"]
        self.name = data["name"]
        self.cost = data["cost"]
        self.out_of_combat = data.get("out_of_combat") if data.get("out_of_combat") else False

        self.entries = data.get("entries")  # 可能无词条
        self.dice = data.get("dice")        # 可能无骰子

        self.state = CardState.DEFAULT

    def __str__(self):
        return f"{self.name}, cost: {self.cost} of {self.character}, side {self.player.side}"

    def get_meta(self, side = False, cost = False):
        side_add = ""
        cost_add = ""
        if side:
            side_add = f"Side {self.player.side} | "
        if cost:
            cost_add = f"| Cost: {self.cost}"
        return side_add + f"From {self.character}, [{self.name}]" + cost_add

    def print(self, owner = None):
        """Pass owner to show its detail if it's in FACE-DOWN state if identity matchs"""
        if self.state == CardState.PLACED_FACE_DOWN:
            if owner != self.player:
                print(f"From {self.character} | Face-down")
                return
            
        print(f"From {self.character}: [{self.name}] | cost [{self.cost}]")
        return