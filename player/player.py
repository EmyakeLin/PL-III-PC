import random

from models.duel import DuelSlot, DuelSpace
from models.opcode import OpCode
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from game import Game

class Player():
    def __init__(self, side, name):
        self.game: Game
        
        self.side = side
        self.name = name

        self.characters = []

        self.max_cost = None
        self.used_cost = 0

        # deck
        from .card_space import CardSpace
        self.cardspace = CardSpace(self)

    def reset_on_turn_start(self):
        """Reset some state at logic_turn_start"""
        self.max_cost = self.game.gamerule.MAX_BASIC_COST
        for char in self.characters:
            char.used_duels = 0
            char.used_independent_cost = 0
        self.used_cost = 0

    def calculate_speed(self):
        """ONLY FOR TEMPORARY USE! NOT REAL GAME LOGIC!!!"""
        self.speed = random.randint(1,4)


    def draw_card(self, draw_count):
        from entry.builtin_operations import parse_builtin_operation
        op = parse_builtin_operation(f"Draw-Card: {draw_count}", self)
        self.game.context.eval_block(op)

    def select_card(self, total_draw, draw_count):
        """抽X弃Y"""
        for c in self.cardspace.draw.content[:total_draw]:
            # we use print in mock phase
            print(f"[{self.cardspace.draw.content.index(c) + 1}] {c.name}, cost: {c.cost}")

        while True:
            ask = input("Please select which card to discard. Type the index.").replace(",", " ").split()
            if len(ask) != total_draw - draw_count:
                print(f"Invalid discard amount! Expected: {total_draw - draw_count} inputs!")
            else:
                break
        discard = []
        for a in ask:
            a = int(a)
            a -= 1
            discard.append(self.cardspace.draw.content[a])
        for c in self.cardspace.draw.content[:total_draw]:
            if c in discard:
                self.cardspace.draw.move_card_to(c, self.cardspace.draw)
        self.draw_card(draw_count)

    def place_card(self, game):
        if len(self.cardspace.hand.content) == 0:
            print(f"{self.name} have no card to place. End Placement.")
            return "ended"

        for c in self.cardspace.hand.content:
            print(f"[{self.cardspace.hand.content.index(c) + 1}] {c.name}, cost: {c.cost}")
        while True:
            ask = input("Please select a card to place. If you don't type anything, you announce [End Placement].\n >")
            if ask == "":
                print(f"{self.name} End Placement?")
                confirm = input("Confirm? Type anything to cancel.\n >")
                if confirm == "":
                    print(f"{self.name} Ended Placement.")
                    return "ended"
                else:
                    print("Canceled.")
            else:
                try:
                    ask = int(ask) -1
                    if ask >= 0 and ask < len(self.cardspace.hand.content):
                        # check if the character can access this duel
                        char_max_duels = self.cardspace.hand.get_character(ask).max_duels
                        char_used_duels = self.cardspace.hand.get_character(ask).used_duels
                        if char_used_duels >= char_max_duels:
                            print(f"Character {self.cardspace.hand.get_character(ask).name} have reached max duel count. Cannot place this character's card.")
                            continue

                        print(f"{self.name} Place {self.cardspace.hand.content[ask].name} in Duel {self.game.duelspace.locate_nearest_empty_duel(self.side) +1}?")
                        confirm = ""
                        confirm = input("Confirm? Type anyghing to confirm. Type \"end\" to announce [End Placement] after this place action.\n >")
                        if confirm != "":
                            print(f"{self.name} Placed {self.cardspace.hand.content[ask].name} in Duel {self.game.duelspace.locate_nearest_empty_duel(self.side) +1}.")
                            game.auto_place_in_duel(self.side, self.cardspace.hand.remove_card(ask))
                                                        
                            if confirm == "end":
                                print(f"{self.name} Ended Placement.")
                                return "ended"
                            return "placed"
                        else:
                            print("Canceled.")
                    else:
                        print("Invailid input!")
                except:
                    print("Invailid input!")
            
