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
DEFENSE = {"gather", "sprout", "latent", "shed"}
PRINTED_NAMES = {
    "纳流": "intake", "收束": "gather", "蜕形": "shed", "潜相": "latent",
    "折返": "return", "透界": "cross", "归拢": "restore", "探隙": "probe",
    "横生": "sprout", "断节": "sever", "倾身": "lean", "并行": "parallel",
    "贯核": "core", "横亘": "span", "全形": "whole",
}


def _skill(card):
    return (card.get("id") or "").removeprefix("residue_")


def _board_cards(slots, side):
    for slot in slots:
        lane = next(s for s in slot["sides"] if s["side"] == side)
        opposed = bool(next(s for s in slot["sides"] if s["side"] != side)["cards"])
        for card in lane["cards"]:
            if not any(card.get(k) for k in ("used", "destroyed", "skipped")):
                yield card, opposed


def _sequence(cards, energy, imprint, defensive, missing, enemies, opposed, *, at_prompt=False):
    """Compare spending now with keeping that energy for a later card."""
    if not cards:
        return 0, False
    card, *later = cards
    key = _skill(card)
    clash = opposed[0] if opposed else True
    base = VALUE.get(key, (1, 1))[0]
    price, gain = 0, 0
    if unfold := card.get("unfold"):
        if imprint:
            price = unfold["cost"]
            face = VALUE.get(imprint, (0, 1))[1]
            gain = unfold["copies"] * (face + (2 if defensive else 7))
            if defensive and not clash:
                gain = 3 if key == "parallel" else 0
    if key == "intake" and not at_prompt:
        energy += 3
    elif key == "lean":
        price, gain = 4, 5
    elif key == "span":
        base += 2 * (enemies - 1)
        price, gain = 3, 3 if clash else 0
    elif key == "restore" and missing >= 3:
        price, gain = 3, min(5, missing)
    elif key == "gather":
        base += min(4, missing)
    # Unopposed passive dice never roll. A slash followed by an unused block
    # leaves the slash, while a passive-only card preserves the previous die.
    if key != "latent" or not imprint:
        if clash or key not in {"gather", "shed", "latent"}:
            imprint, defensive = key, key in DEFENSE and clash

    def future(balance, lost):
        return 0.96 * _sequence(later, balance, imprint, defensive, lost, enemies, opposed[1:])[0]

    skip = future(energy, missing)
    if price and gain and energy >= price:
        pay = gain + future(energy - price, max(0, missing - 5) if key == "restore" else missing)
        if pay > skip:
            return base + pay, True
    return base + skip, False


@avoid_restricted_plays
def choose_move(frame, moves):
    side = frame["viewer_side"]
    own = next(p for p in frame["players"] if p["side"] == side)
    enemy = next(p for p in frame["players"] if p["side"] != side)
    actor = own["characters"][0]
    missing = actor["max_hp"] - actor["hp"]
    heal_safe = actor["hp"] < actor["max_lightcore_hp"]
    hand = {c.get("action_key", c["id"]): c for c in own["hand"]}
    stored = actor.get("stored_dice", {}).get("余形", {})
    imprint = PRINTED_NAMES.get((stored.get("label") or "").split(" · ", 1)[0])
    defensive = (stored.get("die") or {}).get("type") in {"block", "evade"}
    energy = actor["statuses"].get("能源", 0)
    enemies = sum(c["alive"] for c in enemy["characters"])
    slots_opposed = [bool(next(s for s in slot["sides"] if s["side"] != side)["cards"]) for slot in frame["duels"]]
    placements = {m["card_id"]: m for m in moves if m["kind"] == "place"}
    if placements:
        placed = [card for card, _ in _board_cards(frame["duels"], side)]
        budget = own["cost"]["available"] + actor["cost"]["available"] - sum(c["cost"] for c in placed)
        slots = actor["duels"]["max"] - actor["duels"]["used"]
        best, value = None, float("-inf")
        for count in range(1, min(slots, len(placements)) + 1):
            for order in permutations(placements, count):
                extra = [hand[key] for key in order]
                if sum(c["cost"] for c in extra) > budget:
                    continue
                opposed = slots_opposed if enemy.get("placement_ended") else []
                candidate, _ = _sequence(placed + extra, energy, imprint, defensive,
                                         missing if heal_safe else 0, enemies, opposed)
                if candidate > value:
                    best, value = placements[order[0]], candidate
        return best or next(m for m in moves if m["kind"] == "end")
    choices = [m for m in moves if m["kind"] == "special_choose_option"]
    if choices:
        selected = choices[0]
        decline = next((m for m in moves if m["kind"] == "special_decline_option"), selected)
        option = selected.get("option_id")
        if option == "restore" and (not heal_safe or missing < 3):
            return decline
        combat = frame.get("combat") or {}
        if combat.get("kind") == "regular" and option in {"unfold", "lean", "span", "restore"}:
            index = combat["duel_number"] - 1
            slots = frame["duels"][index:]
            remaining = list(_board_cards(slots, side))
            active = next(s["card_id"] for s in combat["sides"] if s["side"] == side)
            if remaining and remaining[0][0]["id"] == active:
                cards, opposed = zip(*remaining)
                _, spend = _sequence(cards, energy, imprint, defensive, missing if heal_safe else 0,
                                     enemies, opposed, at_prompt=True)
                if not spend:
                    return decline
        return selected
    attacks = [m for m in moves if m["kind"] == "attack"]
    if attacks:
        return next((m for m in attacks if m.get("duel_number") == 1), attacks[0])
    intercepts = [m for m in moves if m["kind"] in ("intercept", "special_intercept")]
    if intercepts:
        return max(intercepts, key=lambda m: VALUE.get(_skill(hand.get(m["card_id"], {})), (0,))[0])
    return next((m for m in moves if m["kind"] in ("special_place", "end_attack", "let_through", "end")), moves[0])
