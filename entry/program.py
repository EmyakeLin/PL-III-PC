"""Translate JSON effect programs into blocks for the existing postfix VM."""

from entry.entry import character_of
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
        if field == "value_ref":
            return event["value_ref"]
        if field == "printed_level":
            return event["die"].printed_level.value
        if field == "final_score":
            return event["die"].get_value()
        if field == "clash_score":
            return event["die"].clash_score
        if field in ("card", "die", "target"):
            return event.get(field)
        if field == "skill_target":
            return event.get("target") or ctx.game.pipeline.resolve_skill_target(event.get("card"))
        if field == "next_duel_target":
            return ctx.game.duelspace.next_duel_target(player.side)
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
        if field == "player":
            return player
        if field == "hand_count":
            return len(player.cardspace.hand.content)
        if field == "previous_hand_count":
            return event["previous_count"]
        if field == "current_hand_count":
            return event["hand_count"]
        if field == "duel_number":
            return ctx.game.duelspace.current_duel_index + 1
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
        vm.push(target.statuses.get(name, 0))

    def spent_count(vm):
        name, card = vm.pop(), vm.pop()
        vm.push(card.use_state.get("spent_statuses", {}).get(name, 0))

    def skill_state(vm):
        name, card = vm.pop(), vm.pop()
        vm.push(card.use_state.get(name, 0))

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

    def spend(vm):
        vm.push(vm.execute_op(OpCode.SPEND_STATUS) or 0)

    def spend_in_full(vm):
        vm.push(bool(vm.execute_op(OpCode.SPEND_STATUS, result_field="paid_in_full")))

    words = {
        "STATUS_COUNT": status_count, "SPENT_STATUS_COUNT": spent_count,
        "SKILL_STATE": skill_state, "STORE": store_local, "SPEND_STATUS": spend,
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
            elif isinstance(token, dict):
                block.append(lambda vm, operation=token: run_effect(vm, entry, operation))
            elif isinstance(token, str) and token.startswith("$"):
                block.append(lambda vm, field=token[1:]: vm.push(read(field)))
            elif isinstance(token, str):
                block.append(words.get(token, OpCode.__members__.get(token, token)))
            else:
                block.append(token)
        return block

    # A BEFORE listener may replace a pending operand (e.g. the skill price).
    # Each program has private locals and returns the stack at its original depth.
    previous_stack = ctx.stack.copy()
    try:
        with ctx.binding(source=actor, authority=entry.authority):
            ctx.eval_block(compile_block(tokens))
            if ctx.executions and ctx.executions[-1].cancelled:
                ctx.stack[:] = previous_stack
                return
            if len(ctx.stack) != len(previous_stack):
                raise ValueError("词条程序结束时操作栈深度发生变化")
    except Exception:
        ctx.stack[:] = previous_stack
        raise
