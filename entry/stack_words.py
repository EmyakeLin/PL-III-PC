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


def contains(vm):
    element, collection = vm.pop(), vm.pop()
    vm.push(element in collection)


def insert_at(vm):
    at, entity = vm.pop(), vm.pop()
    vm.push({"at": at, "target": entity})


WORDS = {
    "REPEAT_WHILE": repeat_while,
    "CHARACTER_OF": lambda vm: vm.push(character_of(vm.pop())),
    "STATUS_ACTIVE": status_active,
    "SKILL_USE": skill_use, "SKILL_COPY": skill_copy, "INSERT_AT": insert_at,
    "CARD_COST": lambda vm: vm.push(vm.pop().cost), "CONTAINS": contains,
    "SHIELD_COUNT": shield_count,
    "STATUS_COUNT": status_count,
}
