from .dynamic_pipeline import DynamicPipeline

class MockCard:
    def __init__(self, name: str, dice_count: int):
        self.name = name
        self.dice = [f"{name}_d{i+1}" for i in range(dice_count)]


class MockDuelSlot:
    def __init__(self):
        # A: 1张卡，3动 (3颗骰子)
        # B: 2张卡 (卡1有2动，卡2有2动)
        self.cards = {
            1: [MockCard("Card_A1", 3)],
            2: [MockCard("Card_B1", 2), MockCard("Card_B2", 2)],
        }
        self.card_index = {1: -1, 2: -1}
        self.dice_index = {1: -1, 2: -1}

    def has_cards(self, side: int) -> bool:
        return side in self.cards and len(self.cards[side]) > 0

    def has_next_card(self, side: int) -> bool:
        return self.card_index[side] + 1 < len(self.cards[side])

    def advance_card(self, side: int):
        self.card_index[side] += 1
        self.dice_index[side] = -1

    def has_next_die(self, side: int) -> bool:
        if self.card_index[side] < 0 or self.card_index[side] >= len(self.cards[side]):
            return False
        curr_card = self.cards[side][self.card_index[side]]
        return self.dice_index[side] + 1 < len(curr_card.dice)

    def advance_die(self, side: int):
        self.dice_index[side] += 1

    def can_hit(self, side: int) -> bool:
        # 演示中 A 始终可以命中，B 招架/防御不可命中
        return side == 1

    def resolve_clash(self, eligible_sides: list) -> dict:
        # A 拼点获胜，B 拼点失败
        return {1: "WIN", 2: "LOSE"}


if __name__ == "__main__":
    slot = MockDuelSlot()
    dp = DynamicPipeline(slot, sides=[1, 2])

    print("==================================================")
    print("      动态展开管线测试运行 (A: 3动 vs B: 2动+2动)    ")
    print("==================================================")

    step_count = 0
    while not dp.is_finished and step_count < 85:
        action_A, action_B = dp.next_step()
        step_count += 1
        print(f"[{step_count:02d}] A: {str(action_A):<30} | B: {str(action_B)}")
