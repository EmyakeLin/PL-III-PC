from collections import deque
from contextlib import contextmanager
from copy import copy
import random

from entry.effects import GRADES, damage_part, independent_damage_part, run_effect
from entry.entry import AUTHORITY, Entry, EntryExecution, TriggerType, character_of, kind_of
from entry.scheduling import deliver_scheduled
from models.opcode import OpCode
from models.opcodes import DISPATCH_TABLE, OPERANDS, VALUE_RESOLVERS
from models.values import ValueBounds
from pipeline.pipeline_errors import PipelineSystemError, StackUnderflowError


_NON_MUTATING_OPCODES = frozenset({
    OpCode.RESOLVE_DAMAGE_BASE,
    OpCode.ENTRY, OpCode.CHOOSE_CARD, OpCode.CHOOSE_OPTION, OpCode.CHOOSE_CHARACTER, OpCode.CHOOSE_SLOT,
    OpCode.OPPONENT, OpCode.BOARD_SLOTS, OpCode.ZONE_CARDS, OpCode.SLOT_CARDS, OpCode.REMAINING_CARDS,
    OpCode.REAR_SLOT_CARDS, OpCode.REAR_CAPACITY, OpCode.SLOT_AT_OFFSET, OpCode.SKILL_RESTRICTED,
    OpCode.CAN_JOIN_DUEL, OpCode.NEXT_PLANNED_DIE, OpCode.DIE_VALUE, OpCode.SIZE, OpCode.ALL_IN,
    OpCode.FILTER, OpCode.MAP, OpCode.FLATTEN, OpCode.FIRST, OpCode.LOOKUP, OpCode.EACH,
    OpCode.FIRST_IN_ORDER, OpCode.COALESCE, OpCode.WITH_BINDINGS, OpCode.SKILL_USE_COUNT,
    OpCode.CLASH_COUNT, OpCode.DUEL_OFFSET, OpCode.ROUND_TRIGGER_COUNT, OpCode.WINDOW_OPEN,
    OpCode.FLOOR_DIV, OpCode.MIN, OpCode.MAX, OpCode.DIVIDE, OpCode.LT, OpCode.LE, OpCode.GT, OpCode.GE,
    OpCode.EQ, OpCode.IS, OpCode.AND, OpCode.OR, OpCode.NOT, OpCode.WHEN, OpCode.IF_ELSE,
    OpCode.CLAMP, OpCode.DUP, OpCode.POP, OpCode.SWAP, OpCode.PAIR,
})


