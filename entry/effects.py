"""Resolve printed damage segments, executable programs and public status keywords."""
import re

from entry.compiler import Program, prepare_effect
from entry.entry import character_of
from models.opcode import OpCode


_DAMAGE_PART = re.compile(r"(\d+)\s*(?:点\s*)?(超穿甲|穿甲|普通|物理)?(?:直伤|伤害)?\Z")
_INDEPENDENT_DAMAGE_PART = re.compile(r"(\d+)\s*(?:点\s*)?(光点|真实)(?:伤害)?\Z")
GRADES = {"普通": "normal", "物理": "normal", "穿甲": "pierce", "超穿甲": "concept", "normal": "normal",
          "pierce": "pierce", "concept": "concept"}
GRADE_RANK = {"normal": 0, "pierce": 1, "concept": 2}
GRADE_NAMES = {"normal": "普通", "pierce": "穿甲", "concept": "超穿甲"}


def damage_part(text):
    match = _DAMAGE_PART.fullmatch(str(text).strip())
    return (int(match[1]), GRADES[match[2] or "普通"]) if match else None


def independent_damage_part(text):
    match = _INDEPENDENT_DAMAGE_PART.fullmatch(str(text).strip())
    if match:
        opcode = OpCode.LIGHTCORE_DAMAGE if match[2] == "光点" else OpCode.REAL_DAMAGE
        return int(match[1]), opcode


def select_entity(ctx, selector, owner):
    if not isinstance(selector, str):
        return selector
    if selector == "self":
        return character_of(owner) or owner
    if selector == "owner":
        return owner
    if selector == "execution":
        return ctx.event.get("execution")
    return ctx.event.get(selector)


def run_effect(ctx, entry, operation):
    """Execute one rule in its triggering event, retaining its actual source."""
    if isinstance(operation, (str, dict)):
        operation = prepare_effect(operation)
    if isinstance(operation, Program):
        from entry.program import run_program
        return run_program(ctx, entry, operation)
    if isinstance(operation, list):
        if all(isinstance(item, (dict, str, Program)) for item in operation):
            for item in operation:
                if ctx.executions and ctx.executions[-1].cancelled:
                    break
                run_effect(ctx, entry, item)
        else:
            ctx.eval_block(operation)
        return
    if callable(operation):
        operation(ctx)
        return
    if isinstance(operation, dict):
        data = operation
    elif isinstance(operation, str):
        data = {"keyword": operation}
    else:
        raise ValueError(f"无效词条操作 {operation!r}")
    name = data.get("op")
    if name == "program":
        from entry.program import run_program
        if "damage_part" in data:
            with ctx.binding(damage_part=data["damage_part"]):
                return run_program(ctx, entry, data["code"])
        return run_program(ctx, entry, data["code"])
    if name == "cancel":
        ctx.cancel_op(entry.authority, frame=ctx.event.get("opcode_frame", -1))
        return
    selector = data.get("target", entry.target or "target")
    target = select_entity(ctx, selector, entry.owner)
    if target is None:
        return
    source = character_of(entry.owner) or ctx.event.get("source")
    if name == "damage":
        amount = int(data["amount"])
        grade = GRADES[data.get("grade", "normal")]
        die = ctx.event.get("die")
        attack_type = data.get("attack_type", getattr(die, "type", "none"))
        fields = {}
        if "credit" in data:
            credited = select_entity(ctx, data["credit"], entry.owner)
            if credited is None or character_of(credited) is not source:
                return
            fields["damage_die"] = credited
        ctx.deal_damage(source, target, amount, grade, attack_type,
                        damage_part=data.get("damage_part", False), **fields)
        return
    # Status packs can publish keywords that invoke their existing settlement
    # rule on a target, with credit for the damage going to the caller.
    for status, rule in getattr(target, "status_rules", {}).items():
        keywords = rule.get("activation", {}).get("keywords", ())
        if data["keyword"] in keywords:
            owner = entry.owner
            if "credit" in data:
                owner = select_entity(ctx, data["credit"], entry.owner)
                if (owner is None or character_of(owner) is not source
                        or ctx.range_blocks_target(target, die=owner if getattr(owner, "card", None) else None)):
                    return
            ctx.stack.extend((target, status))
            return ctx.execute_op(OpCode.ACTIVATE_STATUS, source=source, side=source.player.side,
                                  activation_owner=owner, activation_kind=keywords[0],
                                  adjustments=data.get("adjustments"))
    raise ValueError(f"未知词条关键词 {data['keyword']!r}")
