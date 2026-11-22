"""Comparisons shared by numeric or flagged conditions on printed components."""

from operator import eq, ge, gt, le, lt, ne


COMPARISONS = {"eq": eq, "ne": ne, "lt": lt, "le": le, "gt": gt, "ge": ge}


def matches_value(actual, condition):
    if "op" not in condition:
        return bool(actual)
    try:
        compare = COMPARISONS[condition["op"]]
        expected = condition["value"]
    except KeyError as error:
        raise ValueError(f"无效的数值比较 {condition!r}") from error
    return compare(actual, expected)


def skill_state_allows(values, gate):
    if not gate:
        return True
    if isinstance(gate, str):
        return bool(values.get(gate))
    return matches_value(values.get(gate["key"], 0), gate)
