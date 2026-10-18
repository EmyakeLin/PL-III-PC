from models.pack_types import PackType
from .pipeline_base import PipelineTriggerNode

class DynamicNode(PipelineTriggerNode):
    def __init__(self, node_id: str, pack_type: PackType, is_wait_check: bool = False):
        super().__init__(node_id)
        self.pack_type = pack_type
        self.is_wait_check = is_wait_check

    def __repr__(self):
        return f"{self.id}"


def create_duel_pack():
    return [
        DynamicNode("before_duel_start", PackType.DUEL),
        DynamicNode("logic_duel_start", PackType.DUEL),
        DynamicNode("on_duel_start", PackType.DUEL),
        DynamicNode("after_duel_start", PackType.DUEL),
        DynamicNode("wait_skill_section_expand_check", PackType.DUEL, is_wait_check=True),
        DynamicNode("before_duel_end", PackType.DUEL),
        DynamicNode("logic_duel_end", PackType.DUEL),
        DynamicNode("on_duel_end", PackType.DUEL),
        DynamicNode("after_duel_end", PackType.DUEL),
        DynamicNode("wait_duel_section_expand_check", PackType.DUEL, is_wait_check=True),
    ]


def create_skill_pack():
    return [
        DynamicNode("before_skill_use", PackType.SKILL),
        DynamicNode("logic_skill_use", PackType.SKILL),
        DynamicNode("on_skill_use", PackType.SKILL),
        DynamicNode("wait_dice_section_expand_check", PackType.SKILL, is_wait_check=True),
        DynamicNode("after_skill_use", PackType.SKILL),
        DynamicNode("wait_skill_section_expand_check", PackType.SKILL, is_wait_check=True),
    ]


def create_dice_pack():
    return [
        DynamicNode("before_dice_use", PackType.DICE),
        DynamicNode("logic_dice_use", PackType.DICE),
        DynamicNode("on_dice_use", PackType.DICE),
        DynamicNode("wait_can_clash_check", PackType.DICE, is_wait_check=True),
        DynamicNode("after_dice_use", PackType.DICE),
        DynamicNode("wait_dice_section_expand_check", PackType.DICE, is_wait_check=True),
    ]


def create_clash_pack():
    return [
        DynamicNode("before_dice_clash", PackType.CLASH),
        DynamicNode("logic_dice_clash", PackType.CLASH),
        DynamicNode("on_dice_clash", PackType.CLASH),
        DynamicNode("wait_clash_result_check", PackType.CLASH, is_wait_check=True),
        DynamicNode("after_dice_clash", PackType.CLASH),
    ]


def create_clash_win_pack():
    return [
        DynamicNode("before_clash_win", PackType.CLASH),
        DynamicNode("logic_resolve_clash_result", PackType.CLASH),
        DynamicNode("on_clash_win", PackType.CLASH),
        DynamicNode("wait_can_hit_check", PackType.CLASH, is_wait_check=True),
        DynamicNode("after_clash_win", PackType.CLASH),
    ]


def create_clash_lose_pack():
    return [
        DynamicNode("before_clash_lose", PackType.CLASH),
        DynamicNode("logic_resolve_clash_result", PackType.CLASH),
        DynamicNode("on_clash_lose", PackType.CLASH),
        DynamicNode("after_clash_lose", PackType.CLASH),
    ]


def create_clash_draw_pack():
    return [
        DynamicNode("before_clash_draw", PackType.CLASH),
        DynamicNode("logic_resolve_clash_result", PackType.CLASH),
        DynamicNode("on_clash_draw", PackType.CLASH),
        DynamicNode("after_clash_draw", PackType.CLASH),
    ]


def create_dice_hit_pack():
    return [
        DynamicNode("before_dice_hit", PackType.HIT),
        DynamicNode("logic_dice_hit", PackType.HIT),
        DynamicNode("on_dice_hit", PackType.HIT),
        DynamicNode("after_dice_hit", PackType.HIT),
    ]
