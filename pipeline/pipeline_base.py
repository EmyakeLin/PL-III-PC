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


class PipelineNode():
    def __init__(self, id, operation_code, is_period=False, period_args = {}):
        self.id = id
        self.period_args = period_args if period_args is not None else {}
        self.is_period = is_period
        
        self.operation = compile(operation_code, f"<pipeline_node_{id}>", "exec")

    def execute(self):
        try:
            exec(self.operation, globals(), {"self": self})
        except Exception as e:
            raise PipelineError(f"节点执行崩溃: {e}", node_id=self.id) from e



pipeline_trigger_logic = """
print(self.id)
if hasattr(self, "game") and self.game and getattr(self.game, "context", None):
    self.game.context.dispatch_pipeline(self.id)
"""

class PipelineTriggerNode(PipelineNode):
    def __init__(self, trigger_id):
        """trigger_id will be the Node id"""
        super().__init__(trigger_id, pipeline_trigger_logic)



class PipelineSection():
    def __init__(self, id, repeat_logic, nodes):
        self.id = id
        self.repeat_logic = compile(repeat_logic, f"<pipeline_section_{id}>", "exec")
        self.nodes = nodes

    def execute(self):
        can_loop = exec(self.repeat_logic)
        if can_loop:
            for node in self.nodes:
                can_loop = exec(self.repeat_logic)
                if not can_loop:
                    break
                node.execute()

