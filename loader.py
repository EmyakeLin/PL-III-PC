import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


PACKS = Path(__file__).parent / "_packs"


@dataclass
class EffectDefinitions:
    status_rules: dict = field(default_factory=dict)
    status_entries: dict = field(default_factory=dict)
    ability_rules: dict = field(default_factory=dict)
    turn_end_statuses: list = field(default_factory=list)
    status_aliases: dict = field(default_factory=dict)

    def resolve_aliases(self):
        for name, aliases in self.status_aliases.items():
            rule = self.status_rules.get(name, {})
            self.status_rules[name] = {**rule, "aliases": list(dict.fromkeys([*rule.get("aliases", ()), *aliases]))}
        return self


def _add_effects(definitions, pack):
    for character in pack.get("characters", ()):
        for action in character.get("actions", ()):
            _validate_action(action)
    for name, rule in pack.get("status_rules", {}).items():
        if name in definitions.status_rules:
            raise ValueError(f"重复的状态规则 {name}")
        retired = {"restrict_highest_hand_cost", "overflow_batch"} & rule.keys()
        if retired:
            raise ValueError(f"{name} 含有已移除的状态字段 {sorted(retired)}，请在 skill_use 或 global_entries 中声明规则")
        if rule.get("pool", "character") not in ("character", "team"):
            raise ValueError(f"{name} 的层数归属须为 character 或 team")
        cap = rule.get("cap")
        if "cap" in rule and (type(cap) is not int or cap < 0):
            raise ValueError(f"{name} 的上限须为非负整数")
        if type(rule.get("track_overflow", False)) is not bool:
            raise ValueError(f"{name} 的溢出累计标记须为布尔值")
        if any(target == name or type(amount) is not int or amount <= 0
               for target, amount in rule.get("sustain", {}).items()):
            raise ValueError(f"{name} 的持续加成须指定其他状态及正整数层数")
        if type(rule.get("max_hp_per_stack", 0)) is not int or type(rule.get("permanent", False)) is not bool:
            raise ValueError(f"{name} 的每层生命上限修正须为整数，永久标记须为布尔值")
        activation = rule.get("activation")
        if activation is not None and (not isinstance(activation, dict)
                or not isinstance(activation.get("operation"), (str, dict, list))
                or not isinstance(activation.get("label", name), str)
                or type(activation.get("remove_after", False)) is not bool):
            raise ValueError(f"{name} 的发动规则须指定有效的操作、名称与移除标记")
        definitions.status_rules[name] = rule
    for name, aliases in pack.get("status_aliases", {}).items():
        if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias for alias in aliases):
            raise ValueError(f"{name} 的别名须为非空字符串列表")
        definitions.status_aliases.setdefault(name, []).extend(aliases)
    definitions.turn_end_statuses.extend(pack.get("turn_end_statuses", ()))
    for name, entries in pack.get("status_entries", {}).items():
        if name in definitions.status_entries:
            raise ValueError(f"重复的状态定义 {name}")
        definitions.status_entries[name] = [dict(entry, origin="status") for entry in entries]
    for name, rule in pack.get("ability_rules", {}).items():
        if name in definitions.ability_rules:
            raise ValueError(f"重复的能力效果 {name}")
        if "action" in rule:
            _validate_action(rule["action"])
        definitions.ability_rules[name] = rule


def _validate_action(action):
    from entry.predicates import compile_when

    if "requires_draw_pile" in action:
        raise ValueError("主动能力的牌堆条件须在 when 中声明")
    compile_when(action.get("when", []), None, None)


def _read_pack(path, definitions):
    try:
        pack = json.loads(path.read_text(encoding="utf-8-sig"))
        _add_effects(definitions, pack)
        return pack
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"卡包 {path.name} 无法载入：{exc}") from exc


def _shared_effects(directory):
    # A custom roster inherits the shared packs. A complete copied pack directory
    # can supply the same filenames locally without registering each effect twice.
    paths = {p.name: p for p in (PACKS / "effects").glob("*.json")}
    paths.update({p.name: p for p in (directory / "effects").glob("*.json")})
    definitions = EffectDefinitions()
    for _, path in sorted(paths.items()):
        _read_pack(path, definitions)
    return definitions


@lru_cache(maxsize=1)
def base_effects():
    """Built-in definitions for games and model objects created without a roster loader."""
    return _shared_effects(PACKS).resolve_aliases()


def load_characters_from_packs(packs_dir=None, *, extra_packs=()):
    from models.card import validate_skill_traits
    from models.conditions import validate_skill_gate
    from models.character import CharacterRank, RANK_SKILL_COUNT
    from models.dice import Dice

    directory = Path(packs_dir) if packs_dir is not None else PACKS
    if not directory.is_dir():
        raise ValueError(f"找不到卡包目录 {directory}")
    characters = []
    ids = set()
    definitions = _shared_effects(directory)
    for path in [*sorted(directory.glob("*.json")), *extra_packs]:
        pack = _read_pack(path, definitions)
        try:
            for original in pack.get("characters", ()):
                char = dict(original, faction=pack.get("faction", ""),
                            faction_passives=pack.get("faction_passives", []),
                            status_entries=definitions.status_entries, status_rules=definitions.status_rules,
                            ability_rules=definitions.ability_rules, turn_end_statuses=definitions.turn_end_statuses)
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
                if "min_max_duels" in char and (type(char["min_max_duels"]) is not int or char["min_max_duels"] < 0):
                    raise ValueError(f"{char['name']} 的交锋额度下限须为非负整数")
                regular = [card for card in char["skills"] if not card.get("out_of_combat")]
                if len(regular) != RANK_SKILL_COUNT[rank]:
                    raise ValueError(f"{char['name']} 应有 {RANK_SKILL_COUNT[rank]} 张常规技能")
                card_ids = set()
                for card in char["skills"]:
                    validate_skill_traits(card)
                    if card.get("deck", "draw") not in ("draw", "decisive"):
                        raise ValueError(f"{card['name']} 指定了无效的起始牌堆")
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
                            if "requires_skill_state" in die_data:
                                validate_skill_gate(die_data["requires_skill_state"])
                            die = Dice(die_data)
                            die.value = 1
                            die.get_value()
                characters.append(char)
        except (ValueError, KeyError, TypeError, SyntaxError) as exc:
            raise ValueError(f"卡包 {path.name} 无法载入：{exc}") from exc
    definitions.resolve_aliases()
    return characters
