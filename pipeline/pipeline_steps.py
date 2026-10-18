from .pipeline_base import PipelineNode, PipelineTriggerNode, PipelineSection

# ==================== 1. 已有 Logic 节点代码 ====================

turn_start_draw_code = """
for p in self.game.players:
    char_count = len(p.characters)
    draw_count = self.game.gamerule.DRAW_COUNT
    if char_count == 1:
        total_draw = draw_count
        selection = False
    elif char_count <= 0:
        raise ValueError("Invalid character count!")
    else:
        total_draw = draw_count - 1 + char_count
        selection = True
    if selection:
        p.select_card(total_draw, draw_count)
    else:
        p.draw_card(total_draw)
"""

logic_turn_start_code = """
print("LogicTurnStart!")
self.game.duelspace.current_duel_index = 0
while True:
    for p in self.game.players:
        p.calculate_speed()
    print(f"Speed roll! {self.game.players[0].name}: {self.game.players[0].speed} vs {self.game.players[1].name}: {self.game.players[1].speed}")
    if self.game.players[0].speed != self.game.players[1].speed:
        fast_player = self.game.players[0] if self.game.players[0].speed > self.game.players[1].speed else self.game.players[1]
        break
print(f"Speed determined. {self.game.players[0].name}: {self.game.players[0].speed} vs {self.game.players[1].name}: {self.game.players[1].speed}\\n - {fast_player.name} first!")
""" + turn_start_draw_code

logic_start_placement_code = """
for p in self.game.players:
    p.reset_on_turn_start()
self.game.first_player = self.game.players[0] if self.game.players[0].speed > self.game.players[1].speed else self.game.players[1]
self.game.placing = self.game.first_player
player_action = self.game.first_player.place_card(self.game)
if player_action == "ended":
    self.game.ended_player.append(self.game.first_player)
self.game.switch_place_right()
place_capacity = self.game.gamerule.PLACE_CAPACITY if hasattr(self.game.gamerule, "PLACE_CAPACITY") else 2
while True:
    if place_capacity <= 0:
        try:
            self.game.switch_place_right()
            place_capacity = self.game.gamerule.PLACE_CAPACITY if hasattr(self.game.gamerule, "PLACE_CAPACITY") else 2
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
            place_capacity = self.game.gamerule.PLACE_CAPACITY if hasattr(self.game.gamerule, "PLACE_CAPACITY") else 2
        except:
            break
print(self.game.duelspace)
"""

logic_reveal_code = """
from models.card import CardState
for ds in self.game.duelspace.space:
    for side in ds.content:
        for c in ds.get_content(side):
            if c.state == CardState.PLACED_FACE_DOWN:
                c.state = CardState.PLACED_FACE_UP
            if c.state == CardState.DEFAULT:
                raise TypeError("Wrong CardState!")
"""

logic_turn_end_code = """
print("LogicTurnEnd!")
"""


# ==================== 2. 回合开始阶段 (Turn Start) ====================

before_turn_start = PipelineTriggerNode("before_turn_start")
logic_turn_start = PipelineNode("logic_turn_start", logic_turn_start_code)
on_turn_start = PipelineTriggerNode("on_turn_start")
after_turn_start = PipelineTriggerNode("after_turn_start")

turn_start_steps = [
    before_turn_start,
    logic_turn_start,
    on_turn_start,
    after_turn_start,
]


# ==================== 3. 置卡阶段 (Placement Phase) ====================

logic_start_placement = PipelineNode("logic_start_placement", logic_start_placement_code)

placement_phase = [
    logic_start_placement,
]


# ==================== 4. 开牌阶段 (Reveal Phase) ====================

before_reveal = PipelineTriggerNode("before_reveal")
logic_before_reveal_phase = PipelineNode("logic_before_reveal_phase", "pass")
on_before_reveal_phase_start = PipelineTriggerNode("on_before_reveal_phase_start")
after_before_reveal_phase_start = PipelineTriggerNode("after_before_reveal_phase_start")

