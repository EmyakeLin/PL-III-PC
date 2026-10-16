
from player.player import Player


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
    def __init__(self, player: Player, data, character = None):
        self.player = player
        self.character = character
        self.data = data

        self.id = data["id"]
        self.name = data["name"]
        self.cost = data["cost"]
        self.out_of_combat = data.get("out_of_combat") if data.get("out_of_combat") else False

        self.entries = data.get("entries")  # 可能无词条
        self.dice = data.get("dice")        # 可能无骰子
    