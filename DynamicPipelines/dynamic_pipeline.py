from collections import deque
from typing import Dict, List, Optional
from .pack_types import PackType
from .packs import (
    DynamicNode,
    create_duel_pack,
    create_skill_pack,
    create_dice_pack,
    create_clash_pack,
    create_clash_win_pack,
    create_clash_lose_pack,
    create_clash_draw_pack,
    create_dice_hit_pack,
)

class SidePipeline:
    def __init__(self, side: int):
        self.side = side
        self.queue = deque()
        self.blocked_at: Optional[DynamicNode] = None
        self.current_node: Optional[DynamicNode] = None

    @property
    def current_pack_type(self) -> PackType:
        if self.blocked_at:
            return self.blocked_at.pack_type
        if self.queue:
            return self.queue[0].pack_type
        return PackType.NONE

    def push_pack(self, pack_nodes: List[DynamicNode]):
        """将打包好的新 Section 注入到待办队列的最前列（展开），并解除当前阻塞"""
        self.blocked_at = None
        for node in reversed(pack_nodes):
            self.queue.appendleft(node)

    def unblock(self):
        """仅解除当前 wait 节点的阻塞，继续往下流经"""
        self.blocked_at = None

    def step(self):
        """执行单步：若遇到 wait 节点则自我阻塞并停住"""
        if self.blocked_at is not None:
            return f"BLOCKED({self.blocked_at.id})"

        if not self.queue:
            return "NONE"

        node = self.queue.popleft()
        if node.is_wait_check:
            self.blocked_at = node
            return f"BLOCKED({node.id})"

        self.current_node = node
        return node.id