before_before_reveal_phase_end = PipelineTriggerNode("before_before_reveal_phase_end")
logic_before_reveal_phase_end = PipelineNode("logic_before_reveal_phase_end", "pass")
on_before_reveal_phase_end = PipelineTriggerNode("on_before_reveal_phase_end")
after_before_reveal_phase_end = PipelineTriggerNode("after_before_reveal_phase_end")

near_before_reveal = PipelineTriggerNode("near_before_reveal")
logic_reveal = PipelineNode("logic_reveal", logic_reveal_code)
on_reveal = PipelineTriggerNode("on_reveal")
after_reveal = PipelineTriggerNode("after_reveal")

reveal_phase = [
    before_reveal,
    logic_before_reveal_phase,
    on_before_reveal_phase_start,
    after_before_reveal_phase_start,
    before_before_reveal_phase_end,
    logic_before_reveal_phase_end,
    on_before_reveal_phase_end,
    after_before_reveal_phase_end,
    near_before_reveal,
    logic_reveal,
    on_reveal,
    after_reveal,
]


# ==================== 5. 循环节封装 (Duel / Skill / Dice Sections) ====================

# 骰子层面循环节 (Dice Loop: 仅使用前、logic使用、使用时、使用后)
before_dice_use = PipelineTriggerNode("before_dice_use")
logic_dice_use = PipelineNode("logic_dice_use", "pass")
on_dice_use = PipelineTriggerNode("on_dice_use")
after_dice_use = PipelineTriggerNode("after_dice_use")

dice_loop_nodes = [
    before_dice_use,
    logic_dice_use,
    on_dice_use,
    after_dice_use,
]
dice_loop = PipelineSection("dice_loop", "False", dice_loop_nodes)


# 技能层面循环节 (Skill Loop)
before_skill_use = PipelineTriggerNode("before_skill_use")
logic_skill_use = PipelineNode("logic_skill_use", "pass")
on_skill_use = PipelineTriggerNode("on_skill_use")
after_skill_use = PipelineTriggerNode("after_skill_use")

skill_loop_nodes = [
    before_skill_use,
    logic_skill_use,
    on_skill_use,
    dice_loop,
    after_skill_use,
]
skill_loop = PipelineSection("skill_loop", "False", skill_loop_nodes)


# 交锋层面循环节 (Duel Loop)
before_duel_start = PipelineTriggerNode("before_duel_start")
logic_duel_start = PipelineNode("logic_duel_start", "pass")
on_duel_start = PipelineTriggerNode("on_duel_start")
after_duel_start = PipelineTriggerNode("after_duel_start")

logic_duel_end_code = """
self.game.duelspace.current_duel_index += 1
"""

before_duel_end = PipelineTriggerNode("before_duel_end")
logic_duel_end = PipelineNode("logic_duel_end", logic_duel_end_code)
on_duel_end = PipelineTriggerNode("on_duel_end")
after_duel_end = PipelineTriggerNode("after_duel_end")

duel_loop_nodes = [
    before_duel_start,
    logic_duel_start,
    on_duel_start,
    after_duel_start,
    skill_loop,
    before_duel_end,
    logic_duel_end,
    on_duel_end,
    after_duel_end,
]
duel_loop = PipelineSection("duel_loop", "self.game.duelspace.has_next_duel()", duel_loop_nodes)


# ==================== 6. 回合结束阶段 (Turn End) ====================

before_turn_end = PipelineTriggerNode("before_turn_end")
logic_turn_end = PipelineNode("logic_turn_end", logic_turn_end_code)
on_turn_end = PipelineTriggerNode("on_turn_end")
after_turn_end = PipelineTriggerNode("after_turn_end")

turn_end_steps = [
    before_turn_end,
    logic_turn_end,
    on_turn_end,
    after_turn_end,
]


# ==================== 7. 全局管线步骤表 (Step List) ====================

step_list = turn_start_steps + placement_phase + reveal_phase + [duel_loop] + turn_end_steps
