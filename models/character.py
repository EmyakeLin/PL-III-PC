from enum import Enum, auto
import random

from models.card import Card
from models.opcode import OpCode


class CharacterRank(Enum):
    NORMAL = auto()
    ELITE = auto()
    BOSS = auto()
    EMPOWERED_BOSS = auto()


class SpeedDie:
    """An unprinted die used only to determine initiative."""
    card = None

    def __init__(self, owner):
        self.owner = owner
        self.value = 0


RANK_DUEL_MAP = dict(zip(CharacterRank, (1, 2, 3, 4)))
RANK_SKILL_COUNT = dict(zip(CharacterRank, (3, 5, 7, 11)))
STATUS_ALIASES = {
    "burn": "烧伤", "bleed": "裂血", "energy": "能源", "breath": "呼吸",
    "呼吸法": "呼吸", "stagger": "失衡", "fatal_stagger": "致命失衡",
}
STATUS_CAPS = {"裂血": 9, "呼吸": 6, "失衡": 20}
ONE_TURN_STATUSES = ("强壮", "虚弱", "迅捷", "束缚")
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
        self.max_hp = data["max_hp"]
        self.passive_skill_data = data.get("passive_skills", [])
        self.passive_skills = self.passive_skill_data
        self.skill_data = data["skills"]
        self.skills = []
        self.hp = self.max_hp
        self.is_alive = True
        self.used_duels = 0
        self.reset_shields()
        self.independent_cost = 0
        self.used_independent_cost = 0
        self.turn_cost_adjustment = 0
        self.statuses = {}
        self._status_listeners = {}
        self.bleed_burst = False
        self.round_triggers = set()
        if self.game:
            self.game.status_entries.update(data.get("status_entries", {}))
            self.game.turn_end_statuses.update(data.get("turn_end_statuses", ()))
            self.game.context.register_entries(self, self.passive_skill_data)
            player.register_faction_passives(self)

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
    def base_duels(data):
        return data.get("base_max_duels", RANK_DUEL_MAP[CharacterRank[data["rank"]]])

    @property
    def available_cost(self):
        return self.independent_cost + self.turn_cost_adjustment - self.used_independent_cost

    def queue_status(self, name, amount, source=None):
        """Apply an already scheduled status before next turn's draw and speed roll."""
        if self.is_alive:
            source = self if source is None else source
            authority = self.game.context.event.get("authority", 0)
            self.game.next_turn_statuses.append((source, self, name, amount, authority))

    def roll_speed(self):
        die = SpeedDie(self)
        low, high = self.data.get("speed_die", (1, 4))
        with self.game.context.binding(roll_kind="speed"):
            rolled = self.game.context.eval_block([low, high, 0, die, OpCode.ROLL])
        raw = min(high, max(low, die.value)) if rolled is not None else 0
        self.speed = raw + self.statuses.get("迅捷", 0) - self.statuses.get("束缚", 0)
        return self.speed

    def init_cards(self):
        self.skills = [Card(self.player, skill, self) for skill in self.skill_data]

    def setup_deck(self):
        for card in self.skills:
            zone = self.player.cardspace.out_of_combat if card.out_of_combat else self.player.cardspace.draw
            zone.add_card(card)

    def reset_shields(self):
        self.shield = self.reinforced_shield = self.concept_shield = 0

    def combat_summary(self):
        parts = [f"{self.name} {self.hp}/{self.max_hp} HP"]
        for label, value in (("护盾", self.shield), ("强化护盾", self.reinforced_shield),
                             ("概念护盾", self.concept_shield)):
            if value:
                parts.append(f"{label} {value}")
        for label, value in self.statuses.items():
            if label == "裂血" and self.bleed_burst:
                label = "裂血（爆发）"
            parts.append(f"{label} {value}")
        return " · ".join(parts)

    def add_shield(self, kind, amount):
        field = SHIELD_FIELDS[kind]
        value = max(0, getattr(self, field) + int(amount))
        setattr(self, field, value)
        return value

    def add_status(self, name, amount):
        """Apply a status through the same listeners as a card or delayed effect."""
        name = STATUS_ALIASES.get(name, name)
        if self.game:
            return self.game.context.eval_block([self, name, amount, OpCode.STATUS])
        return self.apply_status_delta(name, amount)

    def apply_status_delta(self, name, amount):
        """Commit a resolved STATUS or SPEND_STATUS and bind entries to its holder."""
        if not self.is_alive:
            return 0
        name = STATUS_ALIASES.get(name, name)
        previous = self.statuses.get(name, 0)
        value = max(0, previous + int(amount))
        cap = self.data.get("resource_rules", {}).get("caps", {}).get(name, STATUS_CAPS.get(name))
        if cap is not None:
            value = min(value, cap)
        if value:
            self.statuses[name] = value
            if self.game and not previous and name in self.game.status_entries:
                specs = self.game.status_entries[name]
                self._status_listeners[name] = self.game.context.register_entries(self, specs)
        else:
            self.clear_status(name)
        if name == "裂血":
            self.bleed_burst = value >= 6 or (self.bleed_burst and value > 0)
        return value

    def clear_status(self, name):
        """End a status and its listeners, including expiry after the holder dies."""
        self.statuses.pop(name, None)
        if name == "裂血":
            self.bleed_burst = False
        listeners = self._status_listeners.pop(name, None)
        if listeners:
            entries = self.game.context.entries
            entries[:] = [entry for entry in entries if entry not in listeners]

    def begin_dice_round(self):
        self.round_triggers = set()

    def damage_multiplier(self):
        return 2 if self.statuses.get("致命失衡", 0) else 1

    def on_duel_start(self):
        if self.is_alive and self.statuses.get("裂血", 0) >= 3:
            self.take_damage(1, "pierce", damage_cause="裂血")

    def after_damage_part(self):
        if self.is_alive and self.bleed_burst:
            self.take_damage(1, "pierce", damage_cause="裂血爆发")
            self.add_status("裂血", -2)

    def on_attack_hit(self, die, target):
        stacks = self.statuses.get("呼吸", 0)
        rng = getattr(self.game, "rng", random)
        die.critical = stacks > 0 and rng.randint(1, 6) <= stacks
        if die.critical and self.game:
            print(f"{self.name} 触发暴击。")
            self.game.context.dispatch_pipeline("on_critical", source=self, target=target,
                                                side=self.player.side, card=die.card, die=die)
        return die.critical

    def trigger_stagger(self):
        if not self.is_alive:
            return False
        rng = getattr(self.game, "rng", random)
        if rng.randint(1, 20) <= self.statuses.get("失衡", 0):
            self.add_status("致命失衡", 1)
            self.add_status("失衡", -5)
            return True
        self.add_status("失衡", 2)
        return False

    def on_turn_end(self):
        if not self.is_alive:
            return
        burn = self.statuses.get("烧伤", 0) // 4
        if burn:
            damage = self.take_damage(min(3, burn), damage_cause="烧伤")
            if damage > 0:
                self.add_status("烧伤", -burn - 2)

    def heal(self, amount):
        if not self.is_alive or amount <= 0:
            return 0
        old_hp = self.hp
        self.hp = min(self.max_hp, self.hp + int(amount))
        return self.hp - old_hp

    def lose_hp(self, amount):
        if not self.is_alive or amount <= 0:
            return 0
        lost = min(self.hp, amount)
        self.hp -= lost
        self.check_death()
        return lost

    def take_damage(self, amount, penetration="normal", attack_type="none", *,
                    modified=False, damage_cause=None, result_field="result"):
        """Resolve damage to this character. Request hp_lost for effects that require life loss."""
        if result_field not in ("result", "hp_lost"):
            raise ValueError(f"未知伤害结果字段 {result_field!r}")
        if not self.is_alive:
            return 0
        grade = DAMAGE_GRADES[getattr(penetration, "name", str(penetration)).lower()]
        if self.game:
            return self.game.context.deal_damage(self, self, amount, grade, attack_type,
                                                 damage_cause=damage_cause, modified=modified,
                                                 result_field=result_field)
        damage = max(0, int(amount if modified else amount * self.damage_multiplier()))
        hp_lost = self.apply_resolved_damage(damage, grade)
        return hp_lost if result_field == "hp_lost" else damage

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
        if self.statuses.get("致命失衡") and "致命失衡" not in self.round_triggers:
            self.round_triggers.add("致命失衡")
            self.add_status("致命失衡", -1)
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
