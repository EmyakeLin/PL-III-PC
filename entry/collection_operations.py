"""Collection recipes usable both as printed commands and as postfix VM blocks."""
from entry.commands import builtins
from models.opcode import OpCode


@builtins.define("RANDOM_ITEM")
def random_item(collection):
    """Sample one index uniformly. An empty collection supplies no item."""
    return [
        collection, OpCode.DUP, OpCode.SIZE, OpCode.DUP, 0, OpCode.GT,
        [1, OpCode.SUB, 0, OpCode.SWAP, OpCode.SAMPLE_INT, None, OpCode.LOOKUP],
        [OpCode.POP, OpCode.POP, None], OpCode.IF_ELSE,
    ]
