import random

from models.duel import DuelSlot, DuelSpace
from models.opcode import OpCode
from game import Game
from entry.builtin_operations import parse_builtin_operation

class Player():
    def __init__(self, side, name):
        self.game: Game
        
        self.side = side
        self.name = name

        self.characters = []

        # deck
        from .card_space import CardSpace
        self.cardspace = CardSpace(self)

    

    def calculate_speed(self):
        """ONLY FOR TEMPORARY USE! NOT REAL GAME LOGIC!!!"""
        self.speed = random.randint(1,4)


    def draw_card(self, draw_count):
        op = parse_builtin_operation(f"Draw-Card: {draw_count}", self)
        self.game.context.eval_block(op)

    def select_card(self, total_draw, draw_count):
        """抽X弃Y"""
        for c in self.cardspace.draw.content[:total_draw]:
            # we use print in mock phase
            print(f"[{self.cardspace.draw.content.index(c) + 1}] {c.name}, cost: {c.cost}")

        while True:
            ask = list(input("Please select which card to discard. Type the index."))
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
        input_text = input(f"[{self.name}] Place card in this duel? Type anything to place. If you typed \"end\", you will announce [End Placement] after you place your card; if you don't type anything, you will announce [End Placement] immediately. \n - Choice: ")
        if input_text != "":
            do_place = True
        else:
            do_place = False
        if do_place:
            # firstly find out the nearest empty duel of this player
            ned_index = game.duelspace.locate_nearest_nonempty_duel(self.side)
            print(f"[debug] Located NED at duel idx {ned_index}")
            game.auto_place_in_duel(self.side, f"Card of {self.name}")
            return "placed" if input_text != "end" else "ended"
        else:
            return "ended"
