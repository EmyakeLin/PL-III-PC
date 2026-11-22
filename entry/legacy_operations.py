"""Printed spellings from earlier packs and their explicit instruction expansions."""
from models.opcode import OpCode


def _team_status(action):
    return [{"literal": ["subject", "status", "amount"]},
            ["$bindings.amount", 0, "GT",
             ["$bindings.subject.player.characters", ["$item.is_alive", action, "WHEN"], "EACH"], "WHEN"],
            "WITH_BINDINGS"]


WORD_ALIASES = {
    "DAMAGE_AMOUNT": [{"call": "DAMAGE", "result": "result", "default": 0}],
    "ACTIVATE_STATUS": [{"call": "ACTIVATE_STATUS", "result": "result", "default": False}],
    "TAKE_HAND_CARD": [{"call": "TAKE_HAND_CARD", "result": "result"}],
    "SPEND_STATUS": [{"call": "SPEND_STATUS", "result": "result", "default": 0}],
    "SPEND_ABILITY_EFFECT": [{"call": "SPEND_ABILITY_EFFECT", "result": "result", "default": 0}],
    "SPEND_STATUS_IN_FULL": [{"call": "SPEND_STATUS", "with": {"require_full": True},
                              "result": "paid_in_full", "default": False}],
    "SPEND_ABILITY_EFFECT_IN_FULL": [{"call": "SPEND_ABILITY_EFFECT", "with": {"require_full": True},
                                      "result": "paid_in_full", "default": False}],
    "TEAM_STATUS": _team_status(["$item", "$bindings.status", "$bindings.amount", "STATUS"]),
    "NEXT_TEAM_STATUS": _team_status(["$bindings.subject", "$item", "$bindings.status",
                                     "$bindings.amount", "QUEUE_STATUS"]),
    "USED_SKILL_THIS_TURN": ["SKILL_USE_COUNT", 0, "GT"],
    "ONCE_PER_ROUND": ["DUP", "$self", "SWAP", "ROUND_TRIGGER_COUNT", 1, "LT", "SWAP",
                       "$self", "SWAP", "RECORD_ROUND_TRIGGER"],
}


def compile_targeted_action(name, data, args):
    from entry.compiler import Field, Program, TargetedProgram, compile_program

    if name == "reveal_lock":
        return compile_program(["placement", "WINDOW_OPEN", "$event.target.state.name", "PLACED_FACE_DOWN", "EQ", "AND",
                                ["SET_CARD_FACE $event.target up", "SET_PLACEMENT_LOCK $event.target true"], "WHEN"])
    default = "self" if name in ("heal", "draw", "draw_card", "discard", "shield") else "target"
    selector = data.get("target")
    target = Field("event.target")
    if name in ("draw", "draw_card", "discard"):
        opcode = OpCode.DISCARD if name == "discard" else OpCode.DRAW
        operands = [Field("event.selected_player"), int(data.get("amount", args[0] if args else 1))]
    elif name in ("heal", "lightcore_damage", "real_damage"):
        opcode = OpCode[name.upper()]
        operands = [target, int(data.get("amount", args[0] if args else 1))]
    elif name == "shield":
        opcode = OpCode.SHIELD
        kind = data.get("kind", args[1] if len(args) > 1 else "normal")
        operands = [target, kind, int(data.get("amount", args[0] if args else 1))]
    elif name == "status":
        opcode = OpCode.STATUS
        status = data.get("name", args[0] if args else None)
        if not status:
            raise ValueError("Status 需要状态名")
        operands = [target, status, int(data.get("amount", args[1] if len(args) > 1 else 1))]
    elif name in ("destroy", "stagger"):
        opcode, operands = OpCode[name.upper()], [target]
        if name == "destroy" and args:
            selector = args[0]
    else:
        return None
    return TargetedProgram(selector, default, Program((*operands, opcode)))
