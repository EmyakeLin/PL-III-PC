"""Status commands composed from the entry vocabulary."""
from entry.commands import builtins


@builtins.define("TRANSFER_STATUS")
def transfer_status(donor, recipient, status, amount):
    """Move at most amount ordinary stacks and return how many the recipient accepted."""
    giver, receiver, mark, limit = ("$event.bindings." + key for key in ("giver", "receiver", "mark", "limit"))
    debit, accepted = "$event.bindings.debit", "$event.bindings.accepted"
    change = {"call": "STATUS", "result": "actual_delta", "default": 0}
    settle = [
        debit, accepted, "GT", [giver, mark, debit, accepted, "SUB", "STATUS"], "WHEN", accepted,
    ]
    credit = [
        debit, 0, "GT",
        [receiver, mark, debit, change, 0, "MAX", debit, "MIN",
         {"literal": ["accepted"]}, settle, "WITH_BINDINGS"], [0], "IF_ELSE",
    ]
    move = [
        giver, mark, 0, limit, "SUB", change, -1, "MUL", 0, "MAX",
        {"literal": ["debit"]}, credit, "WITH_BINDINGS",
    ]
    return [
        donor, recipient, status, amount, {"literal": ["giver", "receiver", "mark", "limit"]},
        [giver, receiver, "IS", "NOT", "$event.bindings.giver.is_alive", "AND",
         "$event.bindings.receiver.is_alive", "AND", limit, 0, "GT", "AND", move, [0], "IF_ELSE"],
        "WITH_BINDINGS",
    ]


@builtins.define("CAP_STATUS")
def cap_status(holder, status, limit):
    """Remove the excess over the given limit, with one ordinary STATUS action."""
    return [
        holder, status, limit, {"literal": ["holder", "status", "limit"]},
        ["$event.bindings.limit", "$event.bindings.holder", "$event.bindings.status", "STATUS_COUNT", "SUB",
         {"literal": ["delta"]}, [
             "$event.bindings.delta", 0, "LT",
             ["$event.bindings.holder", "$event.bindings.status", "$event.bindings.delta", "STATUS"], "WHEN"
         ], "WITH_BINDINGS"], "WITH_BINDINGS",
    ]
