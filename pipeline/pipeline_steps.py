"""一回合的公开时刻表。每次置牌由 Game 广播自己的时点，逐骰交锋由双阵营管线推进。"""

from .pipeline_base import PipelineNode, PipelineTriggerNode


before_turn_start = PipelineTriggerNode("before_turn_start")
logic_draw_cards = PipelineNode("logic_draw_cards", lambda node: node.game.draw_phase())
logic_resolve_speed = PipelineNode("logic_resolve_speed", lambda node: node.game.determine_first_player())
logic_turn_start = PipelineNode("logic_turn_start", lambda node: node.game.start_turn())
on_turn_start = PipelineTriggerNode("on_turn_start")
after_turn_start = PipelineTriggerNode("after_turn_start")
logic_start_placement = PipelineNode("logic_start_placement", lambda node: node.game.run_placement())

turn_start_steps = [
    before_turn_start, logic_draw_cards, logic_resolve_speed, logic_turn_start, on_turn_start, after_turn_start,
]

placement_phase = [logic_start_placement]

reveal_phase = [
    PipelineTriggerNode("before_reveal", ready=lambda node: node.game.placing is None),
    PipelineNode("logic_before_reveal_phase", lambda node: None),
    PipelineTriggerNode("on_before_reveal_phase_start"),
    PipelineTriggerNode("after_before_reveal_phase_start"),
    PipelineNode("logic_before_reveal_declarations", lambda node: node.game.start_pre_reveal_declarations()),
    PipelineNode("logic_before_reveal_combat", lambda node: node.game.pre_reveal.begin_resolution(),
                 ready=lambda node: node.game.pre_reveal.actor is None),
    PipelineTriggerNode("before_before_reveal_phase_end"),
    PipelineNode("logic_before_reveal_phase_end", lambda node: None),
    PipelineTriggerNode("on_before_reveal_phase_end"),
    PipelineTriggerNode("after_before_reveal_phase_end"),
    PipelineTriggerNode("near_before_reveal"),
    PipelineNode("logic_reveal", lambda node: node.game.reveal_cards()),
    PipelineTriggerNode("on_reveal"),
    PipelineTriggerNode("after_reveal"),
]

logic_start_duel_combat = PipelineNode("logic_start_duel_combat", lambda node: node.game.pipeline.start_duel_combat())
logic_turn_end = PipelineNode("logic_turn_end", lambda node: node.game.finish_turn())
turn_end_steps = [
    PipelineTriggerNode("before_turn_end"), logic_turn_end,
    PipelineTriggerNode("on_turn_end"), PipelineTriggerNode("after_turn_end"),
]

step_list = turn_start_steps + placement_phase + reveal_phase + [logic_start_duel_combat] + turn_end_steps
