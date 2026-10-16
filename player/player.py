import random

from models.duel import DuelSlot, DuelSpace

class Player():
    def __init__(self, side, name):
        self.side = side
        self.name = name

    def calculate_speed(self):
        """ONLY FOR TEMPORARY USE! NOT REAL GAME LOGIC!!!"""
        self.speed = random.randint(1,4)


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
