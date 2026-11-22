"""Postfix words shared by compiled entry programs."""
from entry.entry import character_of
from models.character import SHIELD_FIELDS


def status_count(vm):
    name, target = vm.pop(), vm.pop()
    vm.push(target.statuses.get(target.canonical_status_name(name), 0) if target is not None else 0)


def status_active(vm):
    name, target = vm.pop(), vm.pop()
    vm.push(target is not None and target.canonical_status_name(name) in target.active_statuses)


def duel_status_lost(vm):
    name, side_owner = vm.pop(), vm.pop()
    duel = vm.game.resolving_duel
    vm.push(duel.status_lost.get((side_owner.side, name), 0) if duel is not None else 0)


def repeat_while(vm):
    action, condition, limit = vm.pop(), vm.pop(), vm.pop()
    for _ in range(limit):
        if vm.executions and vm.executions[-1].cancelled:
            break
        vm.eval_block(condition)
        if (vm.executions and vm.executions[-1].cancelled) or not vm.pop():
            break
        vm.eval_block(action)


def ability_count(vm):
    name, target = vm.pop(), vm.pop()
    vm.push(target.ability_effects.get(name, 0) if target is not None else 0)


def shield_count(vm):
    kind, target = vm.pop(), vm.pop()
    vm.push(getattr(target, SHIELD_FIELDS[kind]))


def spent_count(vm):
    name, card = vm.pop(), vm.pop()
    vm.push(card.use_state.get("spent_statuses", {}).get(name, 0))


def skill_state(vm):
    name, card = vm.pop(), vm.pop()
    vm.push(card.use_state.get(name, 0))


def character_state(vm):
    name, actor = vm.pop(), vm.pop()
    vm.push(actor.rule_state.get(name, 0) if actor is not None else 0)


def die_state(vm):
    name, die = vm.pop(), vm.pop()
    vm.push(die.use_state.get(name, 0) if die is not None else 0)


def find_skill(vm):
    zone, skill_id, character = vm.pop(), vm.pop(), vm.pop()
    if zone not in ("hand", "draw", "delayed_discard", "out_of_combat"):
        raise ValueError(f"未知牌区 {zone!r}")
    cards = getattr(character.player.cardspace, zone).content if character is not None else ()
    vm.push(next((card for card in cards if card.id == skill_id
                  and card.character is character and not card.destroyed), None))


def skill_use(vm):
    from models.special_actions import SkillUse
    terms, card = vm.pop(), vm.pop()
    vm.push(SkillUse(card, **terms) if isinstance(terms, dict) else SkillUse(card, discount=terms))


def copy_skill(vm):
    from models.special_actions import SkillCopy
    skill_id, actor = vm.pop(), vm.pop()
    data = next((card.printed_data for card in actor.skills if card.id == skill_id), None) if actor else None
    vm.push(SkillCopy(actor, data) if data is not None else None)


def contains(vm):
    element, collection = vm.pop(), vm.pop()
    vm.push(element in collection)


def insert_at(vm):
    at, entity = vm.pop(), vm.pop()
    vm.push({"at": at, "target": entity})


WORDS = {
    "REPEAT_WHILE": repeat_while, "DUEL_STATUS_LOST": duel_status_lost,
    "CHARACTER_OF": lambda vm: vm.push(character_of(vm.pop())),
    "STATUS_ACTIVE": status_active,
    "DIE_STATE": die_state,
    "SKILL_USE": skill_use, "COPY_SKILL": copy_skill, "INSERT_AT": insert_at,
    "CARD_COST": lambda vm: vm.push(vm.pop().cost), "CONTAINS": contains,
    "SHIELD_COUNT": shield_count,
    "STATUS_COUNT": status_count, "ABILITY_COUNT": ability_count, "SPENT_STATUS_COUNT": spent_count,
    "CHARACTER_STATE": character_state, "SKILL_STATE": skill_state,
    "FIND_SKILL": find_skill,
}
