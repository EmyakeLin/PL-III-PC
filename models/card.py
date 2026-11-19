from enum import Enum, auto


class CardState(Enum):
    DEFAULT = auto()
    PLACED_FACE_UP = auto()
    PLACED_FACE_DOWN = auto()
    NEGATED = auto()


class Card:
    def __init__(self, player, data, character=None):
        self.player = player
        self.character = character
        self.data = data
        self.id = data["id"]
        self.name = data["name"]
        self.cost = data["cost"]
        self.out_of_combat = bool(data.get("out_of_combat"))
        self.entries = data.get("entries", [])
        self.dice = data.get("dice", [])
        self.state = CardState.DEFAULT
        self.current_dice_index = 0
        self._dice_order = list(range(len(self.dice)))
        self.instantiated_dice = None
        self.final_bonus = 0
        self.level_bonus = 0
        self.use_state = {}
        self.destroyed = False
        if player is not None and getattr(player, "game", None) is not None:
            player.game.context.register_entries(self, self.entries)

    def has_next_die(self):
        return not self.destroyed and self.current_dice_index < len(self._dice_order)

    def get_current_die(self, game):
        if not self.has_next_die():
            return None
        if self.instantiated_dice is None:
            self.instantiated_dice = [None] * len(self._dice_order)
        index = self.current_dice_index
        if self.instantiated_dice[index] is None:
            printed_index = self._dice_order[index]
            die = game.init_dice(self.dice[printed_index])
            die.position = printed_index + 1
            die.card = self
            game.context.register_entries(die, die.entries)
            self.instantiated_dice[index] = die
        return self.instantiated_dice[index]

    def advance_die(self):
        if self.instantiated_dice and self.has_next_die():
            index = self.current_dice_index
            die = self.instantiated_dice[index]
            if die is not None and die.repeat_requested and not die.destroyed:
                # The next round instantiates and registers the printed die again.
                self._dice_order.insert(index + 1, self._dice_order[index])
                self.instantiated_dice.insert(index + 1, None)
        self.current_dice_index += 1

    def reset_for_draw(self):
        if self.instantiated_dice:
            for die in self.instantiated_dice:
                if die is not None:
                    self.player.game.context.unregister_entries(die)
        self.instantiated_dice = None
        self.current_dice_index = 0
        self._dice_order = list(range(len(self.dice)))
        self.final_bonus = self.level_bonus = 0
        self.use_state.clear()
        self.state = CardState.DEFAULT
        self.destroyed = False

    def __str__(self):
        return f"{self.name}（{self.cost} 费）"

    def get_meta(self, side=False, cost=False):
        prefix = f"{self.player.name} · " if side else ""
        if self.state is CardState.PLACED_FACE_DOWN:
            return prefix + "已扣置"
        suffix = f" · {self.cost} 费" if cost else ""
        return f"{prefix}{self.name}{suffix}"

    def print(self, owner=None):
        if self.state is CardState.PLACED_FACE_DOWN and owner is not self.player:
            print("已扣置")
        else:
            print(f"{self.character.name} · {self.name} · {self.cost} 费")

    def describe(self):
        from models.dice import describe_die
        actions = " → ".join(describe_die(die) for die in self.dice)
        effects = "；".join(describe_entry(entry) for entry in self.entries)
        return " · ".join(part for part in [str(self), actions, effects] if part)


def describe_entry(entry):
    if isinstance(entry, dict):
        if entry.get("description"):
            return entry["description"]
        return f"{entry.get('trigger', '命中')} {entry.get('operation', '')}".strip()
    from entry.effects import GRADE_NAMES, damage_part
    part = damage_part(entry)
    if part:
        amount, grade = part
        return f"{amount} 点{GRADE_NAMES[grade]}伤害"
    return str(entry)
