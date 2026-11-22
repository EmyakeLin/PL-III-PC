"""Shared arithmetic authoring commands, expressed entirely in entry instructions."""
from entry.commands import builtins


@builtins.define("DIVMOD")
def divide_with_remainder(dividend, divisor):
    """Leave the floor quotient and remainder on the stack, in that order."""
    return [
        dividend, divisor, {"literal": ["dividend", "divisor"]},
        ["$bindings.dividend", "$bindings.divisor", "FLOOR_DIV", "DUP",
         "$bindings.divisor", "MUL", "$bindings.dividend", "SWAP", "SUB"],
        "WITH_BINDINGS",
    ]
