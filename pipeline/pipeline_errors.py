# 由Gemini编写，且上下文未知。需要谨慎考量，后期需要AI Agent辅助审阅。

from typing import Optional

class PipelineError(Exception):
    """
    管线异常基类：所有管线内抛出的错误都继承自此类。
    自动携带发生错误的节点 ID、当前步数以及发生时的上下文快照。
    """
    def __init__(self, message: str, node_id: Optional[str] = None, step_index: Optional[int] = None, payload: Optional[dict] = None):
        self.node_id = node_id
        self.step_index = step_index
        self.payload = payload or {}
        
        # 组装极具可读性的调试前缀
        location_info = f"[Node: {node_id or 'Unknown'} | Step: {step_index}]"
        full_message = f"{location_info} {message}"
        super().__init__(full_message)


# ----------------------------------------------------
# 1. 系统级异常 (程序实现层面的 Bug)
# ----------------------------------------------------
class PipelineSystemError(PipelineError):
    """底层系统错误"""
    pass

class PipelineCompileError(PipelineSystemError):
    """节点动态逻辑 compile 失败（如语法错误、缩进错误）"""
    pass

class PipelineScopeError(PipelineSystemError):
    """动态执行环境未正确提供上下文（如丢失 self 或关键变量）"""
    pass

class PipelineRecursionLimitError(PipelineSystemError):
    """单帧级联深度超限（检测到死循环相互触发）"""
    pass


# ----------------------------------------------------
# 2. 流程控制类 (类似 StopIteration，用于正常业务流转)
# ----------------------------------------------------
class PipelineFlowControl(PipelineError):
    """流程控制，不代表程序出错，上层应捕获并改变流程"""
    pass

class PipelineFinished(PipelineFlowControl):
    """管线自然到底结束"""
    pass

class PipelineHalted(PipelineFlowControl):
    """管线被外界强行中断（例如回合被强制跳过、游戏胜负已分）"""
    pass


# ----------------------------------------------------
# 3. 规则级异常 (类似咒法学的 Mishap / 施法失误)
# ----------------------------------------------------
class PipelineMishapError(PipelineError):
    """游戏规则层面的失误/异常，通常伴随游戏内的代价惩罚"""
    pass

class StackUnderflowError(PipelineMishapError):
    """操作码出栈参数不足（例如结算扣血需要 2 个操作数，栈顶只有 1 个）"""
    pass

class InvalidTargetError(PipelineMishapError):
    """目标非法（目标丢失、处于免疫状态、超出结算作用域）"""
    pass

class CostExceededError(PipelineMishapError):
    """结算代价超出承受能力（费用透支、能量不足）"""
    pass