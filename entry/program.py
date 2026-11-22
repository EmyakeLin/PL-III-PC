"""Translate JSON effect programs into blocks for the existing postfix VM."""

from entry.commands import expand_command
from entry.field_aliases import FIELD_ALIASES
from entry.references import read_path
from entry.entry import character_of
from models.character import SHIELD_FIELDS
from models.opcode import OpCode


def run_program(ctx, entry, tokens):
    from entry.effects import run_effect, select_entity

    actor = character_of(entry.owner)
    if actor is None or not actor.is_alive:
        return
    player = actor.player
    variables = {}

    def read(field):
        root, *path = field.split(".")
        event = ctx.event
        if root in ("recipient", "recipient_player"):
            entity = select_entity(ctx, entry.target or "self", entry.owner)
            value = getattr(entity, "player", entity) if root == "recipient_player" else entity
        elif root == "self":
            value = actor
        elif root == "player":
            value = player
        elif root == "owner":
            value = entry.owner
        elif root == "game":
            value = ctx.game
        elif root == "event":
            value = event
        elif root == "opponent_player":
            value = next(other for other in ctx.game.players if other is not player)
        elif root in ("skill_target", "target_speed_lead"):
            value = event.get("target") or ctx.game.pipeline.resolve_skill_target(event.get("card"))
            if root == "target_speed_lead":
                value = actor.speed - value.speed if value is not None else 0
        elif root == "target_next_die":
            value = ctx.game.pipeline.next_planned_die(event.get("target"))
        elif root == "own_hand_skills":
            value = ctx.game.special.own_hand_skills(actor)
        elif root == "own_regular_duels":
            value = [slot for slot in ctx.game.duelspace.space if ctx.game.pipeline.can_join(slot)
                     and any(card.character is actor for card in slot.get_content(player.side))]
        elif root == "board_skills":
            value = [card for seat in ctx.game.players for member in seat.characters
                     for card in ctx.game.special.board_skills(member)]
        elif root in ("own_board_skills", "target_board_skills"):
            value = ctx.game.special.board_skills(actor if root == "own_board_skills" else event.get("target"))
        elif root in ("in_duel", "duel_damage_taken"):
            duel = ctx.game.resolving_duel
            value = duel is not None if root == "in_duel" else duel.damage_taken.get(actor, 0) if duel else 0
        elif root == "final_score":
            value = event["die"].get_value()
        elif root == "next_duel_target":
            value = ctx.game.active_duelspace.next_duel_target(player.side)
        elif root == "next_duel_enemy_skills":
            value = ctx.game.active_duelspace.next_duel_enemy_skills(player.side)
        elif root in ("primary_target", "is_primary_target"):
            value = event.get("primary_target", event.get("target"))
            if root == "is_primary_target":
                value = event.get("target") is value
        elif root == "die_owner":
            value = character_of(event.get("die"))
        elif root == "duel_number":
            value = ctx.game.duel_position()[1] + 1
        elif root == "damage_cause":
            value = bool(event.get("damage_cause"))
        else:
            value = event.get(root)
        return read_path(value, path)

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

    def team_status(vm, delayed):
        amount, name, source = vm.pop(), vm.pop(), vm.pop()
        if amount <= 0:
            return
        for member in source.player.characters:
            if member.is_alive:
                if delayed:
                    vm.eval_block([source, member, name, amount, OpCode.QUEUE_STATUS])
                else:
                    vm.eval_block([member, name, amount, OpCode.STATUS])

    def store_local(vm):
        name = vm.pop()
        variables[name] = vm.pop()

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

    def damage_add(vm):
        run_effect(vm, entry, {"op": "damage_add", "amount": vm.pop()})

    def spend(vm):
        vm.push(vm.execute_op(OpCode.SPEND_STATUS) or 0)

    def spend_in_full(vm):
        vm.push(vm.pay_status_cost())

    words = {
        "REPEAT_WHILE": repeat_while, "DUEL_STATUS_LOST": duel_status_lost,
        "CHARACTER_OF": lambda vm: vm.push(character_of(vm.pop())),
        "DAMAGE_AMOUNT": lambda vm: vm.push(vm.execute_op(OpCode.DAMAGE) or 0),
        "DAMAGE_ADD": damage_add,
        "STATUS_ACTIVE": status_active,
        "DIE_STATE": die_state,
        "ACTIVATE_STATUS": lambda vm: vm.push(bool(vm.execute_op(OpCode.ACTIVATE_STATUS))),
        "SKILL_USE": skill_use, "COPY_SKILL": copy_skill, "INSERT_AT": insert_at,
        "CARD_COST": lambda vm: vm.push(vm.pop().cost), "CONTAINS": contains,
        "TAKE_HAND_CARD": lambda vm: vm.push(vm.execute_op(OpCode.TAKE_HAND_CARD)),
        "SHIELD_COUNT": shield_count,
        "STATUS_COUNT": status_count, "ABILITY_COUNT": ability_count, "SPENT_STATUS_COUNT": spent_count,
        "SPEND_ABILITY_EFFECT": lambda vm: vm.push(vm.execute_op(OpCode.SPEND_ABILITY_EFFECT) or 0),
        "SPEND_ABILITY_EFFECT_IN_FULL": lambda vm: vm.push(bool(vm.execute_op(
            OpCode.SPEND_ABILITY_EFFECT, require_full=True, result_field="paid_in_full"))),
        "CHARACTER_STATE": character_state, "SKILL_STATE": skill_state,
        "STORE": store_local, "SPEND_STATUS": spend,
        "FIND_SKILL": find_skill,
        "SPEND_STATUS_IN_FULL": spend_in_full,
        "TEAM_STATUS": lambda vm: team_status(vm, False),
        "NEXT_TEAM_STATUS": lambda vm: team_status(vm, True),
    }

    def compile_block(items):
        block = []
        for token in items:
            if isinstance(token, list):
                block.append(compile_block(token))
            elif isinstance(token, dict) and "local" in token:
                block.append(lambda vm, name=token["local"]: vm.push(variables[name]))
            elif isinstance(token, dict) and "literal" in token:
                block.append(token["literal"])
            elif isinstance(token, dict):
                block.append(lambda vm, operation=token: run_effect(vm, entry, operation))
            elif isinstance(token, str) and token.startswith("$"):
                field = token[1:]
                if field in FIELD_ALIASES:
                    block.extend(compile_block(FIELD_ALIASES[field]))
                else:
                    block.append(lambda vm, name=field: vm.push(read(name)))
            elif token == "USED_SKILL_THIS_TURN":
                block.extend([OpCode.SKILL_USE_COUNT, 0, OpCode.GT])
            elif token == "ONCE_PER_ROUND":
                # Old programs consume a key and receive the pre-record comparison.
                block.extend([OpCode.DUP, actor, OpCode.SWAP, OpCode.ROUND_TRIGGER_COUNT, 1, OpCode.LT,
                              OpCode.SWAP, actor, OpCode.SWAP, OpCode.RECORD_ROUND_TRIGGER])
            elif isinstance(token, str):
                expansion = expand_command(token) if len(token.split(maxsplit=1)) > 1 else None
                if expansion is None:
                    block.append(words.get(token, OpCode.__members__.get(token, token)))
                else:
                    block.extend(compile_block(expansion))
            else:
                block.append(token)
        return block

    with ctx.binding(source=actor, authority=entry.authority):
        return execute_program_block(ctx, compile_block(tokens))


def execute_program_block(ctx, block):
    """Execute a compiled program or its deferred branch at the current stack depth."""
    previous_stack = ctx.stack.copy()
    try:
        result = ctx.eval_block(block)
        if ctx.executions and ctx.executions[-1].cancelled:
            ctx.stack[:] = previous_stack
            return False
        if len(ctx.stack) != len(previous_stack):
            raise ValueError("词条程序结束时操作栈深度发生变化")
        return result
    except Exception:
        ctx.stack[:] = previous_stack
        raise
