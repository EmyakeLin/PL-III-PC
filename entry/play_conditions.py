"""Read the observations declared for a hand play, and apply active use conditions."""
from entry.legacy_operations import skill_use_rules
from entry.predicates import Rank, Reference, compile_value, compile_when


def observations(rule, owner, card):
    values = {}
    for key, spec in rule.get("capture", {}).items():
        expression = compile_value(spec)
        if not isinstance(expression, (Reference, Rank)):
            raise ValueError(f"出牌记录需要只读表达式 {spec!r}")
        values[key] = expression.read(owner, {"card": card})
    return values


def record_hand_play(card):
    owner = card.character
    card.play_observations = {
        (name, index): observations(rule, owner, card)
        for name, status in getattr(owner, "status_rules", {}).items()
        for index, rule in enumerate(skill_use_rules(status))
    }


def denies_skill_use(owner, card):
    in_hand = card in owner.player.cardspace.hand.content
    for name, stacks in owner.statuses.items():
        if stacks <= 0:
            continue
        for index, rule in enumerate(skill_use_rules(owner.status_rules.get(name, {}))):
            observed = (observations(rule, owner, card) if in_hand
                        else card.play_observations.get((name, index), {}))
            event = {"card": card, "stacks": stacks, "observed": observed}
            if all(condition.evaluate(owner, event) for condition in compile_when(rule["deny_when"], None, None)):
                return True
    return False
