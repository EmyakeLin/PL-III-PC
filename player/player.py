from models.opcode import OpCode


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
        return self.game.context.eval_block([card, card.cost, OpCode.PAY_COST]) is True

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
            self.select_card(keep + alive_count - 1, keep)

    def select_card(self, total_draw, draw_count):
        """在真实抽到的候选中选择弃底，牌库不足时优先保留能抽到的牌。"""
        draw = self.cardspace.draw
        candidates = draw.content[:total_draw]
        keep = min(len(candidates), draw_count)
        discard_count = len(candidates) - keep
        if discard_count:
            self.game.begin_private_view(self)
            print(f"{self.name} 从 {len(candidates)} 张候选牌中选 {discard_count} 张置于牌堆底。")
            for number, card in enumerate(candidates, 1):
                print(f"  [{number}] {card.character.name} · {card.describe()}")
            while True:
                raw = input("输入弃置编号，多个编号以空格或逗号隔开 ").strip()
                values = raw.replace("，", " ").replace(",", " ").split()
                if len(values) == discard_count and all(value.isdecimal() for value in values):
                    indices = [int(value) - 1 for value in values]
                    if len(set(indices)) == discard_count and all(0 <= i < len(candidates) for i in indices):
                        break
                print(f"请选择 {discard_count} 个不同的有效编号。")
            for index in indices:
                draw.move_card_to(candidates[index], draw)
        self.draw_card(keep)

    def place_card(self, game):
        hand = self.cardspace.hand.content
        if not any(c.character.is_alive and c.character.used_duels < c.character.max_duels for c in hand):
            print(f"{self.name} 没有可置入的牌，结束本轮置卡。")
            return "ended"
        slot_number = game.duelspace.locate_nearest_empty_duel(self.side) + 1
        print(f"\n{self.name} 置卡 · 交锋 {slot_number}　通用费 {self.available_cost}")
        opposing = next(p for p in game.players if p is not self)
        for player in (self, opposing):
            status = "；".join(f"{c.combat_summary()}，交锋 {c.used_duels}/{c.max_duels}"
                              for c in player.characters if c.is_alive)
            print(f"{player.name}（牌堆 {len(player.cardspace.draw.content)}，手牌 {len(player.cardspace.hand.content)}）：{status}")
        for number, slot in enumerate(game.duelspace.space, 1):
            own = "、".join(card.name for card in slot.content.get(self.side, ())) or "空"
            opposing_cards = slot.content.get(opposing.side, ())
            opposing_count = len(opposing_cards)
            hidden = f"扣置 {opposing_count} 张" if opposing_count else "空"
            public = [c.name for c in opposing_cards if c.state.name == "PLACED_FACE_UP"]
            if public:
                hidden = "、".join(public + ["扣置牌"] * (opposing_count - len(public)))
            print(f"交锋 {number}　己方 {own}　对方 {hidden}")
        for number, card in enumerate(hand, 1):
            char = card.character
            print(f"  [{number}] {char.name} · {card.describe()}　个人费 {char.available_cost}")
        while True:
            extra = "，pass 暂交置卡权" if game.placed_this_window else ""
            answer = input(f"输入手牌编号，回车结束本轮置卡{extra} ").strip().lower()
            if answer == "pass" and game.placed_this_window:
                return "passed"
            if answer in ("", "end"):
                if not input("再按回车确认结束本轮置卡，输入其他内容取消 ").strip():
                    print(f"{self.name} 结束本轮置卡。")
                    return "ended"
                continue
            if not answer.isdecimal() or not 1 <= int(answer) <= len(hand):
                print("请输入有效的手牌编号。")
                continue
            card = hand[int(answer) - 1]
            if not card.character.is_alive or card.character.used_duels >= card.character.max_duels:
                print("该角色已阵亡或已用完交锋数，请选其他牌。")
                continue
            confirm = input("输入 y 扣置、pass 扣置并交权、end 扣置并结束本轮，回车取消 ").strip().lower()
            if confirm not in ("y", "yes", "pass", "end"):
                continue
            if not game.auto_place_in_duel(self.side, card):
                print("此次置卡未生效。")
                return "passed"
            print(f"{self.name} 已在第 {slot_number} 交锋扣置一张牌。")
            return {"pass": "passed", "end": "ended"}.get(confirm, "placed")
