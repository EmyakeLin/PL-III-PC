"""Status commands composed from the entry vocabulary."""
from entry.commands import builtins


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
