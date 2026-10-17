
from .player import Player
from models.card import Card

class CardList():
    def __init__(self, all_cards = None):
        self.content = list(all_cards) if all_cards is not None else []

    def add_card(self, card, position = -1):
        """Do not pass `position` to let card append in the end of the list (latest)"""
        if position == -1:
            self.content.append(card)
        elif position > len(self.content): # if the index is too big, we put it at the latest
            self.content.append(card)
        elif position >= 0: # if it's a valid index
            self.content.insert(position, card)

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
        return self.content.pop(index)


    def move_card_to(self, index, target_deck: CardList):
        if isinstance(index, Card):
            if not index in self.content:
                raise ValueError("Card does not exist!")
            idx = self.content.index(index)
        elif isinstance(index, int):
            if index >= len(self.content):
                raise ValueError("Card does not exist!")
            idx = index
        else:
            raise TypeError("Wrong type: index must be int or Card!")
        target_deck.add_card(self.remove_card(idx))

    def shuffle(self):
        import random
        random.shuffle(self.content)
        
class Hand(CardList):
    def __init__(self, player: Player, all_cards = None):
        super().__init__(all_cards)
        self.player = player

class Draw(CardList):
    def __init__(self, player: Player, all_cards = None):
        super().__init__(all_cards)
        self.player = player

class DelayedDiscard(CardList):
    def __init__(self, player: Player, all_cards = None):
        super().__init__(all_cards)
        self.player = player

    def push_to_draw(self):
      while len(self.content) > 0:
          self.move_card_to(0, self.player.cardspace.draw)
          
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