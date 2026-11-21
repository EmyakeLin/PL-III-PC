from enum import Enum, auto

from models.opcode import OpCode


RANGE_NAMES = ("近战", "普通远程", "强化远程", "极限远程")


def range_trait(data, key, card):
    """Resolve a printed range trait with an optional status or current-use condition."""
    value = data.get(key, 0)
    condition = data.get(key + "_when")
    if condition and card is not None:
        if "skill_state" in condition:
            active = card.use_state.get(condition["skill_state"])
        else:
            active = card.character is not None and card.character.statuses.get(condition["status"], 0)
        if active:
            value = max(value, condition["amount"])
    per_stack = data.get(key + "_per_stack")
    if per_stack and card is not None and card.character is not None:
        value = max(value, min(3, card.character.statuses.get(per_stack, 0)))
    return value


def allows_interception(data, *, pre_reveal):
    """A numbered pre-reveal attack invites a response; a field play needs printed permission."""
    return data.get("interceptable", pre_reveal)


def validate_range_trait(data, key):
    value = data.get(key, 0)
    if type(value) is not int or not 0 <= value <= 3:
        raise ValueError(f"{key} 必须是 0 到 3 的整数")
    if key + "_when" in data:
        condition = data[key + "_when"]
        if (not isinstance(condition, dict)
                or set(condition) not in ({"status", "amount"}, {"skill_state", "amount"})
                or not isinstance(name := condition.get("status", condition.get("skill_state")), str)
                or not name.strip() or type(condition["amount"]) is not int or not 0 <= condition["amount"] <= 3):
            raise ValueError(f"{key}_when 需要状态或本次技能标记，以及 0 到 3 的远程等级")


def validate_skill_traits(data):
    for key in ("range_level", "ignore_range"):
        validate_range_trait(data, key)
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


def describe_range_traits(data):
    traits = []
    for key in ("range_level", "ignore_range"):
        def label(amount):
            return RANGE_NAMES[amount] if key == "range_level" else f"无视 {amount} 级远程"
        if data.get(key):
            traits.append(label(data[key]))
        if condition := data.get(key + "_when"):
            when = f"【{condition['status']}】" if "status" in condition else "本技能相应词条生效时"
            traits.append(when + label(condition["amount"]))
        if per_stack := data.get(key + "_per_stack"):
            traits.append(f"每层{per_stack}提供1级" + ("远程" if key == "range_level" else "无视远程"))
    return traits


