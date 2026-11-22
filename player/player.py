from models.opcode import OpCode
from .draw_choice import DrawChoice


class Player:
    def __init__(self, side, name):
        from .card_space import CardSpace
        self.game = None
        self.side = side
        self.name = name
        self.characters = []
        self.max_cost = 0
        self.used_cost = 0
        self.turn_cost_adjustment = 0
        self.next_turn_common_cost = 0
        self.turn_common_cost_bonus = 0
        self.lost_duels = set()
        self.faction_representatives = {}
        self.speed = 0
        self.default_target_character = None
        self.cardspace = CardSpace(self)

    @property
    def available_cost(self):
        return self.max_cost + self.turn_cost_adjustment - self.used_cost

    def register_faction_passives(self, character):
        specs = character.data.get("faction_passives")
        faction = character.faction
        if specs and faction not in self.faction_representatives:
            self.faction_representatives[faction] = character
            self.game.context.register_entries(character, specs)

    def retire_faction_passives(self, character):
        faction = character.faction
        if self.faction_representatives.get(faction) is character:
            del self.faction_representatives[faction]
            for ally in self.characters:
                if ally.is_alive and ally.faction == faction:
                    self.register_faction_passives(ally)
                    break

    def lost_clash_in_previous_duel(self):
        series, index = self.game.duel_position()
        return (series, index - 1) in self.lost_duels

    def set_default_target(self, target):
        self.default_target_character = target
        print(f"{self.name} 的默认目标已设为 {target.name}。")

    def get_default_target(self, enemy_player):
        alive = [character for character in enemy_player.characters if character.is_alive]
        if self.default_target_character in alive:
            return self.default_target_character
        return max(alive, key=lambda char: char.hp, default=None)

    def choose_one_sided_target(self, enemy_player):
        alive = [character for character in enemy_player.characters if character.is_alive]
        if len(alive) <= 1:
            return alive[0] if alive else None
        default = self.get_default_target(enemy_player)
        print(f"{self.name} 选择单方面攻击的目标：")
        for number, character in enumerate(alive, 1):
            print(f"  [{number}] {character.combat_summary()}")
        while True:
            answer = input(f"输入编号，回车选 {default.name}，set 编号可更改默认目标 ").strip()
            if not answer:
                return default
            persistent = answer.lower().startswith("set ")
            number = answer[4:].strip() if persistent else answer
            if number.isdecimal() and 1 <= int(number) <= len(alive):
                chosen = alive[int(number) - 1]
                if persistent:
                    self.set_default_target(chosen)
                return chosen
            print("请输入存活目标的编号。")

    def reset_on_turn_start(self):
        rule = self.game.gamerule
        common = max(0, rule.MAX_BASIC_COST + self.turn_common_cost_bonus)
        self.game.context.eval_block([self, common, rule.CHAR_INDEPENDENT_COST, OpCode.RESET_COST])

    def calculate_speed(self):
        speeds = [char.roll_speed() for char in self.characters if char.is_alive]
        if len(speeds) > 1:
            speeds.remove(min(speeds))
        self.speed = sum(speeds) / len(speeds) if speeds else 0
        return self.speed

    def pay_skill_cost(self, card):
        if card.player is not self:
            return False
        return self.game.context.pay_skill_cost(card)["paid"]

    def draw_card(self, draw_count):
        available = min(draw_count, len(self.cardspace.draw.content))
        if available > 0:
            self.game.context.eval_block([self, available, OpCode.DRAW])

    def draw_for_turn(self):
        alive_count = sum(c.is_alive for c in self.characters)
        if alive_count == 0:
            return
        keep = self.game.gamerule.DRAW_COUNT + int(self.game.turn_count == 0)
        if alive_count == 1:
            self.draw_card(keep)
        else:
            return self.select_card(keep + alive_count - 1, keep)

    def select_card(self, total_draw, draw_count):
        choice = DrawChoice.from_deck(self, total_draw, draw_count)
        if choice.discard_count:
            return choice
        choice.settle(())
