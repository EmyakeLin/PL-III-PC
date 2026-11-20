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
                if "speed_die" in char:
                    low, high = char["speed_die"]
                    if type(low) is not int or type(high) is not int or not 1 <= low <= high:
                        raise ValueError(f"{char['name']} 的速度骰需要有效的正整数范围")
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
                    extra = card.get("resource_cost")
                    if extra is not None and (not isinstance(extra, dict)
                            or not isinstance(extra.get("status"), str) or not extra["status"]
                            or type(extra.get("amount")) is not int or extra["amount"] <= 0):
                        raise ValueError(f"{card['name']} 的附加费用须指定资源及正整数数量")
                    forms = card.get("forms", {})
                    if not isinstance(forms, dict) or any(not isinstance(form, dict)
                            or not isinstance(form.get("name"), str) or not form["name"]
                            or not isinstance(form.get("dice"), list) for form in forms.values()):
                        raise ValueError(f"{card['name']} 的技能形态须包含名称和骰组")
                    for form in (card, *forms.values()):
                        for die_data in form.get("dice", []):
                            if "requires_skill_state" in die_data and not isinstance(die_data["requires_skill_state"], str):
                                raise ValueError("骰位启用条件须为本次技能状态名称")
                            die = Dice(die_data)
                            die.value = 1
                            die.get_value()
                characters.append(char)
        except (ValueError, KeyError, TypeError, SyntaxError) as exc:
            raise ValueError(f"卡包 {path.name} 无法载入：{exc}") from exc
    return characters
