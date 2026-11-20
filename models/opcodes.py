import operator
import random

from entry.entry import EntryExecution
from entry.effects import GRADE_NAMES, GRADE_RANK
from models.card import Card, CardState
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
    OpCode.FLOOR_DIV: operator.floordiv, OpCode.MIN: min,
    OpCode.LT: operator.lt, OpCode.LE: operator.le, OpCode.GT: operator.gt,
    OpCode.GE: operator.ge, OpCode.EQ: operator.eq, OpCode.AND: lambda a, b: bool(a and b),
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


def handle_set_skill_state(ctx):
    value, key, card = ctx.pop(), ctx.pop(), ctx.pop()
    if _usable_component(card):
        card.use_state[key] = value
        return value


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
    hand = target.player.cardspace.hand
    if not hand.content or target.player is receiver.player:
        return None
    card = ctx.game.rng.choice(hand.content)
    card.set_controller(receiver)
    destination = receiver.player.cardspace.hand
    hand.move_card_to(card, destination)
    print(f"{receiver.combat_name} 从对方手中抽取了一张技能。")
    return card


def handle_queue_prepaid_card(ctx):
    resource, card = ctx.pop(), ctx.pop()
    if card is None or card.destroyed or not card.character.is_alive:
        return False
    actor = card.character
    hand = actor.player.cardspace.hand
    if card not in hand.content or actor.statuses.get(resource, 0) < card.cost:
        return False
    slots = [i for i, slot in enumerate(ctx.game.duelspace.space)
             if ctx.game.pipeline.can_join(slot)
             and any(skill.character is actor for skill in slot.get_content(actor.player.side))]
    if not slots:
        return False
    if card.cost:
        ctx.stack.extend((actor, resource, card.cost))
        if not ctx.execute_op(OpCode.SPEND_STATUS, result_field="paid_in_full"):
            return False
    if card not in hand.content or card.character is not actor or not actor.is_alive:
        return False
    ctx.game.special.queue_placement(card, actor, slots)
    return True


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


def handle_queue_status(ctx):
    amount, status, target, source = ctx.pop(), ctx.pop(), ctx.pop(), ctx.pop()
    if not target.is_alive:
        return False
    target.queue_status(status, amount, source=source)
    return True


def handle_draw(ctx):
    count, player = ctx.pop(), ctx.pop()
    draw = player.cardspace.draw
    for _ in range(min(max(0, count), len(draw.content))):
        if not draw.content:
            break
        draw.move_card_to(0, player.cardspace.hand)


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
    cost = 0 if card.use_state.pop("cost_prepaid", False) else max(0, amount)
    ctx.event.update(amount=cost, personal_spent=0, common_spent=0)
    player, character = card.player, card.character
    if (character is None or character.player is not player or not character.is_alive
            or card.destroyed or card.state == CardState.NEGATED):
        return False
    personal = min(cost, max(0, character.available_cost))
    common = cost - personal
    if common > player.available_cost:
        return False
    extra = card.data.get("resource_cost")
    if extra and card.range_deficit < 3:
        ctx.stack.extend((character, extra["status"], extra["amount"]))
        if not ctx.execute_op(OpCode.SPEND_STATUS, result_field="paid_in_full"):
            return False
        if not character.is_alive or card.destroyed or card.state == CardState.NEGATED:
            return False
        personal = min(cost, max(0, character.available_cost))
        common = cost - personal
        if common > player.available_cost:
            return False
    character.used_independent_cost += personal
    player.used_cost += common
    ctx.event.update(personal_spent=personal, common_spent=common)
    return True


def handle_next_turn_cost(ctx):
    amount, player = ctx.pop(), ctx.pop()
    player.next_turn_common_cost += amount
    return player.next_turn_common_cost


