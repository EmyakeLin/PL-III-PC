import operator
import random

from entry.entry import Entry, EntryExecution, TriggerType, character_of, kind_of
from entry.effects import GRADE_RANK
from entry.play_conditions import record_hand_play
from entry.program import adjusted_value
from entry.scheduling import schedule_effect
from models.card import Card, CardState
from models.die_response import DieResponse, SkillDieTemplate
from models.duel import DuelSlot
from models.opcode import OpCode


def handle_add(ctx):
    b, a = ctx.pop(), ctx.pop()
    ctx.push(a + b)


def handle_sub(ctx):
    b, a = ctx.pop(), ctx.pop()
    ctx.push(a - b)


def handle_mul(ctx):
    b, a = ctx.pop(), ctx.pop()
    ctx.push(a * b)


def handle_clamp(ctx):
    hi, lo, value = ctx.pop(), ctx.pop(), ctx.pop()
    ctx.push(max(lo, min(hi, value)))


_BINARY_OPERATIONS = {
    OpCode.PAIR: lambda left, right: (left, right), OpCode.IS: operator.is_, OpCode.FLOOR_DIV: operator.floordiv, OpCode.MIN: min,
    OpCode.COALESCE: lambda value, default: default if value is None else value,
    OpCode.ALL_IN: lambda members, collection: all(item in collection for item in members),
    OpCode.LT: operator.lt, OpCode.LE: operator.le, OpCode.GT: operator.gt,
    OpCode.GE: operator.ge, OpCode.EQ: operator.eq, OpCode.AND: lambda a, b: bool(a and b), OpCode.OR: lambda a, b: bool(a or b),
}


def handle_binary(ctx):
    right, left = ctx.pop(), ctx.pop()
    ctx.push(_BINARY_OPERATIONS[ctx.current_op](left, right))


def handle_when(ctx):
    block, condition = ctx.pop(), ctx.pop()
    if condition:
        return ctx.eval_block(block)


def handle_if_else(ctx):
    otherwise, then, condition = ctx.pop(), ctx.pop(), ctx.pop()
    return ctx.eval_block(then if condition else otherwise)


VALUE_RESOLVERS = (OpCode.RESOLVE_DIE_LEVEL, OpCode.RESOLVE_FINAL_SCORE, OpCode.RESOLVE_CLASH_SCORE)


def handle_resolve_value(ctx):
    value, die = ctx.pop(), ctx.pop()
    return die.record_value(ctx.current_op, ctx.event["value_ref"].apply(value))


def handle_range_deficit(ctx):
    value, card = ctx.pop(), ctx.pop()
    card.range_deficit = min(3, max(0, int(ctx.event["value_ref"].apply(value))))
    return card.range_deficit


def handle_value_bound(ctx):
    bound, value_ref = ctx.pop(), ctx.pop()
    if ctx.current_op == OpCode.VALUE_FLOOR:
        value_ref.set_floor(bound)
    else:
        value_ref.set_ceiling(bound)


def _usable_component(component):
    card = getattr(component, "card", component)
    return not component.destroyed and (card is None or (
        not card.destroyed and card.state != CardState.NEGATED
        and (card.character is None or card.character.is_alive)))


def handle_final_add(ctx):
    amount, component = ctx.pop(), ctx.pop()
    if _usable_component(component):
        component.final_bonus += amount
        return component.final_bonus


def handle_die_base_add(ctx):
    amount, die = ctx.pop(), ctx.pop()
    if _usable_component(die):
        die.base_value += amount
        return die.base_value


def handle_skill_level_add(ctx):
    amount, card = ctx.pop(), ctx.pop()
    if _usable_component(card):
        card.level_bonus += amount
        die = ctx.active_dice.get(card.player.side) if card.player else None
        if die is not None and die.card is card:
            die.refresh_resolved_level()
        return card.level_bonus


def handle_die_level_add(ctx):
    amount, die = ctx.pop(), ctx.pop()
    if _usable_component(die):
        die.add_levels(amount)
        return die.level.value


def handle_repeat_die(ctx):
    die = ctx.pop()
    return die.card is not None and _usable_component(die) and die.request_repeat()


def handle_capture_skill_die(ctx):
    position, card = ctx.pop(), ctx.pop()
    ctx.push(SkillDieTemplate.capture(card, position))


def handle_grant_die_response(ctx):
    amount, stage, through_turn, trigger = ctx.pop(), ctx.pop(), ctx.pop(), ctx.pop()
    count, template, holder = ctx.pop(), ctx.pop(), ctx.pop()
    if template is None or not holder.is_alive or count <= 0:
        return False
    holder.reserved_dice.append(DieResponse(template, trigger, count, through_turn, stage, amount))
    return True


def handle_queue_hit(ctx):
    targeted = ctx.current_op == OpCode.QUEUE_TARGET_HIT
    target = ctx.pop() if targeted else None
    origin, mode, die = ctx.pop(), ctx.pop(), ctx.pop()
    if mode not in ("full", "damage_only", "effects_only"):
        raise ValueError(f"未知命中结算方式 {mode!r}")
    if die is not None and die.is_attack and _usable_component(die):
        if targeted and (target is None or not target.is_alive):
            return False
        recipient = target if targeted else die.hit_target
        die.queued_hits.append((mode, origin, recipient) if recipient is not None else (mode, origin))
        return True
    return False


def handle_skip_round(ctx):
    die = ctx.pop()
    pair = ctx.game.pipeline.current_clash_pair
    if pair is not None and die in pair.dice_dict.values():
        pair.skipped = True
        return True
    return False


def handle_unopposed_result(ctx):
    result, die = ctx.pop(), ctx.pop()
    if result not in ("win", "lose", "draw"):
        raise ValueError(f"未知的拼点结果 {result!r}")
    pair = ctx.game.pipeline.current_clash_pair
    if pair is not None and die in pair.dice_dict.values() and not die.destroyed:
        pair.unopposed_results[die] = result
        return True
    return False


def handle_choose_card(ctx):
    specification, candidates = ctx.pop(), ctx.pop()
    return ctx.game.special.choose_card(ctx, candidates, specification)


def handle_insert_skill(ctx):
    anchor, use = ctx.pop(), ctx.pop()
    return ctx.game.special.insert_skill(use, anchor, ctx)


def handle_set_component_state(ctx):
    value, key, component = ctx.pop(), ctx.pop(), ctx.pop()
    if component is not None and _usable_component(component):
        component.use_state[key] = value
        return value


def handle_set_status_overflow(ctx):
    value, name, holder = ctx.pop(), ctx.pop(), ctx.pop()
    if type(value) is not int or value < 0:
        raise ValueError("状态累计溢出量须为非负整数")
    if holder is None:
        return
    name = holder.canonical_status_name(name)
    if value:
        holder.status_overflow[name] = value
    else:
        holder.status_overflow.pop(name, None)
    return value


