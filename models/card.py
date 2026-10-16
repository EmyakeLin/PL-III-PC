
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
    def __init__(self, player: Player, arg):
        self.player = player
        self.original_arg = arg
    