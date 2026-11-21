"""Compact model input derived exclusively from an already seat-filtered observation."""


def fields(record, *names):
    return {key: record[key] for key in names if record.get(key) is not None}


def actor_view(actor):
    data = fields(actor, "id", "name", "hp", "max_hp", "lightcore_hp", "max_lightcore_hp",
                  "speed", "cost", "duels")
    data["duels"] = fields(data["duels"], "max", "used")
    for key in ("shields", "statuses", "ability_effects", "status_overflow"):
        values = {name: n for name, n in actor.get(key, {}).items() if n}
        if values:
            data[key] = values
    if actor.get("reserved_dice"):
        data["reserved_dice"] = actor["reserved_dice"]
    if actor["bleed_burst"]:
        data["bleed_burst"] = actor["bleed_burst"]
    return data


def card_view(card):
    if card.get("hidden"):
        return {"hidden": True}
    return fields(card, "id", "name", "cost", "state", "play_mode", "action_key", "instance_id",
                  "borrowed", "use_restricted")


def player_view(player):
    data = fields(player, "side", "speed", "cost", "draw_count", "hand_count")
    data["characters"] = [actor_view(c) for c in player["characters"]]
    if player["placement_ended"]:
        data["placement_ended"] = True
    for zone in ("hand", "delayed_discard", "out_of_combat"):
        if player.get(zone):
            data[zone] = [card_view(c) for c in player[zone]]
        elif zone != "hand" and player.get(zone + "_count"):
            data[zone + "_count"] = player[zone + "_count"]
    return data


def duel_view(slot):
    data = fields(slot, "number", "ready", "interceptable", "attacking_side", "target",
                  "pulled_card_id", "resolved_target_id")
    data["sides"] = [{"side": p["side"], "cards": [card_view(c) for c in p["cards"]]}
                     for p in slot["sides"] if p["cards"]]
    return data


def combat_view(combat):
    data = fields(combat, "kind", "duel_number", "round_id")
    data["sides"] = []
    for member in combat["sides"]:
        fighter = fields(member, "side", "card_id", "character_id", "target_id", "die_number", "play_mode")
        if member["range_deficit"]:
            fighter["range_deficit"] = member["range_deficit"]
        die = member["die"]
        if die:
            fighter["die"] = fields(die, "type", "level", "roll_max", "base_value", "rolled_value",
                                    "final_score", "clash_score", "result")
            for key in ("critical", "destroyed", "win_branch_skipped"):
                if die[key]:
                    fighter["die"][key] = True
        data["sides"].append(fighter)
    return data


def decision_view(room):
    """Keep actionable data and visible score layers. Printed card text lives in rules('catalog')."""
    source = room["frame"]
    frame = fields(source, "turn", "phase", "mode", "first_side", "placing_side", "winner_side")
    if source.get("timing"):
        frame["timing"] = source["timing"]
    frame["players"] = [player_view(p) for p in source["players"]]
    if source["duels"]:
        frame["duels"] = [duel_view(s) for s in source["duels"]]
        frame["cards_revealed"] = source["cards_revealed"]
    pre = source["pre_reveal"]
    if pre["duels"] or source["mode"] == "pre_reveal":
        frame["pre_reveal"] = fields(pre, "phase", "attacking_side", "eligible_sides")
        frame["pre_reveal"]["duels"] = [duel_view(s) for s in pre["duels"]]
        if source["response_times"]:
            frame["response_times"] = [fields(t, "number", "declared_at_ms", "answered_at_ms")
                                       for t in source["response_times"]]
    if source["special_duels"]:
        frame["special_duels"] = [duel_view(s) for s in source["special_duels"]]
    if source.get("combat"):
        frame["combat"] = combat_view(source["combat"])
    result = {key: room[key] for key in ("side", "revision", "cursor", "started", "finished", "options", "events")}
    result["frame"] = frame
    if not room["started"]:
        result["ready_sides"] = room["ready_sides"]
    if room["declarations"]:
        result["declarations"] = [{k: v for k, v in p.items() if v not in ({}, False)}
                                  for p in room["declarations"]]
    result["event"] = fields(room["event"], "kind", "nodes", "action_kind", "actor_side", "scores")
    return result