def describe_skill_traits(data):
    traits = describe_range_traits(data)
    if data.get("pre_reveal"):
        traits.append("可在开牌前交锋打出")
    if data.get("before_duel_attack"):
        traits.append("可在交锋开始前打出")
    if data.get("pre_reveal_target") == "occupied_enemy_slot":
        traits.append("开牌前仅可指定已有敌方置牌的交锋")
    if extra := data.get("resource_cost"):
        traits.append(f"使用时须支付{extra['amount']}{extra['status']}")
    if requirements := data.get("requires_status"):
        traits.extend(f"须持有{count}层{name}" for name, count in requirements.items())
    if condition := data.get("form_when"):
        traits.append(f"持有{condition['status']}时使用「{condition['form']}」形态")
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
        self.printed_data = data
        self.data = data
        self._form = None
        self.id = data["id"]
        self.name = data["name"]
        self.cost = data["cost"]
        self.hand_cost_rank = None
        self.range_level = data.get("range_level", 0)
        self.ignore_range = data.get("ignore_range", 0)
        self.range_opponent = None
        self.range_deficit = 0
        self.out_of_combat = bool(data.get("out_of_combat"))
        self.entries = data.get("entries", [])
        self.dice = data.get("dice", [])
        self.state = CardState.DEFAULT
        self.current_dice_index = 0
        self._dice_order = [(index, False) for index in range(len(self.dice))]
        self.instantiated_dice = None
        self.final_bonus = 0
        self.level_bonus = 0
        self.use_state = {}
        self.destroyed = False
        self._printed_listeners = game.context.register_entries(self, self.entries) if game else []
        if character is not None and "form_when" in data:
            character.conditional_cards.append(self)
            self.refresh_status_form()

    def meets_use_requirements(self):
        return all(self.character is not None and self.character.statuses.get(name, 0) >= minimum
                   for name, minimum in self.data.get("requires_status", {}).items())

    def has_next_die(self):
        return not self.destroyed and self.current_dice_index < len(self._dice_order)

    def get_current_die(self, game, *, register=True):
        while self.has_next_die():
            printed_index, _ = self._dice_order[self.current_dice_index]
            spec = self.dice[printed_index]
            gate = spec.get("requires_skill_state")
            if not gate or self.use_state.get(gate):
                break
            self.current_dice_index += 1
        if not self.has_next_die():
            return None
        die = self._materialize_die(game, self.current_dice_index)
        if register:
            die.register_entries()
        return die

    def _materialize_die(self, game, index):
        """Give a planned use its identity without activating its entries."""
        if self.instantiated_dice is None:
            self.instantiated_dice = [None] * len(self._dice_order)
        if self.instantiated_dice[index] is None:
            printed_index, repeated = self._dice_order[index]
            die = game.init_dice(self.dice[printed_index])
            die.position = printed_index + 1
            die.card = self
            die.is_repeat = repeated
            self.instantiated_dice[index] = die
        return self.instantiated_dice[index]

    def planned_dice(self, game, *, after_current=False):
        """Iterate identifiable, unspent uses without moving the actual cursor."""
        if self.destroyed:
            return
        self._sync_requested_repeat()
        for index in range(self.current_dice_index + int(after_current), len(self._dice_order)):
            printed_index, _ = self._dice_order[index]
            spec = self.dice[printed_index]
            gate = spec.get("requires_skill_state")
            if spec["type"] == "skip" or gate and not self.use_state.get(gate):
                continue
            die = self._materialize_die(game, index)
            if not die.destroyed and die.can_afford_use():
                yield die

    def set_form(self, key):
        form = self.printed_data["forms"][key] if key is not None else {}
        self._form = key
        self.data = {**self.printed_data, **form} if form else self.printed_data
        self._release_dice()
        self.name = self.data["name"]
        self.cost = self.data["cost"]
        self.dice = self.data.get("dice", [])
        self.range_level = self.data.get("range_level", 0)
        self.ignore_range = self.data.get("ignore_range", 0)
        entries = self.data.get("entries", [])
        if entries != self.entries:
            self.entries = entries
            if game := getattr(self.player, "game", None):
                for listener in self._printed_listeners:
                    if listener in game.context.entries:
                        game.context.entries.remove(listener)
                self._printed_listeners = game.context.register_entries(self, entries)
        self._dice_order = [(index, False) for index in range(len(self.dice))]
        self.current_dice_index = 0

    def refresh_status_form(self):
        condition = self.printed_data.get("form_when")
        if condition:
            key = condition["form"] if self.character.statuses.get(condition["status"], 0) else None
            if key != self._form:
                self.set_form(key)

    def take_remaining_dice(self, other):
        """Move the remaining uses, including queued repeats, without editing either printed skill."""
        if not other.has_next_die():
            return
        start = other.current_dice_index + 1
        other._sync_requested_repeat()
        future_uses = [use for i, use in enumerate(other._dice_order[start:], start)
                       if not other.instantiated_dice or not getattr(other.instantiated_dice[i], "destroyed", False)]
        remaining = [other.dice[index] for index, _ in future_uses]
        del other._dice_order[start:]
        if other.instantiated_dice is not None:
            current = other.instantiated_dice[other.current_dice_index]
            if current is not None:
                # A current repeat transferred with the tail must never be queued again here.
                current.repeat_materialized = current.repeat_requested = False
            del other.instantiated_dice[start:]
        if not remaining:
            return
        first = len(self.dice)
        self.dice = [*self.dice, *remaining]
        self._dice_order.extend((first + offset, repeated)
                                for offset, (_, repeated) in enumerate(future_uses))
        if self.instantiated_dice is not None:
            self.instantiated_dice.extend([None] * len(remaining))
        for spec in remaining:
            gate = spec.get("requires_skill_state")
            if gate and other.use_state.get(gate):
                self.use_state[gate] = other.use_state[gate]

    def set_controller(self, character):
        if self.character is not character and "form_when" in self.printed_data:
            if self.character is not None:
                self.character.conditional_cards.remove(self)
            character.conditional_cards.append(self)
        self.character = character
        self.player = character.player
        self.refresh_status_form()

    def belongs_to(self, character):
        """Both current use and printed ownership matter when a character leaves battle."""
        return self.character is character or self.printed_owner is character

    def return_to_printed_owner(self):
        self.reset_for_draw()
        self.set_controller(self.printed_owner)

    @property
    def effective_range(self):
        return range_trait(self.data, "range_level", self)

    @property
    def effective_ignore_range(self):
        return range_trait(self.data, "ignore_range", self)

    def set_range_opponent(self, opponent, *, own_range=None, opposing_range=None, ignore_range=None):
        """Retain this pairing for excess dice, until the next skill joins."""
        self.range_opponent = opponent
        self.range_deficit = 0
        if opponent is None:
            return
        own_range = self.effective_range if own_range is None else own_range
        opposing_range = opponent.effective_range if opposing_range is None else opposing_range
        ignore_range = self.effective_ignore_range if ignore_range is None else ignore_range
        deficit = max(0, opposing_range - own_range - ignore_range)
        if deficit:
            from models.opcode import OpCode
            ctx = self.player.game.context
            with ctx.binding(opponent_card=opponent, target=opponent.character):
                ctx.eval_block([self, deficit, OpCode.RESOLVE_RANGE_DEFICIT])

    def _sync_requested_repeat(self):
        if self.instantiated_dice and self.has_next_die():
            index = self.current_dice_index
            die = self.instantiated_dice[index]
            if die is None:
                return
            requested = die.repeat_requested and not die.destroyed
            if requested and not die.repeat_materialized:
                printed_index, _ = self._dice_order[index]
                self._dice_order.insert(index + 1, (printed_index, True))
                self.instantiated_dice.insert(index + 1, None)
            elif die.repeat_materialized and not requested:
                del self._dice_order[index + 1]
                del self.instantiated_dice[index + 1]
            die.repeat_materialized = requested

    def advance_die(self):
        self._sync_requested_repeat()
        self.current_dice_index += 1

    def skip_unpaid_die(self):
        index = self.current_dice_index
        die = self.instantiated_dice[index]
        if die.entries_registered:
            self.player.game.context.unregister_entries(die)
        self.instantiated_dice[index] = None
        self.current_dice_index += 1

    def _release_dice(self):
        if self.instantiated_dice:
            for die in self.instantiated_dice:
                if die is not None:
                    self.player.game.context.unregister_entries(die)
        self.instantiated_dice = None

    def reset_for_draw(self):
        self.hand_cost_rank = None
        self.set_form(self._form if "form_when" in self.printed_data else None)
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
        in_hand = self.player and self in self.player.cardspace.hand.content
        restriction = "当前无法使用" if in_hand and self.character.skill_restricted(self) else ""
        return " · ".join(part for part in [str(self), restriction, describe_skill_traits(self.data), actions, effects] if part)


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
