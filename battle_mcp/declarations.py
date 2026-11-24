"""Player-authored predicates. Only the seat's projected frame is available here."""

EVENTS = ("decision", "placement", "pre_reveal", "roll", "scores_ready", "timing", "action",
          "combat", "reveal", "turn_end", "timer")
ORDINARY = {"place", "pass", "end", "attack", "intercept", "let_through", "end_attack",
            "special_intercept", "special_pass_intercept", "special_choose_card", "special_decline_card",
            "special_choose_slot", "special_choose_option", "special_decline_option",
            "special_choose_character", "special_decline_character"}
KINDS = ORDINARY | {"special_place", "special_replace", "special_attack", "special_custom", "special_ability"}
MOVE_KEYS = {"kind", "card_id", "character_id", "duel_number", "response_number", "target_card_id", "ability_id", "option_id"}
CONDITIONS = {"turn", "duel_kind", "duel_number", "die_number", "own_card_id", "score",
              "timing", "actor_side", "action_kind", "pending_number", "after_ms"}
NUMBERS = {"turn", "duel_number", "die_number", "actor_side", "pending_number", "after_ms",
           "response_number"}


def _fields(data, allowed):
    if not isinstance(data, dict) or data.keys() - allowed:
        raise ValueError("声明含有未知字段或不是对象。")


def validate(data):
    _fields(data, {"event", "mode", "match", "when", "repeat"})
    event, mode = data.get("event"), data.get("mode")
    if event not in EVENTS or mode not in ("reserve", "execute"):
        raise ValueError("请选择声明的触发事件及 reserve/execute 方式。")
    match, when = data.get("match", {}), data.get("when", {})
    _fields(match, MOVE_KEYS)
    _fields(when, CONDITIONS)
    for key, value in [*match.items(), *when.items()]:
        if key in NUMBERS:
            if type(value) is not int or not 1 <= value <= 2**31 - 1:
                raise ValueError(f"{key} 必须是正整数。")
        elif not isinstance(value, str) or not 0 < len(value) <= 128:
            raise ValueError(f"{key} 必须是非空短字符串。")
    for key, allowed in (("score", ("lt", "eq", "gt")), ("duel_kind", ("regular", "pre_reveal", "instant")),
                         ("action_kind", KINDS), ("actor_side", (1, 2))):
        if key in when and when[key] not in allowed:
            raise ValueError(f"{key} 的取值无效。")
    if "kind" in match and match["kind"] not in KINDS:
        raise ValueError("未知动作。")
    if mode == "execute" and "kind" not in match:
        raise ValueError("条件执行必须指定 match.kind。")
    if (event == "timer") != ("after_ms" in when) or (event == "timer" and "pending_number" not in when):
        raise ValueError("timer 必须指定待迎击编号 pending_number 和等待毫秒 after_ms。")
    if type(data.get("repeat", False)) is not bool:
        raise ValueError("repeat 必须是布尔值。")
    return dict(event=event, mode=mode, match=dict(match), when=dict(when), repeat=data.get("repeat", False))


def select_moves(options, match):
    return [move for move in options if all(move.get(k) == v for k, v in match.items())]


def pending(frame, number):
    return any(d["number"] == number and not d["ready"] for d in frame["pre_reveal"]["duels"])


def matches(plan, event, frame, side, required):
    trigger = plan["event"]
    if trigger == "decision":
        if not required:
            return False
    elif trigger != event["kind"]:
        return False
    when = plan["when"]
    if not when:
        return True
    combat = frame.get("combat") or {}
    sides = {s["side"]: s for s in combat.get("sides", [])}
    own = sides.get(side, {})
    facts = {"turn": frame["turn"], "duel_kind": combat.get("kind"),
             "duel_number": combat.get("duel_number"), "die_number": own.get("die_number"),
             "own_card_id": own.get("card_id"), "action_kind": event.get("action_kind"),
             "actor_side": event.get("actor_side")}
    if "score" in when:
        dice = [(sides.get(s, {}).get("die") or {}) for s in (side, 3-side)]
        value = "rolled_value" if event["kind"] == "roll" else "clash_score"
        if any(d.get("rolled_value") is None or d.get(value) is None for d in dice):
            return False
        a, b = (d[value] for d in dice)
        facts["score"] = "lt" if a < b else "gt" if a > b else "eq"
    if "timing" in when and when["timing"] not in [event.get("timing"), *event.get("nodes", [])]:
        return False
    if "pending_number" in when and not pending(frame, when["pending_number"]):
        return False
    return all(facts.get(k) == v for k, v in when.items() if k not in ("timing", "after_ms", "pending_number"))
