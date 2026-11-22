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
        if not operands and any(p.default is p.empty for p in parameters.parameters.values()):
            return None  # A bare parameterized word retains its postfix or legacy meaning.
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

    return builtins.expand(line)
