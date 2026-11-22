"""Compile entry JSON to inspectable instructions, without a game or an owner."""
from dataclasses import dataclass

from entry.commands import expand_command
from entry.field_aliases import FIELD_ALIASES
from entry.legacy_operations import WORD_ALIASES, compile_targeted_action
from models.opcode import OpCode


@dataclass(frozen=True)
class Program:
    instructions: tuple


@dataclass(frozen=True)
class TargetedProgram:
    selector: object
    default: str
    program: Program


@dataclass(frozen=True)
class Field:
    name: str


@dataclass(frozen=True)
class Access:
    path: tuple
    optional: bool = False
    default: object = None

    def execute(self, vm):
        from entry.references import read_path
        entity = vm.pop()
        value = read_path(entity, self.path, missing=self.default) if self.optional else read_path(entity, self.path)
        vm.push(self.default if value is None and self.optional else value)


@dataclass(frozen=True)
class Local:
    name: str


@dataclass(frozen=True)
class Invocation:
    opcode: OpCode
    options: tuple
    result: str | None
    default: object

    def execute(self, vm):
        value = vm.execute_op(self.opcode, result_field=self.result or "result", **dict(self.options))
        if self.result is not None:
            vm.push(self.default if value is None else value)


@dataclass(frozen=True)
class Effect:
    operation: object


@dataclass(frozen=True)
class Word:
    name: str


def compile_program(tokens, *, expand=expand_command):
    from entry.stack_words import WORDS

    def compile_items(items, path):
        if not isinstance(items, (list, tuple)):
            raise ValueError("词条程序需要有序指令列表")
        for token in items:
            if isinstance(token, list):
                yield Program(tuple(compile_items(token, path)))
                continue
            if isinstance(token, dict):
                if "literal" in token:
                    yield token["literal"]
                elif "call" in token:
                    opcode = OpCode[token["call"]]
                    result = token.get("result")
                    if result is not None and not isinstance(result, str):
                        raise ValueError("调用的结果字段需要名称")
                    options = token.get("with", {})
                    if not isinstance(options, dict) or {"result_field", "defer_payment", "opcode", "authority", "execution"} & options.keys():
                        raise ValueError("调用参数不能覆盖执行栈或词条话语权")
                    yield Invocation(opcode, tuple(options.items()), result, token.get("default"))
                elif "field" in token:
                    yield Access(tuple(token["field"].split(".")), "default" in token, token.get("default"))
                elif "local" in token:
                    yield Local(token["local"])
                else:
                    yield Effect(prepare_effect(token))
                continue
            if not isinstance(token, str):
                yield token
                continue
            if token.startswith("$"):
                root, *suffix = token[1:].split(".")
                if any(not part.isidentifier() or part.startswith("_") for part in (root, *suffix)):
                    raise ValueError(f"无效的词条字段 {token!r}")
                if root == "local" and suffix:
                    yield Local(suffix[0])
                    if len(suffix) > 1:
                        yield Access(tuple(suffix[1:]))
                    continue
                body = FIELD_ALIASES.get(root)
                if body is None:
                    yield Field(token[1:])
                    continue
                name = "$" + root
                if suffix:
                    body = [*body, {"field": ".".join(suffix)}]
            elif token in WORD_ALIASES:
                name, body = token, WORD_ALIASES[token]
            elif token in WORDS or token == "STORE":
                yield Word(token)
                continue
            elif token in OpCode.__members__:
                yield OpCode[token]
                continue
            else:
                name = token.split(maxsplit=1)[0] if token.strip() else token
                body = expand(token)
                if body is None:
                    yield token
                    continue
            if name in path:
                raise ValueError("词条指令循环展开：" + " → ".join((*path, name)))
            yield from compile_items(body, (*path, name))

    return Program(tuple(compile_items(tokens, ())))


# Each stage accepts one numeric input and produces one numeric result.
NUMERIC_STAGES = {"damage_multiplier", "final_damage"}
_NUMERIC_RESULTS = {OpCode.ADD: 1, OpCode.SUB: 1, OpCode.MUL: 1, OpCode.FLOOR_DIV: 1,
                    OpCode.MIN: 1, OpCode.CLAMP: 1, OpCode.POP: 0, OpCode.DUP: 2, OpCode.SWAP: 2}


def compile_adjustments(*declarations):
    from models.opcodes import OPERANDS
    stages = {}
    for spec in declarations:
        if spec is None:
            continue
        if not isinstance(spec, dict):
            raise ValueError("数值修正需要阶段与程序的映射")
        for stage, tokens in spec.items():
            if stage not in NUMERIC_STAGES:
                raise ValueError(f"未知的数值修正阶段 {stage!r}")
            program = compile_program(tokens)
            depth = 1
            for instruction in program.instructions:
                if type(instruction) in (int, float) or isinstance(instruction, (Field, Local)):
                    depth += 1
                elif isinstance(instruction, Access) and depth:
                    continue
                elif isinstance(instruction, OpCode) and instruction in _NUMERIC_RESULTS:
                    needed = len(OPERANDS[instruction])
                    if depth < needed:
                        raise ValueError(f"{stage} 的 {instruction.name} 缺少操作数")
                    depth += _NUMERIC_RESULTS[instruction] - needed
                else:
                    raise ValueError(f"{stage} 需要只读数值指令，收到 {instruction!r}")
            if depth != 1:
                raise ValueError(f"{stage} 须留下一个数值")
            stages.setdefault(stage, []).extend(program.instructions)
    return {stage: Program(tuple(code)) for stage, code in stages.items()}


def prepare_effect(operation):
    if isinstance(operation, list) and all(isinstance(item, (str, dict)) for item in operation):
        prepared = [prepare_effect(item) for item in operation]
        if prepared and all(isinstance(item, Program) for item in prepared):
            return Program(tuple(instruction for part in prepared for instruction in part.instructions))
        return prepared
    if isinstance(operation, str):
        expansion = expand_command(operation)
        if expansion is not None:
            return compile_program(expansion)
        from entry.effects import independent_damage_part
        part = independent_damage_part(operation)
        if part:
            amount, opcode = part
            data, args, name = {"amount": amount}, [], opcode.name
        else:
            name, _, operands = operation.partition(":")
            args = [item.strip() for item in operands.split(",") if item.strip()]
            data = {}
    elif isinstance(operation, dict):
        name, args, data = operation["op"], operation.get("args", []), operation
    else:
        return operation

    name = name.lower().strip().replace("-", "_")
    if name == "program":
        if isinstance(data["code"], Program):
            return operation
        return {**data, "code": compile_program(data["code"])}
    return compile_targeted_action(name, data, args) or operation
