"""Room ruleset definitions, rank power scale, validation, and squad presets."""

import random

RANK_POWER = {
    "NORMAL": 1,
    "ELITE": 2,
    "BOSS": 3,
    "EMPOWERED_BOSS": 4,
    "EXTREME": 5,
}

RANK_LABELS = {
    "NORMAL": "常人",
    "ELITE": "精英",
    "BOSS": "首领",
    "EMPOWERED_BOSS": "强化首领",
    "EXTREME": "极端战力",
}

DUPLICATE_POLICIES = ("team_unique", "strict_unique", "free_duplicates")
PICK_MODES = ("open", "blind", "draft")
ROOM_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_room_code(existing=(), length=6):
    existing_set = set(existing)
    for _ in range(256):
        code = "".join(random.SystemRandom().choice(ROOM_CODE_ALPHABET) for _ in range(length))
        if code not in existing_set:
            return code
    raise RuntimeError("无法分配新的房间码。")


def default_ruleset(*, online=False):
    """Official rulebook baseline, with chill unlimited pause time by default for friend lobbies."""
    return {
        "power_cap": None,                # None (unlimited) or int >= 1
        "max_chars": None,                # None (unlimited) or int >= 1
        "duplicate_policy": "team_unique",  # "team_unique" | "strict_unique" | "free_duplicates"
        "pick_mode": "blind" if online else "open",  # "open" | "blind" | "draft"
        "draft_first_side": 1,            # 1 or 2
        "draw_count": 2,                  # Base cards kept per turn (Turn 1 automatically +1)
        "max_basic_cost": 5,              # Shared faction cost refilled each turn
        "char_independent_cost": 1,       # Personal cost refilled per living character each turn
        "place_capacity": 2,              # Max cards placed per subsequent placement window
        "hp_scale_pct": 100,              # Max HP & Lightcore scale percentage (25..500)
        "pause_limit_s": None,            # None (unlimited) or int seconds (5..600)
        "hotseat_curtain": True,          # Privacy handoff curtains in hotseat mode
    }


def _opt_positive_int(val, label, maximum=999):
    if val is None or val == "" or val == 0:
        return None
    if type(val) is not int or not 1 <= val <= maximum:
        raise ValueError(f"{label}须为不设限或 1～{maximum} 的整数。")
    return val


def _bounded_int(val, label, minimum, maximum):
    if type(val) is not int or not minimum <= val <= maximum:
        raise ValueError(f"{label}须为 {minimum}～{maximum} 的整数。")
    return val


ROOM_RULE_BOUNDS = {
    "draw_count": (1, 12),
    "max_basic_cost": (0, 30),
    "char_independent_cost": (0, 10),
    "place_capacity": (1, 12),
}


def normalize_ruleset(patch, *, base=None, online=False):
    current = dict(base) if base is not None else default_ruleset(online=online)
    if patch is None:
        return current
    if not isinstance(patch, dict):
        raise ValueError("房间规则格式无效。")
    unknown = set(patch) - set(current)
    if unknown:
        raise ValueError(f"包含未知的房间规则项：{', '.join(sorted(unknown))}。")

    out = dict(current)
    if "power_cap" in patch:
        out["power_cap"] = _opt_positive_int(patch["power_cap"], "总战力标度上限", 500)
    if "max_chars" in patch:
        out["max_chars"] = _opt_positive_int(patch["max_chars"], "每方人数上限", 50)
    if "duplicate_policy" in patch:
        val = patch["duplicate_policy"]
        if val not in DUPLICATE_POLICIES:
            raise ValueError("同名角色规则无效。")
        out["duplicate_policy"] = val
    if "pick_mode" in patch:
        val = patch["pick_mode"]
        if val not in PICK_MODES:
            raise ValueError("选人模式无效。")
        out["pick_mode"] = val
    if "draft_first_side" in patch:
        val = patch["draft_first_side"]
        if val not in (1, 2):
            raise ValueError("轮选先手席位须为 1 或 2。")
        out["draft_first_side"] = val
    if "draw_count" in patch:
        out["draw_count"] = _bounded_int(patch["draw_count"], "每回合基础留牌数", *ROOM_RULE_BOUNDS["draw_count"])
    if "max_basic_cost" in patch:
        out["max_basic_cost"] = _bounded_int(patch["max_basic_cost"], "每回合基础通用费", *ROOM_RULE_BOUNDS["max_basic_cost"])
    if "char_independent_cost" in patch:
        out["char_independent_cost"] = _bounded_int(patch["char_independent_cost"], "角色独立费", *ROOM_RULE_BOUNDS["char_independent_cost"])
    if "place_capacity" in patch:
        out["place_capacity"] = _bounded_int(patch["place_capacity"], "单窗口连扣上限", *ROOM_RULE_BOUNDS["place_capacity"])
    if "hp_scale_pct" in patch:
        out["hp_scale_pct"] = _bounded_int(patch["hp_scale_pct"], "生命倍率(%)", 25, 500)
    if "pause_limit_s" in patch:
        val = patch["pause_limit_s"]
        if val is None or val == 0 or val == "":
            out["pause_limit_s"] = None
        else:
            out["pause_limit_s"] = _bounded_int(val, "思考暂停限时(秒)", 5, 600)
    if "hotseat_curtain" in patch:
        if not isinstance(patch["hotseat_curtain"], bool):
            raise ValueError("同屏防窥遮帘开关须为布尔值。")
        out["hotseat_curtain"] = patch["hotseat_curtain"]
    return out


