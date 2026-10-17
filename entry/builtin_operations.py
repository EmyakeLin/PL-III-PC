import ast
import inspect
from collections import deque
from itertools import product


def expect(args=None, rules=None):
    """
    强契约声明装饰器：
    - args: 声明来自文本输入必须提供的参数名列表（支持数值、字符串等多数值/参数输入，如 args=['amount', 'dmg_type']）。
            门禁校验：若函数签名未包含全部 args，或文本传入个数不符，则严格报错！
    - rules: 关系与判定规则约束函数（如 rules=lambda amount, dmg_type, target, owner: ...）。
             未出现在 args 中的参数将自动由实体图谱求解器在战局中解算注入。
    """
    if args is None:
        args = []

    def decorator(func):
        sig = inspect.signature(func)
        func_params = list(sig.parameters.keys())

        # 门禁 1：函数签名必须包含全部 args 声明的参数！
        missing = [a for a in args if a not in func_params]
        if missing:
            raise ValueError(f"函数 {func.__name__} 缺少在 @expect(args=...) 中声明的参数: {missing}")

        func.expect_args = args
        func.expect_rules = rules
        if rules is not None and callable(rules):
            func.rule_param_names = list(inspect.signature(rules).parameters.keys())
        else:
            func.rule_param_names = []
        return func

    return decorator


def parse_text_arg(raw):
    """
    智能文本参数类型解析：
    优先尝试解析为 Python 原生字面量（int, float, bool 等）；
    若非字面量则作为纯字符串（str）返回，彻底保留所有类型自由度！
    """
    raw = raw.strip()
    try:
        return ast.literal_eval(raw)
    except Exception:
        return raw


def parse_args_from_text(arg_part):
    """
    从冒号后文本中解析多数值/多参数列表（支持逗号分隔，如 '5, pierce, 0.5'）。
    """
    parts = [p.strip() for p in arg_part.split(",") if p.strip()]
    return [parse_text_arg(p) for p in parts]


def collect_universe(start_entity):
    """
    从起点实体出发，通过 Python 原生对象反射 (__dict__) 动态遍历对象图谱。
    搜集所有可达的候选实体与集合（零硬编码属性名）。
    """
    universe = []
    visited = set()
    queue = deque([start_entity])

    while queue:
        curr = queue.popleft()
        if curr is None:
            continue
        curr_id = id(curr)
        if curr_id in visited:
            continue
        visited.add(curr_id)
        universe.append(curr)

        if hasattr(curr, "__dict__"):
            for val in curr.__dict__.values():
                if val is None or isinstance(val, (int, float, str, bool)):
                    continue
                if isinstance(val, (list, tuple, set)):
                    if id(val) not in visited:
                        universe.append(list(val))
                    for item in val:
                        if item is not None and not isinstance(item, (int, float, str, bool)) and id(item) not in visited:
                            queue.append(item)
                elif id(val) not in visited:
                    queue.append(val)

    return universe


def solve_constraints(universe, predicate, param_names, context_env):
    """
    在候选对象全集中求解满足 predicate 约束的实体组合。
    """
    needed_names = [p for p in param_names if p not in context_env]
    fixed_env = {p: context_env[p] for p in param_names if p in context_env}

    if not needed_names:
        trial = dict(fixed_env)
        try:
            if predicate(**trial):
                return {}
        except Exception:
            return None
        return None

    # 排列组合搜索满足约束的实体解
    for combo in product(universe, repeat=len(needed_names)):
        trial = dict(zip(needed_names, combo))
        trial.update(fixed_env)
        try:
            if predicate(**trial):
                return {p: trial[p] for p in needed_names}
        except Exception:
            continue

    return None


def parse_builtin_operation(text: str, owner=None):
    """
    通用内置操作分发入口。
    基于统一语法 'Command: Arg1, Arg2, ...' 动态拼接映射为对应的 stack_xxx 函数。
    严格执行 @expect(args=..., rules=...) 契约门禁：
    1. 文本参数个数与类型校验；
    2. 未指定实体自动由图谱求解注入；
    3. 全参数按形参名注入调用！
    """
    if not isinstance(text, str):
        return None

    cleaned_text = text.strip()
    if ":" in cleaned_text:
        cmd_part, arg_part = cleaned_text.split(":", 1)
        parsed_vals = parse_args_from_text(arg_part)
    else:
        cmd_part = cleaned_text
        parsed_vals = []

    func_name = "stack_" + cmd_part.strip().lower().replace("-", "_")
    func = globals().get(func_name)
    if func is None:
        raise NotImplementedError(f"未实现的操作指令: {func_name}")

    # 门禁 2：校验文本参数个数与声明的 args 是否绝对一致
    declared_args = getattr(func, "expect_args", [])
    if len(parsed_vals) != len(declared_args):
        raise ValueError(
            f"指令 {func_name} 期望 {len(declared_args)} 个输入参数 {declared_args}，"
            f"实际传入 {len(parsed_vals)} 个: {parsed_vals}"
        )

    # 绑定文本参数
    bound_text_args = dict(zip(declared_args, parsed_vals))
    context_env = {"owner": owner, **bound_text_args}

    # 求解实体参数
    resolved_entities = {}
    rules = getattr(func, "expect_rules", None)
    if rules is not None:
        universe = collect_universe(owner)
        param_names = getattr(func, "rule_param_names", [])
        solved = solve_constraints(universe, rules, param_names, context_env)
        if solved is None:
            raise ValueError(f"无法为函数 {func_name} 解算满足规则约束的实体组合！")
        resolved_entities = solved

    # 合并文本参数与求解出的实体参数，按名字注入调用！
    final_kwargs = {**bound_text_args, **resolved_entities}
    return func(**final_kwargs)


# ALL BUILTIN OPERATIONS
from player.player import Player
from models.opcode import OpCode
from models.card import Card

@expect(
    args=["count"],
    rules=lambda count, target: count > 0 and isinstance(target, Player)
)
def stack_draw_card(count, target):
    return [target, count, OpCode.DRAW]

@expect(
    args=["side", "idx"],
    rules=lambda side, idx, card, owner: isinstance(side, int) and isinstance(idx, int) and card == owner
)
def stack_place_card(side, idx, card):
    return [side, idx, card, OpCode.PLACE]