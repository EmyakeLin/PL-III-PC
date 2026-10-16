
from .player import Player

class CardList():
    def __init__(self, all_cards = []):
        self.content = all_cards

    def add_card(self, card, position = -1):
        """Do not pass `position` to let card append in the end of the list (latest)"""
        if position == -1:
            self.content.append(card)
        elif position > len(self.content): # if the index is too big, we put it at the latest
            self.content.append(card)
        elif position >= 0: # if it's a valid index
            self.content.insert(position, card)

    def get_card(self, index):
        if index > len(self.content):
            return None
        return self.content[index]

    def remove_card(self, index):
        if index > len(self.content):
            raise ValueError("Card does not exist!")
        return self.content.pop(index)


    def move_card_to(self, index, target_deck: CardList):
        if index > len(self.content):
            raise ValueError("Card does not exist!")
        target_deck.add_card(self.remove_card(index))
        
class Hand(CardList):
    def __init__(self, player: Player, all_cards = []):
        self.content = all_cards
        self.player = player

class Draw(CardList):
    def __init__(self, player: Player, all_cards = []):
        self.content = all_cards
        self.player = player

class DelayedDiscard(CardList):
    def __init__(self, player: Player, all_cards = []):
        self.content = all_cards
        self.player = player

    def push_to_draw(self):
        for i in range(len(self.content)):
            self.move_card_to(self.content[i],self.player.cardarea.draw)

class OutOfCombat(CardList):
    def __init__(self, player: Player, all_cards = []):
        self.conteng = all_cards
        self.player = player

class CardArea():
    def __init__(self, player: Player):
        """Default: only Hand, Draw, DelayedDiscard, and OutOfCombat"""
        self.hand = Hand(player)
        self.draw = Draw(player)
        self.delayed_discard = DelayedDiscard(player)
        self.out_of_combat = OutOfCombat(player)