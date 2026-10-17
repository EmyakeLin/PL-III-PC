# game.py
from pipeline.pipeline import Pipeline
from pipeline.pipeline_steps import step_list

from types import SimpleNamespace

from context.context import Context
from models.duel import DuelSpace, DuelSlot

from models.character import Character

from gamerule import GameRule

class Game:
    def __init__(self, players):
        self.players = players
        self.gamerule = GameRule()
        for p in self.players:
            p.game = self
            p.max_cost = self.gamerule.MAX_BASIC_COST
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

    def select_character(self, characters):
        import copy
        import random
        from models.character import Character

        pool = copy.deepcopy(characters)
        chosen_data = {p: [] for p in self.players}

        # === 阶段一：纯数据挑选阶段 ===
        max_char_count = self.gamerule.MAX_CHAR_COUNT
        for p in self.players:
            while len(chosen_data[p]) < max_char_count:
                print(f"\n--- [{p.name}] 请选择角色 (已选 {len(chosen_data[p])}/{max_char_count}) ---")
                for idx, c in enumerate(pool, start=1):
                    print(f"  [{idx}] {c['name']} ({c['rank']})")
                
                val = input("请输入角色编号 (直接回车确认并结束选人): ").strip()
                if not val:
                    if len(chosen_data[p]) == 0:
                        print("至少需要选择 1 个角色！")
                        continue
                    break
                
                if val.isdigit() and 1 <= int(val) <= len(pool):
                    picked = pool.pop(int(val) - 1)
                    chosen_data[p].append(picked)
                    print(f"已暂选: {picked['name']}")
                else:
                    print("无效输入，请重新输入。")
            
            print(f"[{p.name}] 阵容锁定: {[c['name'] for c in chosen_data[p]]}")

        # === 阶段二：双方全部确认后，统一实例化与装配卡组 ===
        print("\n=== 双方确认完毕，正在初始化角色与牌库 ===")
        for p in self.players:
            p.characters = []
            for data in chosen_data[p]:
                char = Character(data, p)
                char.init_cards()
                char.setup_deck()
                p.characters.append(char)
            p.cardspace.draw.shuffle()
            print(f"[{p.name}] 就绪！出战角色: {[c.name for c in p.characters]}，牌库总数: {len(p.cardspace.draw.content)}")
            

    def next_step(self):
        """推进一小步管线"""
        return self.pipeline.next_step()

    def auto_place_in_duel(self, side, content):
        """Place in the nearest empty duel"""
        idx = self.duelspace.locate_nearest_empty_duel(side)
        self.place_in_duel(side, content, idx)

    def place_in_duel(self, side, content, duel_idx):
        from entry.builtin_operations import parse_builtin_operation
        op = parse_builtin_operation(f"Place-Card: {side}, {duel_idx}, {id(content)}", self)
        self.context.eval_block(op)


    def switch_place_right(self):
        """切换放置权；必须提前检查是否均置卡结束"""
        if self.ended_player:
            if self.ended_player == self.players:
                raise Exception("All players have ended placement, but switch_place_right() is still called. This should not happen.")
            self.placing = [p for p in self.players if p not in self.ended_player][0]
        else:
            self.placing = [p for p in self.players if p != self.placing][0]