class DynamicPipeline:
    def __init__(self, mock_slot, sides: List[int] = [1, 2]):
        self.mock_slot = mock_slot
        self.sides: Dict[int, SidePipeline] = {s: SidePipeline(s) for s in sides}
        self.is_finished = False

        # 初始化：检测并向满足条件的 SidePipeline 注入 DUEL SECTION
        self._check_duel_start()

    def _check_duel_start(self):
        for side, pipe in self.sides.items():
            if self.mock_slot.has_cards(side):
                pipe.push_pack(create_duel_pack())

    def _eligible_sides(self) -> List[int]:
        """当前槽位中放了卡的有效参战阵营"""
        return [s for s in self.sides if self.mock_slot.has_cards(s)]

    def check_and_dispatch(self) -> Optional[str]:
        """
        主管线巡视并分发 Packs：
        根据各个 SidePipeline 的阻塞状态以及战局事实做判定与发包。
        """
        dispatched_events = []

        # 1. 检查技能展开检查点 (wait_skill_section_expand_check) - 单独发包
        for side, pipe in self.sides.items():
            if pipe.blocked_at and pipe.blocked_at.id == "wait_skill_section_expand_check":
                if self.mock_slot.has_next_card(side):
                    self.mock_slot.advance_card(side)
                    pipe.push_pack(create_skill_pack())
                    dispatched_events.append(f"Push Packed SKILL to Side {side}")
                else:
                    pipe.unblock()

        # 2. 检查骰子展开检查点 (wait_dice_section_expand_check) - 单独发包
        for side, pipe in self.sides.items():
            if pipe.blocked_at and pipe.blocked_at.id == "wait_dice_section_expand_check":
                if self.mock_slot.has_next_die(side):
                    self.mock_slot.advance_die(side)
                    pipe.push_pack(create_dice_pack())
                    dispatched_events.append(f"Push Packed DICE to Side {side}")
                else:
                    pipe.unblock()

        # 3. 检查拼点检查点 (wait_can_clash_check) - 双方/多方等待对齐
        blocked_can_clash = [
            s for s in self.sides
            if self.sides[s].blocked_at and self.sides[s].blocked_at.id == "wait_can_clash_check"
        ]
        eligible = self._eligible_sides()

        if blocked_can_clash and set(blocked_can_clash) == set(eligible):
            if len(eligible) >= 2:
                # 双方全部就位，推送 CLASH SECTION
                for s in eligible:
                    self.sides[s].push_pack(create_clash_pack())
                dispatched_events.append("All sides ready -> Push Packed CLASH to all sides")
            elif len(eligible) == 1:
                # 单方面攻击：直接判定 can_hit
                solo_side = eligible[0]
                if self.mock_slot.can_hit(solo_side):
                    self.sides[solo_side].push_pack(create_dice_hit_pack())
                    dispatched_events.append(f"One-sided hit -> Push Packed DICE HIT to Side {solo_side}")
                else:
                    self.sides[solo_side].unblock()

        # 4. 检查拼点结果检查点 (wait_clash_result_check)
        blocked_clash_result = [
            s for s in self.sides
            if self.sides[s].blocked_at and self.sides[s].blocked_at.id == "wait_clash_result_check"
        ]
        if blocked_clash_result and set(blocked_clash_result) == set(eligible):
            # 获取拼点结果并分发不同包
            results = self.mock_slot.resolve_clash(eligible)
            for s, res in results.items():
                if res == "WIN":
                    self.sides[s].push_pack(create_clash_win_pack())
                elif res == "LOSE":
                    self.sides[s].push_pack(create_clash_lose_pack())
                else:
                    self.sides[s].push_pack(create_clash_draw_pack())
            dispatched_events.append(f"Clash resolved: {results} -> Push Win/Lose packs")

        # 5. 检查命中检查点 (wait_can_hit_check)
        for s in eligible:
            pipe = self.sides[s]
            if pipe.blocked_at and pipe.blocked_at.id == "wait_can_hit_check":
                if self.mock_slot.can_hit(s):
                    pipe.push_pack(create_dice_hit_pack())
                    dispatched_events.append(f"Can hit verified -> Push Packed DICE HIT to Side {s}")
                else:
                    pipe.unblock()

        # 6. 检查交锋结束检查点 (wait_duel_section_expand_check)
        blocked_duel_expand = [
            s for s in self.sides
            if self.sides[s].blocked_at and self.sides[s].blocked_at.id == "wait_duel_section_expand_check"
        ]
        if blocked_duel_expand and set(blocked_duel_expand) == set(eligible):
            self.is_finished = True
            dispatched_events.append("Duel Section fully completed")

        return "; ".join(dispatched_events) if dispatched_events else None

    def next_step(self):
        """
        单步推进：
        1. 先由主管线巡视并分发 Pack；
        2. 依据阶梯等待规则调度当前步进者：
           - 有方处于 HIT 时，CLASH 等 HIT；
           - 有方处于 SKILL 且另一方处于 DICE 时，DICE 等 SKILL；
           - 有方处于 DUEL 且另一方处于更低层级时，低层级等 DUEL；
           - 其余情况（同层级，或一方为 NONE）：共同推进，谁都不用等 NONE！
        3. 返回 (action_A, action_B)。
        """
        if self.is_finished:
            return ("FINISHED", "FINISHED")

        # 步骤 1: 巡视发包
        event = self.check_and_dispatch()
        if event:
            return ("[PIPELINE]", event)

        # 步骤 2: 读取各方当前的 PackType 位阶
        types = {s: self.sides[s].current_pack_type for s in self.sides}
        active_sides = [s for s in self.sides if types[s] != PackType.NONE]

        if not active_sides:
            self.is_finished = True
            return ("FINISHED", "FINISHED")

        # 步骤 3: 确定谁该走、谁该等（谁都不用等 NONE）
        runnable_sides = set()
        
        # 规则 A: 有方在打 HIT 伤害，CLASH 必须等待 HIT 结算完毕
        if any(types[s] == PackType.HIT for s in active_sides):
            runnable_sides = {s for s in active_sides if types[s] == PackType.HIT}

        # 规则 B: 有方处于 DUEL，低层级等待 DUEL 产出 SKILL
        elif any(types[s] == PackType.DUEL for s in active_sides) and any(types[s] in (PackType.SKILL, PackType.DICE) for s in active_sides):
            runnable_sides = {s for s in active_sides if types[s] == PackType.DUEL}

        # 规则 C: 有方处于 SKILL，DICE 等待 SKILL 产出 DICE
        elif any(types[s] == PackType.SKILL for s in active_sides) and any(types[s] == PackType.DICE for s in active_sides):
            runnable_sides = {s for s in active_sides if types[s] == PackType.SKILL}

        # 规则 D: 同层级或无高阶依赖，全员共同推进
        else:
            runnable_sides = set(active_sides)

        # 步骤 4: 产生本步动作
        results = {}
        for s in self.sides:
            pipe = self.sides[s]
            if types[s] == PackType.NONE:
                results[s] = None
            elif s not in runnable_sides:
                results[s] = f"WAIT_{types[s].name}"
            else:
                results[s] = pipe.step()

        side_list = sorted(self.sides.keys())
        return (results[side_list[0]], results[side_list[1]])
