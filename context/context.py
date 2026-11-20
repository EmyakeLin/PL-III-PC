from collections import deque
from contextlib import contextmanager
from copy import copy
import random

from entry.effects import GRADES, damage_part, run_effect
from entry.entry import Entry, EntryExecution, TriggerType, character_of, kind_of
from models.opcode import OpCode
from models.opcodes import DISPATCH_TABLE, OPERANDS, VALUE_RESOLVERS
from models.values import ValueBounds
from pipeline.pipeline_errors import PipelineSystemError, StackUnderflowError


class Context:
    def __init__(self, parent=None, game=None):
        self.parent = parent
        self.game = parent.game if parent else game
        self.stack = []
        self.entries = []
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
        self.hit_modifiers = {}
        self.roll_adjustments = {}
        # Entries whose printed duration outlives the physical card's return to hand.
        self._lasting_entries = {}

    @property
    def current_op(self):
        return self.op_stack[-1] if self.op_stack else None

    @current_op.setter
    def current_op(self, value):
        if self.op_stack:
            self.op_stack[-1] = value

    def cancel_op(self, authority=None, *, frame=-1):
        if (self.op_stack and not self._range_blocks_op(self.op_stack[frame], self._op_events[frame])
                and (authority is None or authority >= self._op_events[frame].get("authority", 0))):
            self.op_stack[frame] = None

    def range_blocks_target(self, target):
        """Use the actual originating skill; character and status passives remain independent."""
        card = self.executions[-1].entry.owning_card if self.executions else None
        if card is None or not card.range_deficit or card.range_opponent is None:
            return False
        if isinstance(target, EntryExecution):
            target = target.entry.owner
        protected = card.range_opponent.character
        return character_of(target) is protected or target is protected.player

    def _range_blocks_op(self, opcode, fields):
        if not self.executions:
            return False
        if opcode == OpCode.ENTRY:
            return self.range_blocks_target(fields.get("execution"))
        if opcode == OpCode.CLASH:
            return any(self.range_blocks_target(die) for die in fields["clash_pair"].dice_dict.values())
        if opcode == OpCode.SPLIT_CLASH:
            pair = self.game.pipeline.current_clash_pair
            return pair is not None and any(self.range_blocks_target(die) for die in pair.dice_dict.values())
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

    def execute_op(self, opcode, *, result_field="result", **fields):
        """Run one hooked operation and read a result field from its own event."""
        names = OPERANDS.get(opcode, ())
        if len(self.stack) < len(names):
            raise StackUnderflowError(f"{opcode.name} 参数不足")
        mark = len(self.stack) - len(names)
        fields.update(zip(names, self.stack[mark:]))
        originating_entry = self.executions[-1] if self.executions else None
        if self._range_blocks_op(opcode, fields) or (
                opcode == OpCode.RESOLVE_HIT and getattr(fields["die"].card, "range_deficit", 0)):
            del self.stack[mark:]
            return None
        if originating_entry is not None:
            fields["execution"] = originating_entry
        if opcode == OpCode.RESOLVE_RANGE_DEFICIT:
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
        elif opcode == OpCode.PAY_COST:
            card = fields["card"]
            fields.update(source=card.character, player=card.player, side=card.player.side)
        elif opcode in (OpCode.RESET_COST, OpCode.NEXT_TURN_COST):
            fields.update(source=None, side=fields["player"].side)
        elif opcode == OpCode.TURN_COST_ADD:
            pool = fields["pool"]
            player = getattr(pool, "player", pool)
            fields.update(player=player, source=None if pool is player else pool, side=player.side)
        elif opcode == OpCode.SPEND_STATUS:
            actor = fields["target"]
            fields.update(source=actor, side=actor.player.side)
        elif opcode in (OpCode.SKILL_FINAL_ADD, OpCode.SKILL_LEVEL_ADD, OpCode.SET_SKILL_STATE,
                        OpCode.DIE_FINAL_ADD, OpCode.DIE_LEVEL_ADD, OpCode.REPEAT_DIE, OpCode.ROUTE_DIE_ATTACK):
            part = fields.get("die") or fields["card"]
            actor = character_of(part)
            fields.update(source=actor, side=actor.player.side if actor else None)
            if "die" in fields:
                fields["card"] = part.card
        elif opcode in (OpCode.QUEUE_STATUS, OpCode.NEXT_TURN_DUELS, OpCode.TURN_DUELS_ADD, OpCode.LOSE_HP):
            fields.setdefault("source", self.event.get("source") or fields["target"])
            fields["side"] = fields["source"].player.side
            if opcode == OpCode.LOSE_HP:
                fields.update(damage_amount=None, hp_lost=None, result=None)
        elif opcode in (OpCode.DAMAGE, OpCode.RESOLVE_DAMAGE):
            if fields["target"] == "target":
                fields["target"] = self.event.get("target")
            # Nested damage has its own measurements, even inside an AFTER DAMAGE listener.
            fields.update(result=None, hp_lost=None)
            if opcode == OpCode.DAMAGE:
                fields.setdefault("damage_precomputed", False)
                fields.update(base_amount=fields["amount"], damage_amount=None)
                fields["modifiers"] = list(self.event.get("hit_modifiers", ())) if self.event.get("damage_part") else []
            else:
                fields["damage_amount"] = fields["amount"]
        with self.binding(**fields) as event, self._pending(opcode):
            self.dispatch_opcode(opcode, "BEFORE")
            if self.current_op is None or (originating_entry is not None and originating_entry.cancelled):
                del self.stack[mark:]
                return None
            handler = DISPATCH_TABLE.get(self.current_op)
            if handler is None:
                raise PipelineSystemError(f"未实现的操作码: {self.current_op}")
            executed_op = self.current_op
            result = handler(self)
            if self.current_op is None:
                return None
            event["result"] = result
            self.dispatch_opcode(executed_op, "AFTER")
            return event.get(result_field)

    def register_entries(self, owner, specs):
        """Instantiate a character's passives, a card's entries or a die's entries."""
        if getattr(owner, "type", None) == "blank" and kind_of(owner) == "die":
            return []
        registered = []
        for spec in specs or ():
            if isinstance(spec, dict) and "entries" in spec and "trigger" not in spec:
                registered.extend(self.register_entries(owner, spec["entries"]))
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

    def _in_scope(self, entry):
        owner, event = entry.owner, self.event
        character = character_of(owner)
        if entry.blanked:
            return False
        if character is not None and not character.is_alive:
            return False
        if getattr(owner, "destroyed", False) or getattr(getattr(owner, "state", None), "name", "") == "NEGATED":
            return False
        if not entry.window_open:
            return False
        card = owner if kind_of(owner) == "card" else getattr(owner, "card", None)
        if card is not None and getattr(card, "destroyed", False):
            return False
        player = getattr(character, "player", None)
        side = getattr(player, "side", None)
        if entry.scope == "die":
            return (owner is event.get("die") or owner is event.get("target")
                    or owner is self.active_dice.get(side))
        if entry.scope == "card":
            return card is not None and (card is event.get("card") or card is event.get("target")
                                         or card is self.active_cards.get(side))
        if entry.scope == "next_skill":
            return entry.next_card is not None and entry.next_card is event.get("card")
        if entry.scope == "duel" and card is not None:
            duel = event.get("duel")
            if entry in self._lasting_entries:
                return self._lasting_entries[entry][0] is duel
            return duel is not None and card in duel.content.get(side, ())
        if entry.scope == "turn" and card is not None:
            return entry.turn_active
        return True

    def _matches(self, entry, *, ordering=False):
        if not self._in_scope(entry):
            return False
        if any(frame.entry is entry for frame in self.executions):
            return False
        if entry.turn_limit:
            key = self._turn_limit_key(entry)
            if self.turn_entry_uses.get(key, 0) >= entry.turn_limit["count"]:
                return False
        event = self.event
        for key, value in entry.when.items():
            if key == "die_type":
                if getattr(event.get("die"), "type", None) != value:
                    return False
            elif key in ("owner_status_at_least", "target_status_at_least"):
                actor = character_of(entry.owner) if key.startswith("owner") else event.get("target")
                statuses = getattr(actor, "statuses", {})
                if any(statuses.get(name, 0) < minimum for name, minimum in value.items()):
                    return False
            elif key in ("owner_hp_at_most", "target_hp_at_most"):
                actor = character_of(entry.owner) if key.startswith("owner") else event.get("target")
                if actor is None or not hasattr(actor, "hp") or actor.hp > value:
                    return False
            elif key in ("amount_at_least", "result_at_least", "damage_amount_at_least", "hp_lost_at_least"):
                actual = event.get(key.removesuffix("_at_least"))
                pending_amount = key == "amount_at_least" or (key == "damage_amount_at_least"
                                                             and entry.trigger == OpCode.RESOLVE_DAMAGE)
                if pending_amount and entry.trigger_type == TriggerType.OPCODE and entry.timing == "BEFORE":
                    operands = OPERANDS.get(entry.trigger, ())
                    if "amount" in operands:
                        # Earlier listeners can replace a fixed price with "all" or vice versa.
                        if ordering:
                            continue
                        actual = self.peek(len(operands) - 1 - operands.index("amount"))
                if not isinstance(actual, (int, float)) or actual < value:
                    return False
            elif event.get(key) != value:
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
                    OpCode.DAMAGE, OpCode.RESOLVE_DAMAGE, OpCode.CHECK_DEATH, OpCode.HEAL, OpCode.STATUS, OpCode.SPEND_STATUS, OpCode.SHIELD,
                    OpCode.DESTROY, OpCode.QUEUE_STATUS, OpCode.NEXT_TURN_DUELS, OpCode.TURN_DUELS_ADD, OpCode.LOSE_HP):
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
                        self._invoke(entry)

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
                                      and self._range_blocks_op(self.current_op, self.event) else None)
                try:
                    run_effect(self, entry, entry.operation)
                finally:
                    if protected_operands is not None:
                        self.stack[:] = protected_operands
            if entry.trigger != OpCode.ENTRY and not invocation.cancelled:
                with self.binding(execution=invocation, entry_trigger=entry.trigger):
                    self.dispatch_opcode(OpCode.ENTRY, "AFTER")
        finally:
            self.executions.pop()

    def dispatch_opcode(self, opcode, timing):
        with self.binding(opcode=opcode.name, timing=timing, opcode_frame=len(self.op_stack) - 1):
            self._dispatch(TriggerType.OPCODE, opcode, timing)

    def dispatch_pipeline(self, node_id, **fields):
        side, card, die = fields.get("side"), fields.get("card"), fields.get("die")
        if node_id == "before_turn_start":
            self.game.open_turn()
        if node_id == "before_skill_use":
            self.active_cards[side] = card
        if node_id == "before_dice_use":
            self.active_dice[side] = die
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
                self.active_cards.pop(side, None)
            if node_id in ("after_dice_use", "on_clash_skip", "after_skill_use"):
                self.active_dice.pop(side, None)
            if node_id in ("after_dice_hit", "after_dice_use"):
                self.hit_modifiers.pop(die, None)
                self.roll_adjustments.pop(die, None)
            if node_id == "after_turn_end":
                self.expire_lasting_entries(None)
                self.hit_modifiers.clear()
                self.roll_adjustments.clear()
            if node_id in ("after_duel_end", "after_turn_end"):
                for active in (self.active_cards, self.active_dice):
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
            if self.active_cards.get(side) is card:
                self.active_cards.pop(side, None)
            if getattr(self.active_dice.get(side), "card", None) is card:
                die = self.active_dice.get(side)
            for entry in self.entries[:]:
                if entry.next_card is card:
                    entry.next_card = None
                    if entry.detached:
                        self.entries.remove(entry)
        if die is not None:
            if self.active_dice.get(side) is die:
                self.active_dice.pop(side, None)
            self.hit_modifiers.pop(die, None)
            self.roll_adjustments.pop(die, None)

    def _turn_limit_key(self, entry):
        original = self._lasting_entries[entry][1] if entry in self._lasting_entries else entry.owner
        return original, entry.turn_limit["key"]

    def withdraw_card_use(self, card, duel, used):
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
            if (entry.owning_card is not card or entry.scope not in ("duel", "turn")
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
        """Return this damage part's resolved amount, or its HP loss with result_field="hp_lost"."""
        if target is None or not target.is_alive or (self.executions and self.executions[-1].cancelled):
            return 0
        authority = self.executions[-1].entry.authority if self.executions else 0
        with self.binding(**{**fields, "source": source, "target": target,
                              "damage_part": damage_part, "damage_cause": damage_cause, "authority": authority}):
            self.stack.extend((target, amount, GRADES[penetration], attack_type))
            return self.execute_op(OpCode.DAMAGE, result_field=result_field, damage_precomputed=modified) or 0

    def resolve_hit(self, die, target, **fields):
        if not (die.is_attack or fields.get("simultaneous_solo") and die.is_passive):
            return
        card = die.card
        source = card.character
        with self.binding(**{**fields, "source": source, "target": target, "die": die, "card": card,
                              "hit_modifiers": self.hit_modifiers.get(die, [])}):
            self.eval_block([die, target, OpCode.RESOLVE_HIT])

    def execute_hit_parts(self, die, target):
        """Report whether the die landed, independently of HP lost to its damage parts."""
        card = die.card
        source = card.character
        if (not (die.is_attack or self.event.get("simultaneous_solo") and die.is_passive)
                or not target.is_alive or not source.is_alive or die.destroyed or card.destroyed):
            return False
        source.on_attack_hit(die, target)
        for text in die.entries or ():
            if not target.is_alive or not source.is_alive or die.destroyed or card.destroyed:
                break
            if isinstance(text, dict):
                continue
            part = damage_part(text)
            if part:
                bit = {"op": "damage", "amount": part[0], "grade": part[1], "damage_part": True}
                self._invoke(Entry(die, TriggerType.PIPELINE, "damage_part", bit))
            else:
                self._invoke(Entry(die, TriggerType.PIPELINE, "on_dice_hit", text))
        return True