def char_power(spec):
    return RANK_POWER.get(spec.get("rank"), 1)


def team_power(team, pool):
    return sum(char_power(pool[cid]) for cid in team if cid in pool)


def validate_single_team(team, pool, ruleset, *, allow_empty=False):
    if not isinstance(team, (list, tuple)):
        raise ValueError("队伍列表格式无效。")
    items = list(team)
    if not items and not allow_empty:
        raise ValueError("请至少选择 1 名出战角色。")
    seen = set()
    policy = ruleset.get("duplicate_policy", "team_unique")
    for cid in items:
        if not isinstance(cid, str) or cid not in pool:
            raise ValueError("出战角色不在本房间的卡包中。")
        if policy != "free_duplicates" and cid in seen:
            raise ValueError(f"当前房间规则不允许同队重复编入「{pool[cid]['name']}」。")
        seen.add(cid)
    max_chars = ruleset.get("max_chars")
    if max_chars is not None and len(items) > max_chars:
        raise ValueError(f"超出本房间每方人数上限（最多 {max_chars} 人）。")
    power_cap = ruleset.get("power_cap")
    total_p = team_power(items, pool)
    if power_cap is not None and total_p > power_cap:
        raise ValueError(f"队伍总战力（{total_p}）超出本房间上限（{power_cap}）。")
    return items


def validate_match_teams(teams, pool, ruleset, *, fixed_opponent=False):
    if not isinstance(teams, (list, tuple)) or len(teams) != 2:
        raise ValueError("双方都需要有效的出战阵容。")
    t1 = validate_single_team(teams[0], pool, ruleset, allow_empty=False)
    opponent_rules = {**ruleset, "power_cap": None, "max_chars": None} if fixed_opponent else ruleset
    t2 = validate_single_team(teams[1], pool, opponent_rules, allow_empty=False)
    if ruleset.get("duplicate_policy") == "strict_unique":
        overlap = [cid for cid in t1 if cid in set(t2) and not pool[cid].get("mirror_allowed")]
        if overlap:
            names = "、".join(dict.fromkeys(pool[cid]["name"] for cid in overlap))
            raise ValueError(f"全场唯一规则下双方撞车了不可镜像角色：{names}。")
    return [t1, t2]


def snake_turn_side(pick_count, first_side=1):
    """1 - 2 - 2 - 1 - 1 - 2 - 2 - 1 ... snake draft order."""
    second_side = 3 - first_side
    return first_side if ((pick_count + 1) // 2) % 2 == 0 else second_side


def build_opponent_presets(pool):
    """Auto-discover faction squads and boss encounters from loaded character packs."""
    by_faction = {}
    solos = []
    for cid, spec in pool.items():
        faction = (spec.get("faction") or "").strip()
        if faction:
            by_faction.setdefault(faction, []).append(cid)
        if spec.get("rank") in ("BOSS", "EMPOWERED_BOSS", "EXTREME"):
            solos.append(cid)

    presets = []
    for faction, members in by_faction.items():
        if len(members) >= 2:
            squad = members[:4]
            presets.append({
                "id": f"faction:{faction}",
                "name": f"{faction}（{len(squad)}人）",
                "characters": squad,
                "power": team_power(squad, pool),
            })
    for cid in solos:
        spec = pool[cid]
        presets.append({
            "id": f"solo:{cid}",
            "name": f"{RANK_LABELS.get(spec['rank'], '首领')} · {spec['name']}",
            "characters": [cid],
            "power": char_power(spec),
        })
    return presets


def generate_matched_team(pool, target_power, *, ruleset=None, exclude_ids=(), rng=None):
    """Sample an AI opponent squad closely matching `target_power` under the room's ruleset."""
    rules = ruleset or default_ruleset()
    r = rng or random.Random()
    strict = rules.get("duplicate_policy") == "strict_unique"
    candidates = [
        cid for cid, spec in pool.items()
        if not (strict and cid in exclude_ids and not spec.get("mirror_allowed"))
    ]
    if not candidates:
        candidates = list(pool.keys())

    cap = rules.get("power_cap")
    goal = max(1, int(target_power or 3))
    if cap is not None:
        goal = min(goal, cap)
    max_c = rules.get("max_chars") or 4

    best_team = None
    best_diff = 9999
    allow_dup = rules.get("duplicate_policy") == "free_duplicates"

    for _ in range(48):
        team = []
        cur_p = 0
        avail = list(candidates)
        r.shuffle(avail)
        while avail and len(team) < max_c:
            cid = avail.pop()
            p = char_power(pool[cid])
            if cap is not None and cur_p + p > cap:
                continue
            if team and cur_p + p > goal + 1:
                continue
            team.append(cid)
            cur_p += p
            if allow_dup:
                avail.append(cid)
                r.shuffle(avail)
            if cur_p >= goal:
                break
        if not team:
            afford = [c for c in candidates if cap is None or char_power(pool[c]) <= cap]
            if afford:
                pick = min(afford, key=lambda c: abs(char_power(pool[c]) - goal))
                team = [pick]
                cur_p = char_power(pool[pick])
        if team:
            diff = abs(cur_p - goal)
            if diff < best_diff:
                best_diff = diff
                best_team = team
                if diff == 0:
                    break
    return best_team or [next(iter(pool))]
