from copy import copy, deepcopy

from .pipeline_errors import PipelineError


class PipelineNode:
    def __init__(self, id, operation_code, is_period=False, period_args=None, *, ready=None):
        self.id = id
        self.period_args = period_args or {}
        self.is_period = is_period
        self.ready = ready
        self.game = None
        if callable(operation_code):
            self.operation = operation_code
        else:
            code = compile(operation_code, f"<pipeline_node_{id}>", "exec")
            self.operation = lambda node: exec(code, globals(), {"self": node})

    def bind(self, game):
        """Keep compiled logic reusable while isolating each match's node state."""
        node = copy(self)
        node.period_args = deepcopy(self.period_args)
        node.game = game
        return node

    def execute(self):
        try:
            self.operation(self)
        except EOFError:
            raise
        except Exception as exc:
            raise PipelineError(str(exc), node_id=self.id) from exc


class PipelineTriggerNode(PipelineNode):
    def __init__(self, trigger_id, *, ready=None):
        super().__init__(trigger_id, self.broadcast, ready=ready)

    @staticmethod
    def broadcast(node):
        node.game.context.dispatch_pipeline(node.id)
