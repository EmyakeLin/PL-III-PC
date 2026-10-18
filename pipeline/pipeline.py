from collections import deque
from typing import Dict, List, Optional

from .pipeline_base import PipelineNode, PipelineTriggerNode, PipelineSection
from models.pack_types import PackType
from .pipeline_packs import (
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
from .pipeline_errors import (
    PipelineError,
    PipelineSystemError,
    PipelineCompileError,
    PipelineScopeError,
    PipelineRecursionLimitError,
    PipelineFlowControl,
    PipelineFinished,
    PipelineHalted,
    PipelineMishapError,
    StackUnderflowError,
    InvalidTargetError,
    CostExceededError,
)


class SidePipeline:
    def __init__(self, side: int, game = None):
        self.side = side
        self.game = game
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
            node.game = self.game
            self.queue.appendleft(node)

    def unblock(self):
        """仅解除当前 wait 节点的阻塞，继续往下流经"""
        self.blocked_at = None

    def is_blocked_at(self, check_id: str) -> bool:
        """检查当前管线是否被指定的检查节点阻塞"""
        return self.blocked_at is not None and self.blocked_at.id == check_id

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
        node.game = self.game
        node.execute()
        return node.id


class DynamicPipeline:
    def __init__(self, game, sides: List[int] = [1, 2]):
        self.game = game
        self.sides: Dict[int, SidePipeline] = {s: SidePipeline(s, game) for s in sides}
        self.is_finished = False

        # 初始化：检测并向满足条件的 SidePipeline 注入 DUEL SECTION
        self._check_duel_start()

    def _check_duel_start(self):
        current_duel = self.game.duelspace.current_duel if hasattr(self.game.duelspace, "current_duel") else None
        for side, pipe in self.sides.items():
            has_cards = False
            if current_duel and hasattr(current_duel, "content"):
                cards = current_duel.content.get(side, [])
                has_cards = any(c != "" for c in cards)
            if has_cards:
                pipe.push_pack(create_duel_pack())

    def _eligible_sides(self) -> List[int]:
        """当前槽位中真正放了卡的有效参战阵营"""
        current_duel = self.game.duelspace.current_duel if hasattr(self.game.duelspace, "current_duel") else None
        eligible = []
        for side in self.sides:
            if current_duel and hasattr(current_duel, "content"):
                cards = current_duel.content.get(side, [])
                if any(c != "" for c in cards):
                    eligible.append(side)
        return eligible

    def check_and_dispatch(self) -> Optional[str]:
        """
        主管线巡视并分发 Packs：
        根据各个 SidePipeline 的阻塞状态以及战局事实做判定与发包。
        """
        dispatched_events = []
        current_duel = self.game.duelspace.current_duel if hasattr(self.game.duelspace, "current_duel") else None
        eligible = self._eligible_sides()

        # 1. 检查技能展开检查点 (wait_skill_section_expand_check)
        for side, pipe in self.sides.items():
            if pipe.is_blocked_at("wait_skill_section_expand_check"):
                has_next = current_duel.has_next_card(side) if (current_duel and hasattr(current_duel, "has_next_card")) else False
                if has_next:
                    pipe.push_pack(create_skill_pack())
                    dispatched_events.append(f"Push Packed SKILL to Side {side}")
                else:
                    pipe.unblock()

        # 2. 检查骰子展开检查点 (wait_dice_section_expand_check)
        for side, pipe in self.sides.items():
            if pipe.is_blocked_at("wait_dice_section_expand_check"):
                has_next = current_duel.has_next_die(side) if (current_duel and hasattr(current_duel, "has_next_die")) else False
                if has_next:
                    pipe.push_pack(create_dice_pack())
                    dispatched_events.append(f"Push Packed DICE to Side {side}")
                else:
                    pipe.unblock()

        # 3. 检查拼点检查点 (wait_can_clash_check)
        blocked_can_clash = [
            s for s in self.sides
            if self.sides[s].is_blocked_at("wait_can_clash_check")
        ]

        if blocked_can_clash and set(blocked_can_clash) == set(eligible):
            if len(eligible) >= 2:
                for s in eligible:
                    self.sides[s].push_pack(create_clash_pack())
                dispatched_events.append("Push Packed CLASH to all sides")
            elif len(eligible) == 1:
                solo_side = eligible[0]
                # 单方面攻击，直接跳过拼点
                pipe = self.sides[solo_side]
                pipe.unblock()
                pipe.push_pack(create_dice_hit_pack())
                dispatched_events.append(f"One-sided hit -> Push Packed DICE HIT to Side {solo_side}")

        # 4. 检查拼点结果检查点 (wait_clash_result_check) - 拼点真实逻辑暂不急着编
        blocked_clash_result = [
            s for s in self.sides
            if self.sides[s].is_blocked_at("wait_clash_result_check")
        ]
        if blocked_clash_result and set(blocked_clash_result) == set(eligible):
            # 暂留占位分发，等待后续编写具体拼点比对逻辑
            for s in eligible:
                self.sides[s].push_pack(create_clash_draw_pack())
            dispatched_events.append("Clash check reached -> Push clash result packs")

        # 5. 检查命中检查点 (wait_can_hit_check)
        for s in eligible:
            pipe = self.sides[s]
            if pipe.is_blocked_at("wait_can_hit_check"):
                pipe.push_pack(create_dice_hit_pack())
                dispatched_events.append(f"Push Packed DICE HIT to Side {s}")

        # 6. 检查交锋结束检查点 (wait_duel_section_expand_check)
        blocked_duel_expand = [
            s for s in self.sides
            if self.sides[s].is_blocked_at("wait_duel_section_expand_check")
        ]
        if blocked_duel_expand and set(blocked_duel_expand) == set(eligible):
            self.is_finished = True
            dispatched_events.append("Duel Section completed")

        return "; ".join(dispatched_events) if dispatched_events else None

    def step(self):
        """
        单步推进当前交锋的动态发包与执行：
        依据 PackType 阶梯调度当前步进者。
        """
        if self.is_finished:
            return ("FINISHED", "FINISHED")

        event = self.check_and_dispatch()
        if event:
            return ("[PIPELINE]", event)

        types = {s: self.sides[s].current_pack_type for s in self.sides}
        active_sides = [s for s in self.sides if types[s] != PackType.NONE]

        if not active_sides:
            self.is_finished = True
            return ("FINISHED", "FINISHED")

        runnable_sides = set()
        if any(types[s] == PackType.HIT for s in active_sides):
            runnable_sides = {s for s in active_sides if types[s] == PackType.HIT}
        elif any(types[s] == PackType.DUEL for s in active_sides) and any(types[s] in (PackType.SKILL, PackType.DICE) for s in active_sides):
            runnable_sides = {s for s in active_sides if types[s] == PackType.DUEL}
        elif any(types[s] == PackType.SKILL for s in active_sides) and any(types[s] == PackType.DICE for s in active_sides):
            runnable_sides = {s for s in active_sides if types[s] == PackType.SKILL}
        else:
            runnable_sides = set(active_sides)

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


class Pipeline():
    def __init__(self, game = None, step_list = []):
        self.game = game
        self.step_list = step_list
        self.current_step_index = -1
        self.is_finished = False

    def next_step(self):
        if self.is_finished or self.current_step_index >= len(self.step_list) - 1:
            self.is_finished = True
            raise PipelineFinished("管线所有步骤已执行完毕", step_index=self.current_step_index)

        self.current_step_index += 1
        cur_step = self.step_list[self.current_step_index]
        cur_step.game = self.game
        cur_step.execute()
        return cur_step.id
