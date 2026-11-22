from collections import Counter
from enum import Enum, auto
from math import prod
import random

from models.card import Card
from models.dice import Dice, DiceLevel, dice_value_range
from models.opcode import OpCode
from models.values import ValueBounds


class CharacterRank(Enum):
    NORMAL = auto()
    ELITE = auto()
    BOSS = auto()
    EMPOWERED_BOSS = auto()


class SpeedDie(Dice):
    """An initiative die uses the same level ladder as combat dice."""

    def __init__(self, owner, high):
        grade = next((level for level, bounds in dice_value_range.items() if bounds[1] >= high), DiceLevel.D20)
        super().__init__({"type": "blank", "level": grade.value, "roll_max": high}, owner.game)
        self.owner = self.character = owner


RANK_DUEL_MAP = dict(zip(CharacterRank, (1, 2, 3, 4)))
RANK_SKILL_COUNT = dict(zip(CharacterRank, (3, 5, 7, 11)))
SHIELD_FIELDS = {
    "normal": "shield", "shield": "shield", "护盾": "shield", "普通护盾": "shield",
    "reinforced": "reinforced_shield", "强化护盾": "reinforced_shield",
    "concept": "concept_shield", "概念护盾": "concept_shield",
}
DAMAGE_GRADES = {
    "normal": "normal", "普通": "normal", "普通伤害": "normal",
    "pierce": "pierce", "piercing": "pierce", "armor_piercing": "pierce", "穿甲": "pierce",
    "concept": "concept", "super_armor_piercing": "concept", "超穿甲": "concept",
}


