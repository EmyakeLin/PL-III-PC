"""Compile entry JSON to inspectable instructions, without a game or an owner."""
from dataclasses import dataclass

from entry.commands import expand_command
from entry.field_aliases import FIELD_ALIASES
from models.opcode import OpCode


@dataclass(frozen=True)
class Program:
    instructions: tuple


@dataclass(frozen=True)
class Field:
    name: str


@dataclass(frozen=True)
class Local:
    name: str


@dataclass(frozen=True)
class Effect:
    operation: dict


@dataclass(frozen=True)
class Word:
    name: str


COMPATIBILITY = {
    "USED_SKILL_THIS_TURN": ["SKILL_USE_COUNT", 0, "GT"],
    "ONCE_PER_ROUND": ["DUP", "$self", "SWAP", "ROUND_TRIGGER_COUNT", 1, "LT", "SWAP",
                       "$self", "SWAP", "RECORD_ROUND_TRIGGER"],
}


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
                elif "local" in token:
                    yield Local(token["local"])
                else:
                    yield Effect(prepare_effect(token))
                continue
            if not isinstance(token, str):
                yield token
                continue
            if token.startswith("$"):
                body = FIELD_ALIASES.get(token[1:])
                if body is None:
                    yield Field(token[1:])
                    continue
                name = token
            elif token in COMPATIBILITY:
                name, body = token, COMPATIBILITY[token]
            elif token in WORDS or token in ("STORE", "DAMAGE_ADD"):
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


def prepare_effect(operation):
    if isinstance(operation, list) and all(isinstance(item, (str, dict)) for item in operation):
        return [prepare_effect(item) for item in operation]
    if isinstance(operation, dict) and operation.get("op", "").lower() == "program":
        return {**operation, "code": compile_program(operation["code"])}
    if isinstance(operation, str):
        expansion = expand_command(operation)
        if expansion is not None:
            return compile_program(expansion)
    return operation
