from models.card import CardState
from models.opcode import OpCode


class DuelSpace:
    def __init__(self, game):
        self.game = game
        self.space = []
        self.current_duel_index = 0

    def __str__(self):
        return "\n".join(f"交锋 {i + 1}：{slot}" for i, slot in enumerate(self.space))

    def append_new_duel(self, duel_slot_instance):
        duel_slot_instance.game = self.game
        duel_slot_instance.settled = True
        self.space.append(duel_slot_instance)

    def is_empty_duel(self, target_side, target_duel_index):
        return (target_duel_index >= len(self.space)
                or not self.space[target_duel_index].content.get(target_side))

    def locate_nearest_empty_duel(self, target_side):
        return next((i for i in range(len(self.space)) if self.is_empty_duel(target_side, i)),
                    len(self.space))

    def has_next_duel(self):
        return any(any(slot.content.values()) or any(slot.tail_is_live(card) for card in slot.dice_tails)
                   for slot in self.space[self.current_duel_index:])


class DuelSlot:
    def __init__(self, game=None):
        self.game = game
        self.content = {}
        self.settled = False
        self.end_requested = False
        self.current_card_index = {}
        self.used_skill_faces = {}
        # A continuation plays the original dice. The physical card stays in its own slot.
        self.dice_tails = {}
        self.damage_taken = {}
        self.status_lost = {}

    def add_content(self, side, content):
        self.content.setdefault(side, []).append(content)

    def get_content(self, side):
        return self.content.get(side, [])

    def play_mode(self, card):
        return None

    def get_current_card(self, side):
        cards = self.get_content(side)
        index = self.current_card_index.get(side, 0)
        return cards[index] if index < len(cards) else None

    def has_next_card(self, side):
        return self.get_current_card(side) is not None

    def playable_cards(self, side):
        """Inspect the remaining live cards without advancing this side's cursor."""
        for card in self.get_content(side)[self.current_card_index.get(side, 0):]:
            if card.character.is_alive and not card.destroyed and card.state != CardState.NEGATED:
                yield card

    def next_playable_card(self, side):
        while (card := self.get_current_card(side)) is not None:
            if card.character.is_alive and not card.destroyed and card.state != CardState.NEGATED:
                return card
            self.advance_card(side)
        return None

    def tail_is_live(self, card):
        if card not in self.dice_tails:
            return False
        origin, instances = self.dice_tails[card]
        return (not card.destroyed and card.character.is_alive and card.instantiated_dice is instances
                and card in origin.get_content(card.player.side))

    def next_combat_card(self, side, *, advance=True):
        ordinary = self.next_playable_card(side) if advance else next(self.playable_cards(side), None)
        if ordinary is not None:
            return ordinary
        return next((card for card in self.dice_tails
                     if card.player.side == side and self.tail_is_live(card)), None)

    def get_current_opposing_card(self, attacking_side):
        if self.game:
            side = next(p.side for p in self.game.players if p.side != attacking_side)
        else:
            side = next((side for side in self.content if side != attacking_side), None)
        return self.get_current_card(side)

    def advance_card(self, side):
        self.current_card_index[side] = self.current_card_index.get(side, 0) + 1

    def finish_card(self, side, card):
        # Death may already have removed the current card and shifted its successor into place.
        if self.get_current_card(side) is card:
            self.advance_card(side)
        self.dice_tails.pop(card, None)

    def remove_card(self, card):
        """Detach this exact card; keep the cursor pointing at the next playable card."""
        side = card.player.side
        cards = self.get_content(side)
        if card not in cards:
            return False
        position = cards.index(card)
        cards.pop(position)
        if position < self.current_card_index.get(side, 0):
            self.current_card_index[side] -= 1
        return True

    def remove_character(self, character):
        removed = []
        for side, cards in self.content.items():
            index = self.current_card_index.get(side, 0)
            self.current_card_index[side] = sum(not card.belongs_to(character) for card in cards[:index])
            removed.extend(card for card in cards if card.belongs_to(character))
            cards[:] = [card for card in cards if not card.belongs_to(character)]
        return removed

    def resolve_target_character(self, attacking_side, clash_pair=None, previous_opponent=None):
        attacking_player = next(p for p in self.game.players if p.side == attacking_side)
        enemy = next(p for p in self.game.players if p is not attacking_player)
        if clash_pair and enemy.side in clash_pair.dice_dict:
            defender = clash_pair.dice_dict[enemy.side].card.character
            if defender.is_alive:
                return defender
        for card in (self.get_current_card(enemy.side), previous_opponent):
            if card is not None and card.character.is_alive:
                return card.character
        return attacking_player.choose_one_sided_target(enemy)

    def __str__(self):
        def label(card):
            if card.state == CardState.PLACED_FACE_DOWN:
                return "扣置牌"
            return card.name
        return " / ".join(f"{side} 方 " + "、".join(label(card) for card in cards)
                          for side, cards in self.content.items())


class ClashPair:
    def __init__(self, dice_dict):
        if len(dice_dict) > 2:
            raise ValueError("每次拼点最多两方")
        self.dice_dict = dict(dice_dict)
        self.split = False
        self.skipped = False
        self.drawn = False
        self.unopposed_results = {}

    def clash_roll(self):
        for die in self.dice_dict.values():
            die.roll(clash=len(self.dice_dict) == 2)
        return self.clash_check()

    def clash_check(self):
        if len(self.dice_dict) != 2:
            return {}
        (a, die_a), (b, die_b) = self.dice_dict.items()
        sides = ((die_a, die_b), (die_b, die_a))
        # Both final scores settle before either side derives a clash score.
        for opcode in (OpCode.RESOLVE_FINAL_SCORE, OpCode.RESOLVE_CLASH_SCORE):
            for die, opposing in sides:
                initial = die.calculate_final_score() if opcode == OpCode.RESOLVE_FINAL_SCORE else die.final_score
                target = getattr(opposing.card, "character", None)
                if die.resolve_value(opcode, initial, target=target,
                                     opponent_card=opposing.card, opponent_die=opposing) is None:
                    return None
        va, vb = die_a.clash_score, die_b.clash_score
        if va == vb:
            return {a: "draw", b: "draw"}
        lower_wins = die_a.reverses_clash or die_b.reverses_clash
        winner, loser = (a, b) if (va < vb if lower_wins else va > vb) else (b, a)
        return {winner: "win", loser: "lose"}
