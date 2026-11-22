"""Translate JSON effect programs into blocks for the existing postfix VM."""

from entry.compiler import Access, Effect, Field, Invocation, Local, Program, Word, compile_program
from entry.stack_words import WORDS
from entry.references import read_path
from entry.entry import character_of


def run_program(ctx, entry, tokens):
    from entry.effects import run_effect, select_entity

    actor = character_of(entry.owner)
    if actor is not None and not actor.is_alive:
        return
    player = getattr(actor, "player", None)
    variables = {}

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
        elif root == "skill_target":
            value = event.get("target") or ctx.game.pipeline.resolve_skill_target(event.get("card"))
        else:
            value = event.get(root)
        return read_path(value, path)

    def store_local(vm):
        name = vm.pop()
        variables[name] = vm.pop()

    def damage_add(vm):
        run_effect(vm, entry, {"op": "damage_add", "amount": vm.pop()})

    def bind(program):
        block = []
        for instruction in program.instructions:
            if isinstance(instruction, Program):
                block.append(bind(instruction))
            elif isinstance(instruction, (Access, Invocation)):
                block.append(instruction.execute)
            elif isinstance(instruction, Field):
                block.append(lambda vm, name=instruction.name: vm.push(read(name)))
            elif isinstance(instruction, Local):
                block.append(lambda vm, name=instruction.name: vm.push(variables[name]))
            elif isinstance(instruction, Effect):
                block.append(lambda vm, op=instruction.operation: run_effect(vm, entry, op))
            elif isinstance(instruction, Word):
                if instruction.name == "STORE":
                    block.append(store_local)
                elif instruction.name == "DAMAGE_ADD":
                    block.append(damage_add)
                else:
                    block.append(WORDS[instruction.name])
            else:
                block.append(instruction)
        return block

    program = tokens if isinstance(tokens, Program) else compile_program(tokens)
    with ctx.binding(source=actor or ctx.event.get("source"), authority=entry.authority):
        return execute_program_block(ctx, bind(program))


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
