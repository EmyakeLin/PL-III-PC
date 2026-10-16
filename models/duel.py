

class DuelSpace():
    def __init__(self, game):
        self.game = game
        self.space = []
        self.total_duel_count = 0

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

    def locate_nearest_nonempty_duel(self, target_side):
        for i in range(len(self.space)):
            if self.is_empty_duel(target_side, i):
                return i
        return len(self.space) # 如果所有已加载交锋都被占满了，那么第一个未被加载的交锋一定是空的，而且是最近空交锋（定义上来说）


class DuelSlot():
    def __init__(self):
        self.content = {}
        self.settled = False

    def add_content(self, side, content):
        if not self.content.get(side):
            self.content[side] = [content]
        else:
            self.content[side].append(content)

    def __str__(self):
        return f"[DuelSlot] Content: {self.content}"


    