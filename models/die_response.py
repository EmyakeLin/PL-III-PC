from copy import copy, deepcopy
from dataclasses import dataclass, field

from models.card import Card


@dataclass(frozen=True)
class SkillDieTemplate:
    card: Card
    position: int

    @classmethod
    def capture(cls, card, position):
        if card is None or not 1 <= position <= len(card.dice):
            return None
        snapshot = copy(card)
        snapshot.dice = list(card.dice)
        snapshot.dice[position - 1] = deepcopy(card.dice[position - 1])
        snapshot.use_state = card.use_state.copy()
        snapshot._dice_order = [(position - 1, False)]
        snapshot.current_dice_index = 0
        snapshot.instantiated_dice = None
        snapshot.range_opponent, snapshot.range_deficit = None, 0
        return cls(snapshot, position)

    def create_die(self, game, holder):
        card = copy(self.card)
        card.character, card.player = holder, holder.player
        card.use_state = self.card.use_state.copy()
        card._dice_order = self.card._dice_order.copy()
        return card.get_current_die(game, register=False)


@dataclass(eq=False)
class DieResponse:
    template: SkillDieTemplate
    trigger: str
    remaining: int
    through_turn: int | None
    spend_on: str
    spend_amount: int
    pending: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.trigger, str) or not self.trigger:
            raise ValueError("迎击机会需要触发时机")
        if self.through_turn is not None and type(self.through_turn) is not int:
            raise ValueError("迎击期限须为回合编号或空值")
        if self.spend_on not in ("attempt", "use"):
            raise ValueError("迎击机会须指定在尝试或使用时扣次")
        if type(self.spend_amount) is not int or self.spend_amount < 0:
            raise ValueError("迎击扣减量须为非负整数")

    def available(self, trigger, turn_number):
        return (not self.pending and self.trigger == trigger and self.remaining > 0 and self.remaining >= self.spend_amount
                and (self.through_turn is None or turn_number <= self.through_turn))

    def spend(self, stage):
        if stage == self.spend_on:
            self.remaining -= self.spend_amount
