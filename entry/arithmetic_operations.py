"""Shared arithmetic authoring commands, expressed entirely in entry instructions."""
from entry.commands import builtins


@builtins.define("DIVMOD")
def divide_with_remainder(dividend, divisor):
    """Leave the floor quotient and remainder on the stack, in that order."""
    return [
        dividend, divisor, {"literal": ["dividend", "divisor"]},
        ["$event.bindings.dividend", "$event.bindings.divisor", "FLOOR_DIV", "DUP",
         "$event.bindings.divisor", "MUL", "$event.bindings.dividend", "SWAP", "SUB"],
        "WITH_BINDINGS",
    ]


@builtins.define("CEIL_DIV")
def ceiling_divide():
    """Consume a dividend and divisor. ceil(a / b) equals -floor(-a / b)."""
    return ["SWAP", -1, "MUL", "SWAP", "FLOOR_DIV", -1, "MUL"]
