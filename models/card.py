from enum import Enum, auto

from models.opcode import OpCode


RANGE_NAMES = ("近战", "普通远程", "强化远程", "极限远程")


def allows_interception(data, *, pre_reveal):
    """A numbered pre-reveal attack invites a response; a field play needs printed permission."""
    return data.get("interceptable", pre_reveal)


def validate_skill_traits(data):
    for key in ("range_level", "ignore_range"):
        value = data.get(key, 0)
        if type(value) is not int or not 0 <= value <= 3:
            raise ValueError(f"{key} 必须是 0 到 3 的整数")
    for key in ("pre_reveal", "interceptable", "anytime_replace", "before_duel_attack"):
        if key in data and type(data[key]) is not bool:
            raise ValueError(f"{key} 必须是布尔值")
    modes = data.get("anytime_play", [])
    if (not isinstance(modes, list) or any(mode not in ("attack", "place", "custom") for mode in modes)
            or len(modes) != len(set(modes))):
        raise ValueError("anytime_play 须为不重复的 attack、place 或 custom 方式列表")
    if "replace_targets" in data:
        targets = data["replace_targets"]
        if (not data.get("anytime_replace") or not isinstance(targets, list) or not targets
                or any(not isinstance(name, str) or not name for name in targets)):
            raise ValueError("replace_targets 须配合 anytime_replace 列出允许替换的友方技能 ID")


def describe_skill_traits(data):
    traits = []
    if data.get("range_level"):
        traits.append(RANGE_NAMES[data["range_level"]])
    if data.get("ignore_range"):
        traits.append(f"无视 {data['ignore_range']} 级远程")
    if data.get("pre_reveal"):
        traits.append("可在开牌前交锋打出")
    if data.get("before_duel_attack"):
        traits.append("可在交锋开始前打出")
    if data.get("pre_reveal_target") == "occupied_enemy_slot":
        traits.append("开牌前仅可指定已有敌方置牌的交锋")
    if extra := data.get("resource_cost"):
        traits.append(f"使用时须支付{extra['amount']}{extra['status']}")
    if not allows_interception(data, pre_reveal=True):
        traits.append("不可拦截")
    modes = {"attack": "主动进攻", "place": "置于空交锋", "custom": "依卡面执行"}
    if data.get("anytime_play"):
        traits.append("可在任意时刻打出（" + "、".join(modes[m] for m in data["anytime_play"]) + "）")
    if "attack" in data.get("anytime_play", ()) and allows_interception(data, pre_reveal=True):
        traits.append("场内进攻可迎击" if allows_interception(data, pre_reveal=False) else "场内进攻不可拦截")
    if data.get("anytime_replace"):
        traits.append("可在任意时刻替换指定技能" if data.get("replace_targets") else "可在任意时刻替换自身技能")
    return " · ".join(traits)


class CardState(Enum):
    DEFAULT = auto()
    PLACED_FACE_UP = auto()
    PLACED_FACE_DOWN = auto()
    NEGATED = auto()


class Card:
    def __init__(self, player, data, character=None):
        validate_skill_traits(data)
        game = getattr(player, "game", None)
        if game is not None:
            game.card_serial += 1
        self.instance_id = game.card_serial if game is not None else None
        self.player = player
        self.character = character
        self.printed_owner = character
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
        while self.has_next_die():
            spec = self.dice[self._dice_order[self.current_dice_index]]
            gate = spec.get("requires_skill_state")
            if not gate or self.use_state.get(gate):
                break
            self.current_dice_index += 1
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

    def set_form(self, key):
        form = self.data["forms"][key]
        self._release_dice()
        self.name = form["name"]
        self.dice = form["dice"]
        self._dice_order = list(range(len(self.dice)))
        self.current_dice_index = 0

    def take_remaining_dice(self, other):
        """Move the remaining uses, including queued repeats, without editing either printed skill."""
        start = other.current_dice_index + 1
        remaining = [other.dice[i] for i in other._dice_order[start:]]
        if not remaining:
            return
        del other._dice_order[start:]
        if other.instantiated_dice is not None:
            del other.instantiated_dice[start:]
        first = len(self.dice)
        self.dice = [*self.dice, *remaining]
        self._dice_order.extend(range(first, first + len(remaining)))
        if self.instantiated_dice is not None:
            self.instantiated_dice.extend([None] * len(remaining))
        for spec in remaining:
            gate = spec.get("requires_skill_state")
            if gate and other.use_state.get(gate):
                self.use_state[gate] = other.use_state[gate]

    def set_controller(self, character):
        self.character = character
        self.player = character.player

    def belongs_to(self, character):
        """Both current use and printed ownership matter when a character leaves battle."""
        return self.character is character or self.printed_owner is character

    def return_to_printed_owner(self):
        self.reset_for_draw()
        self.set_controller(self.printed_owner)

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

    def _release_dice(self):
        if self.instantiated_dice:
            for die in self.instantiated_dice:
                if die is not None:
                    self.player.game.context.unregister_entries(die)
        self.instantiated_dice = None

    def reset_for_draw(self):
        self._release_dice()
        self.dice = self.data.get("dice", [])
        self.name = self.data["name"]
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
    from entry.effects import GRADE_NAMES, damage_part, independent_damage_part
    part = damage_part(entry)
    if part:
        amount, grade = part
        return f"{amount} 点{GRADE_NAMES[grade]}伤害"
    independent = independent_damage_part(entry)
    if independent:
        amount, opcode = independent
        label = "光点" if opcode is OpCode.LIGHTCORE_DAMAGE else "真实"
        return f"{amount} 点{label}伤害"
    return str(entry)
