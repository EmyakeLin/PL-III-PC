# game.py
from pipeline.pipeline import Pipeline
from pipeline.pipeline_steps import step_list

from types import SimpleNamespace

from context.context import Context
from models.duel import DuelSpace, DuelSlot

class Game:
    def __init__(self, players):
        self.players = players
        self.first_player = None
        self.ended_player = []
        self.turn_count = 0
        self.is_over = False
        
        # 初始化游戏根上下文
        self.context = Context(game=self)

        # 将自身实例 (game=self) 注入到管线中
        self.pipeline = Pipeline(self, step_list)

        # temp variables
        self.tmp = SimpleNamespace()

        # 交锋槽位
        self.duelspace = DuelSpace(self)

    def next_step(self):
        """推进一小步管线"""
        return self.pipeline.next_step()

    def auto_place_in_duel(self, side, content, force_create = False):
        """Place in the nearest empty duel"""
        # firstly check if duelspace has some empty duel for this side
        if not force_create:
            for i in range(len(self.duelspace.space)):
                if self.duelspace.is_empty_duel(side, i):
                    ds = self.duelspace.space[i]
                    ds.add_content(side, content)
                    return
        ds = DuelSlot()
        ds.add_content(side, content)
        self.duelspace.append_new_duel(ds)

    def place_in_duel(self, side, content, duel_idx):
        if duel_idx < len(self.duelspace.space):
            ds = self.duelspace.space[duel_idx]
            ds.add_content(side, content)
        else:
            missing_duels = duel_idx+1 - len(self.duelspace.space)

            for i in range(missing_duels):
                eds = DuelSlot()
                eds.add_content(side, [])
                self.duelspace.append_new_duel(eds)
            ds = self.duelspace.space[duel_idx]
            ds.add_content(side, content)


    def switch_place_right(self):
        """切换放置权；必须提前检查是否均置卡结束"""
        if self.ended_player:
            if self.ended_player == self.players:
                raise Exception("All players have ended placement, but switch_place_right() is still called. This should not happen.")
            self.placing = [p for p in self.players if p not in self.ended_player][0]
        else:
            self.placing = [p for p in self.players if p != self.placing][0]