from __future__ import annotations

from .player import Player
from models.card import Card

class CardList():
    def __init__(self, all_cards = None):
        self.content = list(all_cards) if all_cards is not None else []

    def add_card(self, card, position = -1):
        """Do not pass `position` to let card append in the end of the list (latest)"""
        if isinstance(card, Card) and card.temporary:
            card.dissolve()
            return
        before = len(self.content)
        if position == -1:
            self.content.append(card)
        elif position > len(self.content): # if the index is too big, we put it at the latest
            self.content.append(card)
        elif position >= 0: # if it's a valid index
            self.content.insert(position, card)
        self._on_size_changed(before, len(self.content))

    def _on_size_changed(self, before, after):
        """A zone can publish its count after a completed mutation."""

    def get_card(self, index):
        if index >= len(self.content) or index < 0:
            return None
        return self.content[index]

    def get_character(self, index):
        if index >= len(self.content) or index < 0:
            raise ValueError("Card does not exist!")
        return self.content[index].character

    def remove_card(self, index):
        if index >= len(self.content) or index < 0:
            raise ValueError("Card does not exist!")
        before = len(self.content)
        card = self.content.pop(index)
        self._on_size_changed(before, len(self.content))
        return card

    def remove_character(self, character, *, notify=True):
        removed = [card for card in self.content if card.belongs_to(character)]
        if removed:
            before = len(self.content)
            self.content[:] = [card for card in self.content if not card.belongs_to(character)]
            if notify:
                self._on_size_changed(before, len(self.content))
        return removed


    def move_card_to(self, index, target_deck: CardList):
        if isinstance(index, Card):
            if not index in self.content:
                raise ValueError("Card does not exist!")
            idx = self.content.index(index)
        elif isinstance(index, int):
            if not 0 <= index < len(self.content):
                raise ValueError("Card does not exist!")
            idx = index
        else:
            raise TypeError("Wrong type: index must be int or Card!")
        before, target_before = len(self.content), len(target_deck.content)
        target_deck.content.append(self.content.pop(idx))
        if target_deck is not self:
            # Both zones are settled before a listener can move another card.
            self._on_size_changed(before, before - 1)
            target_deck._on_size_changed(target_before, target_before + 1)

    def shuffle(self, rng=None):
        import random
        (random if rng is None else rng).shuffle(self.content)
        
class Hand(CardList):
    def __init__(self, player: Player, all_cards = None):
        super().__init__(all_cards)
        self.player = player

    def cost_rank(self, card):
        # Stable sorting preserves hand order within a tie and excludes teammates' cards.
        candidates = [other for other in self.content if other.character is card.character]
        candidates.sort(key=lambda other: other.cost, reverse=True)
        return candidates.index(card) + 1

    def remember_play_rank(self, card):
        card.hand_cost_rank = self.cost_rank(card)

    def remove_card(self, index):
        if 0 <= index < len(self.content):
            self.remember_play_rank(self.content[index])
        return super().remove_card(index)

    def _on_size_changed(self, before, after):
        if before != after and self.player.game:
            self.player.game.context.dispatch_pipeline(
                "on_hand_changed", player=self.player, side=self.player.side,
                source=None, target=None, card=None, die=None,
                participants=tuple(c for c in self.player.characters if c.is_alive),
                previous_count=before, hand_count=after)

class Draw(CardList):
    def __init__(self, player: Player, all_cards = None):
        super().__init__(all_cards)
        self.player = player

class DelayedDiscard(CardList):
    def __init__(self, player: Player, all_cards = None):
        super().__init__(all_cards)
        self.player = player

    def push_to_draw(self):
        while self.content:
            card = self.content[0]
            card.set_controller(card.printed_owner)
            self.move_card_to(0, card.player.cardspace.draw)
          
class OutOfCombat(CardList):
    def __init__(self, player: Player, all_cards = None):
        super().__init__(all_cards)
        self.player = player

class CardSpace():
    def __init__(self, player: Player):
        """Default: only Hand, Draw, DelayedDiscard, and OutOfCombat"""
        self.hand = Hand(player)
        self.draw = Draw(player)
        self.delayed_discard = DelayedDiscard(player)
        self.out_of_combat = OutOfCombat(player)
