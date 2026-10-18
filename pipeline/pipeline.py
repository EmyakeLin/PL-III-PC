from .pipeline_base import PipelineNode, PipelineTriggerNode, PipelineSection 
from .pipeline_errors import (
    PipelineError,
    PipelineSystemError,
    PipelineCompileError,
    PipelineScopeError,
    PipelineRecursionLimitError,
    PipelineFlowControl,
    PipelineFinished,
    PipelineHalted,
    PipelineMishapError,
    StackUnderflowError,
    InvalidTargetError,
    CostExceededError,
)
# Pipeline Nodes

# codes

# trigger common logic




class Pipeline():
    def __init__(self, game = None, step_list = []):
        self.game = game
        self.step_list = step_list
        self.current_step_index = -1
        self.is_finished = False

    def next_step(self):
        if self.is_finished or self.current_step_index >= len(self.step_list) - 1:
            self.is_finished = True
            raise PipelineFinished("管线所有步骤已执行完毕", step_index=self.current_step_index)

        self.current_step_index += 1
        cur_step = self.step_list[self.current_step_index]
        cur_step.game = self.game
        cur_step.execute()
        return cur_step.id

