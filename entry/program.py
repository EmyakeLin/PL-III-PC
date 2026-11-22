"""Translate JSON effect programs into blocks for the existing postfix VM."""

from entry.compiler import Access, Effect, Field, Invocation, Local, Program, Word, compile_program
from entry.stack_words import WORDS
from entry.references import read_path
from entry.scheduling import ScheduledProgram
from entry.entry import character_of


def run_program(ctx, entry, tokens):
    from entry.effects import run_effect, select_entity

    actor = character_of(entry.owner)
    if actor is not None and not actor.is_alive:
        return
    player = getattr(actor, "player", None)
    invocation = ctx.executions[-1] if ctx.executions else None
    variables = invocation.variables if invocation is not None and invocation.entry is entry else {}

    def read(field):
        root, *path = field.split(".")
        event = ctx.event
        if root in ("recipient", "recipient_player"):
            entity = select_entity(ctx, entry.target or "self", entry.owner)
            value = getattr(entity, "player", entity) if root == "recipient_player" else entity
        elif root == "self":
            value = actor
        elif root == "player":
            value = player
        elif root == "owner":
            value = entry.owner
        elif root == "game":
            value = ctx.game
        elif root == "event":
            value = event
        else:
            raise ValueError(f"当前事件没有词条字段 ${root}")
        return read_path(value, path)

    def store_local(vm, scope):
        name = vm.pop()
        scope[name] = vm.pop()

    def bind(program, scope):
        block = []
        for instruction in program.instructions:
            if isinstance(instruction, Program):
                block.append(bind(instruction, scope))
            elif isinstance(instruction, ScheduledProgram):
                # Bind each delivery with fresh locals; named captures live on the reservation.
                def push_scheduled(vm, body=instruction.program):
                    vm.push([lambda current: execute_program_block(current, bind(body, {}))])
                block.append(push_scheduled)
            elif isinstance(instruction, (Access, Invocation)):
                block.append(instruction.execute)
            elif isinstance(instruction, Field):
                block.append(lambda vm, name=instruction.name: vm.push(read(name)))
            elif isinstance(instruction, Local):
                block.append(lambda vm, name=instruction.name: vm.push(scope[name]))
            elif isinstance(instruction, Effect):
                block.append(lambda vm, op=instruction.operation: run_effect(vm, entry, op))
            elif isinstance(instruction, Word):
                if instruction.name == "STORE":
                    block.append(lambda vm: store_local(vm, scope))
                else:
                    block.append(WORDS[instruction.name])
            else:
                block.append(instruction)
        return block

    program = tokens if isinstance(tokens, Program) else compile_program(tokens)
    with ctx.binding(source=actor or ctx.event.get("source"), authority=entry.authority):
        return execute_program_block(ctx, bind(program, variables))


def adjusted_value(ctx, stage, value):
    """Apply the current entry's numeric program without exposing the enclosing operand stack."""
    if not ctx.executions:
        return value
    entry = ctx.executions[-1].entry
    program = entry.adjustments.get(stage)
    if program is None:
        return value
    previous = ctx.stack
    ctx.stack = [value]
    try:
        run_program(ctx, entry, program)
        result = ctx.pop()
        if type(result) not in (int, float):
            raise ValueError(f"{stage} 的结果须为数值")
        return result
    finally:
        ctx.stack = previous


def execute_program_block(ctx, block):
    """Execute a compiled program or its deferred branch at the current stack depth."""
    previous_stack = ctx.stack.copy()
    try:
        result = ctx.eval_block(block)
        if ctx.executions and ctx.executions[-1].cancelled:
            ctx.stack[:] = previous_stack
            return False
        if len(ctx.stack) != len(previous_stack):
            raise ValueError("词条程序结束时操作栈深度发生变化")
        return result
    except Exception:
        ctx.stack[:] = previous_stack
        raise
