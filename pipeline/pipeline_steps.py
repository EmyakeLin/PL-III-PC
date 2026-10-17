from .pipeline_base import PipelineNode, PipelineTriggerNode, PipelineSection

# All Logic Node

logic_turn_start_code = """
print("LogicTurnStart!")
while True:
    for p in self.game.players:
        p.calculate_speed()
    print(f"Speed roll! {self.game.players[0].name}: {self.game.players[0].speed} vs {self.game.players[1].name}: {self.game.players[1].speed}")
    if self.game.players[0].speed != self.game.players[1].speed:
        fast_player = self.game.players[0] if self.game.players[0].speed > self.game.players[1].speed else self.game.players[1]
        break
print(f"Speed determined. {self.game.players[0].name}: {self.game.players[0].speed} vs {self.game.players[1].name}: {self.game.players[1].speed}\\n - {fast_player.name} first!")
"""

turn_start_draw_code = """

for p in self.game.players:
    char_count = len(p.characters)
    draw_count = gamerule.DRAW_COUNT
    if char_count == 1:
        total_draw = draw_count
        selection = False
    else:
        total_draw = draw_count - 1 + char_count
        selection = True
    if selection:
        p.select_card(total_draw, draw_count)
    else:
        p.draw_card(total_draw)
            

"""

logic_turn_end_code = """
print("LogicTurnEnd!")
"""

# TurnStart
before_turn_start = PipelineTriggerNode("before_turn_start")

logic_turn_start = PipelineNode("logic_turn_start", logic_turn_start_code)

on_turn_start = PipelineTriggerNode("on_turn_start")
after_turn_start = PipelineTriggerNode("after_turn_start")

# Placement

logic_start_placement_code = """

# decide who is the first player first, as speed may be modified between logic_turn_start and logic_start_placement
self.game.first_player = self.game.players[0] if self.game.players[0].speed > self.game.players[1].speed else self.game.players[1]
self.game.placing = self.game.first_player
player_action = self.game.first_player.place_card(self.game)
if player_action == "ended":
    self.game.ended_player.append(self.game.first_player)
self.game.switch_place_right()
place_capacity = 2
while True:
    if place_capacity <= 0:
        try:
            self.game.switch_place_right()
            place_capacity = 2
        except:
            self.game.ended_player.append(self.game.placing)
            break
    player_action = self.game.placing.place_card(self.game)
    if player_action == "placed":
        place_capacity -= 1
    elif player_action == "ended":
        self.game.ended_player.append(self.game.placing)
        try:
            self.game.switch_place_right()
            place_capacity = 2
        except:
            break
print(self.game.duelspace)

"""


logic_start_placement = PipelineNode("logic_start_placement", logic_start_placement_code)


# TurnEnd

before_turn_end = PipelineTriggerNode("before_turn_end")

logic_turn_end = PipelineNode("logic_turn_end", logic_turn_end_code)

on_turn_end = PipelineTriggerNode("on_turn_end")
after_turn_end = PipelineTriggerNode("after_turn_end")


# StepList

turn_start_steps = [
    before_turn_start,
    logic_turn_start,
    on_turn_start,
    after_turn_start,
]

placement_phase = [
    logic_start_placement
]

turn_end_steps = [
    before_turn_end,
    logic_turn_end,
    on_turn_end,
    after_turn_end,
]

step_list = turn_start_steps + placement_phase + turn_end_steps