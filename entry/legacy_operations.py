"""Printed spellings from earlier packs and their explicit instruction expansions."""
from models.opcode import OpCode


def _team_status(action):
    return [{"literal": ["subject", "status", "amount"]},
            ["$bindings.amount", 0, "GT",
             ["$bindings.subject.player.characters", ["$item.is_alive", action, "WHEN"], "EACH"], "WHEN"],
            "WITH_BINDINGS"]


def _lookup(path):
    return ["SWAP", {"field": path}, "SWAP", 0, "LOOKUP"]


WORD_ALIASES = {
    "COPY_SKILL": [{"literal": ["owner", "id"]}, [
        "$bindings.owner", "$bindings.owner.skills", {"literal": []}, "COALESCE",
        ["$item.id", "$bindings.id", "EQ"], "FILTER", "FIRST",
        {"field": "printed_data", "default": None}, "SKILL_COPY",
    ], "WITH_BINDINGS"],
    "DIE_STATE": _lookup("use_state"), "SKILL_STATE": _lookup("use_state"),
    "CHARACTER_STATE": _lookup("rule_state"), "ABILITY_COUNT": _lookup("ability_effects"),
    "SPENT_STATUS_COUNT": _lookup("use_state.spent_statuses"),
    "DUEL_STATUS_LOST": ["SWAP", {"field": "side"}, "SWAP", "PAIR", "$game.resolving_duel.status_lost",
                         "SWAP", 0, "LOOKUP"],
    "FIND_SKILL": [{"literal": ["holder", "id", "zone"]},
                   ["$bindings.holder.player", "$bindings.zone", "ZONE_CARDS",
                    ["$item.id", "$bindings.id", "EQ", "$item.character", "$bindings.holder", "IS", "AND",
                     "$item.destroyed", "NOT", "AND"], "FILTER", "FIRST"], "WITH_BINDINGS"],
    "DAMAGE_ADD": [{"literal": ["amount"]},
                   ["$event.target", "$active_damage_modifiers", "damage_add", "$bindings.amount", "normal",
                    "ADD_DAMAGE_MODIFIER"], "WITH_BINDINGS"],
    "BOARD_SKILLS_OF": [{"literal": ["holder"]},
                       ["$bindings.holder.is_alive",
                        ["BOARD_SLOTS", ["$item", "$bindings.holder.player.side", "SLOT_CARDS"], "MAP", "FLATTEN",
                         ["$item.character", "$bindings.holder", "IS", "$item.destroyed", "NOT", "AND"], "FILTER"],
                        [{"literal": []}], "IF_ELSE"], "WITH_BINDINGS"],
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


# Earlier packs spell this printed restriction as a single boolean.
HIGHEST_HAND_COST = {
    "capture": {"position": {"rank_of": "$event.card", "in": "$self.player.cardspace.hand.content",
                             "where": [{"left": "$event.item.character", "op": "eq", "right": "$self"}],
                             "by": "$event.item.cost", "descending": True}},
    "deny_when": [{"left": "$event.observed.position", "op": "le", "right": "$event.stacks"}],
}


def skill_use_rules(status):
    if status.get("restrict_highest_hand_cost"):
        yield HIGHEST_HAND_COST
    yield from status.get("skill_use", ())


def keyword_activation_options(data):
    fields = {"adjustments": data.get("adjustments")}
    for old, name in (("multiplier", "activation_multiplier"), ("final_divisor", "activation_final_divisor")):
        if old in data:
            fields[name] = data[old]
    return fields


def normalize_activation_options(fields):
    # Old field names remain observable to listeners on this activation event.
    factor = fields.setdefault("activation_multiplier", 1)
    divisor = fields.setdefault("activation_final_divisor", 1)
    if type(divisor) is not int or divisor < 1:
        raise ValueError("状态发动的最终伤害除数须为正整数")
    rules = dict(fields.get("adjustments") or {})
    if factor != 1:
        rules["damage_multiplier"] = [factor, "MUL", *rules.get("damage_multiplier", ())]
    if divisor != 1:
        rules["final_damage"] = [divisor, "CEIL_DIV", *rules.get("final_damage", ())]
    fields["adjustments"] = rules


def compile_ability_requirements(spec):
    from entry.predicates import compile_when

    conditions = compile_when(spec.get("when", ()), None, None) if spec.get("when") else ()
    if spec.get("requires_draw_pile"):
        conditions += compile_when([{"left": {"field": "$self.player.cardspace.draw.content", "size": True},
                                     "op": "gt", "right": 0}], None, None)
    return conditions


def overflow_followup(batch):
    if "reduce_to" in batch:
        return {"op": "program", "code": ["$targets", [
            "SET_STATUS_OVERFLOW $item $event.status 0",
            "$item.is_alive", [f"CAP_STATUS $item $event.status {batch['reduce_to']}"], "WHEN",
        ], "EACH"]}
    return batch.get("then")


def compile_targeted_action(name, data, args):
    from entry.compiler import Field, Program, TargetedProgram, compile_program

    if name == "place_skill":
        zone = data.get("zone", "out_of_combat")
        card_id = data.get("card_id", args[0] if args else None)
        return compile_program(["$game.active_duelspace.space", "$event.duel", "CONTAINS", [
            "$player", {"literal": zone}, "ZONE_CARDS",
            ["$item.id", {"literal": card_id}, "EQ", "$item.player", "$player", "IS", "AND",
             "$item.character.is_alive", "AND", "$item.destroyed", "NOT", "AND"], "FILTER", "FIRST",
            "DUP", ["$event.duel", "PLACE_IN_DUEL"], ["POP"], "IF_ELSE"], "WHEN"])
    if name == "reveal_lock":
        return compile_program(["placement", "WINDOW_OPEN", "$event.target.state.name", "PLACED_FACE_DOWN", "EQ", "AND",
                                ["SET_CARD_FACE $event.target up", "SET_PLACEMENT_LOCK $event.target true"], "WHEN"])
    if name in ("damage_add", "damage_multiply", "armor"):
        from entry.effects import GRADES
        value = data.get("amount", args[0] if args else 0)
        if isinstance(value, str):
            value = int(value) if value.lstrip("+-").isdecimal() else float(value)
        grade = GRADES[data.get("grade", args[1] if len(args) > 1 else "normal")]
        return compile_program(["$event.target", "$active_damage_modifiers", name, value, grade, "ADD_DAMAGE_MODIFIER"])
    if name in ("roll_add", "roll_set", "base_add", "final_add"):
        amount = int(data.get("amount", args[0] if args else 0))
        die = "$event.target"
        if name in ("base_add", "final_add"):
            tokens = [die, amount, OpCode.DIE_BASE_ADD if name == "base_add" else OpCode.DIE_FINAL_ADD]
        else:
            mode = name.removeprefix("roll_")
            tokens = ["$event.opcode", {"literal": "ROLL"}, "EQ", "$event.timing", "AFTER", "EQ", "AND",
                      "$event.node_id", "on_dice_clash", "EQ", "OR",
                      [die, mode, amount, "UPDATE_ROLL"], [die, mode, amount, "QUEUE_ROLL_UPDATE"], "IF_ELSE"]
        return TargetedProgram(data.get("target"), "die", compile_program(tokens))
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
