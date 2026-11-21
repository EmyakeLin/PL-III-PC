"""Card-pack rules.

Use {"trigger": "on_clash_win", "operation": "Shield: 1"} on a die, card or
passive. "BEFORE DAMAGE" and "AFTER STATUS" listen to operation events.
Operations may be a list in printed order or a dict, e.g.
{"op":"place_skill","card_id":"reserve","zone":"out_of_combat"}.
BEFORE DAMAGE accepts modifiers on the incoming base amount. AFTER RESOLVE_DAMAGE
exposes $damage_amount after modifiers and before shields, HP loss, and death.
AFTER DAMAGE exposes $damage_dealt (including a settled zero), $damage_received
(positive damage before shields), $damage_amount and $hp_lost. $damage_die is
the originating die, if any. At after_dice_use, $did_deal_damage reports whether
any direct damage from this use settled. A character entry can attribute its own
follow-up to the current die with {"op":"damage","from_die":true}.
BEFORE PAY_COST observes the acting card and its proposed amount. AFTER PAY_COST
also reports result, personal_spent and common_spent. RESET_COST addresses one
player and supplies the new common and per-character personal budgets.
Target selectors include self (owner's character), source, target, card, die,
opponent_card, opponent_die, and execution. Subscription subject (whose event)
is independent of effect target. The default subject is the owner; use
source, target, ally, enemy or any for explicit reactions.

Scope defaults to the owner's lifetime; duel, turn, next_skill or global can
be specified. A period {"from":"after_turn_start","until":"on_turn_end"}
narrows it. The when mapping compares event fields, e.g. {"status":"烧伤"},
or checks thresholds, e.g. {"owner_status_at_least":{"能源":2}}.
Authority (0/1/2 or 常规/较高话语权/最高话语权) arbitrates attempts to cancel
a pending operation. Entries with the same source execute in printed order.
"""
import re

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
    selected = ctx.event.get(selector)
    if selected is None and selector == "target":
        actor = character_of(owner)
        player = getattr(actor, "player", None)
        if player is not None:
            enemy = next((op for op in ctx.game.players if op is not player), None)
            if enemy is not None:
                selected = player.choose_one_sided_target(enemy)
                ctx.event["target"] = selected
    return selected


