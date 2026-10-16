
from enum import Enum, auto

class OpCode(Enum):
    # 基础栈与求值控制
    POP = auto()
    DUP = auto()
    SWAP = auto()
    EVAL = auto()
    
    # 算术与点数计算
    ADD = auto()
    SUB = auto()
    MUL = auto()
    CLAMP = auto()
    ROLL = auto()
    
    # 战斗与拼点核心
    CLASH = auto()
    RESOLVE_HIT = auto()
    
    # 状态与业务原子操作
    DAMAGE = auto()
    HEAL = auto()
    DRAW = auto()
    DESTROY = auto()

def handle_add(ctx):
    # 此时如果栈元素不足 2 个，ctx.pop() 会自动触发 StackUnderflowError
    b = ctx.pop()
    a = ctx.pop()
    ctx.push(a + b)

def handle_dup(ctx):
    ctx.dup()

def handle_pop(ctx):
    ctx.pop()


DISPATCH_TABLE = {
    OpCode.ADD: handle_add,
    OpCode.DUP: handle_dup,
    OpCode.POP: handle_pop,
}
