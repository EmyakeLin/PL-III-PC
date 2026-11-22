"""Author-facing command lines expand into ordinary entry program tokens."""

from inspect import signature
from json import JSONDecoder


class CommandSet:
    def __init__(self):
        self.definitions = {}

    def define(self, name):
        def register(expand):
            if name in self.definitions:
                raise ValueError(f"重复定义词条指令 {name}")
            self.definitions[name] = signature(expand), expand
            return expand
        return register

    def expand(self, line):
        parts = line.split(maxsplit=1)
        if not parts or parts[0] not in self.definitions:
            return None
        name = parts[0]
        operands = parts[1] if len(parts) > 1 else ""
        parameters, expand = self.definitions[name]
        try:
            arguments = parameters.bind(*read_operands(operands))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name}{parameters} 的参数无效：{operands}") from error
        return expand(*arguments.args)


def read_operands(source):
    """Numbers and JSON literals retain their types. Bare $names read the event."""
    decoder = JSONDecoder()
    while source:
        if source[0] in '"[{':
            value, end = decoder.raw_decode(source)
            if end < len(source) and not source[end].isspace():
                raise ValueError("操作数之间需要空格")
            source = source[end:].lstrip()
            yield {"literal": value}
        else:
            parts = source.split(maxsplit=1)
            word, source = parts[0], parts[1] if len(parts) == 2 else ""
            if word.startswith("$"):
                yield word
                continue
            if word.startswith("+") and word[1:].isascii() and word[1:].isdecimal():
                yield int(word)
                continue
            try:
                value, end = decoder.raw_decode(word)
            except ValueError:
                value, end = word, len(word)
            if end != len(word):
                value = word
            yield {"literal": value} if isinstance(value, str) else value


builtins = CommandSet()


def expand_command(line):
    # Builtins use model types. Load their declarations after the VM modules
    # have finished initialising, before resolving the first command line.
    from entry import builtin_operations

    expansion = builtins.expand(line)
    if expansion is not None:
        return expansion
    from models.opcode import OpCode
    from models.opcodes import OPERANDS

    parts = line.split(maxsplit=1)
    if len(parts) != 2 or parts[0] not in OpCode.__members__:
        return None
    opcode = OpCode[parts[0]]
    operands = list(read_operands(parts[1]))
    names = OPERANDS.get(opcode, ())
    if len(operands) != len(names):
        raise ValueError(f"{opcode.name} 需要 {len(names)} 个操作数：{', '.join(names)}")
    return [*operands, opcode]