def handle_set_character_state(ctx):
    value, key, actor = ctx.pop(), ctx.pop(), ctx.pop()
    if actor is not None and actor.is_alive:
        actor.rule_state[key] = value
        return value


def handle_map_or_filter(ctx):
    block, items = ctx.pop(), ctx.pop()
    filtering = ctx.current_op == OpCode.FILTER
    result = []
    for item in tuple(items):
        if ctx.executions and ctx.executions[-1].cancelled:
            break
        surrounding, ctx.stack = ctx.stack, []
        try:
            with ctx.binding(item=item):
                ctx.eval_block(block)
            if ctx.executions and ctx.executions[-1].cancelled:
                break
            if len(ctx.stack) != 1:
                raise ValueError("集合表达式必须产生一个结果")
            value = ctx.pop()
        finally:
            ctx.stack = surrounding
        if not filtering or value:
            result.append(item if filtering else value)
    ctx.push(result)


def handle_lookup(ctx):
    default, key, source = ctx.pop(), ctx.pop(), ctx.pop()
    if source is None:
        ctx.push(default)
        return
    try:
        ctx.push(source[key])
    except (KeyError, IndexError):
        ctx.push(default)


def handle_zone_cards(ctx):
    name, player = ctx.pop(), ctx.pop()
    ctx.push(player.cardspace.zone(name).content if player is not None else ())


def handle_place_in_duel(ctx):
    slot, card = ctx.pop(), ctx.pop()
    space = ctx.game.active_duelspace.space
    if card is not None and slot in space:
        return ctx.game.place_in_duel(card.player.side, card, space.index(slot))
    return False


def handle_slot_cards(ctx):
    side, slot = ctx.pop(), ctx.pop()
    cards = slot.get_content(side) if slot is not None else []
    if ctx.current_op == OpCode.REMAINING_CARDS and slot is not None:
        cards = cards[slot.current_card_index.get(side, 0):]
    ctx.push(cards)


def handle_opponent(ctx):
    player = ctx.pop()
    if player not in ctx.game.players:
        raise ValueError("查询对手需要对局中的一个席位")
    ctx.push(next(other for other in ctx.game.players if other is not player))


def handle_slot_offset(ctx):
    offset, space = ctx.pop(), ctx.pop()
    index = space.current_duel_index + offset
    ctx.push(space.space[index] if 0 <= index < len(space.space) else None)


def handle_skill_restricted(ctx):
    card, character = ctx.pop(), ctx.pop()
    ctx.push(character.skill_restricted(card))