def run_effect(ctx, entry, operation):
    """Execute one rule in its triggering event, retaining its actual source."""
    if isinstance(operation, list):
        if all(isinstance(item, (dict, str)) for item in operation):
            for item in operation:
                if ctx.executions[-1].cancelled:
                    break
                run_effect(ctx, entry, item)
        else:
            ctx.eval_block(operation)
        return
    if callable(operation):
        operation(ctx)
        return
    if isinstance(operation, str):
        part = independent_damage_part(operation)
        if part:
            amount, opcode = part
            name, args, data = opcode.name, [], {"amount": amount}
        else:
            name, _, rest = operation.partition(":")
            args = [x.strip() for x in rest.split(",") if x.strip()]
            data = {}
    elif isinstance(operation, dict):
        data = operation
        name, args = data["op"], data.get("args", [])
    else:
        raise ValueError(f"无效词条操作 {operation!r}")
    name = name.lower().strip().replace("-", "_")
    if name == "reveal_lock":
        from models.card import CardState
        card = ctx.event["target"]
        if ctx.game.special.window_open("placement") and card.state == CardState.PLACED_FACE_DOWN:
            card.state = CardState.PLACED_FACE_UP
            ctx.game.special.locked_cards.add(card)
            print(f"「{card.name}」翻正，本置卡阶段锁定位置。")
        return
    if name == "program":
        from entry.program import run_program
        if "damage_part" in data:
            with ctx.binding(damage_part=data["damage_part"]):
                return run_program(ctx, entry, data["code"])
        return run_program(ctx, entry, data["code"])
    if name == "cancel":
        ctx.cancel_op(entry.authority, frame=ctx.event.get("opcode_frame", -1))
        return
    if name == "place_skill":
        player = character_of(entry.owner).player
        duel = ctx.event.get("duel")
        if duel not in ctx.game.active_duelspace.space:
            return
        zone_name = data.get("zone", "out_of_combat")
        if zone_name not in ("hand", "draw", "delayed_discard", "out_of_combat"):
            raise ValueError(f"未知牌区 {zone_name!r}")
        zone = getattr(player.cardspace, zone_name)
        card_id = data.get("card_id", args[0] if args else None)
        card = next((c for c in zone.content if c.id == card_id and c.player is player
                     and c.character.is_alive and not c.destroyed), None)
        if card is not None:
            ctx.game.place_in_duel(player.side, card, ctx.game.active_duelspace.space.index(duel))
        return
    if name in ("roll_add", "roll_set", "base_add", "final_add"):
        die = select_entity(ctx, data.get("target", entry.target or "die"), entry.owner)
        if die is None or ctx.range_blocks_target(die):
            return
        amount = int(data.get("amount", args[0] if args else 0))
        if name == "base_add":
            die.base_value += amount
        elif name == "final_add":
            die.final_bonus += amount
        elif ((ctx.event.get("opcode"), ctx.event.get("timing")) == ("ROLL", "AFTER")
              or ctx.event.get("node_id") == "on_dice_clash"):
            die.value = amount if name == "roll_set" else die.value + amount
        else:
            ctx.roll_adjustments.setdefault(die, []).append((name, amount))
        return
    if name in ("damage_add", "damage_multiply", "armor"):
        if ctx.range_blocks_target(ctx.event.get("target")):
            return
        # A conditional program can run between the listener and the pending damage.
        modifiers = ctx.event.get("modifiers") if ctx.event.get("opcode") == "DAMAGE" else None
        if modifiers is None:
            modifiers = ctx.event.get("hit_modifiers")
        if modifiers is None:
            raise ValueError(f"{name} 需要命中或伤害的上下文")
        value = float(data.get("amount", args[0] if args else 0))
        grade = GRADES[data.get("grade", args[1] if len(args) > 1 else "normal")]
        modifiers.append((name, value, grade))
        return
    default_target = "self" if name in ("heal", "shield", "draw", "draw_card", "discard") else "target"
    selector = data.get("target", entry.target or default_target)
    if name == "destroy" and args:
        selector = args[0]
    target = select_entity(ctx, selector, entry.owner)
    if target is None:
        return
    source = character_of(entry.owner) or ctx.event.get("source")
    amount = int(data.get("amount", args[0] if args and name not in ("destroy", "status") else 1))
    if name == "damage":
        grade = GRADES[data.get("grade", args[1] if len(args) > 1 else "normal")]
        die = ctx.event.get("die")
        attack_type = data.get("attack_type", getattr(die, "type", "none"))
        fields = {}
        if data.get("from_die"):
            if die is None or character_of(die) is not source:
                return
            fields["damage_die"] = die
        ctx.deal_damage(source, target, amount, grade, attack_type,
                        damage_part=data.get("damage_part", False), **fields)
        return
    if name in ("lightcore_damage", "real_damage"):
        block = [target, amount, OpCode[name.upper()]]
    elif name == "status":
        status = data.get("name", args[0] if args else None)
        if not status:
            raise ValueError("Status 需要状态名")
        block = [target, status, int(data.get("amount", args[1] if len(args) > 1 else 1)), OpCode.STATUS]
    elif name == "shield":
        kind = data.get("kind", args[1] if len(args) > 1 else "normal")
        block = [target, kind, amount, OpCode.SHIELD]
    elif name in ("draw", "draw_card", "discard"):
        player = getattr(target, "player", target)
        block = [player, amount, OpCode.DISCARD if name == "discard" else OpCode.DRAW]
    elif name == "heal":
        block = [target, amount, OpCode.HEAL]
    elif name == "stagger":
        block = [target, OpCode.STAGGER]
    elif name == "destroy":
        block = [target, OpCode.DESTROY]
    else:
        # Status packs can publish keywords that invoke their existing settlement
        # rule on a target, with credit for the damage going to the caller.
        for status, rule in getattr(target, "status_rules", {}).items():
            keywords = rule.get("activation", {}).get("keywords", ())
            if name in keywords:
                owner = entry.owner
                final_divisor = data.get("final_divisor", 1)
                if type(final_divisor) is not int or final_divisor < 1:
                    raise ValueError("状态发动的最终伤害除数须为正整数")
                if data.get("from_die"):
                    owner = (ctx.event.get("activation_die") if ctx.event.get("opcode") == "ACTIVATE_STATUS"
                             else ctx.event.get("die"))
                    if (owner is None or character_of(owner) is not source
                            or ctx.range_blocks_target(target, card=owner.card)):
                        return
                ctx.stack.extend((target, status))
                return ctx.execute_op(OpCode.ACTIVATE_STATUS, source=source, side=source.player.side,
                                      activation_owner=owner, activation_kind=keywords[0],
                                      activation_multiplier=data.get("multiplier", 1),
                                      activation_final_divisor=final_divisor)
        raise ValueError(f"未知词条操作 {name!r}")
    with ctx.binding(source=source, target=target, authority=entry.authority):
        ctx.eval_block(block)
