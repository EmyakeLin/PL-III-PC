from enum import Enum, auto

from entry.predicates import Calculation, Conditional, Rank, Reference, compile_value, read_value
from models.conditions import matches_value, skill_state_allows
from models.opcode import OpCode


RANGE_NAMES = ("近战", "普通远程", "强化远程", "极限远程")
COMPARISON_SIGNS = {"lt": "<", "le": "≤", "eq": "=", "ne": "≠", "ge": "≥", "gt": ">"}


def range_trait(data, key, card):
    """Combine printed range with the amount supplied by its rule expression."""
    value = data.get(key, 0)
    amount = data.get(key + "_amount")
    if amount is not None and card is not None:
        result = read_value(compile_value(amount["value"]), card.character, {"card": card})
        if type(result) is not int or not 0 <= result <= 3:
            raise ValueError(f"{key}_amount 的计算结果须为 0 到 3 的整数，实际为 {result!r}")
        value = max(value, result)
    return value


def allows_interception(data, *, pre_reveal):
    """A numbered pre-reveal attack invites a response; a field play needs printed permission."""
    return data.get("interceptable", pre_reveal)


def validate_range_trait(data, key):
    value = data.get(key, 0)
    if type(value) is not int or not 0 <= value <= 3:
        raise ValueError(f"{key} 必须是 0 到 3 的整数")
    for name in data:
        if name.startswith(key + "_") and name != key + "_amount":
            raise ValueError(f"未知的远程属性 {name!r}")
    if key + "_amount" in data:
        amount = data[key + "_amount"]
        if (not isinstance(amount, dict) or "value" not in amount or set(amount) - {"value", "description"}
                or "description" in amount and not isinstance(amount["description"], str)):
            raise ValueError(f"{key}_amount 须给出取值表达式")
        expression = compile_value(amount["value"])
        if not isinstance(expression, (Calculation, Conditional, Reference, Rank)) and not (
                type(expression) is int and 0 <= expression <= 3):
            raise ValueError(f"{key}_amount 需要整数或只读数值表达式")


def validate_skill_traits(data):
    if type(data.get("match_opposing_range", False)) is not bool:
        raise ValueError("匹配对方远程等级须为布尔值")
    reduction = data.get("opponent_range_reduction", 0)
    if type(reduction) is not int or not 0 <= reduction <= 3:
        raise ValueError("对方远程等级减量须为0～3的整数")
    if (data.get("form_when") or {}).get("snapshot") not in (None, "use"):
        raise ValueError("形态快照的时点必须是 use")
    for key in ("range_level", "ignore_range"):
        validate_range_trait(data, key)
    for key in ("pre_reveal", "interceptable", "preserve_pre_reveal_target", "anytime_replace", "before_duel_attack"):
        if key in data and type(data[key]) is not bool:
            raise ValueError(f"{key} 必须是布尔值")
    if data.get("pre_reveal_bind", "slot") not in ("slot", "declared_card"):
        raise ValueError("pre_reveal_bind 须为 slot 或 declared_card")
    modes = data.get("anytime_play", [])
    if (not isinstance(modes, list) or any(mode not in ("attack", "place", "custom") for mode in modes)
            or len(modes) != len(set(modes))):
        raise ValueError("anytime_play 须为不重复的 attack、place 或 custom 方式列表")
    if "replace_targets" in data:
        targets = data["replace_targets"]
        if (not data.get("anytime_replace") or targets != "ally" and (
                not isinstance(targets, list) or not targets or any(not isinstance(name, str) or not name for name in targets))):
            raise ValueError("replace_targets 须配合 anytime_replace 列出允许替换的友方技能 ID")


def describe_range_traits(data):
    traits = []
    if data.get("match_opposing_range"):
        traits.append("与远程技能交锋时视为同等级远程")
    if data.get("opponent_range_reduction"):
        traits.append(f"对方远程等级−{data['opponent_range_reduction']}")
    for key in ("range_level", "ignore_range"):
        def label(amount):
            return RANGE_NAMES[amount] if key == "range_level" else f"无视 {amount} 级远程"
        if data.get(key):
            traits.append(label(data[key]))
        if (amount := data.get(key + "_amount")) and amount.get("description"):
            traits.append(amount["description"])
    return traits


