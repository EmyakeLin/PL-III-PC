

class DuelSpace():
    def __init__(self, game):
        self.game = game
        self.space = []
        self.current_duel_index = 0
        

    def __str__(self):
        response = f"[DuelSpace] Total elements: {len(self.space)}"
        for ds in self.space:
            response += f"\n {ds}"
        return response



    def append_new_duel(self, duel_slot_instance):
        duel_slot_instance.settled = True
        self.space.append(duel_slot_instance)


    def is_empty_duel(self, target_side, target_duel_index):
        if target_duel_index >= len(self.space):
            return True # 超出现在已加载的交锋不等于该交锋不可能存在，反正至少它是空的doge 但是必须写这个if否则会报错
        ds = self.space[target_duel_index]
        if not ds.content.get(target_side) or ds.content[target_side] == []:
            return True
        else:
            return False

    def locate_nearest_empty_duel(self, target_side):
        for i in range(len(self.space)):
            if self.is_empty_duel(target_side, i):
                return i
        return len(self.space) # 如果所有已加载交锋都被占满了，那么第一个未被加载的交锋一定是空的，而且是最近空交锋（定义上来说）

    def has_next_duel(self):
        """检查是否还有未处理的有效交锋（自动剔除尾部空交锋槽位）"""
        total_duel_count = len(self.space)
        i = -1
        while total_duel_count > 0:
            verified = False
            for side in self.space[i].content:
                cards = self.space[i].content[side]
                if cards and any(c != "" for c in cards):
                    verified = True
                    break
            if verified:
                break
            else:
                total_duel_count -= 1
                i -= 1

        return self.current_duel_index < total_duel_count



class DuelSlot():
    def __init__(self):
        self.content = {}
        self.settled = False

    def add_content(self, side, content):
        if not self.content.get(side):
            self.content[side] = [content]
        else:
            self.content[side].append(content)

    def get_content(self, side):
        return self.content[side]

    def has_next_card(self, side):
        pass
    

    def __str__(self):
        card_meta = []
        for side, cards in sorted(self.content.items(), key=lambda item: item[0]):
            for c in cards:
                if hasattr(c, "get_meta"):
                    card_meta.append(c.get_meta(side=True))
                elif c != "":
                    card_meta.append(f"Side {side} | {c}")
        return f"[DuelSlot] Content: {card_meta}"


    