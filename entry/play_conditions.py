"""Read the observations declared for a hand play, and apply active use conditions."""
from entry.predicates import Count, Rank, Reference, compile_value, compile_when


def observations(rule, owner, card):
    values = {}
    for key, spec in rule.get("capture", {}).items():
        expression = compile_value(spec)
        if not isinstance(expression, (Reference, Rank, Count)):
            raise ValueError(f"出牌记录需要只读表达式 {spec!r}")
        values[key] = expression.read(owner, {"card": card})
    return values


def record_card_play(card, *, from_hand=True):
    if card.temporary:
        return
    owner = card.character
    history = getattr(getattr(owner, "game", None), "turn_history", None)
    if history is not None:
        history.played_sides.add(card.player.side)
    if not from_hand:
        return
    if history is not None:
        history.hand_plays[owner] += 1
    card.play_observations = {
        (name, index): observations(rule, owner, card)
        for name, status in getattr(owner, "status_rules", {}).items()
        for index, rule in enumerate(status.get("skill_use", ()))
    }


def denies_skill_use(owner, card):
    for name, stacks in owner.statuses.items():
        if stacks <= 0:
            continue
        for index, rule in enumerate(owner.status_rules.get(name, {}).get("skill_use", ())):
            zones = getattr(owner.player, "cardspace", None)
            observed = (observations(rule, owner, card) if zones and card in zones.hand.content
                        else card.play_observations.get((name, index), {}))
            event = {"card": card, "stacks": stacks, "observed": observed}
            if all(condition.evaluate(owner, event) for condition in compile_when(rule["deny_when"], None, None)):
                exception = rule.get("except_when")
                if exception and all(condition.evaluate(owner, event) for condition in compile_when(exception, None, None)):
                    continue
                return True
    return False
