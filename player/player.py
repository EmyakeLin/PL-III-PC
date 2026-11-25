from models.opcode import OpCode
from .draw_choice import DrawChoice


class Player:
    def __init__(self, side, name):
        from .card_space import CardSpace
        self.game = None
        self.side = side
        self.name = name
        self.characters = []
        self.team_statuses = {}
        self.max_cost = 0
        self.used_cost = 0
        self.turn_cost_adjustment = 0
        self.next_turn_common_cost = 0
        self.turn_common_cost_bonus = 0
        self.faction_representatives = {}
        self.speed = 0
        self.default_target_character = None
        self.target_priority = (("hp", -1),)
        self.target_order = None
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
        return self.game.turn_history.clash_count(self, "lose", (series, index - 1)) > 0

    def set_default_target(self, target):
        self.default_target_character = target

    def get_default_target(self, enemy_player):
        alive = [character for character in enemy_player.characters if character.is_alive]
        if self.default_target_character in alive:
            return self.default_target_character
        return min(alive, key=lambda char: tuple(getattr(char, field) * direction
                                                  for field, direction in self.target_priority), default=None)

    def choose_one_sided_target(self, enemy_player):
        eligible = [member for member in enemy_player.characters if member.is_alive]
        default = self.get_default_target(enemy_player)
        if len(eligible) < 2 or self.target_order is None:
            return default
        order, self.target_order = self.target_order, None
        return order.resolve(eligible, default)

    def reset_on_turn_start(self):
        rule = self.game.gamerule
        common = max(0, rule.MAX_BASIC_COST + self.turn_common_cost_bonus)
        ctx = self.game.context
        ctx.stack.extend((self, common, rule.CHAR_INDEPENDENT_COST))
        ctx.execute_op(OpCode.RESET_COST, refill=True)
        self.game.context.record("turn_budget", side=self.side, common=self.available_cost,
                                 personal=tuple((c.id, c.available_cost) for c in self.characters if c.is_alive))

    def calculate_speed(self):
        rolls = [(char, char.roll_speed()) for char in self.characters if char.is_alive]
        dropped = min(rolls, key=lambda pair: pair[1]) if len(rolls) > 1 else None
        if dropped is not None:
            rolls.remove(dropped)
        self.speed = sum(value for _, value in rolls) / len(rolls) if rolls else 0
        self.game.context.record("team_speed", side=self.side, speed=self.speed,
                                 dropped=dropped[0].id if dropped else None)
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
        ctx = self.game.context
        ctx.stack.extend((self, self.game.gamerule.DRAW_COUNT + int(self.game.turn_count == 0)))
        keep = ctx.execute_op(OpCode.RESOLVE_TURN_DRAW_COUNT) or 0
        if keep == 0:
            return
        if alive_count == 1:
            with self.game.context.binding(turn_draw=True):
                self.draw_card(keep)
        else:
            return self.select_card(keep + alive_count - 1, keep)

    def select_card(self, total_draw, draw_count):
        choice = DrawChoice.from_deck(self, total_draw, draw_count)
        if choice.discard_count:
            return choice
        choice.settle(())
