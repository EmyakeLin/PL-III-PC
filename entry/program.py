"""Translate JSON effect programs into blocks for the existing postfix VM."""

from entry.entry import character_of
from models.character import SHIELD_FIELDS
from models.opcode import OpCode


def run_program(ctx, entry, tokens):
    from entry.effects import run_effect

    actor = character_of(entry.owner)
    if actor is None or not actor.is_alive:
        return
    player = actor.player
    variables = {}

    def read(field):
        event = ctx.event
        if field == "hp":
            return actor.hp
        if field == "original_max_hp":
            return actor.original_max_hp
        if field == "in_turn_end":
            return ctx.game.turn_ending
        if field in ("lightcore_hp", "max_lightcore_hp"):
            return getattr(actor, field)
        if field in ("target_lightcore_hp", "target_max_lightcore_hp"):
            return getattr(event.get("target"), field.removeprefix("target_"), 0)
        if field == "speed_lead":
            return actor.speed - next(other.speed for other in ctx.game.players if other is not player)
        if field == "target_speed_lead":
            target = event.get("target") or ctx.game.pipeline.resolve_skill_target(event.get("card"))
            return actor.speed - target.speed if target is not None else 0
        if field == "printed_min":
            return event["printed_min"]
        if field == "opponent_player":
            return next(other for other in ctx.game.players if other is not player)
        if field == "target_alive":
            return bool(getattr(event.get("target"), "is_alive", False))
        if field == "target_player":
            return getattr(event.get("target"), "player", None)
        if field == "target_next_die":
            return ctx.game.pipeline.next_planned_die(event.get("target"))
        if field == "own_hand_skills":
            return ctx.game.special.own_hand_skills(actor)
        if field == "own_regular_duels":
            return [slot for slot in ctx.game.duelspace.space if ctx.game.pipeline.can_join(slot)
                    and any(card.character is actor for card in slot.get_content(player.side))]
        if field == "target_board_skills":
            return ctx.game.special.board_skills(event.get("target"))
        if field in ("chosen_card", "chosen_slot", "choice_subject"):
            return event.get(field)
        if field == "allies":
            return [member for member in player.characters if member.is_alive]
        if field == "roll_value":
            return event["die"].value
        if field == "roll_max":
            return event["die"].roll_max
        if field == "is_attack":
            return event["die"].is_attack
        if field == "is_repeat":
            return event["die"].is_repeat
        if field == "has_damage_part":
            return event["die"].has_damage_part
        if field == "did_deal_damage":
            return event["die"].did_deal_damage
        if field == "damage_die_is_attack":
            return bool(getattr(event.get("damage_die"), "is_attack", False))
        if field in ("activation_kind", "activation_multiplier", "activation_owner", "activation_origin",
                     "activation_die", "activation_die_type", "damage_card", "damage_status"):
            return event.get(field)
        if field == "clash_result":
            return event["die"].clash_result
        if field in ("hit_index", "hit_mode", "targets", "status", "ability", "status_overflow",
                     "previous_stacks", "current_stacks", "actual_delta"):
            return event.get(field)
        if field in ("in_duel", "duel_damage_taken"):
            duel = ctx.game.resolving_duel
            if field == "in_duel":
                return duel is not None
            return duel.damage_taken.get(actor, 0) if duel is not None else 0
        if field == "value_ref":
            return event["value_ref"]
        if field == "printed_level":
            return event["die"].printed_level.value
        if field == "final_score":
            return event["die"].get_value()
        if field == "clash_score":
            return event["die"].clash_score
        if field == "opponent_clash_score":
            return event["opponent_die"].clash_score
        if field in ("opponent_card", "opponent_die", "combat_window", "clash_difference", "prospective_result"):
            return event.get(field)
        if field in ("amount", "result", "damage_amount", "damage_dealt", "damage_received", "damage_die",
                     "base_amount", "hp_lost",
                     "lightcore_lost", "lightcore_collapsed"):
            return event.get(field)
        if field in ("card", "die", "duel", "target", "play_mode", "replaced_card"):
            return event.get(field)
        if field == "skill_target":
            return event.get("target") or ctx.game.pipeline.resolve_skill_target(event.get("card"))
        if field == "next_duel_target":
            return ctx.game.active_duelspace.next_duel_target(player.side)
        if field == "next_duel_enemy_skills":
            return ctx.game.active_duelspace.next_duel_enemy_skills(player.side)
        if field == "is_primary_target":
            return event.get("target") is event.get("primary_target", event.get("target"))
        if field == "enemies":
            enemy = next(p for p in ctx.game.players if p is not player)
            living = [member for member in enemy.characters if member.is_alive]
            primary = event.get("primary_target", event.get("target"))
            return sorted(living, key=lambda member: member is not primary)
        if field == "self":
            return actor
        if field == "owner":
            return entry.owner
        if field == "own_skills_in_hand":
            regular = [card for card in actor.skills if not card.out_of_combat]
            return bool(regular) and all(card in player.cardspace.hand.content for card in regular)
        if field == "turn_number":
            return ctx.game.turn_number
        if field == "die_type":
            return getattr(event.get("die"), "type", None)
        if field == "die_range":
            return event["die"].effective_range
        if field == "die_owner":
            return character_of(event.get("die"))
        if field == "player":
            return player
        if field == "hand_count":
            return len(player.cardspace.hand.content)
        if field == "previous_hand_count":
            return event["previous_count"]
        if field == "current_hand_count":
            return event["hand_count"]
        if field == "duel_number":
            return ctx.game.duel_position()[1] + 1
        if field == "faster":
            enemy = next(p for p in ctx.game.players if p is not player)
            return player.speed > enemy.speed
        if field == "won_clash":
            return actor.won_clash_this_turn
        if field == "previous_loss":
            return player.lost_clash_in_previous_duel()
        if field == "full_hp":
            return actor.hp >= actor.max_hp
        if field == "repeat_count":
            return sum(die is not None and die.repeat_requested
                       for die in event["card"].instantiated_dice or ())
        if field == "damage_cause":
            return bool(event.get("damage_cause"))
        if field == "self_damage":
            return actor is event.get("target")
        raise ValueError(f"未知的词条字段 ${field}")

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

    def once_per_round(vm):
        key = vm.pop()
        vm.push(key not in actor.round_triggers)
        actor.round_triggers.add(key)

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

    def used_skill_this_turn(vm):
        skill_id, character = vm.pop(), vm.pop()
        vm.push((character, skill_id) in vm.game.used_skill_ids)

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
        "ONCE_PER_ROUND": once_per_round, "STATUS_ACTIVE": status_active,
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
        "USED_SKILL_THIS_TURN": used_skill_this_turn, "FIND_SKILL": find_skill,
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
                block.append(lambda vm, field=token[1:]: vm.push(read(field)))
            elif isinstance(token, str):
                block.append(words.get(token, OpCode.__members__.get(token, token)))
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
