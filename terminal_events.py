"""Chinese hot-seat presentation of settled battle facts."""

from entry.effects import GRADE_NAMES


MESSAGES = {
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
    if "source" in values and values["source"] is None:
        values["source"] = "效果"
    if kind == "direct_damage":
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
