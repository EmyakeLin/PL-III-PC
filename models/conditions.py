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

def validate_skill_gate(gate):
    if isinstance(gate, str) and gate:
        return
    if (isinstance(gate, dict) and isinstance(gate.get("key"), str) and gate["key"]
            and gate.get("op") in COMPARISONS and "value" in gate):
        return
    raise ValueError("骰位启用条件需要状态名，或包含 key、op、value 的比较式")