def describe_skill_traits(data):
    traits = describe_range_traits(data)
    if data.get("pre_reveal"):
        traits.append("可在开牌前交锋打出")
    if required := data.get("pre_reveal_requires_status"):
        traits.append("、".join(f"{name}达到{count}层" for name, count in required.items()) + "时可在开牌前交锋打出")
    if data.get("before_duel_attack"):
        traits.append("可在交锋开始前打出")
    if data.get("pre_reveal_target") == "occupied_enemy_slot":
        traits.append("开牌前仅可指定已有敌方置牌的交锋")
    if data.get("pre_reveal_bind") == "declared_card":
        traits.append("指定交锋时锁定其中下一张敌方技能；放行后该牌不可牵制则本场跳过")
    if extra := data.get("resource_cost"):
        traits.append(f"使用时须支付{extra['amount']}{extra['status']}")
    if requirements := data.get("requires_status"):
        traits.extend(f"须持有{count}层{name}" for name, count in requirements.items())
    if condition := data.get("form_when"):
        if "op" in condition:
            sign = COMPARISON_SIGNS[condition["op"]]
            traits.append(f"{condition['status']}{sign}{condition['value']}时使用「{condition['form']}」形态")
        else:
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
    def __init__(self, player, data, character=None, *, temporary=False):
        validate_skill_traits(data)
        game = getattr(player, "game", None)
        if game is not None:
            game.card_serial += 1
        self.instance_id = game.card_serial if game is not None else None
        self.player = player
        self.character = character
        self.printed_owner = character
        self.deck_owner = character
        self.deck_name = data.get("deck", "draw")
        self.ignore_conditions = False
        self.temporary = temporary
        self.printed_data = data
        self.data = data
        self._form = None
        self.form_locked = False
        self.id = data["id"]
        self.name = data["name"]
        self.cost = data["cost"]
        self.play_observations = {}
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
        self.positive_modifiers = {}
        self.final_bonus = 0
        self.level_bonus = 0
        self.use_state = {}
        self.use_effects_resolved = False
        self.destroyed = False
        self._printed_listeners = game.context.register_entries(self, self.entries) if game else []
        if character is not None and "form_when" in data:
            character.conditional_cards.append(self)
            self.refresh_status_form()

    def meets_use_requirements(self):
        return self.ignore_conditions or all(self.character is not None and self.character.statuses.get(name, 0) >= minimum
                   for name, minimum in self.data.get("requires_status", {}).items())

    @property
    def home_deck(self):
        return self.deck_owner.player.cardspace.zone(self.deck_name)

    @property
    def can_open_pre_reveal(self):
        if self.effective_range > 0 or self.data.get("pre_reveal"):
            return True
        required = self.data.get("pre_reveal_requires_status", {})
        return bool(required) and self.character is not None and all(
            self.character.statuses.get(name, 0) >= count for name, count in required.items())

    @property
    def range_target(self):
        game = getattr(self.player, "game", None)
        if game is not None and game.pipeline.in_duel_phase:
            sides = game.pipeline.side_pipelines
            pipe = sides.get(self.player.side)
            if pipe is not None and pipe.card is self:
                other = next((p.card for side, p in sides.items() if side != self.player.side and p.card is not None), None)
                if other is not None:
                    return other.character
                if pipe.target is not None:
                    return pipe.target
        return self.range_opponent.character if self.range_opponent is not None else None

    def has_next_die(self):
        return not self.destroyed and self.current_dice_index < len(self._dice_order)

    def get_current_die(self, game, *, register=True):
        while self.has_next_die():
            printed_index, _ = self._dice_order[self.current_dice_index]
            spec = self.dice[printed_index]
            gate = spec.get("requires_skill_state")
            if skill_state_allows(self.use_state, gate):
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
            if spec["type"] == "skip" or not skill_state_allows(self.use_state, gate):
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
        if condition and not self.form_locked:
            value = self.character.statuses.get(condition["status"], 0)
            key = condition["form"] if matches_value(value, condition) else None
            if key != self._form:
                self.set_form(key)

    def prepend_printed_die(self, printing, count, *, extra_entries=()):
        """Place fresh copies before the cursor, leaving original positions and materialized uses intact."""
        if printing is None or count <= 0 or self.destroyed:
            return
        index = self.current_dice_index
        face_index = self._dice_order[index][0] if index < len(self._dice_order) else len(self.dice)
        copies = [dict(printing) for _ in range(count)]
        if extra_entries:
            for face in copies:
                face["entries"] = [*face.get("entries", ()), *extra_entries]
        self.dice = [*self.dice[:face_index], *copies, *self.dice[face_index:]]
        self._dice_order = [(i + count if i >= face_index else i, repeated) for i, repeated in self._dice_order]
        self._dice_order[index:index] = [(face_index + i, False) for i in range(count)]
        if self.instantiated_dice is not None:
            for die in self.instantiated_dice:
                if die is not None and die.position > face_index:
                    die.position += count
            self.instantiated_dice[index:index] = [None] * count

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
            if gate:
                key = gate if isinstance(gate, str) else gate["key"]
                if key in other.use_state:
                    self.use_state[key] = other.use_state[key]

    def set_controller(self, character):
        if self.character is not character and "form_when" in self.printed_data:
            if self.character is not None:
                self.character.conditional_cards.remove(self)
            character.conditional_cards.append(self)
        self.character = character
        self.player = character.player
        self.refresh_status_form()

    def belongs_to(self, character):
        """A card leaves with its current controller or the owner of its home deck."""
        return self.character is character or self.deck_owner is character

    def return_to_printed_owner(self):
        self.reset_for_draw()
        self.set_controller(self.deck_owner)

    def dissolve(self):
        """Release a temporary skill's listeners and any materialized dice when it leaves play."""
        self.destroyed = True
        self._release_dice()
        self.player.game.context.unregister_entries(self)
        if self in self.character.conditional_cards:
            self.character.conditional_cards.remove(self)

    @property
    def effective_range(self):
        if self.use_state.get("blank_skill"):
            return 0
        return min(3, range_trait(self.data, "range_level", self) + self.use_state.get("range_bonus", 0))

    @property
    def effective_ignore_range(self):
        return 0 if self.use_state.get("blank_skill") else range_trait(self.data, "ignore_range", self)

    def set_range_opponent(self, opponent, *, own_range=None, opposing_range=None, ignore_range=None):
        """Retain this pairing for excess dice, until the next skill joins."""
        was_blank = self.range_opponent is opponent and self.range_deficit >= 3
        self.range_opponent = opponent
        self.range_deficit = 0
        if opponent is None:
            return
        own_range = self.effective_range if own_range is None else own_range
        opposing_range = opponent.effective_range if opposing_range is None else opposing_range
        ignore_range = self.effective_ignore_range if ignore_range is None else ignore_range
        own_range, opposing_range = self.paired_ranges(opponent, own_range, opposing_range)
        deficit = max(0, opposing_range - own_range - ignore_range)
        if deficit:
            from models.opcode import OpCode
            ctx = self.player.game.context
            with ctx.binding(opponent_card=opponent, target=opponent.character):
                ctx.eval_block([self, deficit, OpCode.RESOLVE_RANGE_DEFICIT])
            if self.range_deficit >= 3 and not was_blank:
                ctx.dispatch_pipeline("on_skill_disabled", source=self.character, card=self,
                                      target=opponent.character, opponent_card=opponent, reason="range")

    @property
    def blanked(self):
        return self.range_deficit >= 3 or bool(self.use_state.get("blank_skill"))

    def paired_ranges(self, opponent, own_range=None, opposing_range=None):
        def levels(card, opposing, supplied):
            reduction = 0 if opposing.use_state.get("blank_skill") else opposing.data.get("opponent_range_reduction", 0)
            skill = max(0, card.effective_range - reduction)
            die = max(0, supplied - reduction) if supplied is not None else 0
            return skill, die if die > skill else 0

        own, own_die = levels(self, opponent, own_range)
        other, other_die = levels(opponent, self, opposing_range)
        match = self.data.get("match_opposing_range", False)
        matched_by = opponent.data.get("match_opposing_range", False)
        if match and matched_by:
            own = other = max(own, other)
        elif match and other:
            own = other
        elif matched_by and own:
            other = own
        return max(own, own_die), max(other, other_die)

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
        self.play_observations = {}
        self.form_locked = False
        self.set_form(self._form if "form_when" in self.printed_data else None)
        self.refresh_status_form()
        self.positive_modifiers.clear()
        self.final_bonus = self.level_bonus = 0
        self.range_opponent = None
        self.range_deficit = 0
        self.use_state.clear()
        self.use_effects_resolved = False
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

    def describe(self):
        from models.dice import describe_die
        actions = " → ".join(describe_die(die) for die in self.dice)
        in_hand = self.player and self in self.player.cardspace.hand.content
        restriction = "当前无法使用" if in_hand and self.character.skill_restricted(self) else ""
        if "description" in self.data:
            parts = [str(self), restriction, self.data["description"], actions]
        else:
            effects = "；".join(describe_entry(entry) for entry in self.entries
                               if not (isinstance(entry, dict) and entry.get("hidden")))
            parts = [str(self), restriction, describe_skill_traits(self.data), actions, effects]
        return " · ".join(part for part in parts if part)


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
    text = str(entry).strip()
    return f"【命中时】{text}。" if text and not text.startswith("【") else text