class Character:
    def __init__(self, data, player):
        self.player = player
        self.game = getattr(player, "game", None)
        self.data = data
        self.faction = data.get("faction", "")
        self.id = data["id"]
        self.name = data["name"]
        self.rank = CharacterRank[data["rank"]]
        self.turn_duel_bonus = 0
        self.next_turn_duels = 0
        self.won_clash_this_turn = False
        self.speed = 0
        self.original_max_hp = data["max_hp"]
        self._base_max_hp = self.original_max_hp
        self._status_max_hp_delta = 0
        self.max_lightcore_hp = self.initial_lightcore_max(self.original_max_hp)
        self.lightcore_hp = self.max_lightcore_hp
        self.passive_skill_data = data.get("passive_skills", [])
        self.passive_skills = self.passive_skill_data
        self.skill_data = data["skills"]
        self.skills = []
        self.conditional_cards = []
        self.hp = self.max_hp
        self.is_alive = True
        self.used_duels = 0
        self.reset_shields()
        self.independent_cost = 0
        self.used_independent_cost = 0
        self.turn_cost_adjustment = 0
        self.statuses = {}
        self.ability_effects = {}
        self.reserved_dice = []
        self.rule_state = {}
        self.status_overflow = {}
        # While a status supplies stacks, keep the ordinary stacks independently
        # so expiring the turn or removing the source only removes its own part.
        self._ordinary_stacks = {}
        self._sustained_stacks = {}
        self._status_listeners = {}
        self.activating_statuses = set()
        self.active_statuses = set()
        self.round_triggers = Counter()
        if self.game:
            self._effect_context = self.game.context
            self.game.status_entries.update(data.get("status_entries", {}))
            self.game.status_rules.update(data.get("status_rules", {}))
            self.game.ability_rules.update(data.get("ability_rules", {}))
            self.game.turn_end_statuses.update(data.get("turn_end_statuses", ()))
            self.game.context.register_entries(self, self.passive_skill_data)
            player.register_faction_passives(self)
        else:
            from context.context import Context
            from loader import base_effects

            shared = base_effects()
            self._effect_context = Context()
            self._standalone_status_rules = {**shared.status_rules, **data.get("status_rules", {})}
            self._standalone_status_entries = {**shared.status_entries, **data.get("status_entries", {})}
            self._standalone_ability_rules = {**shared.ability_rules, **data.get("ability_rules", {})}

    @property
    def max_hp(self):
        return max(0, self._base_max_hp + self._status_max_hp_delta)

    @max_hp.setter
    def max_hp(self, value):
        self._base_max_hp = value - self._status_max_hp_delta

    @property
    def max_duels(self):
        return max(0, self.base_duels(self.data) + self.turn_duel_bonus)

    @property
    def combat_name(self):
        if self.game and any(c is not self and c.name == self.name
                             for player in self.game.players for c in player.characters):
            return f"{self.player.name}的{self.name}"
        return self.name

    @staticmethod
    def initial_lightcore_max(original_max_hp):
        return ((original_max_hp + 2) // 3) * 4 + 4

    @staticmethod
    def base_duels(data):
        return data.get("base_max_duels", RANK_DUEL_MAP[CharacterRank[data["rank"]]])

    @property
    def available_cost(self):
        return self.independent_cost + self.turn_cost_adjustment - self.used_independent_cost

    def queue_status(self, name, amount, source=None):
        """Apply an already scheduled status before next turn's draw and speed roll."""
        if self.is_alive and name not in self.ability_rules:
            source = self if source is None else source
            authority = self.game.context.event.get("authority", 0)
            self.game.next_turn_statuses.append((source, self, name, amount, authority))

    def roll_speed(self):
        low, high = self.data.get("speed_die", (1, 4))
        die = SpeedDie(self, high)
        ctx = self.game.context
        minimum = ValueBounds()
        ctx.dispatch_pipeline("before_speed_roll", source=self, side=self.player.side, die=die,
                              value_ref=minimum, printed_min=low, roll_kind="speed")
        high = die.roll_max
        low = min(high, max(1, minimum.apply(low)))
        with ctx.binding(roll_kind="speed"):
            rolled = ctx.eval_block([low, high, 0, die, OpCode.ROLL])
        raw = min(high, max(low, die.value)) if rolled is not None else 0
        self.speed = raw + self.status_modifier("speed")
        return self.speed

    def status_modifier(self, value):
        """Read continuous per-stack adjustments without triggering effects in a preview."""
        rules = self.status_rules
        return sum(count * rules.get(name, {}).get("per_stack", {}).get(value, 0)
                   for name, count in self.statuses.items())

    def init_cards(self):
        self.skills = [Card(self.player, skill, self) for skill in self.skill_data]

    def setup_deck(self):
        for card in self.skills:
            zone = self.player.cardspace.out_of_combat if card.out_of_combat else self.player.cardspace.draw
            zone.add_card(card)

    def reset_shields(self):
        self.shield = self.reinforced_shield = self.concept_shield = 0

    def combat_summary(self):
        parts = [f"{self.name}　生命 {self.hp}/{self.max_hp}", f"完整度 {self.lightcore_hp}/{self.max_lightcore_hp}"]
        for label, value in (("护盾", self.shield), ("强化护盾", self.reinforced_shield),
                             ("概念护盾", self.concept_shield)):
            if value:
                parts.append(f"{label} {value}")
        for label, value in self.statuses.items():
            if label in self.active_statuses:
                label = self.status_rules[label].get("active_label", label)
            parts.append(f"{label} {value}")
        for name, amount in self.status_overflow.items():
            threshold = self.status_rules[name]["overflow_batch"]["threshold"]
            parts.append(f"{name}溢出 {amount}/{threshold}")
        parts.extend(f"能力 {label} {count}次" for label, count in self.ability_effects.items())
        parts.extend(f"迎击「{reply.card.name}」第{reply.position}骰 ×{reply.remaining}"
                     for reply in self.reserved_dice)
        return " · ".join(parts)

    def add_shield(self, kind, amount):
        field = SHIELD_FIELDS[kind]
        value = max(0, getattr(self, field) + int(amount))
        setattr(self, field, value)
        return value

    @property
    def ability_rules(self):
        return self.game.ability_rules if self.game else self._standalone_ability_rules

    def add_ability_effect(self, name, amount):
        return self._effect_context.eval_block([self, name, amount, OpCode.ABILITY_EFFECT])

    def apply_ability_delta(self, name, amount):
        if name not in self.ability_rules or not self.is_alive:
            return 0
        remaining = max(0, self.ability_effects.get(name, 0) + amount)
        if remaining:
            self.ability_effects[name] = remaining
        else:
            self.ability_effects.pop(name, None)
        return remaining

    def ability_permission(self, permission):
        return next((name for name in self.ability_effects
                     if self.ability_rules[name].get("permission") == permission), None)

    def spend_ability_effect(self, name, amount=1):
        ctx = self._effect_context
        ctx.stack.extend((self, name, amount))
        return bool(ctx.execute_op(OpCode.SPEND_ABILITY_EFFECT, require_full=True, result_field="paid_in_full"))

    def expire_turn_abilities(self):
        for name in tuple(self.ability_effects):
            if name in self.ability_effects and self.ability_rules[name].get("turn_end"):
                count = self.ability_effects.pop(name)
                self._effect_context.dispatch_pipeline("on_ability_expired", source=self, target=self,
                                                       side=self.player.side, ability=name, status=None, amount=count)

    def action_specs(self):
        yield from self.data.get("actions", ())
        for name in self.ability_effects:
            action = self.ability_rules[name].get("action")
            if action:
                yield action

    def add_status(self, name, amount):
        """Apply a status through the same listeners as a card or delayed effect."""
        name = self.canonical_status_name(name)
        return self._effect_context.eval_block([self, name, amount, OpCode.STATUS])

    @property
    def status_rules(self):
        return self.game.status_rules if self.game else self._standalone_status_rules

    def canonical_status_name(self, name):
        if name == "energy":
            return "能源"
        if name in self.status_rules:
            return name
        return next((label for label, rule in self.status_rules.items() if name in rule.get("aliases", ())), name)

    @property
    def bleed_burst(self):
        """Compatibility field for the original public battle snapshot."""
        return self.canonical_status_name("bleed") in self.active_statuses

    def status_cap(self, name):
        global_cap = self.status_rules.get(name, {}).get("cap")
        personal = self.data.get("resource_rules", {}).get("caps", {}).get(name)
        if global_cap is None:
            return personal
        return min(global_cap, personal) if personal is not None else global_cap

    def _ordinary_status(self, name):
        return self._ordinary_stacks.get(name, self.statuses.get(name, 0))

    def spendable_status(self, name):
        return 0 if self.status_rules.get(name, {}).get("permanent") else self._ordinary_status(name)

    def skill_restricted(self, card):
        """A hand play keeps its cost rank for its pending use, including face-down placement."""
        if not card.meets_use_requirements():
            return True
        limit = max((self.statuses.get(name, 0) for name, rule in self.status_rules.items()
                     if rule.get("restrict_highest_hand_cost")), default=0)
        if not limit:
            return False
        hand = self.player.cardspace.hand
        rank = hand.cost_rank(card) if card in hand.content else card.hand_cost_rank
        return rank is not None and rank <= limit

    def apply_status_delta(self, name, amount, *, notify=True, defer_effects=False):
        """Commit a resolved STATUS or SPEND_STATUS and bind entries to its holder."""
        if not self.is_alive or name in self.ability_rules:
            return 0
        name = self.canonical_status_name(name)
        rule = self.status_rules.get(name, {})
        required = rule.get("requires_status")
        if required and not self.statuses.get(required) and not defer_effects:
            return 0
        amount = int(amount)
        if amount < 0 and rule.get("permanent"):
            return self.statuses.get(name, 0)
        cap = self.status_cap(name)
        if amount > 0 and cap is not None:
            accepted = min(amount, max(0, cap - self.statuses.get(name, 0)))
            if accepted < amount and "overflow_batch" in rule:
                self.status_overflow[name] = self.status_overflow.get(name, 0) + amount - accepted
            amount = accepted
        return self._set_status(name, max(0, self._ordinary_status(name) + amount),
                                self._sustained_stacks.get(name, 0), notify=notify, defer_effects=defer_effects)

    def _set_status(self, name, ordinary, sustained, *, notify=True, defer_effects=False):
        previous = self.statuses.get(name, 0)
        if sustained:
            self._ordinary_stacks[name] = ordinary
            self._sustained_stacks[name] = sustained
        else:
            self._ordinary_stacks.pop(name, None)
            self._sustained_stacks.pop(name, None)
        cap = self.status_cap(name)
        value = ordinary + sustained if cap is None else min(cap, ordinary + sustained)
        if value:
            self.statuses[name] = value
            definitions = self.game.status_entries if self.game else self._standalone_status_entries
            if not previous and name in definitions:
                listeners = self._effect_context.register_entries(self, definitions[name])
                for listener in listeners:
                    listener.origin, listener.status_name = "status", name
                self._status_listeners[name] = listeners
        else:
            self.statuses.pop(name, None)
            listeners = self._status_listeners.pop(name, ())
            if listeners:
                entries = self._effect_context.entries
                entries[:] = [entry for entry in entries if entry not in listeners]
        threshold = self.status_rules.get(name, {}).get("active_from")
        if threshold is not None and value >= threshold:
            self.active_statuses.add(name)
        elif not value:
            self.active_statuses.discard(name)
        if not defer_effects:
            self.finish_status_change(name, previous, value, notify=notify)
        return value

    def finish_status_change(self, name, previous, value, *, notify=True):
        """Resolve dependent statuses and notify listeners after committing the new balance."""
        cap_delta = (value - previous) * self.status_rules.get(name, {}).get("max_hp_per_stack", 0)
        if cap_delta:
            self._status_max_hp_delta += cap_delta
            self.hp = min(self.hp, self.max_hp)
            self.check_death()
        if bool(previous) != bool(value):
            for card in self.conditional_cards:
                if card.printed_data["form_when"]["status"] == name:
                    card.refresh_status_form()
            for other, count in self.status_rules.get(name, {}).get("sustain", {}).items():
                grants = self._sustained_stacks.get(other, 0) + (count if value else -count)
                self._set_status(other, self._ordinary_status(other), grants)
            if not value:
                for other, rule in self.status_rules.items():
                    if rule.get("requires_status") == name and self.statuses.get(other):
                        self.clear_status(other)
        if notify:
            self.notify_status_change(name, previous, value)

    def notify_status_change(self, name, previous, current):
        if previous != current:
            duel = self.game.resolving_duel if self.game is not None else None
            if duel is not None and current < previous:
                key = self.player.side, name
                duel.status_lost[key] = duel.status_lost.get(key, 0) + previous - current
            self._status_event("on_status_changed", status=name, previous_stacks=previous,
                               current_stacks=current, actual_delta=current - previous)

    def clear_status(self, name):
        """Expire ordinary stacks; ongoing contributions live as long as their sources."""
        if not self.status_rules.get(name, {}).get("permanent"):
            self._set_status(name, 0, self._sustained_stacks.get(name, 0))

    def begin_dice_round(self):
        # An interrupt retains the outer round's counter until it resumes.
        self.round_triggers = Counter()

    def damage_multiplier(self):
        return prod(self.status_rules.get(name, {}).get("incoming_damage_multiplier", 1) for name in self.statuses)

    def _status_event(self, event, **fields):
        if self.is_alive:
            self._effect_context.dispatch_pipeline(event, source=self, target=self, side=getattr(self.player, "side", None),
                                                   damage_part=False, hit_modifiers=(), **fields)

    def on_duel_start(self):
        self._status_event("on_character_duel_start")

    def after_damage_part(self):
        self._status_event("after_damage_part")

    def _roll_status_check(self, event):
        """A status pack defines the die and the consequences of checking its stacks."""
        from entry.entry import Entry

        if not self.is_alive:
            return False
        for name, rule in self.status_rules.items():
            check = rule.get("check")
            if not check or check["event"] != event:
                continue
            stacks = self.statuses.get(name, 0)
            if not stacks and "failure" not in check:
                continue
            passed = getattr(self.game, "rng", random).randint(1, check["sides"]) <= stacks
            outcome = check.get("success" if passed else "failure")
            if outcome:
                entry = Entry.from_spec(self, {"trigger": event, "operation": outcome, "origin": "status"})
                with self._effect_context.binding(source=self, target=self, damage_part=False):
                    self._effect_context._invoke(entry)
            if passed:
                return True
        return False

    def on_attack_hit(self, die, target):
        die.critical = self._roll_status_check("critical")
        if die.critical and self.game:
            print(f"{self.name} 触发暴击。")
            self.game.context.dispatch_pipeline("on_critical", source=self, target=target,
                                                side=self.player.side, card=die.card, die=die)
        return die.critical

    def trigger_stagger(self):
        return self._roll_status_check("stagger")

    def on_turn_end(self):
        self._status_event("on_character_turn_end")

    def heal(self, amount):
        if not self.is_alive or amount <= 0:
            return 0
        old_hp = self.hp
        self.hp = min(self.max_hp, self.hp + int(amount))
        recovered = self.hp - old_hp
        if recovered > 0 and old_hp >= self.max_lightcore_hp:
            # An actual heal at or above the integrity cap is unconditional death.
            self.hp = 0
            self._die()
            if self.game and self.game.is_over:
                self.game.context.close_combat_effects()
        return recovered

    def lose_hp(self, amount):
        if not self.is_alive or amount <= 0:
            return 0
        lost = min(self.hp, amount)
        self.hp -= lost
        self.check_death()
        return lost

    def take_damage(self, amount, penetration="normal", attack_type="none", *,
                    modified=False, damage_cause=None, result_field="result"):
        """Resolve independent damage and return the requested measurement."""
        if result_field not in ("result", "hp_lost", "damage_dealt", "damage_received"):
            raise ValueError(f"未知伤害结果字段 {result_field!r}")
        if not self.is_alive:
            return False if result_field in ("damage_dealt", "damage_received") else 0
        grade = DAMAGE_GRADES[getattr(penetration, "name", str(penetration)).lower()]
        return self._effect_context.deal_damage(self, self, amount, grade, attack_type,
                                                damage_cause=damage_cause, damage_die=None, modified=modified,
                                                result_field=result_field)

    def apply_resolved_damage(self, incoming, grade):
        """Settle a resolved damage amount against shields and return the HP lost to this hit."""
        if not self.is_alive or incoming <= 0:
            return 0
        remaining = incoming
        # A shield below the incident grade wears down even when it cannot absorb damage.
        if grade == "concept":
            absorb = ("concept_shield",)
            erode = ("shield", "reinforced_shield")
        elif grade == "pierce":
            absorb = ("reinforced_shield",)
            erode = ("shield",)
        else:
            absorb = ("reinforced_shield", "shield")
            erode = ()
        for field in absorb:
            blocked = min(getattr(self, field), remaining)
            setattr(self, field, getattr(self, field) - blocked)
            remaining -= blocked
        for field in erode:
            setattr(self, field, max(0, getattr(self, field) - incoming))
        lost = min(self.hp, remaining)
        self.hp -= lost
        self._status_event("on_direct_damage_applied")
        self.check_death()
        return lost

    def check_death(self):
        """At zero HP, allow death prevention before retiring cards and checking victory."""
        if self.is_alive and self.hp == 0:
            if self.game:
                self.game.context.eval_block([self, OpCode.CHECK_DEATH])
            else:
                self._die()

    def _die(self):
        self.is_alive = False
        if not self.game:
            return
        self.game.context.unregister_entries(self)
        self._status_listeners.clear()
        self.player.retire_faction_passives(self)
        zones = self.player.cardspace
        removed = list(self.skills)
        hand_changes = []
        for player in self.game.players:
            spaces = player.cardspace
            hand = spaces.hand
            before = len(hand.content)
            taken = hand.remove_character(self, notify=False)
            if taken:
                hand_changes.append((hand, before, len(hand.content)))
                removed.extend(taken)
            for pile in (spaces.draw, spaces.delayed_discard):
                removed.extend(pile.remove_character(self))
        for slot in self.game.board_slots():
            for card in slot.remove_character(self):
                if card.character is not card.printed_owner:
                    self.game.pipeline.withdraw_skill(slot, card)
                removed.append(card)
        for card in dict.fromkeys(removed):
            if card.printed_owner is not self:
                card.return_to_printed_owner()
                card.player.cardspace.draw.add_card(card)
                continue
            card.set_controller(self)
            card.destroyed = True
            self.game.context.unregister_entries(card)
            for die in card.instantiated_dice or ():
                if die:
                    die.destroyed = True
                    self.game.context.unregister_entries(die)
            if card not in zones.out_of_combat.content:
                zones.out_of_combat.add_card(card)
        # Death relocates all affected cards as one change, including borrowed cards.
        for hand, before, after in hand_changes:
            hand._on_size_changed(before, after)
        self.game.check_game_over()
