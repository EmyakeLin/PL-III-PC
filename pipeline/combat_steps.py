"""Immutable section templates. A wait consumes its place in the queue;
the central pipeline may insert a whole child section in front of the remainder.
"""

from dataclasses import dataclass
from models.pack_types import PackType

NEXT_CARD = "wait_skill_section_expand_check"
NEXT_DIE = "wait_dice_section_expand_check"
CAN_CLASH = "wait_can_clash_check"
RESULT = "wait_clash_result_check"
CAN_HIT = "wait_can_hit_check"
NEXT_DUEL = "wait_duel_section_expand_check"


@dataclass(frozen=True)
class CombatStep:
    id: str
    pack_type: PackType

    @property
    def is_wait(self):
        return self.id.startswith("wait_")


def section(pack_type, *ids):
    return tuple(CombatStep(node_id, pack_type) for node_id in ids)


DUEL_END = section(PackType.DUEL, "before_duel_end", "logic_duel_end", "on_duel_end", "after_duel_end", NEXT_DUEL)
DUEL = section(PackType.DUEL, "before_duel_start", "logic_duel_start", "on_duel_start",
               "after_duel_start", NEXT_CARD) + DUEL_END
REMAINING_SKILL = section(PackType.SKILL, NEXT_DIE, "after_skill_use", NEXT_CARD)
SKILL = section(PackType.SKILL, "before_skill_use", "logic_skill_use", "on_skill_use") + REMAINING_SKILL
DICE = section(PackType.DICE, "before_dice_use", "logic_dice_use", "on_dice_use",
               CAN_CLASH, "after_dice_use", NEXT_DIE)
SKIPPED_DICE = section(PackType.DICE, "on_clash_skip", NEXT_DIE)
# A die can lose its opponent to an effect after its ordinary DICE packet started.
PASSIVE_SKIP = section(PackType.DICE, "logic_skip_clash", "on_clash_skip")
CLASH = section(PackType.CLASH, "before_dice_clash", "logic_dice_clash", "on_dice_clash",
                RESULT, "after_dice_clash")
HIT = section(PackType.HIT, "before_dice_hit", "logic_dice_hit", "on_dice_hit", "after_dice_hit")


def result_section(result):
    nodes = [f"before_clash_{result}", "logic_resolve_clash_result", f"on_clash_{result}"]
    if result == "win":
        nodes.append(CAN_HIT)
    return section(PackType.CLASH, *nodes, f"after_clash_{result}")
