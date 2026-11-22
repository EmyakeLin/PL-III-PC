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
        if position == -1 or position >= 0:
            self._insert_card(card, len(self.content) if position == -1 else position)
        self._on_size_changed(before, len(self.content))

    def _insert_card(self, card, position):
        self.content.insert(min(position, len(self.content)), card)

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
        card = self.content.pop(idx)
        if target_deck is self:
            self.content.append(card)
            return
        target_deck._insert_card(card, target_before)
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

    def _insert_card(self, card, position):
        if isinstance(card, Card):
            card.play_observations = {}
        super()._insert_card(card, position)

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
    def zone(self, name):
        if name not in ("hand", "draw", "delayed_discard", "out_of_combat"):
            raise ValueError(f"未知牌区 {name!r}")
        return getattr(self, name)

    def __init__(self, player: Player):
        """Default: only Hand, Draw, DelayedDiscard, and OutOfCombat"""
        self.hand = Hand(player)
        self.draw = Draw(player)
        self.delayed_discard = DelayedDiscard(player)
        self.out_of_combat = OutOfCombat(player)