def handle_with_bindings(ctx):
    block, names = ctx.pop(), ctx.pop()
    if (not isinstance(names, (list, tuple))
            or not all(isinstance(name, str) and name.isidentifier() and not name.startswith("_") for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("绑定需要一组互不重复的公开字段名")
    values = [ctx.pop() for _ in names]
    bindings = {**ctx.event.get("bindings", {}), **dict(zip(names, reversed(values)))}
    with ctx.binding(bindings=bindings):
        return ctx.eval_block(block)


def handle_each(ctx):
    action, items = ctx.pop(), ctx.pop()
    for item in tuple(items):
        if ctx.executions and ctx.executions[-1].cancelled:
            break
        with ctx.binding(item=item):
            ctx.eval_block(action)


def handle_publish(ctx):
    fields, name = ctx.pop(), ctx.pop()
    if not isinstance(name, str) or not isinstance(fields, dict):
        raise ValueError("发布事件需要事件名和具名字段")
    ctx.publish(name, fields)


def handle_first_in_order(ctx):
    first, items = ctx.pop(), ctx.pop()
    ctx.push(sorted(items, key=lambda item: item is not first))


def handle_skill_use_count(ctx):
    skill_id, actor = ctx.pop(), ctx.pop()
    ctx.push(ctx.game.turn_history.skill_uses[actor, skill_id])


def handle_clash_count(ctx):
    position, result, subject = ctx.pop(), ctx.pop(), ctx.pop()
    ctx.push(ctx.game.turn_history.clash_count(subject, result, position))


def handle_duel_offset(ctx):
    offset = ctx.pop()
    series, index = ctx.game.duel_position()
    ctx.push((series, index + offset))


def handle_round_trigger_count(ctx):
    key, character = ctx.pop(), ctx.pop()
    ctx.push(character.round_triggers[key])


def handle_record_round_trigger(ctx):
    key, character = ctx.pop(), ctx.pop()
    character.round_triggers[key] += 1


def handle_set_skill_form(ctx):
    key, card = ctx.pop(), ctx.pop()
    if card is not None and _usable_component(card):
        card.set_form(key)


def handle_split_clash(ctx):
    die = ctx.pop()
    pair = ctx.game.pipeline.current_clash_pair
    if pair is not None and die in pair.dice_dict.values():
        pair.split = True


def handle_transfer_remaining_dice(ctx):
    receiving, giving = ctx.pop(), ctx.pop()
    if giving is not None and _usable_component(giving) and _usable_component(receiving):
        receiving.take_remaining_dice(giving)


def handle_take_hand_card(ctx):
    receiver, target = ctx.pop(), ctx.pop()
    if target is None or not target.is_alive or not receiver.is_alive:
        return None
    from entry.collection_operations import random_item
    if target.player is receiver.player:
        return None
    ctx.eval_block(random_item(tuple(target.player.cardspace.hand.content)))
    if ctx.executions and ctx.executions[-1].cancelled:
        return None
    card = ctx.pop()
    if card is not None:
        return ctx.eval_block([target.player, card, receiver, OpCode.TRANSFER_HAND_CARD])


def handle_transfer_hand_card(ctx):
    receiver, card, giver = ctx.pop(), ctx.pop(), ctx.pop()
    if receiver is None or not receiver.is_alive or card is None or card.player is not giver:
        return None
    hand = giver.cardspace.hand
    if card not in hand.content:
        return None
    if card.character is receiver:
        return card
    destination = receiver.player.cardspace.hand
    card.set_controller(receiver)
    if hand is not destination:
        hand.move_card_to(card, destination)
    ctx.record("hand_card_taken", receiver=receiver.combat_name, from_side=giver.side)
    return card


def handle_choose_slot(ctx):
    continuation, candidates, subject = ctx.pop(), ctx.pop(), ctx.pop()
    return ctx.game.special.choose_slot(ctx, subject, candidates, continuation)


def handle_next_turn_duels(ctx):
    amount, target = ctx.pop(), ctx.pop()
    if target.is_alive:
        target.next_turn_duels += amount
        return target.next_turn_duels


def handle_turn_duels_add(ctx):
    amount, target = ctx.pop(), ctx.pop()
    if target.is_alive:
        target.turn_duel_bonus += amount
        return target.max_duels


def handle_turn_cost_add(ctx):
    amount, pool = ctx.pop(), ctx.pop()
    if getattr(pool, "is_alive", True):
        pool.turn_cost_adjustment += max(-pool.available_cost, amount)
        return pool.available_cost


def handle_draw(ctx):
    count, player = ctx.pop(), ctx.pop()
    draw = player.cardspace.draw
    moved = 0
    for _ in range(min(max(0, count), len(draw.content))):
        if not draw.content:
            break
        draw.move_card_to(0, player.cardspace.hand)
        moved += 1
    if moved:
        ctx.record("cards_drawn", side=player.side, count=moved)


def handle_reset_cost(ctx):
    """Replace one team's common and personal budgets and reset the spent counters."""
    personal, common, player = ctx.pop(), ctx.pop(), ctx.pop()
    if common < 0 or personal < 0:
        raise ValueError("费用额度不能为负数")
    ctx.event.update(common=common, personal=personal)
    player.max_cost = common
    player.used_cost = 0
    player.turn_cost_adjustment = 0
    for character in player.characters:
        character.independent_cost = personal
        character.used_independent_cost = 0
        character.turn_cost_adjustment = 0


def handle_pay_cost(ctx):
    """Charge the amount left on the stack after BEFORE PAY_COST, personal funds first."""
    amount, card = ctx.pop(), ctx.pop()
    prepaid = bool(card.use_state.pop("cost_prepaid", False))
    cost = 0 if prepaid else max(0, amount)
    ctx.event.update(amount=cost, prepaid=prepaid)
    player, character = card.player, card.character
    if (character is None or character.player is not player or not character.is_alive
            or character.skill_restricted(card)
            or card.destroyed or card.state == CardState.NEGATED):
        ctx.event["failure_reason"] = "技能当前不可使用"
        return False
    personal = min(cost, max(0, character.available_cost))
    common = cost - personal
    if common > player.available_cost:
        ctx.event["failure_reason"] = f"费用不足（需 {cost}，现有 {personal + max(0, player.available_cost)}）"
        return False
    extra = card.data.get("resource_cost")
    if extra and card.range_deficit < 3:
        ctx.stack.extend((character, extra["status"], extra["amount"]))
        spend = ctx.execute_op(OpCode.SPEND_STATUS, require_full=True, result_field=None)
        if not spend or spend["result"] is None or not spend.get("paid_in_full"):
            status = spend["status"] if spend else extra["status"]
            available = spend.get("available_before") if spend else None
            needed = spend.get("amount") if spend else None
            if isinstance(needed, int) and available is not None and available < needed:
                ctx.event["failure_reason"] = f"{status}不足（需 {needed}，现有 {available}）"
            else:
                ctx.event["failure_reason"] = f"{status}支付受阻"
            return False
        ctx.event["resource_paid"] = {"status": spend["status"], "amount": spend["result"]}
        if not character.is_alive or card.destroyed or card.state == CardState.NEGATED:
            ctx.event["failure_reason"] = "技能当前不可使用"
            return False
        personal = min(cost, max(0, character.available_cost))
        common = cost - personal
        if common > player.available_cost:
            ctx.event["failure_reason"] = f"费用不足（需 {cost}，现有 {personal + max(0, player.available_cost)}）"
            return False
    character.used_independent_cost += personal
    player.used_cost += common
    ctx.event.update(personal_spent=personal, common_spent=common)
    if ctx.event.get("use_discount"):
        ctx.record("discount_used", card=card.name, discount=ctx.event["use_discount"], paid=cost)
    return True


def handle_next_turn_cost(ctx):
    amount, player = ctx.pop(), ctx.pop()
    player.next_turn_common_cost += amount
    return player.next_turn_common_cost


def handle_set_card_face(ctx):
    face, card = ctx.pop(), ctx.pop()
    states = {"up": CardState.PLACED_FACE_UP, "down": CardState.PLACED_FACE_DOWN}
    if face not in states:
        raise ValueError(f"未知卡牌朝向 {face!r}")
    if card.state in states.values() and card.state != states[face]:
        card.state = states[face]
        ctx.record("card_face_changed", card=card.name if face == "up" else None, face=face)


def handle_placement_lock(ctx):
    locked, card = ctx.pop(), ctx.pop()
    if type(locked) is not bool:
        raise ValueError("位置锁定需要布尔值")
    locks = ctx.game.special.locked_cards
    if (card in locks) != locked:
        if locked:
            locks.add(card)
        else:
            locks.discard(card)
        ctx.record("placement_lock", locked=locked,
                   card=card.name if card.state == CardState.PLACED_FACE_UP else None)


def handle_place(ctx):
    card, idx, side = ctx.pop(), ctx.pop(), ctx.pop()
    game = ctx.game
    if idx < 0:
        raise ValueError("交锋索引不能为负")
    if (getattr(card, "destroyed", False) or card.player.side != side
            or not card.character.is_alive or not card.meets_use_requirements()
            or any(card in placed.content.get(side, ()) for placed in game.board_slots())):
        return False
    special = ctx.event.get("special_placement") is card
    if special and (card not in card.player.cardspace.hand.content
                    or not game.special.may_place(card)
                    or game.special.first_open_slot(side) != idx):
        return False
    queued = ctx.event.get("queued_placement") is card
    space = game.duelspace if special or queued else game.active_duelspace
    # Opening a new numbered pre-reveal duel requires a player's attack declaration.
    if space is not game.duelspace and idx >= len(space.space):
        return False
    if special and "place" not in card.data.get("anytime_play", ()):
        owner = card.character
        if not owner.spend_ability_effect(owner.ability_permission("place")):
            return False
        if (not owner.is_alive or card.destroyed or card not in owner.player.cardspace.hand.content
                or owner.used_duels >= owner.max_duels or game.special.first_open_slot(side) != idx):
            return False
    zones = card.player.cardspace
    if card in zones.hand.content:
        record_hand_play(card)
    while idx >= len(space.space):
        space.append_new_duel(DuelSlot(game))
    slot = space.space[idx]
    side_cards = slot.content.get(side, [])
    if (space is game.duelspace and card.character
            and not any(c.character is card.character for c in side_cards if isinstance(c, Card))):
        card.character.used_duels += 1
    slot.add_content(side, card)
    face_up = game.cards_revealed or space is not game.duelspace
    card.state = CardState.PLACED_FACE_UP if face_up else CardState.PLACED_FACE_DOWN
    for zone in (zones.hand, zones.draw, zones.delayed_discard, zones.out_of_combat):
        if card in zone.content:
            zone.remove_card(zone.content.index(card))
            break
    return True


def handle_replace_skill(ctx):
    old_card, card = ctx.pop(), ctx.pop()
    return ctx.game.special.exchange(card, old_card)


def handle_roll_update(ctx):
    amount, mode, die = ctx.pop(), ctx.pop(), ctx.pop()
    if mode not in ("set", "add"):
        raise ValueError(f"未知的掷骰修正 {mode!r}")
    if ctx.current_op == OpCode.QUEUE_ROLL_UPDATE:
        ctx.roll_adjustments.setdefault(die, []).append((mode, amount))
    else:
        die.value = amount if mode == "set" else die.value + amount


def handle_damage_modifier(ctx):
    grade, amount, kind, channel = ctx.pop(), ctx.pop(), ctx.pop(), ctx.pop()
    ctx.pop()  # Subject of the range/authority check.
    if not isinstance(channel, list):
        raise ValueError("修正需要待结算的命中或伤害通道")
    if kind not in ("damage_add", "damage_multiply", "armor") or grade not in GRADE_RANK:
        raise ValueError(f"无效的伤害修正 {kind!r} / {grade!r}")
    channel.append((kind, amount, grade))


def handle_roll(ctx):
    die, bonus, high, low = ctx.pop(), ctx.pop(), ctx.pop(), ctx.pop()
    rng = getattr(ctx.game, "rng", random)
    ctx.stack.extend((die, rng.randint(low, high)))
    rolled = ctx.execute_op(OpCode.RESOLVE_ROLL_VALUE, low=low, high=high)
    if rolled is None:
        ctx.current_op = None
        return
    die.value = max(low, min(high, rolled + bonus))
    for mode, amount in ctx.roll_adjustments.pop(die, ()):
        ctx.eval_block([die, mode, amount, OpCode.UPDATE_ROLL])
    return die.value


def handle_roll_value(ctx):
    value = ctx.pop()
    ctx.pop()
    return value


def handle_defer_remaining_dice(ctx):
    slot, card = ctx.pop(), ctx.pop()
    return ctx.game.pipeline.defer_remaining_dice(card, slot)


def handle_pair_skill_copy(ctx):
    sample, card = ctx.pop(), ctx.pop()
    return ctx.game.pipeline.pair_skill_copy(card, sample)


def handle_move_card(ctx):
    zone, card = ctx.pop(), ctx.pop()
    if zone not in ("hand", "draw", "delayed_discard", "out_of_combat"):
        raise ValueError(f"未知牌区 {zone!r}")
    if card is None or card.destroyed or not card.character.is_alive or ctx.game.special.is_locked(card):
        return False
    zones = card.player.cardspace
    destination = getattr(zones, zone)
    if card in destination.content:
        return False
    for slot in ctx.game.board_slots():
        if slot.remove_card(card):
            ctx.game.pipeline.retire_moved_skill(slot, card)
            if zone == "out_of_combat":
                card.return_to_printed_owner()
                card.player.cardspace.out_of_combat.add_card(card)
            else:
                card.reset_for_draw()
                destination.add_card(card)
            return True
    for pile in (zones.hand, zones.draw, zones.delayed_discard, zones.out_of_combat):
        if card in pile.content:
            if pile is zones.hand and ctx.event["play_from_hand"]:
                record_hand_play(card)
            pile.move_card_to(card, destination)
            return True
    return False


def handle_route_die_attack(ctx):
    target, die = ctx.pop(), ctx.pop()
    if not die.is_attack or not _usable_component(die):
        return False
    die.attack_redirected = True
    die.attack_target = target
    return True


def handle_select_skill_target(ctx):
    card = ctx.pop()
    ctx.push(ctx.game.pipeline.resolve_skill_target(card))


def handle_for_each_target(ctx):
    block, targets = ctx.pop(), ctx.pop()
    primary = ctx.event.get("primary_target", ctx.event.get("target"))
    source, die = ctx.event.get("source"), ctx.event.get("die")
    for target in tuple(targets):
        if (source is not None and not source.is_alive
                or die is not None and not _usable_component(die)
                or ctx.executions and ctx.executions[-1].cancelled):
            break
        live = _usable_component(target) if isinstance(target, Card) else target.is_alive
        if live:
            with ctx.binding(target=target, primary_target=primary):
                ctx.eval_block(block)


def handle_resolve_damage(ctx):
    amount = max(0, int(ctx.pop()))
    target = ctx.pop()
    ctx.stack.extend((target, amount))
    amount = ctx.execute_op(OpCode.FINALIZE_DAMAGE, base_amount=ctx.event["base_amount"])
    if amount is None:
        ctx.current_op = None
        return
    ctx.event.update(amount=amount, damage_amount=amount)
    duel = getattr(ctx.game, "resolving_duel", None)
    if duel is not None and len(ctx.op_stack) > 1 and ctx.op_stack[-2] == OpCode.DAMAGE:
        duel.damage_taken[target] = duel.damage_taken.get(target, 0) + amount
        ctx.event["duel"] = duel
    return amount


def handle_finalize_damage(ctx):
    amount = ctx.pop()
    ctx.pop()  # target
    final = max(0, int(ctx.event["value_ref"].apply(amount)))
    final = max(0, int(adjusted_value(ctx, "final_damage", final)))
    if ctx.executions and ctx.executions[-1].cancelled:
        ctx.current_op = None
        return
    ctx.event.update(amount=final, damage_amount=final)
    return final


def handle_mark_damage_dealt(ctx):
    die = ctx.pop()
    die.did_deal_damage = True


def handle_check_death(ctx):
    target = ctx.pop()
    if target.is_alive and target.hp == 0:
        target._die()
        return True
    return False


def handle_random_int(ctx):
    high, low = ctx.pop(), ctx.pop()
    roll = ctx.game.rng.randint(low, high)
    if ctx.current_op == OpCode.RANDOM_INT:
        source = ctx.event.get("source")
        ctx.record("random_check", source=getattr(source, "combat_name", None), low=low, high=high, roll=roll)
    ctx.push(roll)


def damage_adjustments(modifiers, grade, multiplier):
    fixed = 0
    for kind, value, defense_grade in modifiers:
        reduction = (kind == "armor" or kind == "damage_add" and value < 0
                     or kind == "damage_multiply" and value < 1)
        if reduction and GRADE_RANK[defense_grade] < GRADE_RANK[grade]:
            continue
        if kind == "damage_multiply":
            multiplier *= value
        else:
            fixed += -value if kind == "armor" else value
    return multiplier, fixed


def handle_damage_status(ctx):
    factor, grade = ctx.pop(), ctx.pop()
    ctx.pop()
    ctx.pop()
    if grade not in GRADE_RANK or not isinstance(factor, (int, float)) or factor < 0:
        raise ValueError("状态伤害修正需要有效的伤害等级与非负倍率")
    ctx.event["penetration"] = grade
    return factor


def handle_damage(ctx):
    attack_type, grade, amount, target = ctx.pop(), ctx.pop(), ctx.pop(), ctx.pop()
    if target == "target":
        target = ctx.event.get("target")
    if target is None or not target.is_alive:
        ctx.current_op = None
        return None
    source = ctx.event.get("source")
    ctx.event["base_amount"] = amount
    precomputed = ctx.event["damage_precomputed"]
    modifiers = () if precomputed else ctx.event["modifiers"]
    status_factor = 1
    suppressed = []
    for name in tuple(target.statuses):
        factor = target.status_rules.get(name, {}).get("incoming_damage_multiplier")
        if factor is None or precomputed:
            continue
        multiplier, fixed = damage_adjustments(modifiers, grade, status_factor)
        preview = max(0, int(amount * adjusted_value(ctx, "damage_multiplier", multiplier) + fixed))
        ctx.stack.extend((target, name, grade, factor))
        receipt = ctx.execute_op(OpCode.RESOLVE_DAMAGE_STATUS, result_field=None, incoming=preview)
        if receipt is None or receipt["result"] is None:
            suppressed.append(name)
        else:
            grade = receipt["penetration"]
            status_factor *= receipt["result"]
    ctx.event.update(suppressed_damage_statuses=suppressed, penetration=grade)
    multiplier, fixed = damage_adjustments(modifiers, grade, status_factor)
    if not precomputed:
        multiplier = adjusted_value(ctx, "damage_multiplier", multiplier)
        if ctx.executions and ctx.executions[-1].cancelled:
            ctx.current_op = None
            return
    proposed = max(0, int(amount * multiplier + fixed))
    ctx.stack.extend((target, proposed))
    damage = ctx.execute_op(OpCode.RESOLVE_DAMAGE, base_amount=amount)
    if damage is None or not target.is_alive or (ctx.executions and ctx.executions[-1].cancelled):
        ctx.current_op = None
        return None
    ctx.event["damage_multiplier"] = multiplier
    hp_lost = target.apply_resolved_damage(damage, grade)
    ctx.event.update(amount=damage, damage_amount=damage, hp_lost=hp_lost,
                     damage_dealt=True, damage_received=damage > 0)
    damage_die = ctx.event["damage_die"]
    if damage_die is not None:
        damage_die.did_deal_damage = True
    ctx.record("direct_damage", source=ctx.event.get("damage_cause") or getattr(source, "combat_name", None),
               target=target.combat_name, amount=damage, grade=grade, lost=hp_lost, hp=target.hp,
               maximum=target.max_hp, alive=target.is_alive)
    if ctx.event.get("damage_part") and target.is_alive:
        target.after_damage_part()
    return damage


def handle_heal(ctx):
    amount, target = ctx.pop(), ctx.pop()
    actual = target.heal(amount)
    if actual:
        ctx.record("healed", target=target.combat_name, amount=actual, hp=target.hp,
                   maximum=target.max_hp, alive=target.is_alive)
    return actual


def handle_lightcore_damage(ctx):
    amount, target = max(0, int(ctx.pop())), ctx.pop()
    if target == "target":
        target = ctx.event.get("target")
    if target is None or not target.is_alive:
        ctx.current_op = None
        return
    lost = min(target.lightcore_hp, amount)
    target.lightcore_hp -= lost
    collapsed = lost > 0 and target.lightcore_hp == 0
    ctx.event.update(amount=amount, lightcore_lost=lost, lightcore_collapsed=collapsed)
    ctx.record("lightcore_damage", source=getattr(ctx.event.get("source"), "combat_name", None),
               target=target.combat_name, amount=amount, lost=lost,
               hp=target.lightcore_hp, maximum=target.max_lightcore_hp)
    if collapsed:
        # This whole segment has been consumed. A subsequent segment sees the new pool.
        ctx.record("lightcore_collapse", target=target.combat_name)
        with ctx.binding(source=target, damage_cause="光点形态群崩塌"):
            ctx.eval_block([target, (target.original_max_hp + 1) // 2, OpCode.REAL_DAMAGE])
        target.max_lightcore_hp = max(0, target.max_lightcore_hp - 4)
        target.lightcore_hp = target.max_lightcore_hp
        ctx.record("lightcore_restored", target=target.combat_name, hp=target.lightcore_hp,
                   maximum=target.max_lightcore_hp)
    return amount


def handle_real_damage(ctx):
    amount, target = max(0, int(ctx.pop())), ctx.pop()
    if target == "target":
        target = ctx.event.get("target")
    if target is None or not target.is_alive:
        ctx.current_op = None
        return
    lost = target.lose_hp(amount)
    if not target.is_alive and ctx.game.is_over:
        ctx.close_combat_effects()
    ctx.event.update(amount=amount, hp_lost=lost)
    ctx.record("real_damage", source=ctx.event.get("damage_cause") or getattr(ctx.event.get("source"), "combat_name", None),
               target=target.combat_name, amount=amount, lost=lost, hp=target.hp, maximum=target.max_hp, alive=target.is_alive)
    return amount


def handle_lose_hp(ctx):
    amount, target = ctx.pop(), ctx.pop()
    lost = target.lose_hp(amount)
    ctx.event["hp_lost"] = lost
    if lost:
        ctx.record("hp_lost", target=target.combat_name, lost=lost, hp=target.hp,
                   maximum=target.max_hp, alive=target.is_alive)
    return lost


def handle_hit(ctx):
    target, die = ctx.pop(), ctx.pop()
    return ctx.execute_hit_parts(die, target)


def handle_shield(ctx):
    amount, kind, target = ctx.pop(), ctx.pop(), ctx.pop()
    total = target.add_shield(kind, amount)
    ctx.record("shield_changed", target=target.combat_name, shield=kind, total=total)
    return total


def handle_activate_status(ctx):
    name, target = ctx.pop(), ctx.pop()
    spec = target.status_rules.get(name, {}).get("activation") if target is not None else None
    if not (spec and target.is_alive and target.statuses.get(name) and name not in target.activating_statuses):
        ctx.current_op = None
        return
    owner = ctx.event.get("activation_owner") or target
    origin = ctx.event["activation_origin"]
    status_name = None
    if origin == "status":
        status_name = ctx.executions[-1].entry.status_name if ctx.event.get("activation_owner") else name
    entry = Entry(owner, TriggerType.PIPELINE, "activate_status", spec["operation"],
                  origin=origin, damage_cause=spec.get("label", name), status_name=status_name,
                  adjustments=spec.get("adjustments"), call_adjustments=ctx.event["adjustments"])
    target.activating_statuses.add(name)
    try:
        source = character_of(owner)
        if ctx.event.get("activation_kind"):
            ctx.record("status_activated", source=source.combat_name, origin=origin, status=status_name,
                       card=owner.card.name if origin == "die" else getattr(owner, "name", None),
                       position=getattr(owner, "position", None), target=target.combat_name,
                       effect=entry.damage_cause, count=target.statuses[name])
        with ctx.binding(source=source, target=target, side=source.player.side, damage_part=False,
                         hit_modifiers=(), activation_entry=entry):
            if not ctx._invoke(entry):
                ctx.current_op = None
                return
            if spec.get("remove_after"):
                if target.is_alive:
                    ctx.eval_block([target, name, "all", OpCode.SPEND_STATUS])
                else:
                    target.clear_status(name)
        return True
    finally:
        target.activating_statuses.remove(name)


def handle_ability_effect(ctx):
    amount, name, target = ctx.pop(), ctx.pop(), ctx.pop()
    if not target.is_alive:
        ctx.current_op = None
        return None
    old = target.ability_effects.get(name, 0)
    ctx.event["amount"] = amount
    if ctx.current_op == OpCode.SPEND_ABILITY_EFFECT:
        paid = amount if amount > 0 and old >= amount else 0
        if not paid and ctx.event["require_full"]:
            ctx.current_op = None
            return 0
        total = target.apply_ability_delta(name, -paid)
        ctx.event.update(previous_stacks=old, current_stacks=total, actual_delta=-paid, paid_in_full=paid > 0)
        if paid:
            ctx.record("ability_spent", target=target.combat_name, name=name, amount=paid, total=total)
        return paid
    total = target.apply_ability_delta(name, amount)
    ctx.event.update(previous_stacks=old, current_stacks=total, actual_delta=total - old)
    ctx.record("ability_changed", target=target.combat_name, name=name, total=total)
    return total


def handle_status(ctx):
    amount, name, target = ctx.pop(), ctx.pop(), ctx.pop()
    if target is None or not target.is_alive:
        ctx.current_op = None
        return
    proposed = ctx.event["amount"]
    ctx.event["amount"] = amount
    old = target.statuses.get(name, 0)
    total = target.apply_status_delta(name, amount, notify=False)
    cap = target.status_cap(name)
    overflow = max(0, old + amount - cap) if cap is not None and target.is_alive else 0
    ctx.event.update(previous_stacks=old, current_stacks=total, actual_delta=total-old,
                     status_overflow=overflow)
    if amount == 0 and isinstance(proposed, (int, float)) and proposed > 0:
        ctx.record("status_blocked", target=target.combat_name, name=name)
    else:
        ctx.record("status_changed", target=target.combat_name, name=name, previous=old, total=total)
    target.notify_status_change(name, old, total)
    return total


def handle_spend_status(ctx):
    """Apply a spend after price modifiers, preserving the balance on a failed conditional payment."""
    requested, name, target = ctx.pop(), ctx.pop(), ctx.pop()
    balance = target.spendable_status(name)
    ctx.event.update(status=name, amount=requested, paid_in_full=False, available_before=balance)
    require_full = ctx.event["require_full"]
    if requested == "all" and balance and not target.is_alive and not require_full:
        target.clear_status(name)
        ctx.event["paid_in_full"] = True
        ctx.record("status_cleared", target=target.combat_name, name=name, amount=balance)
        return balance
    cost = balance if requested == "all" else requested
    if (not target.is_alive or not balance or not isinstance(cost, int) or cost <= 0
            or (require_full and balance < cost)):
        if require_full:
            ctx.current_op = None
        return 0
    paid = min(cost, balance)
    previous = target.statuses.get(name, 0)
    deferred = ctx.event["defer_spend_effects"]
    remaining = target.apply_status_delta(name, -paid, notify=False, defer_effects=deferred)
    ctx.event.update(paid_in_full=paid == cost, previous_stacks=previous, current_stacks=remaining)
    ctx.record("status_spent", target=target.combat_name, name=name, amount=paid, cost=cost, total=remaining)
    if not deferred:
        target.notify_status_change(name, previous, remaining)
    return paid


def handle_stagger(ctx):
    return ctx.pop().trigger_stagger()


def handle_destroy(ctx):
    target = ctx.pop()
    if target is None:
        return False
    if isinstance(target, EntryExecution):
        # A contradictory protection can intercept DESTROY before it executes.
        target.cancelled = True
    elif isinstance(target, Card):
        if not target.destroyed:
            ctx.record("card_destroyed", card=target.name)
        target.destroyed = True
        target.state = CardState.NEGATED
    elif hasattr(target, "card") and hasattr(target, "roll"):
        if not target.destroyed:
            ctx.record("die_destroyed", position=getattr(target, "position", None))
            target.keep_position = ctx.event.get("keep_position", False)
        target.destroyed = True
    else:
        raise ValueError("摧毁只能作用于技能、骰子或一次词条执行")
    return True


def handle_discard(ctx):
    card, player = ctx.pop(), ctx.pop()
    hand = player.cardspace.hand
    if card is not None and not isinstance(card, Card):
        raise ValueError("弃置对象必须是实体手牌")
    if card is not None and card in hand.content:
        hand.move_card_to(card, player.cardspace.delayed_discard)
        return card


DISPATCH_TABLE = {
    OpCode.PUBLISH: handle_publish,
    OpCode.SAMPLE_INT: handle_random_int,
    OpCode.TRANSFER_HAND_CARD: handle_transfer_hand_card,
    OpCode.SET_STATUS_OVERFLOW: handle_set_status_overflow,
    OpCode.UPDATE_ROLL: handle_roll_update, OpCode.QUEUE_ROLL_UPDATE: handle_roll_update,
    OpCode.ADD_DAMAGE_MODIFIER: handle_damage_modifier,
    OpCode.WINDOW_OPEN: lambda ctx: ctx.push(ctx.game.special.window_open(ctx.pop())),
    OpCode.SET_CARD_FACE: handle_set_card_face, OpCode.SET_PLACEMENT_LOCK: handle_placement_lock,
    OpCode.WITH_BINDINGS: handle_with_bindings,
    OpCode.FILTER: handle_map_or_filter, OpCode.MAP: handle_map_or_filter,
    OpCode.FLATTEN: lambda ctx: ctx.push([item for group in ctx.pop() for item in group]),
    OpCode.FIRST: lambda ctx: ctx.push(next(iter(ctx.pop()), None)), OpCode.LOOKUP: handle_lookup,
    OpCode.OPPONENT: handle_opponent,
    OpCode.BOARD_SLOTS: lambda ctx: ctx.push(tuple(ctx.game.board_slots())),
    OpCode.ZONE_CARDS: handle_zone_cards, OpCode.PLACE_IN_DUEL: handle_place_in_duel,
    OpCode.SLOT_CARDS: handle_slot_cards, OpCode.REMAINING_CARDS: handle_slot_cards,
    OpCode.SLOT_AT_OFFSET: handle_slot_offset, OpCode.SKILL_RESTRICTED: handle_skill_restricted,
    OpCode.CAN_JOIN_DUEL: lambda ctx: ctx.push(ctx.game.pipeline.can_join(ctx.pop())),
    OpCode.NEXT_PLANNED_DIE: lambda ctx: ctx.push(ctx.game.pipeline.next_planned_die(ctx.pop())),
    OpCode.DIE_VALUE: lambda ctx: ctx.push(ctx.pop().get_value()),
    OpCode.SIZE: lambda ctx: ctx.push(len(ctx.pop())),
    OpCode.EACH: handle_each, OpCode.FIRST_IN_ORDER: handle_first_in_order,
    OpCode.SKILL_USE_COUNT: handle_skill_use_count, OpCode.CLASH_COUNT: handle_clash_count,
    OpCode.DUEL_OFFSET: handle_duel_offset,
    OpCode.ROUND_TRIGGER_COUNT: handle_round_trigger_count,
    OpCode.RECORD_ROUND_TRIGGER: handle_record_round_trigger,
    OpCode.CAPTURE_SKILL_DIE: handle_capture_skill_die, OpCode.GRANT_DIE_RESPONSE: handle_grant_die_response,
    OpCode.ACTIVATE_STATUS: handle_activate_status, OpCode.SET_DIE_STATE: handle_set_component_state,
    OpCode.SET_CHARACTER_STATE: handle_set_character_state,
    OpCode.CHOOSE_CARD: handle_choose_card, OpCode.INSERT_SKILL: handle_insert_skill,
    OpCode.QUEUE_HIT: handle_queue_hit, OpCode.SKIP_ROUND: handle_skip_round,
    OpCode.QUEUE_TARGET_HIT: handle_queue_hit, OpCode.SET_UNOPPOSED_RESULT: handle_unopposed_result,
    OpCode.SCHEDULE_EFFECT: schedule_effect,
    OpCode.SET_SKILL_FORM: handle_set_skill_form, OpCode.SPLIT_CLASH: handle_split_clash,
    OpCode.TRANSFER_REMAINING_DICE: handle_transfer_remaining_dice,
    OpCode.DEFER_REMAINING_DICE: handle_defer_remaining_dice, OpCode.RESOLVE_ROLL_VALUE: handle_roll_value,
    OpCode.PAIR_SKILL_COPY: handle_pair_skill_copy, OpCode.RESOLVE_DAMAGE_STATUS: handle_damage_status,
    OpCode.TAKE_HAND_CARD: handle_take_hand_card, OpCode.CHOOSE_SLOT: handle_choose_slot,
    OpCode.CHECK_DEATH: handle_check_death, OpCode.RANDOM_INT: handle_random_int,
    OpCode.RESOLVE_DAMAGE: handle_resolve_damage, OpCode.FINALIZE_DAMAGE: handle_finalize_damage,
    OpCode.MARK_DAMAGE_DEALT: handle_mark_damage_dealt,
    OpCode.RESOLVE_RANGE_DEFICIT: handle_range_deficit,
    OpCode.LOSE_HP: handle_lose_hp, OpCode.TURN_COST_ADD: handle_turn_cost_add,
    OpCode.TURN_DUELS_ADD: handle_turn_duels_add,
    **dict.fromkeys(VALUE_RESOLVERS, handle_resolve_value),
    OpCode.VALUE_FLOOR: handle_value_bound, OpCode.VALUE_CEILING: handle_value_bound,
    **dict.fromkeys(_BINARY_OPERATIONS, handle_binary),
    OpCode.ADD: handle_add, OpCode.SUB: handle_sub, OpCode.MUL: handle_mul,
    OpCode.NOT: lambda ctx: ctx.push(not ctx.pop()), OpCode.WHEN: handle_when, OpCode.IF_ELSE: handle_if_else,
    OpCode.CLAMP: handle_clamp, OpCode.DUP: lambda ctx: ctx.dup(),
    OpCode.POP: lambda ctx: ctx.pop(), OpCode.SWAP: lambda ctx: ctx.swap(),
    OpCode.EVAL: lambda ctx: ctx.eval_block(ctx.pop()),
    OpCode.DRAW: handle_draw, OpCode.PLACE: handle_place, OpCode.ROLL: handle_roll,
    OpCode.REPLACE_SKILL: handle_replace_skill,
    OpCode.MOVE_CARD: handle_move_card, OpCode.ROUTE_DIE_ATTACK: handle_route_die_attack,
    OpCode.SELECT_SKILL_TARGET: handle_select_skill_target,
    OpCode.FOR_EACH_TARGET: handle_for_each_target,
    OpCode.RESET_COST: handle_reset_cost, OpCode.PAY_COST: handle_pay_cost,
    OpCode.NEXT_TURN_COST: handle_next_turn_cost,
    OpCode.SKILL_FINAL_ADD: handle_final_add, OpCode.SKILL_LEVEL_ADD: handle_skill_level_add,
    OpCode.DIE_FINAL_ADD: handle_final_add, OpCode.DIE_LEVEL_ADD: handle_die_level_add,
    OpCode.DIE_BASE_ADD: handle_die_base_add,
    OpCode.REPEAT_DIE: handle_repeat_die, OpCode.NEXT_TURN_DUELS: handle_next_turn_duels,
    OpCode.SET_SKILL_STATE: handle_set_component_state,
    OpCode.DAMAGE: handle_damage, OpCode.LIGHTCORE_DAMAGE: handle_lightcore_damage,
    OpCode.REAL_DAMAGE: handle_real_damage, OpCode.HEAL: handle_heal, OpCode.SHIELD: handle_shield,
    OpCode.RESOLVE_HIT: handle_hit, OpCode.CLASH: lambda ctx: ctx.pop().clash_check(),
    OpCode.STATUS: handle_status, OpCode.STAGGER: handle_stagger,
    OpCode.SPEND_STATUS: handle_spend_status,
    OpCode.ABILITY_EFFECT: handle_ability_effect, OpCode.SPEND_ABILITY_EFFECT: handle_ability_effect,
    OpCode.DESTROY: handle_destroy, OpCode.DISCARD: handle_discard,
}

# Names follow stack order so pre/post listeners can inspect explicit action operands.
OPERANDS = {
    OpCode.PUBLISH: ("name", "fields"),
    OpCode.SAMPLE_INT: ("low", "high"),
    OpCode.TRANSFER_HAND_CARD: ("giver", "card", "receiver"),
    OpCode.SET_STATUS_OVERFLOW: ("target", "status", "amount"),
    OpCode.UPDATE_ROLL: ("die", "mode", "amount"), OpCode.QUEUE_ROLL_UPDATE: ("die", "mode", "amount"),
    OpCode.ADD_DAMAGE_MODIFIER: ("target", "channel", "kind", "amount", "grade"),
    OpCode.WINDOW_OPEN: ("window",), OpCode.SET_CARD_FACE: ("card", "face"),
    OpCode.SET_PLACEMENT_LOCK: ("card", "locked"), OpCode.WITH_BINDINGS: ("names", "block"),
    OpCode.MAP: ("collection", "expression"), OpCode.FLATTEN: ("collection",), OpCode.FIRST: ("collection",),
    OpCode.LOOKUP: ("collection", "key", "default"), OpCode.OPPONENT: ("seat",), OpCode.BOARD_SLOTS: (),
    OpCode.ZONE_CARDS: ("seat", "zone"), OpCode.PLACE_IN_DUEL: ("card", "slot"),
    OpCode.SLOT_CARDS: ("slot", "side"), OpCode.REMAINING_CARDS: ("slot", "side"),
    OpCode.SLOT_AT_OFFSET: ("space", "offset"), OpCode.SKILL_RESTRICTED: ("holder", "skill"),
    OpCode.CAN_JOIN_DUEL: ("slot",), OpCode.NEXT_PLANNED_DIE: ("holder",), OpCode.DIE_VALUE: ("component",),
    OpCode.SIZE: ("collection",), OpCode.FILTER: ("collection", "predicate"),
    OpCode.EACH: ("collection", "block"), OpCode.FIRST_IN_ORDER: ("collection", "first"),
    OpCode.SKILL_USE_COUNT: ("actor", "skill_id"), OpCode.CLASH_COUNT: ("subject", "outcome", "position"),
    OpCode.DUEL_OFFSET: ("offset",),
    OpCode.ROUND_TRIGGER_COUNT: ("character", "key"),
    OpCode.RECORD_ROUND_TRIGGER: ("character", "key"),
    OpCode.CAPTURE_SKILL_DIE: ("card", "position"),
    OpCode.GRANT_DIE_RESPONSE: ("target", "template", "count", "trigger", "through_turn", "spend_on", "spend_amount"),
    OpCode.ACTIVATE_STATUS: ("target", "status"), OpCode.SET_DIE_STATE: ("die", "key", "value"),
    OpCode.SET_CHARACTER_STATE: ("target", "key", "value"),
    OpCode.CHOOSE_CARD: ("candidates", "specification"), OpCode.INSERT_SKILL: ("use", "anchor"),
    OpCode.QUEUE_HIT: ("die", "mode", "origin"), OpCode.SKIP_ROUND: ("die",),
    OpCode.QUEUE_TARGET_HIT: ("die", "mode", "origin", "target"),
    OpCode.SET_UNOPPOSED_RESULT: ("die", "result_value"),
    OpCode.SCHEDULE_EFFECT: ("source", "target", "capture", "terms", "block"),
    OpCode.SET_SKILL_FORM: ("card", "form"), OpCode.SPLIT_CLASH: ("die",),
    OpCode.TRANSFER_REMAINING_DICE: ("target", "receiving_card"),
    OpCode.DEFER_REMAINING_DICE: ("card", "slot"), OpCode.RESOLVE_ROLL_VALUE: ("die", "value"),
    OpCode.PAIR_SKILL_COPY: ("card", "sample"),
    OpCode.RESOLVE_DAMAGE_STATUS: ("target", "status", "penetration", "factor"),
    OpCode.TAKE_HAND_CARD: ("target", "receiver"), OpCode.CHOOSE_SLOT: ("subject", "candidates", "continuation"),
    OpCode.CHECK_DEATH: ("target",), OpCode.RANDOM_INT: ("low", "high"),
    OpCode.RESOLVE_DAMAGE: ("target", "amount"), OpCode.FINALIZE_DAMAGE: ("target", "amount"),
    OpCode.MARK_DAMAGE_DEALT: ("die",),
    OpCode.RESOLVE_RANGE_DEFICIT: ("card", "value"),
    OpCode.LOSE_HP: ("target", "amount"), OpCode.TURN_DUELS_ADD: ("target", "amount"),
    OpCode.TURN_COST_ADD: ("pool", "amount"),
    **dict.fromkeys(VALUE_RESOLVERS, ("die", "value")),
    OpCode.VALUE_FLOOR: ("value_ref", "bound"), OpCode.VALUE_CEILING: ("value_ref", "bound"),
    **dict.fromkeys(_BINARY_OPERATIONS, ("a", "b")),
    OpCode.ADD: ("a", "b"), OpCode.SUB: ("a", "b"), OpCode.MUL: ("a", "b"),
    OpCode.NOT: ("value",), OpCode.WHEN: ("condition", "block"),
    OpCode.IF_ELSE: ("condition", "then_block", "else_block"),
    OpCode.CLAMP: ("value", "low", "high"), OpCode.DUP: ("value",), OpCode.POP: ("value",),
    OpCode.SWAP: ("a", "b"), OpCode.EVAL: ("block",),
    OpCode.DRAW: ("player", "amount"), OpCode.DISCARD: ("player", "discarded_card"),
    OpCode.RESET_COST: ("player", "common", "personal"), OpCode.PAY_COST: ("card", "amount"),
    OpCode.NEXT_TURN_COST: ("player", "amount"),
    OpCode.SKILL_FINAL_ADD: ("card", "amount"), OpCode.SKILL_LEVEL_ADD: ("card", "amount"),
    OpCode.DIE_FINAL_ADD: ("die", "amount"), OpCode.DIE_LEVEL_ADD: ("die", "amount"),
    OpCode.DIE_BASE_ADD: ("die", "amount"),
    OpCode.REPEAT_DIE: ("die",), OpCode.NEXT_TURN_DUELS: ("target", "amount"),
    OpCode.SET_SKILL_STATE: ("card", "key", "value"),
    OpCode.PLACE: ("side", "duel_index", "card"), OpCode.ROLL: ("low", "high", "bonus", "die"),
    OpCode.REPLACE_SKILL: ("card", "target"),
    OpCode.MOVE_CARD: ("card", "zone"), OpCode.ROUTE_DIE_ATTACK: ("die", "target"),
    OpCode.SELECT_SKILL_TARGET: ("card",),
    OpCode.FOR_EACH_TARGET: ("targets", "block"),
    OpCode.DAMAGE: ("target", "amount", "penetration", "attack_type"),
    OpCode.LIGHTCORE_DAMAGE: ("target", "amount"), OpCode.REAL_DAMAGE: ("target", "amount"),
    OpCode.HEAL: ("target", "amount"), OpCode.STATUS: ("target", "status", "amount"),
    OpCode.SPEND_STATUS: ("target", "status", "amount"),
    OpCode.ABILITY_EFFECT: ("target", "ability", "amount"),
    OpCode.SPEND_ABILITY_EFFECT: ("target", "ability", "amount"),
    OpCode.SHIELD: ("target", "shield_kind", "amount"), OpCode.STAGGER: ("target",),
    OpCode.DESTROY: ("target",),
    OpCode.CLASH: ("clash_pair",), OpCode.RESOLVE_HIT: ("die", "target"),
}
