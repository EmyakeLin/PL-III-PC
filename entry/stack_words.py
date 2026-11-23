"""Postfix words shared by compiled entry programs."""
from entry.entry import character_of
from models.character import SHIELD_FIELDS


def status_count(vm):
    name, target = vm.pop(), vm.pop()
    vm.push(target.statuses.get(target.canonical_status_name(name), 0) if target is not None else 0)


def status_active(vm):
    name, target = vm.pop(), vm.pop()
    vm.push(target is not None and target.canonical_status_name(name) in target.active_statuses)


def repeat_while(vm):
    action, condition, limit = vm.pop(), vm.pop(), vm.pop()
    for _ in range(limit):
        if vm.executions and vm.executions[-1].cancelled:
            break
        vm.eval_block(condition)
        if (vm.executions and vm.executions[-1].cancelled) or not vm.pop():
            break
        vm.eval_block(action)


def shield_count(vm):
    kind, target = vm.pop(), vm.pop()
    vm.push(getattr(target, SHIELD_FIELDS[kind]))


def skill_use(vm):
    from models.special_actions import SkillUse
    terms, card = vm.pop(), vm.pop()
    vm.push(SkillUse(card, **terms) if isinstance(terms, dict) else SkillUse(card, discount=terms))


def skill_copy(vm):
    from models.special_actions import SkillCopy
    data, owner = vm.pop(), vm.pop()
    vm.push(SkillCopy(owner, data) if data is not None and owner is not None else None)


def blank_skill_face(vm):
    """Keep a face's printed dice and numeric formula, removing its effects and costs."""
    face = vm.pop()
    if face is None:
        vm.push(None)
        return
    dice = []
    for printed in face.get("dice", ()):
        die = {key: printed[key] for key in ("level", "roll_max", "fixed_level", "base_value", "multiplier",
                                              "calc_formula", "calc_fomula") if key in printed}
        die["type"] = "skip" if printed["type"] == "skip" else "blank"
        dice.append(die)
    vm.push(dict(id=face["id"], name=face["name"] + "（空白复制品）", cost=0, dice=dice))


def contains(vm):
    element, collection = vm.pop(), vm.pop()
    vm.push(element in collection)


def insert_at(vm):
    at, entity = vm.pop(), vm.pop()
    vm.push({"at": at, "target": entity})


WORDS = {
    "KEYS": lambda vm: vm.push(tuple(vm.pop())),
    "UNIQUE": lambda vm: vm.push(tuple(dict.fromkeys(vm.pop()))),
    "REPEAT_WHILE": repeat_while,
    "CHARACTER_OF": lambda vm: vm.push(character_of(vm.pop())),
    "STATUS_ACTIVE": status_active,
    "SKILL_USE": skill_use, "SKILL_COPY": skill_copy, "INSERT_AT": insert_at,
    "BLANK_SKILL_FACE": blank_skill_face,
    "CARD_COST": lambda vm: vm.push(vm.pop().cost), "CONTAINS": contains,
    "SHIELD_COUNT": shield_count,
    "STATUS_COUNT": status_count,
}