class Context:
    def __init__(self, parent=None, game=None):
        self.parent = parent
        self.game = parent.game if parent else game
        self.stack = []
        self.entries = []
        self.shared_entry_groups = set()
        self.register = {}
        self.interceptions = []
        self.meta = {}
        self.code_stream = None
        self.op_stack = []
        self._op_events = []
        self.event = {}
        self.executions = []
        self.turn_entry_uses = {}
        self.active_cards = {}
        self.active_dice = {}
        self.rear_active_cards = {}
        self.rear_active_dice = {}
        self.hit_modifiers = {}
        self.roll_adjustments = {}
        self.scheduled_effects = []
        self._combat_effects_closed = False
        # Entries whose printed duration outlives the physical card's return to hand.
        self._lasting_entries = {}
        self._fact_collections = []
        self.mutation_serial = 0

    def observe_facts(self, collection=None):
        """Create a reader-owned queue for the lifetime of this context."""
        facts = deque() if collection is None else collection
        self._fact_collections.append(facts)
        return facts

    @contextmanager
    def collect_facts(self):
        """Capture completed domain actions in order without calling an observer."""
        facts = self.observe_facts()
        try:
            yield facts
        finally:
            self._fact_collections[:] = [other for other in self._fact_collections if other is not facts]

    def record(self, kind, **fields):
        for collection in self._fact_collections:
            collection.append((kind, fields.copy()))

    @property
    def current_op(self):
        return self.op_stack[-1] if self.op_stack else None

    @current_op.setter
    def current_op(self, value):
        if self.op_stack:
            self.op_stack[-1] = value

    def cancel_op(self, authority=None, *, frame=-1):
        if not self.op_stack:
            return
        event = self._op_events[frame]
        required = event.get("authority", 0)
        if self._protected_op(self.op_stack[frame], event) or (authority is not None and authority < required):
            return
        if authority == required == AUTHORITY["highest"]:
            first = getattr(self.game, "first_player", None)
            issuer = getattr(character_of(event.get("_authority_owner", event.get("source"))), "player", None)
            owner = self.executions[-1].entry.owner if self.executions else self.event.get("_authority_owner")
            protector = getattr(character_of(owner), "player", None)
            if first is not None and issuer is first and protector is not None and protector is not first:
                return
        self.op_stack[frame] = None

    def range_blocks_target(self, target, *, card=None, die=None):
        """Use the actual originating skill; character and status passives remain independent."""
        if die is None and card is None and self.executions:
            entry = self.executions[-1].entry
            card = entry.owning_card
            die = entry.owner if getattr(entry.owner, "card", None) is not None else None
        if die is not None:
            card = die.card
        if card is None or card.range_opponent is None or not (die or card).range_deficit:
            return False
        if isinstance(target, EntryExecution):
            target = target.entry.owner
        protected = card.range_opponent.character
        return character_of(target) is protected or target is protected.player

    def _range_blocks_op(self, opcode, fields):
        if opcode == OpCode.DAMAGE and fields.get("damage_die") is not None:
            target = self.event.get("target") if fields["target"] == "target" else fields["target"]
            if self.range_blocks_target(target, die=fields["damage_die"]):
                return True
        if not self.executions:
            return False
        if opcode == OpCode.ENTRY:
            return self.range_blocks_target(fields.get("execution"))
        if opcode == OpCode.CLASH:
            return any(self.range_blocks_target(die) for die in fields["clash_pair"].all_dice())
        if opcode in (OpCode.SPLIT_CLASH, OpCode.SKIP_ROUND):
            pair = self.game.pipeline.current_clash_pair
            return pair is not None and any(self.range_blocks_target(die) for die in pair.all_dice())
        if opcode in (OpCode.VALUE_CEILING, OpCode.VALUE_FLOOR):
            return self.range_blocks_target(self.event.get("die") or self.event.get("card"))
        operands = OPERANDS.get(opcode, ())
        for key in ("die", "card", "target", "pool", "player"):
            if key in operands:
                target = fields[key]
                if target == "target":
                    target = self.event.get("target")
                return self.range_blocks_target(target)
        return False

    def side_active_cards(self, side):
        return tuple(c for c in (self.active_cards.get(side), self.rear_active_cards.get(side)) if c is not None)

    def side_active_dice(self, side):
        return tuple(d for d in (self.active_dice.get(side), self.rear_active_dice.get(side)) if d is not None)

    def has_no_hit_carrier(self, target):
        """Use the recipient's own active skill and die, even when the die shows blank."""
        if isinstance(target, EntryExecution):
            target = target.entry.owner
        actor = character_of(target)
        if actor is None:
            return False
        side = actor.player.side
        for card in self.side_active_cards(side):
            if (card.character is actor and (target in (actor, card) or getattr(target, "card", None) is card)
                    and (card.data.get("no_hit_carrier") or card.use_state.get("no_hit_carrier"))):
                return True
        for die in self.side_active_dice(side):
            if die.card.character is actor and target in (actor, die, die.card) and die.data.get("no_hit_carrier"):
                return True
        return False

    def _protected_op(self, opcode, fields):
        if self._range_blocks_op(opcode, fields):
            return True
        issuer = (self.executions[-1].entry.owner if self.executions
                  else getattr(self.event.get("scheduled"), "source", None))
        if issuer is None and not self.executions:
            if opcode not in (OpCode.DAMAGE, OpCode.LIGHTCORE_DAMAGE, OpCode.REAL_DAMAGE):
                return False
            issuer = fields.get("source") or self.event.get("source")
        source = character_of(issuer)
        # Selection and inspection do not apply an effect to the selected object.
        if opcode in (OpCode.CAPTURE_SKILL_DIE, OpCode.SELECT_ENEMY_CHARACTER, OpCode.SELECT_SKILL_TARGET,
                      OpCode.STAGE_PRE_ATTACK, OpCode.ROUTE_DIE_ATTACK,
                      OpCode.QUEUE_TARGET_HIT, OpCode.RESOLVE_HIT):
            keys = ("die",) if opcode in (OpCode.ROUTE_DIE_ATTACK, OpCode.QUEUE_TARGET_HIT) else ()
        elif opcode == OpCode.ENTRY:
            keys = ("execution",)
        elif opcode in (OpCode.VALUE_FLOOR, OpCode.VALUE_CEILING):
            fields, keys = self.event, ("die", "card")
        else:
            keys = OPERANDS.get(opcode, ())
        for key in keys:
            if key not in ("die", "card", "target", "new_target", "pool", "execution", "receiving_card"):
                continue
            recipient = fields.get(key)
            if recipient == "target":
                recipient = self.event.get("target")
            if isinstance(recipient, EntryExecution):
                recipient = recipient.entry.owner
            if character_of(recipient) is not source and self.has_no_hit_carrier(recipient):
                return True
        return False

    def push(self, value):
        self.stack.append(value)

    def pop(self):
        if not self.stack:
            raise StackUnderflowError("栈下溢")
        return self.stack.pop()

    def peek(self, offset):
        if not 0 <= offset < len(self.stack):
            raise StackUnderflowError("栈下溢")
        return self.stack[-1-offset]

    def dup(self):
        self.push(self.peek(0))

    def swap(self):
        a, b = self.pop(), self.pop()
        self.push(a)
        self.push(b)

    def store(self, name):
        self.register[name] = self.pop()

    def load(self, name):
        if name not in self.register:
            raise ValueError(f"Register does not contain {name}!")
        self.push(self.register[name])

    @contextmanager
    def binding(self, **fields):
        previous = self.event
        if "authority" in fields and "_authority_owner" not in fields:
            # Operation hooks may rebind source to their subject (e.g. the resource holder).
            fields["_authority_owner"] = (self.executions[-1].entry.owner if self.executions
                                          else fields.get("source", previous.get("source")))
        self.event = {**previous, **fields}
        try:
            yield self.event
        finally:
            self.event = previous

    @contextmanager
    def _pending(self, opcode):
        self.op_stack.append(opcode)
        self._op_events.append(self.event)
        try:
            yield
        finally:
            self.op_stack.pop()
            self._op_events.pop()

    def eval_block(self, block):
        if not isinstance(block, list):
            raise TypeError("eval_block 必须接收列表形式的指令块")
        previous = self.code_stream
        self.code_stream = deque(block)
        result = None
        execution = self.executions[-1] if self.executions else None
        try:
            while self.code_stream and not (execution and execution.cancelled):
                item = self.code_stream.popleft()
                if isinstance(item, OpCode):
                    result = self.execute_op(item)
                elif callable(item):
                    item(self)
                else:
                    self.push(item)
        finally:
            self.code_stream = previous
        return result

    def pay_status_cost(self):
        """Pay the SPEND_STATUS operands on the stack only if the adjusted cost is affordable."""
        return bool(self.execute_op(OpCode.SPEND_STATUS, require_full=True, result_field="paid_in_full"))

    def pay_skill_cost(self, card, discount=0):
        """Keep the receipt for this use, including price changes made by payment hooks."""
        printed_cost = card.cost
        price = max(0, printed_cost - discount)
        prepaid = bool(card.use_state.get("cost_prepaid"))
        self.stack.extend((card, price))
        event = self.execute_op(OpCode.PAY_COST, result_field=None, use_discount=discount) or {}
        personal = event.get("personal_spent", 0)
        common = event.get("common_spent", 0)
        paid = event.get("result") is True
        receipt = {
            "paid": paid, "cost": personal + common, "personal_paid": personal, "common_paid": common,
            "printed_cost": printed_cost, "required_cost": event.get("amount", 0 if prepaid else price),
            "discount": discount, "prepaid": event.get("prepaid", prepaid), "resource_paid": event.get("resource_paid"),
            "failure_reason": None if paid else event.get("failure_reason") or "支付被取消",
        }

        self.record("skill_payment", side=card.player.side, character_id=card.character.id if card.character else None,
                    card_id=card.id, card_name=card.name, **receipt)
        return receipt

    def pay_action_costs(self, actor, ability_costs, status_costs):
        """Resolve all price modifiers before charging an action with several costs."""
        costs = [(OpCode.SPEND_ABILITY_EFFECT, name, amount) for name, amount in ability_costs.items()]
        costs.extend((OpCode.SPEND_STATUS, name, amount) for name, amount in status_costs.items())
        pending = [] if len(costs) > 1 else None
        for opcode, name, amount in costs:
            self.stack.extend((actor, name, amount))
            if not self.execute_op(opcode, require_full=True, result_field="paid_in_full", defer_payment=pending):
                return False
        if pending is None:
            return True

        # A later BEFORE hook may change a balance or make two prices refer to the same resource.
        balances = {}
        for opcode, (target, name, amount), _ in pending:
            key = opcode, target, name
            if key not in balances:
                balances[key] = (target.spendable_status(name) if opcode == OpCode.SPEND_STATUS
                                 else target.ability_effects.get(name, 0))
            count = balances[key] if amount == "all" and opcode == OpCode.SPEND_STATUS else amount
            if not target.is_alive or not isinstance(count, int) or not 0 < count <= balances[key]:
                return False
            balances[key] -= count

        receipts = []
        for opcode, operands, fields in pending:
            self.stack.extend(operands)
            with self.binding(**fields) as event, self._pending(opcode):
                event["result"] = DISPATCH_TABLE[opcode](self)
                receipts.append((opcode, event))
        for opcode, fields in receipts:
            if opcode == OpCode.SPEND_STATUS:
                with self.binding(**fields) as event, self._pending(opcode):
                    event["target"].finish_status_change(event["status"], event["previous_stacks"],
                                                         event["current_stacks"])
        for opcode, fields in receipts:
            with self.binding(**fields), self._pending(opcode):
                self.dispatch_opcode(opcode, "AFTER")
        return True

    def execute_op(self, opcode, *, result_field="result", defer_payment=None, **fields):
        """Run one hooked operation. A None result_field requests its complete event."""
        names = OPERANDS.get(opcode, ())
        if len(self.stack) < len(names):
            raise StackUnderflowError(f"{opcode.name} 参数不足")
        mark = len(self.stack) - len(names)
        fields.update(zip(names, self.stack[mark:]))
        originating_entry = self.executions[-1] if self.executions else None
        fields["issuer"] = originating_entry.entry if originating_entry else None
        if opcode in (OpCode.ABILITY_EFFECT, OpCode.SPEND_ABILITY_EFFECT):
            holder = fields["target"]
            if holder is None or not holder.is_alive or fields["ability"] not in holder.ability_rules:
                del self.stack[mark:]
                return None
            fields["status"] = None
        elif opcode in (OpCode.STATUS, OpCode.SPEND_STATUS, OpCode.ACTIVATE_STATUS):
            holder = fields["target"]
            if holder is not None:
                name = holder.canonical_status_name(fields["status"])
                if name in holder.ability_rules:
                    del self.stack[mark:]
                    return None
                fields["status"] = self.stack[mark + names.index("status")] = name
            fields["ability"] = None
        if opcode == OpCode.DESTROY:
            fields.setdefault("keep_position", False)
            if type(fields["keep_position"]) is not bool:
                raise ValueError("摧毁骰位的保留标记须为布尔值")
        if opcode == OpCode.RESOLVE_HIT:
            fields["hit_die"] = None
        if opcode == OpCode.DAMAGE:
            fields.setdefault("percentage_damage", False)
            # Nested status and character effects own their damage independently of
            # the die whose event they observed. A die entry owns its own segments.
            owner = originating_entry.entry.owner if originating_entry else None
            fields.setdefault("damage_die", owner if getattr(owner, "card", None) is not None else None)
            fields["damage_card"] = (fields["damage_die"].card if fields["damage_die"] is not None
                                     else originating_entry.entry.owning_card if originating_entry else None)
            fields["damage_status"] = originating_entry.entry.status_name if originating_entry else None
            fields.setdefault("damage_source", fields.get("source") or self.event.get("source") or character_of(owner))
            if originating_entry and fields.get("damage_cause") is None:
                fields["damage_cause"] = originating_entry.entry.damage_cause
        elif opcode == OpCode.ACTIVATE_STATUS:
            # An ordinary activation belongs to the status on its holder. A printed
            # keyword may instead credit its initiating die, skill or status.
            fields.setdefault("activation_owner", None)
            fields.setdefault("activation_kind", None)
            fields.setdefault("adjustments", None)
            owner = fields["activation_owner"]
            fields["activation_origin"] = (
                originating_entry.entry.origin if originating_entry and owner is originating_entry.entry.owner
                else kind_of(owner) if owner is not None else "status")
            fields["activation_die"] = owner if fields["activation_origin"] == "die" else None
            fields["activation_die_type"] = getattr(fields["activation_die"], "type", None)
        if opcode == OpCode.CHECK_DEATH:
            fields.setdefault("lethal", False)
        if self._protected_op(opcode, fields) or (
                opcode == OpCode.RESOLVE_HIT and (fields["die"].range_deficit
                                                  or self.has_no_hit_carrier(fields["target"]))):
            del self.stack[mark:]
            return None
        if originating_entry is not None:
            fields["execution"] = originating_entry
        if opcode == OpCode.APPLY_DAMAGE:
            fields.setdefault("shield_defenses", [])
            fields.setdefault("damage_source", fields.get("damage_source") or fields.get("source") or self.event.get("source"))
        elif opcode == OpCode.RESOLVE_STATUS_AMOUNT:
            fields["value_ref"] = ValueBounds()
        elif opcode == OpCode.RESOLVE_RANGE_DEFICIT:
            card = fields["card"]
            fields.update(value_ref=ValueBounds(), source=card.character, side=card.player.side)
        elif opcode in VALUE_RESOLVERS:
            die = fields["die"]
            actor = character_of(die)
            fields.update(value_ref=ValueBounds(), source=actor, side=actor.player.side if actor else None,
                          card=die.card, participants=(actor,) if actor else ())
        elif opcode == OpCode.ROLL:
            die = fields["die"]
            fields.update(card=getattr(die, "card", None), source=character_of(die) or getattr(die, "owner", None))
            player = getattr(fields["source"], "player", None)
            fields["side"] = getattr(player, "side", None)
        elif opcode in (OpCode.PLACE, OpCode.MOVE_CARD):
            fields["source"] = character_of(fields["card"])
            if opcode == OpCode.MOVE_CARD:
                fields.setdefault("play_from_hand", False)
        elif opcode == OpCode.PAY_COST:
            card = fields["card"]
            fields.update(source=card.character, player=card.player, side=card.player.side,
                          personal_spent=0, common_spent=0, resource_paid=None, failure_reason=None)
        elif opcode in (OpCode.RESET_COST, OpCode.NEXT_TURN_COST):
            fields.update(source=None, side=fields["player"].side)
        elif opcode == OpCode.TURN_COST_ADD:
            pool = fields["pool"]
            player = getattr(pool, "player", pool)
            fields.update(player=player, source=None if pool is player else pool, side=player.side)
        elif opcode in (OpCode.SPEND_STATUS, OpCode.SPEND_ABILITY_EFFECT):
            actor = fields["target"]
            fields.update(source=actor, side=actor.player.side)
            # A nested spend chooses its own mode, even inside a conditional payment hook.
            fields.setdefault("require_full", False)
            fields["defer_spend_effects"] = defer_payment is not None
        elif opcode in (OpCode.SKILL_FINAL_ADD, OpCode.SKILL_LEVEL_ADD, OpCode.SET_SKILL_STATE,
                        OpCode.QUEUE_HIT, OpCode.QUEUE_TARGET_HIT, OpCode.SET_UNOPPOSED_RESULT, OpCode.SKIP_ROUND,
                        OpCode.DIE_FINAL_ADD, OpCode.DIE_BASE_ADD, OpCode.DIE_LEVEL_ADD, OpCode.SET_DIE_STATE,
                        OpCode.REPEAT_DIE, OpCode.ROUTE_DIE_ATTACK):
            part = fields.get("die") or fields["card"]
            actor = character_of(part)
            fields.update(source=actor, side=actor.player.side if actor else None)
            if "die" in fields:
                fields["card"] = part.card
        elif opcode == OpCode.REDIRECT_ATTACK:
            die = fields["die"]
            issuer = originating_entry.entry.owner if originating_entry else character_of(die)
            actor = character_of(issuer) or character_of(die)
            fields.update(
                card=getattr(die, "card", None),
                attacker=character_of(die),
                source=actor,
                side=actor.player.side if actor else None,
            )
        elif opcode in (OpCode.NEXT_TURN_DUELS, OpCode.TURN_DUELS_ADD):
            fields.setdefault("source", self.event.get("source") or fields["target"])
            fields["side"] = fields["source"].player.side
        elif opcode in (OpCode.DAMAGE, OpCode.RESOLVE_DAMAGE, OpCode.FINALIZE_DAMAGE, OpCode.LOSE_HP,
                        OpCode.LIGHTCORE_DAMAGE, OpCode.REAL_DAMAGE):
            if fields["target"] == "target":
                fields["target"] = self.event.get("target")
            # A follow-up segment owns its measurements even inside another channel's listener.
            fields.update(result=None, hp_lost=None, damage_amount=None, damage_dealt=False, damage_received=False,
                          lightcore_lost=None, lightcore_collapsed=False)
            fields.setdefault("base_amount", fields["amount"])
            if opcode == OpCode.DAMAGE:
                fields.setdefault("damage_precomputed", False)
                fields["modifiers"] = list(self.event.get("hit_modifiers", ())) if self.event.get("damage_part") else []
            elif opcode in (OpCode.RESOLVE_DAMAGE, OpCode.FINALIZE_DAMAGE):
                fields["damage_amount"] = fields["amount"]
                if opcode == OpCode.FINALIZE_DAMAGE:
                    fields["value_ref"] = ValueBounds()
            else:
                fields.update(damage_part=False, damage_die=None, damage_card=None, damage_status=None,
                              penetration=None, attack_type=None, modifiers=None)
                if opcode == OpCode.LIGHTCORE_DAMAGE:
                    owner = originating_entry.entry.owner if originating_entry else None
                    credit = (self.event.get("damage_die") if fields.get("credit") == "damage_die"
                              else owner if kind_of(owner) == "die" else None)
                    fields.update(damage_die=credit, damage_card=credit.card if credit else None)
                if opcode == OpCode.LOSE_HP:
                    fields["base_amount"] = None
                    fields.setdefault("source", self.event.get("source") or fields["target"])
                    fields["side"] = fields["source"].player.side
        with self.binding(**fields) as event, self._pending(opcode):
            if opcode == OpCode.DAMAGE and not event["damage_precomputed"]:
                # Establish the segment's base once, before armor, status multipliers
                # and any other DAMAGE listener observe its amount and grade.
                self.stack.extend((event["amount"], event["penetration"], event["percentage_damage"]))
                base = self.execute_op(OpCode.RESOLVE_DAMAGE_BASE)
                if base is None:
                    del self.stack[mark:]
                    return None
                amount, grade, percentage = base
                self.stack[mark + 1:mark + 3] = (amount, grade)
                event.update(amount=amount, base_amount=amount, penetration=grade, percentage_damage=percentage)
            self.dispatch_opcode(opcode, "BEFORE")
            if self.current_op is None or (originating_entry is not None and originating_entry.cancelled):
                del self.stack[mark:]
                return None
            if defer_payment is not None:
                defer_payment.append((self.current_op, tuple(self.stack[mark:]), event))
                del self.stack[mark:]
                return True
            handler = DISPATCH_TABLE.get(self.current_op)
            if handler is None:
                raise PipelineSystemError(f"未实现的操作码: {self.current_op}")
            executed_op = self.current_op
            result = handler(self)
            if self.current_op is None:
                if result_field is None:
                    event["result"] = None
                    return event
                return None
            if executed_op not in _NON_MUTATING_OPCODES:
                self.mutation_serial += 1
            event["result"] = result
            self.dispatch_opcode(executed_op, "AFTER")
            return event if result_field is None else event.get(result_field)

    def register_entries(self, owner, specs):
        """Instantiate a character's passives, a card's entries or a die's entries."""
        if (getattr(owner, "type", None) == "blank" and kind_of(owner) == "die"
                and not getattr(owner, "blanked_by_range", False)):
            return []
        registered = []
        for spec in specs or ():
            if isinstance(spec, dict) and "entries" in spec and "trigger" not in spec:
                group = self.register_entries(owner, spec["entries"])
                for member in group:
                    member.group_name = spec.get("name")
                registered.extend(group)
            elif isinstance(spec, dict):
                entry = Entry.from_spec(owner, spec)
                self.entries.append(entry)
                registered.append(entry)
            elif isinstance(spec, Entry):
                self.entries.append(spec)
                registered.append(spec)
            elif damage_part(spec) is None:
                # Unqualified die text is an operation on hit, just like a printed damage part.
                if kind_of(owner) != "die":
                    raise ValueError(f"词条需要指定触发器: {spec!r}")
        return registered

    def register_status_programs(self, rules):
        for name, rule in rules.items():
            if rule.get("global_entries") and name not in self.shared_entry_groups:
                self.register_entries(None, rule["global_entries"])
                self.shared_entry_groups.add(name)

    def publish(self, name, fields):
        with self.binding(**fields):
            if self.scheduled_effects:
                deliver_scheduled(self, "event", name, fields)
            self._dispatch(TriggerType.EVENT, name)

    def unregister_entries(self, owner):
        if getattr(owner, "is_alive", True) is False:
            for execution in self.executions:
                if character_of(execution.entry.owner) is owner:
                    execution.cancelled = True
        for entry in self.entries[:]:
            if entry.owner is owner:
                char = character_of(owner)
                if entry.scope == "next_skill" and entry.next_armed and char and char.is_alive:
                    entry.detached = True
                else:
                    self.entries.remove(entry)

    def close_combat_effects(self):
        """Stop combatants' outstanding effects; global observers can still read terminal results."""
        self._combat_effects_closed = True
        self.scheduled_effects.clear()
        for execution in self.executions:
            if character_of(execution.entry.owner) is not None:
                execution.cancelled = True

    def _in_scope(self, entry):
        owner, event = entry.owner, self.event
        character = character_of(owner)
        if entry.blanked:
            return False
        if character is not None and (not character.is_alive or self._combat_effects_closed):
            return False
        if getattr(owner, "destroyed", False) or getattr(getattr(owner, "state", None), "name", "") == "NEGATED":
            return False
        if not entry.window_open:
            return False
        card = owner if kind_of(owner) == "card" else getattr(owner, "card", None)
        if card is not None and getattr(card, "destroyed", False):
            return False
        if (card is not None and card is getattr(event.get("die"), "card", None)
                and entry.trigger in ("before_dice_hit", "on_dice_hit", "after_dice_hit", OpCode.RESOLVE_HIT)):
            is_part = isinstance(entry.operation, dict) and entry.operation.get("damage_part")
            if event.get("hit_mode") == "damage_only" and not is_part:
                return False
            if event.get("hit_mode") == "effects_only" and is_part:
                return False
        player = getattr(character, "player", None)
        side = getattr(player, "side", None)
        if entry.scope == "die":
            return (owner is event.get("die") or owner is event.get("target")
                    or owner in self.side_active_dice(side))
        if entry.scope == "card":
            return card is not None and (card is event.get("card") or card is event.get("target")
                                         or card in self.side_active_cards(side))
        if entry.scope == "next_skill":
            return entry.next_card is not None and entry.next_card is event.get("card")
        if entry.scope == "duel" and card is not None:
            duel = event.get("duel")
            if entry in self._lasting_entries:
                return self._lasting_entries[entry][0] is duel
            return duel is not None and card in duel.all_side_cards(side)
        if entry.scope == "turn" and card is not None:
            return entry.turn_active
        return True

    def _matches(self, entry, *, ordering=False):
        if not self._in_scope(entry):
            return False
        if not entry.reentrant and any(frame.entry is entry for frame in self.executions):
            return False
        if entry.turn_limit:
            key = self._turn_limit_key(entry)
            if self.turn_entry_uses.get(key, 0) >= entry.turn_limit["count"]:
                return False
        event = self.event
        if not all(clause.matches(self, entry, ordering) for clause in entry.conditions):
            return False
        if entry.subject == "any":
            return True
        character = character_of(entry.owner)
        if entry.scope == "next_skill" and entry.next_card is not None:
            character = entry.next_card.character
        source, target = event.get("source"), event.get("target")
        subject = entry.subject
        if subject == "owner":
            if entry.trigger == OpCode.TURN_COST_ADD:
                return event["pool"] is character or event["pool"] is getattr(character, "player", None)
            if (entry.trigger_type == TriggerType.OPCODE
                    and entry.trigger in (OpCode.DRAW, OpCode.DISCARD, OpCode.RESET_COST, OpCode.NEXT_TURN_COST)
                    and event.get("player") is not None):
                return getattr(character, "player", None) is event["player"]
            if entry.trigger_type == TriggerType.OPCODE and entry.trigger in (
                    OpCode.DAMAGE, OpCode.RESOLVE_DAMAGE, OpCode.FINALIZE_DAMAGE, OpCode.LIGHTCORE_DAMAGE, OpCode.REAL_DAMAGE,
                    OpCode.CHECK_DEATH, OpCode.HEAL, OpCode.STATUS, OpCode.SPEND_STATUS, OpCode.ACTIVATE_STATUS, OpCode.SHIELD,
                    OpCode.ABILITY_EFFECT, OpCode.SPEND_ABILITY_EFFECT,
                    OpCode.DESTROY, OpCode.SET_STATUS_OVERFLOW, OpCode.NEXT_TURN_DUELS, OpCode.TURN_DUELS_ADD, OpCode.LOSE_HP):
                subject = "target"
            else:
                subject = "source"
        if subject == "source" and source is None:
            if "participants" in event:
                return character in event["participants"]
            side = event.get("side")
            return side is None or getattr(getattr(character, "player", None), "side", None) == side
        if subject == "source":
            return character is source
        if subject == "target":
            return character is (character_of(target) or target)
        if subject in ("ally", "enemy"):
            mine = getattr(character, "player", None)
            theirs = getattr(source, "player", None)
            if entry.trigger in (OpCode.RESET_COST, OpCode.NEXT_TURN_COST, OpCode.TURN_COST_ADD):
                theirs = event["player"]
            return mine is not None and theirs is not None and ((mine is theirs) == (subject == "ally"))
        raise ValueError(f"未知触发对象 {subject!r}")

    def _source_order(self, entry):
        char = character_of(entry.owner)
        player = getattr(char, "player", None)
        first = getattr(self.game, "first_player", None)
        first_rank = 0 if first is None or player is first else 1
        size = {"die": 0, "card": 1, "character": 2, "status": 2, "global": 3}.get(entry.origin, 3)
        src, dst = self.event.get("source"), self.event.get("target")
        status = entry.origin == "status"
        if char is not None and char is src:
            relation = 1 if status else 0
        elif char is not None and char is dst:
            relation = 3 if status else 2
        elif char is None:
            relation = 4
        elif getattr(src, "player", None) is player:
            relation = 7 if status else 5
        else:
            relation = 8 if status else 6
        party = getattr(player, "characters", [])
        return first_rank, size, relation, party.index(char) if char in party else 0

    def _dispatch(self, trigger_type, trigger, timing=None):
        matches = [entry for entry in self.entries
                   if entry.trigger_type == trigger_type and entry.trigger == trigger
                   and (timing is None or entry.timing == timing) and self._matches(entry, ordering=True)]
        # Entries on one source always retain their printed order. Only tied sources roll.
        groups = {}
        for entry in matches:
            groups.setdefault((id(entry.owner), entry.origin), []).append(entry)
        ranks = {}
        for group in groups.values():
            ranks.setdefault(self._source_order(group[0]), []).append(group)
        rng = getattr(self.game, "rng", random)
        die = self.event.get("die")
        suppress_increases = (timing == "BEFORE" and trigger in (
            OpCode.RESOLVE_DIE_LEVEL, OpCode.RESOLVE_ROLL_VALUE, OpCode.RESOLVE_FINAL_SCORE, OpCode.RESOLVE_CLASH_SCORE)
            and getattr(die, "increases_suppressed", False))
        for key in sorted(ranks):
            tied = ranks[key]
            if len(tied) > 1:
                rng.shuffle(tied)
            for group in tied:
                for entry in group:
                    if trigger == OpCode.RESOLVE_DAMAGE and timing == "BEFORE":
                        # Each listener sees the operand left by the preceding listener.
                        self.event.update(amount=self.peek(0), damage_amount=self.peek(0))
                    if entry in self.entries and self._matches(entry):
                        if not suppress_increases:
                            self._invoke(entry)
                            continue
                        before = self.peek(0)
                        bounds = self.event.get("value_ref")
                        floor = bounds.minimum if bounds else None
                        self._invoke(entry)
                        self.stack[-1] = min(before, self.peek(0))
                        if bounds:
                            bounds.minimum = min(floor, bounds.minimum)

    def _invoke(self, entry):
        invocation = EntryExecution(entry)
        self.executions.append(invocation)
        try:
            if entry.trigger != OpCode.ENTRY:
                with self.binding(execution=invocation, entry_trigger=entry.trigger, authority=entry.authority), self._pending(OpCode.ENTRY):
                    self.dispatch_opcode(OpCode.ENTRY, "BEFORE")
                    if self.current_op is None or invocation.cancelled:
                        return
            if entry.turn_limit:
                key = self._turn_limit_key(entry)
                used = self.turn_entry_uses.get(key, 0)
                if used >= entry.turn_limit["count"]:
                    return
                self.turn_entry_uses[key] = used + 1
            with self.binding(execution=self.event.get("execution", invocation)):
                # BEFORE programs can edit pending operands directly (e.g. a fee or
                # a score). A protected skill still lets the listener act on its own caster.
                protected_operands = (self.stack.copy() if self.event.get("timing") == "BEFORE"
                                      and self._protected_op(self.current_op, self.event) else None)
                try:
                    run_effect(self, entry, entry.compiled_operation)
                finally:
                    if protected_operands is not None:
                        self.stack[:] = protected_operands
            if entry.trigger != OpCode.ENTRY and not invocation.cancelled:
                with self.binding(execution=invocation, entry_trigger=entry.trigger):
                    self.dispatch_opcode(OpCode.ENTRY, "AFTER")
            if entry.group_name and not invocation.cancelled:
                actor = character_of(entry.owner)
                if actor is not None:
                    self.record("entry_resolved", side=actor.player.side, character_id=actor.id,
                                character_name=actor.name, group=entry.group_name)
            return True
        finally:
            self.executions.pop()

    def dispatch_opcode(self, opcode, timing):
        with self.binding(opcode=opcode.name, timing=timing, opcode_frame=len(self.op_stack) - 1):
            self._dispatch(TriggerType.OPCODE, opcode, timing)

    def dispatch_pipeline(self, node_id, *, valid=None, **fields):
        side, card, die = fields.get("side"), fields.get("card"), fields.get("die")
        fields["hit_die"] = die if node_id in ("on_dice_hit", "after_dice_hit") else None
        lane = fields.get("lane", "front")
        cards_map = self.rear_active_cards if lane == "rear" else self.active_cards
        dice_map = self.rear_active_dice if lane == "rear" else self.active_dice
        if node_id == "before_turn_end":
            self.game.turn_ending = True
            self.dispatch_pipeline("on_turn_closing", **fields)
        if node_id == "before_turn_start":
            self.game.open_turn()
        if self.scheduled_effects:
            deliver_scheduled(self, "pipeline", node_id, fields, valid)
        if valid is not None and not valid():
            return
        if node_id == "before_skill_use":
            cards_map[side] = card
        if node_id == "before_dice_use":
            dice_map[side] = die
        if node_id == "before_dice_hit":
            self.hit_modifiers[die] = []
        if die in self.hit_modifiers:
            fields["hit_modifiers"] = self.hit_modifiers[die]
        for e in self.entries:
            if e.blanked:
                continue
            if e.period and node_id == e.period.get("from") and self._window_owner(e, fields):
                e.window_open = True
            if (node_id == "before_skill_use" and e.owner is card
                    or node_id == "before_dice_use" and e.owner is die):
                e.turn_active = True
            if node_id == "before_skill_use" and e.scope == "next_skill" and e.next_armed and card is not None:
                if getattr(character_of(e.owner), "player", None) is card.player:
                    e.next_armed, e.next_card = False, card
        try:
            with self.binding(**fields, node_id=node_id):
                self._dispatch(TriggerType.PIPELINE, node_id)
            if node_id == "on_skill_use" and card is not None:
                card.use_effects_resolved = True
        finally:
            for e in self.entries[:]:
                if e.period and node_id == e.period.get("until") and self._window_owner(e, fields):
                    e.window_open = False
                if node_id == "after_turn_end":
                    e.turn_active = False
                if node_id == "after_skill_use" and e.scope == "next_skill" and card is not None:
                    if e.next_card is card:
                        e.next_card = None
                        if e.detached:
                            self.entries.remove(e)
                    if not e.blanked and (e.owner is card or getattr(e.owner, "card", None) is card):
                        e.next_armed = True
            if node_id == "after_skill_use":
                cards_map.pop(side, None)
            if node_id in ("after_dice_use", "on_clash_skip", "after_skill_use"):
                dice_map.pop(side, None)
            if node_id in ("after_dice_hit", "after_dice_use"):
                self.hit_modifiers.pop(die, None)
                self.roll_adjustments.pop(die, None)
            if node_id == "after_turn_end":
                self.expire_lasting_entries(None)
                self.hit_modifiers.clear()
                self.roll_adjustments.clear()
            if node_id in ("after_duel_end", "after_turn_end"):
                for active in (self.active_cards, self.active_dice, self.rear_active_cards, self.rear_active_dice):
                    if side is None:
                        active.clear()
                    else:
                        active.pop(side, None)

    @staticmethod
    def _window_owner(entry, fields):
        side = fields.get("side")
        char = character_of(entry.owner)
        if fields.get("source") is not None and entry.subject == "owner" and char is not None:
            return fields["source"] is char
        player = getattr(char, "player", None)
        return side is None or player is None or player.side == side

    def close_cancelled_use(self, side, card=None, die=None):
        if card is not None:
            for cards_map in (self.active_cards, self.rear_active_cards):
                if cards_map.get(side) is card:
                    cards_map.pop(side, None)
            for dice_map in (self.active_dice, self.rear_active_dice):
                if getattr(dice_map.get(side), "card", None) is card and die is None:
                    die = dice_map.get(side)
            for entry in self.entries[:]:
                if entry.next_card is card:
                    entry.next_card = None
                    if entry.detached:
                        self.entries.remove(entry)
        if die is not None:
            for dice_map in (self.active_dice, self.rear_active_dice):
                if dice_map.get(side) is die:
                    dice_map.pop(side, None)
            self.hit_modifiers.pop(die, None)
            self.roll_adjustments.pop(die, None)

    def _turn_limit_key(self, entry):
        original = self._lasting_entries[entry][1] if entry in self._lasting_entries else entry.owner
        return original, entry.turn_limit["key"]

    def withdraw_card_use(self, card, duel, used, *, scopes=("duel", "turn")):
        for execution in self.executions:
            if execution.entry.owning_card is card:
                execution.cancelled = True
        if not used:
            return
        # The original physical card can immediately be used again. Keep this
        # use's local values and its expiry attached to the old use alone.
        source = copy(card)
        source.use_state = card.use_state.copy()
        for entry in self.entries[:]:
            if (entry.owning_card is not card or entry.scope not in scopes
                    or not entry.turn_active or entry.blanked):
                continue
            retained = copy(entry)
            if entry.owner is card:
                retained.owner = source
            else:
                retained.owner = copy(entry.owner)
                retained.owner.card = source
            expires = duel if entry.scope == "duel" else None
            self._lasting_entries[retained] = (expires, entry.owner)
            self.entries.append(retained)
            entry.turn_active = False

    def expire_lasting_entries(self, duel):
        for entry, (expires, _) in list(self._lasting_entries.items()):
            if expires is duel:
                self.entries.remove(entry)
                del self._lasting_entries[entry]

    def deal_damage(self, source, target, amount, penetration="normal", attack_type="none",
                    damage_part=False, damage_cause=None, *, result_field="result", modified=False, **fields):
        """Read the amount, HP loss, or a success flag from this direct damage segment."""
        no_result = False if result_field in ("damage_dealt", "damage_received") else 0
        if target is None or not target.is_alive or (self.executions and self.executions[-1].cancelled):
            return no_result
        authority = self.executions[-1].entry.authority if self.executions else 0
        with self.binding(source=source, target=target, damage_part=damage_part,
                          damage_cause=damage_cause, authority=authority):
            self.stack.extend((target, amount, GRADES[penetration], attack_type))
            result = self.execute_op(OpCode.DAMAGE, result_field=result_field, damage_precomputed=modified,
                                     damage_cause=damage_cause, **fields)
            return no_result if result is None else result

    def resolve_hit(self, die, target, **fields):
        if not (die.is_attack or fields.get("simultaneous_solo") and die.is_passive):
            return
        card = die.card
        source = card.character
        with self.binding(**{**fields, "source": source, "target": target, "die": die, "card": card,
                              "hit_modifiers": self.hit_modifiers.get(die, [])}):
            return self.eval_block([die, target, OpCode.RESOLVE_HIT])

    def execute_hit_parts(self, die, target):
        """Report whether the die landed, independently of HP lost to its damage parts."""
        card = die.card
        source = card.character
        if (not (die.is_attack or self.event.get("simultaneous_solo") and die.is_passive)
                or not target.is_alive or not source.is_alive or die.destroyed or card.destroyed):
            return False
        self.event["hit_die"] = die
        mode = self.event.get("hit_mode")
        index = self.event.get("hit_index") or 1
        self.record("hit", source=source.combat_name, target=target.combat_name, card=card.name,
                    mode=mode or "full", index=index)
        source.on_attack_hit(die, target)
        for text in die.entries or ():
            if not target.is_alive or not source.is_alive or die.destroyed or card.destroyed:
                break
            if isinstance(text, dict):
                continue
            part = damage_part(text)
            if mode == "effects_only" and (part or independent_damage_part(text)):
                continue
            if part:
                bit = {"op": "damage", "amount": part[0], "grade": part[1], "damage_part": True}
                self._invoke(Entry(die, TriggerType.PIPELINE, "damage_part", bit))
            elif mode != "damage_only" or independent_damage_part(text):
                self._invoke(Entry(die, TriggerType.PIPELINE, "on_dice_hit", text))
        return True
