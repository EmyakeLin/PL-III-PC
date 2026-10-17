from enum import Enum, auto

from models.card import Card

class CharacterRank(Enum):
    NORMAL = auto()
    ELITE = auto()
    BOSS = auto()
    EMPOWERED_BOSS = auto()

RANK_DUEL_MAP = {
    CharacterRank.NORMAL: 1,
    CharacterRank.ELITE: 2,
    CharacterRank.BOSS: 3,
    CharacterRank.EMPOWERED_BOSS: 4,
}

class Character():
    def __init__(self, data: dict, player):
        self.player = player
        self.game = self.player.game

        self.data = data
        self.faction = data["faction"]
        self.id = data["id"]
        self.name = data["name"]
        self.rank = CharacterRank[data["rank"]]
        self.max_duels = RANK_DUEL_MAP[self.rank]
        
        self.max_hp = data["max_hp"]
        self.passive_skill_data= data["passive_skills"]
        self.passive_skills = []
        self.skill_data = data["skills"]
        self.skills = []

        self.hp = self.max_hp
        self.is_alive = True
        self.used_duels = 0
        

        self.independent_cost = self.game.gamerule.CHAR_INDEPENDENT_COST
        self.used_independent_cost = 0

        
    def init_cards(self):
        for s in self.skill_data:
            self.skills.append(Card(self.player, s, self))

    def setup_deck(self):
        for i in range(len(self.skills)):
            if self.skills[i].out_of_combat == True:
                self.player.cardspace.out_of_combat.add_card(self.skills[i])
                continue
            self.player.cardspace.draw.add_card(self.skills[i])

    # def handle_passive_skills(self): xxxxxxxx