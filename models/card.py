from enum import Enum, auto


RANGE_NAMES = ("近战", "普通远程", "强化远程", "极限远程")


def validate_skill_traits(data):
    for key in ("range_level", "ignore_range"):
        value = data.get(key, 0)
        if type(value) is not int or not 0 <= value <= 3:
            raise ValueError(f"{key} 必须是 0 到 3 的整数")
    for key in ("pre_reveal", "interceptable"):
        if key in data and type(data[key]) is not bool:
            raise ValueError(f"{key} 必须是布尔值")


def describe_skill_traits(data):
    traits = []
    if data.get("range_level"):
        traits.append(RANGE_NAMES[data["range_level"]])
    if data.get("ignore_range"):
        traits.append(f"无视 {data['ignore_range']} 级远程")
    if data.get("pre_reveal"):
        traits.append("可在开牌前交锋打出")
    if not data.get("interceptable", True):
        traits.append("不可拦截")
    return " · ".join(traits)


class CardState(Enum):
    DEFAULT = auto()
    PLACED_FACE_UP = auto()
    PLACED_FACE_DOWN = auto()
    NEGATED = auto()


class Card:
    def __init__(self, player, data, character=None):
        validate_skill_traits(data)
        self.player = player
        self.character = character
        self.data = data
        self.id = data["id"]
        self.name = data["name"]
        self.cost = data["cost"]
        self.range_level = data.get("range_level", 0)
        self.ignore_range = data.get("ignore_range", 0)
        self.range_opponent = None
        self.range_deficit = 0
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

    def set_range_opponent(self, opponent):
        """Retain this pairing for excess dice, until the next skill joins."""
        self.range_opponent = opponent
        self.range_deficit = 0
        if opponent is None:
            return
        deficit = max(0, opponent.range_level - self.range_level - self.ignore_range)
        if deficit:
            from models.opcode import OpCode
            ctx = self.player.game.context
            with ctx.binding(opponent_card=opponent, target=opponent.character):
                ctx.eval_block([self, deficit, OpCode.RESOLVE_RANGE_DEFICIT])

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
        self.range_opponent = None
        self.range_deficit = 0
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
        return " · ".join(part for part in [str(self), describe_skill_traits(self.data), actions, effects] if part)


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