def handle_place(ctx):
    card, idx, side = ctx.pop(), ctx.pop(), ctx.pop()
    game = ctx.game
    if idx < 0:
        raise ValueError("交锋索引不能为负")
    if (getattr(card, "destroyed", False) or card.player.side != side
            or not card.character.is_alive
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
    while idx >= len(space.space):
        space.append_new_duel(DuelSlot(game))
    slot = space.space[idx]
    side_cards = slot.content.get(side, [])
    zones = card.player.cardspace
    if (space is game.duelspace and card.character
            and not any(c.character is card.character for c in side_cards if isinstance(c, Card))):
        card.character.used_duels += 1
    if special and "place" not in card.data.get("anytime_play", ()):
        card.character.apply_status_delta("置卡机会", -1)
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


def handle_roll(ctx):
    die, bonus, high, low = ctx.pop(), ctx.pop(), ctx.pop(), ctx.pop()
    rng = getattr(ctx.game, "rng", random)
    die.value = max(low, min(high, rng.randint(low, high) + bonus))
    for action, amount in ctx.roll_adjustments.pop(die, ()):
        die.value = amount if action == "roll_set" else die.value + amount
    return die.value


def handle_move_card(ctx):
    zone, card = ctx.pop(), ctx.pop()
    if zone not in ("hand", "draw", "delayed_discard", "out_of_combat"):
        raise ValueError(f"未知牌区 {zone!r}")
    if card.destroyed or not card.character.is_alive or ctx.game.special.is_locked(card):
        return False
    zones = card.player.cardspace
    destination = getattr(zones, zone)
    if card in destination.content:
        return False
    for slot in ctx.game.board_slots():
        if slot.remove_card(card):
            card.reset_for_draw()
            destination.add_card(card)
            return True
    for pile in (zones.hand, zones.draw, zones.delayed_discard, zones.out_of_combat):
        if card in pile.content:
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


def handle_for_each_target(ctx):
    block, targets = ctx.pop(), ctx.pop()
    primary = ctx.event.get("primary_target", ctx.event.get("target"))
    source, die = ctx.event.get("source"), ctx.event.get("die")
    for target in tuple(targets):
        if (source is not None and not source.is_alive
                or die is not None and not _usable_component(die)
                or ctx.executions and ctx.executions[-1].cancelled):
            break
        if target.is_alive:
            with ctx.binding(target=target, primary_target=primary):
                ctx.eval_block(block)


def handle_resolve_damage(ctx):
    amount = max(0, int(ctx.pop()))
    target = ctx.pop()
    ctx.event.update(amount=amount, damage_amount=amount)
    duel = ctx.game.resolving_duel
    if duel is not None and len(ctx.op_stack) > 1 and ctx.op_stack[-2] == OpCode.DAMAGE:
        duel.damage_taken[target] = duel.damage_taken.get(target, 0) + amount
        ctx.event["duel"] = duel
    return amount


def handle_check_death(ctx):
    target = ctx.pop()
    if target.is_alive and target.hp == 0:
        target._die()
        return True
    return False


def handle_random_int(ctx):
    high, low = ctx.pop(), ctx.pop()
    roll = ctx.game.rng.randint(low, high)
    source = ctx.event.get("source")
    print(f"{getattr(source, 'combat_name', '效果')} 进行 {low}～{high} 判定，掷出 {roll}。")
    ctx.push(roll)


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
    multiplier = 1 if precomputed else target.damage_multiplier()
    fixed = 0
    modifiers = () if precomputed else ctx.event["modifiers"]
    for kind, value, defense_grade in modifiers:
        reduction = (kind == "armor" or kind == "damage_add" and value < 0
                     or kind == "damage_multiply" and value < 1)
        if reduction and GRADE_RANK[defense_grade] < GRADE_RANK[grade]:
            continue
        if kind == "damage_multiply":
            multiplier *= value
        else:
            fixed += -value if kind == "armor" else value
    proposed = max(0, int(amount * multiplier + fixed))
    ctx.stack.extend((target, proposed))
    damage = ctx.execute_op(OpCode.RESOLVE_DAMAGE, base_amount=amount)
    if damage is None or not target.is_alive or (ctx.executions and ctx.executions[-1].cancelled):
        ctx.current_op = None
        return None
    hp_lost = target.apply_resolved_damage(damage, grade)
    ctx.event.update(amount=damage, damage_amount=damage, hp_lost=hp_lost)
    grade_name = GRADE_NAMES[grade]
    cause = ctx.event.get("damage_cause") or getattr(source, "combat_name", "效果")
    print(f"{cause} 对 {target.combat_name} 造成 {damage} 点伤害"
          f"（{grade_name}，剩余生命 {target.hp}/{target.max_hp}）")
    if not target.is_alive:
        print(f"{target.combat_name} 阵亡。")
    if ctx.event.get("damage_part") and target.is_alive:
        target.after_damage_part()
    return damage


def handle_heal(ctx):
    amount, target = ctx.pop(), ctx.pop()
    actual = target.heal(amount)
    if actual:
        if target.is_alive:
            print(f"{target.combat_name} 恢复 {actual} 点生命（{target.hp}/{target.max_hp}）。")
        else:
            print(f"{target.combat_name} 实际恢复 {actual} 点生命，回复生命触发即死，阵亡。")
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
    cause = getattr(ctx.event.get("source"), "combat_name", "效果")
    print(f"{cause} 对 {target.combat_name} 造成 {amount} 点光点伤害"
          f"（完整度 {target.lightcore_hp}/{target.max_lightcore_hp}）。")
    if collapsed:
        # This whole segment has been consumed. A subsequent segment sees the new pool.
        print(f"{target.combat_name} 的光点形态群崩塌。")
        with ctx.binding(source=target, damage_cause="光点形态群崩塌"):
            ctx.eval_block([target, (target.original_max_hp + 1) // 2, OpCode.REAL_DAMAGE])
        target.max_lightcore_hp = max(0, target.max_lightcore_hp - 4)
        target.lightcore_hp = target.max_lightcore_hp
        print(f"{target.combat_name} 的光点生命上限降至 {target.max_lightcore_hp}，"
              f"完整度恢复为 {target.lightcore_hp}/{target.max_lightcore_hp}。")
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
    cause = ctx.event.get("damage_cause") or getattr(ctx.event.get("source"), "combat_name", "效果")
    print(f"{target.combat_name} 承受 {amount} 点真实伤害"
          f"（来源：{cause}，剩余生命 {target.hp}/{target.max_hp}）。")
    if not target.is_alive:
        print(f"{target.combat_name} 阵亡。")
    return amount


def handle_lose_hp(ctx):
    amount, target = ctx.pop(), ctx.pop()
    lost = target.lose_hp(amount)
    ctx.event["hp_lost"] = lost
    if lost:
        print(f"{target.combat_name} 失去 {lost} 点生命，剩余 {target.hp}/{target.max_hp}。")
        if not target.is_alive:
            print(f"{target.combat_name} 阵亡。")
    return lost


def handle_hit(ctx):
    target, die = ctx.pop(), ctx.pop()
    return ctx.execute_hit_parts(die, target)


def handle_shield(ctx):
    amount, kind, target = ctx.pop(), ctx.pop(), ctx.pop()
    total = target.add_shield(kind, amount)
    name = {"normal": "普通护盾", "shield": "普通护盾", "reinforced": "强化护盾",
            "concept": "概念护盾"}.get(kind, kind)
    print(f"{target.combat_name} 的{name}变为 {total}。")
    return total


def handle_status(ctx):
    amount, name, target = ctx.pop(), ctx.pop(), ctx.pop()
    proposed = ctx.event["amount"]
    ctx.event["amount"] = amount
    total = target.apply_status_delta(name, amount)
    if amount == 0 and isinstance(proposed, (int, float)) and proposed > 0:
        print(f"{target.combat_name} 未能获得{name}。")
    else:
        print(f"{target.combat_name} 的{name}变为 {total} 层。")
    return total


def handle_spend_status(ctx):
    """Drain up to the adjusted cost and report the actual debit and its sufficiency."""
    requested, name, target = ctx.pop(), ctx.pop(), ctx.pop()
    ctx.event.update(amount=requested, paid_in_full=False)
    balance = target.statuses.get(name, 0)
    if requested == "all" and balance and not target.is_alive:
        target.clear_status(name)
        ctx.event["paid_in_full"] = True
        print(f"{target.combat_name} 清空剩余 {balance} 层{name}。")
        return balance
    if not target.is_alive or not balance:
        return 0
    if requested == "all":
        cost = balance
    elif isinstance(requested, int) and requested > 0:
        cost = requested
    else:
        return 0
    paid = min(cost, balance)
    remaining = target.apply_status_delta(name, -paid)
    ctx.event["paid_in_full"] = paid == cost
    card = ctx.event.get("card")
    if card is not None and card.character is target:
        spent = card.use_state.setdefault("spent_statuses", {})
        spent[name] = spent.get(name, 0) + paid
    shortfall = f"（需 {cost} 层，未付足）" if paid < cost else ""
    print(f"{target.combat_name} 消耗 {paid} 层{name}{shortfall}，剩余 {remaining} 层。")
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
        target.destroyed = True
        target.state = CardState.NEGATED
    elif hasattr(target, "card") and hasattr(target, "roll"):
        target.destroyed = True
    else:
        raise ValueError("摧毁只能作用于技能、骰子或一次词条执行")
    return True


def handle_discard(ctx):
    amount, player = ctx.pop(), ctx.pop()
    hand = player.cardspace.hand
    discarded = []
    for _ in range(min(max(0, amount), len(hand.content))):
        if not hand.content:
            break
        card = hand.content[0]
        hand.move_card_to(0, player.cardspace.delayed_discard)
        discarded.append(card)
    return discarded


DISPATCH_TABLE = {
    OpCode.SET_SKILL_FORM: handle_set_skill_form, OpCode.SPLIT_CLASH: handle_split_clash,
    OpCode.TRANSFER_REMAINING_DICE: handle_transfer_remaining_dice,
    OpCode.TAKE_HAND_CARD: handle_take_hand_card, OpCode.QUEUE_PREPAID_CARD: handle_queue_prepaid_card,
    OpCode.CHECK_DEATH: handle_check_death, OpCode.RANDOM_INT: handle_random_int,
    OpCode.RESOLVE_DAMAGE: handle_resolve_damage,
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
    OpCode.FOR_EACH_TARGET: handle_for_each_target,
    OpCode.RESET_COST: handle_reset_cost, OpCode.PAY_COST: handle_pay_cost,
    OpCode.NEXT_TURN_COST: handle_next_turn_cost,
    OpCode.SKILL_FINAL_ADD: handle_final_add, OpCode.SKILL_LEVEL_ADD: handle_skill_level_add,
    OpCode.DIE_FINAL_ADD: handle_final_add, OpCode.DIE_LEVEL_ADD: handle_die_level_add,
    OpCode.REPEAT_DIE: handle_repeat_die, OpCode.NEXT_TURN_DUELS: handle_next_turn_duels,
    OpCode.SET_SKILL_STATE: handle_set_skill_state, OpCode.QUEUE_STATUS: handle_queue_status,
    OpCode.DAMAGE: handle_damage, OpCode.LIGHTCORE_DAMAGE: handle_lightcore_damage,
    OpCode.REAL_DAMAGE: handle_real_damage, OpCode.HEAL: handle_heal, OpCode.SHIELD: handle_shield,
    OpCode.RESOLVE_HIT: handle_hit, OpCode.CLASH: lambda ctx: ctx.pop().clash_check(),
    OpCode.STATUS: handle_status, OpCode.STAGGER: handle_stagger,
    OpCode.SPEND_STATUS: handle_spend_status,
    OpCode.DESTROY: handle_destroy, OpCode.DISCARD: handle_discard,
}

# Names follow stack order so pre/post listeners can inspect explicit action operands.
OPERANDS = {
    OpCode.SET_SKILL_FORM: ("card", "form"), OpCode.SPLIT_CLASH: ("die",),
    OpCode.TRANSFER_REMAINING_DICE: ("target", "receiving_card"),
    OpCode.TAKE_HAND_CARD: ("target", "receiver"), OpCode.QUEUE_PREPAID_CARD: ("card", "resource"),
    OpCode.CHECK_DEATH: ("target",), OpCode.RANDOM_INT: ("low", "high"),
    OpCode.RESOLVE_DAMAGE: ("target", "amount"),
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
    OpCode.DRAW: ("player", "amount"), OpCode.DISCARD: ("player", "amount"),
    OpCode.RESET_COST: ("player", "common", "personal"), OpCode.PAY_COST: ("card", "amount"),
    OpCode.NEXT_TURN_COST: ("player", "amount"),
    OpCode.SKILL_FINAL_ADD: ("card", "amount"), OpCode.SKILL_LEVEL_ADD: ("card", "amount"),
    OpCode.DIE_FINAL_ADD: ("die", "amount"), OpCode.DIE_LEVEL_ADD: ("die", "amount"),
    OpCode.REPEAT_DIE: ("die",), OpCode.NEXT_TURN_DUELS: ("target", "amount"),
    OpCode.SET_SKILL_STATE: ("card", "key", "value"), OpCode.QUEUE_STATUS: ("source", "target", "status", "amount"),
    OpCode.PLACE: ("side", "duel_index", "card"), OpCode.ROLL: ("low", "high", "bonus", "die"),
    OpCode.REPLACE_SKILL: ("card", "target"),
    OpCode.MOVE_CARD: ("card", "zone"), OpCode.ROUTE_DIE_ATTACK: ("die", "target"),
    OpCode.FOR_EACH_TARGET: ("targets", "block"),
    OpCode.DAMAGE: ("target", "amount", "penetration", "attack_type"),
    OpCode.LIGHTCORE_DAMAGE: ("target", "amount"), OpCode.REAL_DAMAGE: ("target", "amount"),
    OpCode.HEAL: ("target", "amount"), OpCode.STATUS: ("target", "status", "amount"),
    OpCode.SPEND_STATUS: ("target", "status", "amount"),
    OpCode.SHIELD: ("target", "shield_kind", "amount"), OpCode.STAGGER: ("target",),
    OpCode.DESTROY: ("target",),
    OpCode.CLASH: ("clash_pair",), OpCode.RESOLVE_HIT: ("die", "target"),
}
