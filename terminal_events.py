"""Chinese hot-seat presentation of settled battle facts."""

from entry.effects import GRADE_NAMES
from models.dice import TYPE_NAMES


MESSAGES = {
    "duel_started": "结算{series} {number}",
    "duel_skipped": "进攻牌或目标已离场，本场交锋跳过。",
    "range_advantage": "「{card}」对「{opposing}」有 {amount} 级远程优势。",
    "die_unpaid": "「{card}」第{position}骰未能支付用骰费用，略过此骰。",
    "round_skipped": "{reason}",
    "reserved_intercept": "{target} 以「{card}」第{position}骰迎击。",
    "clash_split": "双方改为单方面攻击，按拼点点数依次命中。",
    "unopposed_clash_win": "空白轮：对位骰消失，{actor} 拼点胜利。",
    "clash_win_suppressed": "{actor} 受远程压制，跳过拼赢分支。",
    "clash_scored": "拼点 {sides}",
    "solo_attack": "单方面攻击：{actor} → {target}",
    "skill_used": "{actor} 使用「{card}」（牌面 {cost} 费）",
    "skill_unpaid": "{actor} 跳过「{card}」，{reason}。",
    "card_pulled": "常规交锋 {number} 的「{card}」被牵制。",
    "attack_declared": "{series} {number}：{player} 声明「{card}」→ {target}。",
    "intercepted": "{player} 用「{card}」迎击{series} {number}。",
    "passed_intercept": "{player} 放行即时交锋 {number}。",
    "special_placement": "{player} 特殊置卡至常规交锋 {number}。",
    "ability_used": "{actor} 使用「{ability}」。",
    "card_played": "{player} 打出「{card}」，依卡面结算。",
    "hidden_card_replaced": "{player} 调换了一张扣置技能，原牌{destination}。",
    "card_replaced": "{actor} 换入「{card}」，「{replaced}」{destination}。",
    "critical": "{actor} 触发暴击。",
    "revealed_and_locked": "「{card}」翻正，本置卡阶段锁定位置。",
    "turn_started": "第 {turn} 回合",
    "turn_ended": "第 {turn} 回合结束。",
    "speed_rolled": "{player} 速度：{members}；阵营速度 {speed:g}。",
    "initiative": "{player} 先手。",
    "speed_tied": "速度相同，双方重掷。",
    "empty_board": "双方空过。",
    "cards_revealed": "双方开牌。",
    "slot_revealed": "交锋 {number}　{sides}",
    "status_batch": "{effect}触发，目标为{targets}。",
    "hand_card_taken": "{receiver} 从对方手中抽取了一张技能。",
    "discount_used": "「{card}」本次费用减免 {discount}，实付 {paid} 费。",
    "random_check": "{source} 进行 {low}～{high} 判定，掷出 {roll}。",
    "direct_damage": "{source} 对 {target} 造成 {amount} 点伤害（{grade}，剩余生命 {hp}/{maximum}）。",
    "healed": "{target} 恢复 {amount} 点生命（{hp}/{maximum}）。",
    "lightcore_damage": "{source} 对 {target} 造成 {amount} 点光点伤害（完整度 {hp}/{maximum}）。",
    "lightcore_collapse": "{target} 的光点形态群崩塌。",
    "lightcore_restored": "{target} 的光点生命上限降至 {maximum}，完整度恢复为 {hp}/{maximum}。",
    "real_damage": "{target} 承受 {amount} 点真实伤害（来源：{source}，剩余生命 {hp}/{maximum}）。",
    "hp_lost": "{target} 失去 {lost} 点生命，剩余 {hp}/{maximum}。",
    "shield_changed": "{target} 的{shield}变为 {total}。",
    "status_activated": "{source}{initiator} 触发{effect}（{target}，{count} 层）。",
    "ability_changed": "{target} 的{name}变为 {total} 次。",
    "ability_spent": "{target} 使用 {amount} 次{name}，剩余 {total} 次。",
    "status_blocked": "{target} 未能获得{name}。",
    "status_changed": "{target} 的{name}变为 {total} 层。",
    "status_cleared": "{target} 清空剩余 {amount} 层{name}。",
    "status_spent": "{target} 消耗 {amount} 层{name}{shortfall}，剩余 {total} 层。",
    "card_destroyed": "「{card}」被摧毁。",
    "die_destroyed": "一颗骰子被摧毁。",
}


def format_fact(kind, fields):
    values = dict(fields)
    if kind == "hit":
        if values["mode"] == "full":
            if values["index"] <= 1:
                return ""
            return "{source}「{card}」追加命中 {target}。".format_map(values)
        values["part"] = {"effects_only": "效果", "damage_only": "伤害"}[values["mode"]]
        return "{source}「{card}」命中 {target}，仅结算{part}部分。".format_map(values)
    if "source" in values and values["source"] is None:
        values["source"] = "效果"
    if "series" in values:
        values["series"] = {"regular": "常规交锋", "instant": "即时交锋", "pre_reveal": "开牌前交锋"}[values["series"]]
    if kind == "attack_declared" and values["target"] is None:
        values["target"] = f"常规交锋 {values['duel_index'] + 1}"
    if "dissolved" in values:
        values["destination"] = "消失" if values["dissolved"] else "回手"
    if kind == "round_skipped":
        values["reason"] = {"printed": "SKIP：跳过本轮。", "passive": "本轮跳过拼点。",
                            "effect": "跳过本轮：双方均不判胜负。"}[values["reason"]]
    elif kind == "clash_scored":
        results = {"win": "胜", "lose": "负", "draw": "平"}
        values["sides"] = " · ".join(
            f"{name} {TYPE_NAMES[die]} 最终 {final} → 拼点 {score}（{results[result]}{'，跳过胜利分支' if skipped else ''}）"
            for name, die, final, score, result, skipped in values["sides"])
    elif kind == "speed_rolled":
        values["members"] = "、".join(f"{name} {speed:g}" for name, speed in values["members"])
    elif kind == "slot_revealed":
        values["sides"] = "　对　".join(name + "：" + ("、".join(cards) or "空") for name, cards in values["sides"])
    elif kind == "status_batch":
        values["targets"] = "、".join(values["targets"])
    elif kind == "direct_damage":
        values["grade"] = GRADE_NAMES[values["grade"]]
    elif kind == "healed" and not values["alive"]:
        return "{target} 实际恢复 {amount} 点生命，回复生命触发即死，阵亡。".format_map(values)
    elif kind == "shield_changed":
        names = {"normal": "普通护盾", "shield": "普通护盾", "reinforced": "强化护盾", "concept": "概念护盾"}
        values["shield"] = names.get(values["shield"], values["shield"])
    elif kind == "status_activated":
        origin = values["origin"]
        if origin == "die":
            values["initiator"] = "「{card}」第{position}骰".format_map(values)
        elif origin == "card":
            values["initiator"] = "「{card}」".format_map(values)
        else:
            values["initiator"] = f"的{values['status']}" if values["status"] else ""
    elif kind == "status_spent":
        values["shortfall"] = "（需 {cost} 层，未付足）".format_map(values) if values["amount"] < values["cost"] else ""
    message = MESSAGES[kind].format_map(values)
    if values.get("alive") is False:
        message += "\n{target} 阵亡。".format_map(values)
    return message
