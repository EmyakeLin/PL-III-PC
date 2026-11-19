import json
from pathlib import Path


def load_characters_from_packs(packs_dir=None):
    from models.card import validate_skill_traits
    from models.character import CharacterRank, RANK_SKILL_COUNT
    from models.dice import Dice

    directory = Path(packs_dir) if packs_dir is not None else Path(__file__).parent / "_packs"
    if not directory.is_dir():
        raise ValueError(f"找不到卡包目录 {directory}")
    characters = []
    ids = set()
    status_entries = {}
    turn_end_statuses = []
    for path in sorted(directory.glob("*.json")):
        try:
            pack = json.loads(path.read_text(encoding="utf-8-sig"))
            turn_end_statuses.extend(pack.get("turn_end_statuses", ()))
            for name, entries in pack.get("status_entries", {}).items():
                if name in status_entries:
                    raise ValueError(f"重复的状态定义 {name}")
                status_entries[name] = [dict(entry, origin="status") for entry in entries]
            for original in pack["characters"]:
                char = dict(original, faction=pack.get("faction", ""),
                            faction_passives=pack.get("faction_passives", []),
                            status_entries=status_entries, turn_end_statuses=turn_end_statuses)
                rank = CharacterRank[char["rank"]]
                if char["id"] in ids:
                    raise ValueError(f"重复的角色 ID {char['id']}")
                ids.add(char["id"])
                if char["max_hp"] <= 0:
                    raise ValueError(f"{char['name']} 的生命上限必须为正")
                if "base_max_duels" in char and (type(char["base_max_duels"]) is not int or char["base_max_duels"] < 1):
                    raise ValueError(f"{char['name']} 的基础交锋上限必须为正整数")
                regular = [card for card in char["skills"] if not card.get("out_of_combat")]
                if len(regular) != RANK_SKILL_COUNT[rank]:
                    raise ValueError(f"{char['name']} 应有 {RANK_SKILL_COUNT[rank]} 张常规技能")
                card_ids = set()
                for card in char["skills"]:
                    validate_skill_traits(card)
                    if card["id"] in card_ids or card["cost"] < 0:
                        raise ValueError(f"{char['name']} 的技能 ID 重复或费用无效")
                    card_ids.add(card["id"])
                    for die_data in card.get("dice", []):
                        die = Dice(die_data)
                        die.value = 1
                        die.get_value()
                characters.append(char)
        except (ValueError, KeyError, TypeError, SyntaxError) as exc:
            raise ValueError(f"卡包 {path.name} 无法载入：{exc}") from exc
    return characters
