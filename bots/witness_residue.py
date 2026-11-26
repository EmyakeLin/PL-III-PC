"""Light Creature Union challenge policy. Reads only the acting seat's public frame and hand."""
from itertools import permutations

from battle_mcp.bot import avoid_restricted_plays


# Estimated combat value of the native dice and the printing left behind.
# Keeping these separate lets a weak attack set up a valuable later unfold.
VALUE = {
    "intake": (1, 1), "gather": (1, 2), "shed": (2, 0.5), "latent": (1, 1),
    "return": (2, 2), "cross": (4, 4), "restore": (2, 2), "probe": (3, 2),
    "sprout": (2, 2), "sever": (5, 4), "lean": (6, 4), "parallel": (4, 2),
    "core": (6, 6), "span": (4, 4), "whole": (4, 3),
}
UNFOLD = {"return": (2, 1), "parallel": (3, 1), "whole": (4, 2)}
DEFENSE = {"gather", "sprout", "latent", "shed"}
PRINTED_NAMES = {
    "纳流": "intake", "收束": "gather", "蜕形": "shed", "潜相": "latent",
    "折返": "return", "透界": "cross", "归拢": "restore", "探隙": "probe",
    "横生": "sprout", "断节": "sever", "倾身": "lean", "并行": "parallel",
    "贯核": "core", "横亘": "span", "全形": "whole",
}


def _skill(card):
    return (card.get("id") or "").removeprefix("residue_")


def _board_cards(frame, side):
    for slot in frame["duels"]:
        lane = next(s for s in slot["sides"] if s["side"] == side)
        yield from (c for c in lane["cards"] if not any(c.get(k) for k in ("used", "destroyed", "skipped")))


def _score(cards, energy, imprint, missing, enemies):
    value = 0
    for index, card in enumerate(cards):
        key = _skill(card)
        base = VALUE.get(key, (1, 1))[0]
        if key == "intake":
            energy += 3
            base += 2 if energy <= 9 else 0
        elif key == "restore" and missing >= 3 and energy >= 3:
            energy -= 3
            base += min(5, missing)
            missing = max(0, missing - 5)
        elif key == "gather":
            base += min(4, missing)
        elif key == "lean" and energy >= 4:
            energy -= 4
            base += 4
        elif key == "span":
            base += 2 * (enemies - 1)
        elif key in UNFOLD and imprint:
            price, copies = UNFOLD[key]
            if energy >= price:
                energy -= price
                base += copies * VALUE.get(imprint, (0, 1))[1]
                if key == "parallel" and imprint in DEFENSE:
                    base += 3
        value += base / (1 + 0.04 * index)
        if key != "latent" or not imprint:
            imprint = key
    return value


@avoid_restricted_plays
def choose_move(frame, moves):
    side = frame["viewer_side"]
    own = next(p for p in frame["players"] if p["side"] == side)
    enemy = next(p for p in frame["players"] if p["side"] != side)
    actor = own["characters"][0]
    missing = actor["max_hp"] - actor["hp"]
    heal_safe = actor["hp"] < actor["max_lightcore_hp"]
    hand = {c.get("action_key", c["id"]): c for c in own["hand"]}
    # The public label includes the original skill followed by its die face.
    imprint = PRINTED_NAMES.get(str(actor.get("passive_values", {}).get("余形", "")).split(" · ", 1)[0])
    placements = {m["card_id"]: m for m in moves if m["kind"] == "place"}
    if placements:
        placed = list(_board_cards(frame, side))
        budget = own["cost"]["available"] + actor["cost"]["available"] - sum(c["cost"] for c in placed)
        slots = actor["duels"]["max"] - actor["duels"]["used"]
        energy = actor["statuses"].get("能源", 0)
        enemies = sum(c["alive"] for c in enemy["characters"])
        best, value = None, float("-inf")
        for count in range(1, min(slots, len(placements)) + 1):
            for order in permutations(placements, count):
                extra = [hand[key] for key in order]
                if sum(c["cost"] for c in extra) > budget:
                    continue
                candidate = _score(placed + extra, energy, imprint, missing if heal_safe else 0, enemies)
                if candidate > value:
                    best, value = placements[order[0]], candidate
        return best or next(m for m in moves if m["kind"] == "end")
    choices = [m for m in moves if m["kind"] == "special_choose_option"]
    if choices:
        selected = choices[0]
        if selected.get("option_id") == "restore" and (not heal_safe or missing < 3):
            return next((m for m in moves if m["kind"] == "special_decline_option"), selected)
        return selected
    attacks = [m for m in moves if m["kind"] == "attack"]
    if attacks:
        return next((m for m in attacks if m.get("duel_number") == 1), attacks[0])
    intercepts = [m for m in moves if m["kind"] in ("intercept", "special_intercept")]
    if intercepts:
        return max(intercepts, key=lambda m: VALUE.get(_skill(hand.get(m["card_id"], {})), (0,))[0])
    return next((m for m in moves if m["kind"] in ("special_place", "end_attack", "let_through", "end")), moves[0])
