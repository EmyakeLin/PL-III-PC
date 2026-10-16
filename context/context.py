from pipeline.pipeline_errors import (
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

from models.opcode import OpCode, DISPATCH_TABLE

from entry.entry import TriggerType, Entry

class Context():
    def __init__(self, parent = None, game = None):
        self.parent = parent
        if self.parent:
            self.game = self.parent.game
        else:
            self.game = game

        self.stack = []
        self.entries = []

        self.register = {}
        self.interceptions = []
        self.meta = {}

    def push(self, value):
        self.stack.append(value)

    def pop(self):
        """返回栈顶元素"""
        if len(self.stack) == 0:
            raise StackUnderflowError("栈下溢")
        return self.stack.pop()

    def peek(self, offset):
        """查看栈元素而不出栈"""
        if len(self.stack) <= offset:
            raise StackUnderflowError("offset 过大")
        return self.stack[-1-offset]

    def dup(self):
        """复制栈顶元素"""
        self.push(self.peek(0))

    def swap(self):
        """交换栈顶两个元素"""

    def store(self, name):
        """将栈顶存入寄存器"""
        self.register[name] = self.pop()

    def load(self, name):
        """从寄存器取值并压入栈顶，不清空寄存器"""
        self.push(self.register.get(name))

    def eval_block(self, block):
        if not isinstance(block, list):
            raise TypeError
        for item in block:
            if isinstance(item, list):
                self.push(item)
            elif callable(item):
                item(self)
            elif isinstance(item, OpCode):
                self.dispatch_opcode(item, "BEFORE")
                handler = DISPATCH_TABLE.get(item)
                if not handler:
                    raise PipelineSystemError(f"未实现的操作码: {item}")
                handler(self)
                self.dispatch_opcode(item, "AFTER")
            else:
                self.push(item)

    def dispatch_opcode(self, opcode, timing):
        for e in list(self.entries):
            if e.trigger_type == TriggerType.OPCODE:
                if e.trigger == opcode:
                    if e.timing == timing:
                        self.eval_block(e.operation)

    def dispatch_pipeline(self, node_id):
        """广播管线时钟节点，唤醒所有监听此节点的 Entry"""
        for e in list(self.entries):
            if e.trigger_type == TriggerType.PIPELINE:
                if e.trigger == node_id:
                    self.eval_block(e.operation)
