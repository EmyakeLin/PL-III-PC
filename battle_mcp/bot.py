"""Deterministic play from a seat's visible frame and legal options."""

from collections import Counter, defaultdict
from functools import wraps


HAND_PLAYS = frozenset({
    "place", "place_rear", "attack", "intercept", "special_place", "special_place_rear",
    "special_replace", "special_attack", "special_intercept", "special_custom",
})


def avoid_restricted_plays(policy):
    """Keep hand plays the seat can currently use. Other choices may target any offered card."""
    @wraps(policy)
    def decide(frame, moves):
        if not moves:
            return None
        if not any(m["kind"] in HAND_PLAYS for m in moves):
            return policy(frame, moves)
        player = next(p for p in frame["players"] if p["side"] == frame["viewer_side"])
        restricted = {card.get("action_key") or card["id"] for card in player["hand"]
                      if card.get("use_restricted")}
        if restricted:
            moves = [m for m in moves if m["kind"] not in HAND_PLAYS or m["card_id"] not in restricted]
        return policy(frame, moves) if moves else None

    return decide


def printed_card_value(cost, range_level, dice):
    """Shared with the lightcore replays. Dice are (type, roll max, base, bonus)."""
    return 3 * (cost + range_level) + sum(
        (roll_max + 1) / 2 + base + bonus + 2 * (kind in ("slash", "pierce", "blunt"))
        for kind, roll_max, base, bonus in dice
    )


def card_value(card):
    dice = ((die["type"], die["roll_max"] or 4, die["base_value"], die["final_bonus"])
            for die in card["dice"])
    return printed_card_value(card["cost"], card["range_level"], dice)


def choose_draw_bottom(draw):
    candidates = draw["candidates"]
    ranked = sorted(candidates, key=card_value, reverse=True)
    keep = {card["action_key"] for card in ranked[:draw["keep"]]}
    return [card["action_key"] for card in candidates if card["action_key"] not in keep]


def _actor_plans(keys, hand, values, budget, slots):
    plans = {(0, 0): (0, ())}
    for key in keys:
        card = hand[key]
        reserve = card["pre_reveal"]
        for (cost, used), (value, keys) in tuple(plans.items()):
            next_cost, next_used = cost + card["cost"], used + (not reserve)
            state = (next_cost, next_used)
            score = value + values[key]
            if next_cost <= budget and next_used <= slots and score > plans.get(state, (0, ()))[0]:
                plans[state] = (score, (*keys, key))
    return plans


def _placement(moves, hand, shared, personal, slots):
    legal = {move["card_id"]: move for move in moves if move["kind"] == "place"}
    values = {key: card_value(hand[key]) for key in legal}
    by_actor = defaultdict(list)
    for key in legal:
        by_actor[hand[key]["character_id"]].append(key)
    # Build each actor's plans independently. Combine them by how much they
    # ask from the shared pool after exhausting that actor's personal fee.
    combined = {0: (0, ())}
    for actor, keys in by_actor.items():
        own_fee = personal[actor]
        plans = _actor_plans(keys, hand, values, shared + own_fee, slots[actor])
        next_combined = {}
        for (cost, _), (value, cards) in plans.items():
            extra = max(0, cost - own_fee)
            for spent, (prev_value, prev_cards) in combined.items():
                total = spent + extra
                if total > shared:
                    continue
                previous = next_combined.get(total, (-1, ()))
                candidate = (prev_value + value, (*prev_cards, *cards))
                if (candidate[0], -len(candidate[1])) > (previous[0], -len(previous[1])):
                    next_combined[total] = candidate
        combined = next_combined
    _, keys = max(combined.values(), key=lambda plan: (plan[0], -len(plan[1])), default=(0, ()))
    regular = (key for key in keys if not hand[key]["pre_reveal"])
    best = max(regular, key=values.get, default=None)
    return legal.get(best)


def _response(moves, hand, affordable, intercept, release):
    pending = [move for move in moves if move["kind"] == release]
    if not pending:
        return None
    first = min(pending, key=lambda move: move["response_number"])
    number = first["response_number"]
    legal = (move for move in moves if move["kind"] == intercept and move["response_number"] == number
             and affordable(move))
    return max(legal, key=lambda move: card_value(hand[move["card_id"]]), default=first)


@avoid_restricted_plays
def choose_move(frame, moves):
    """Answer a required decision. The engine still checks and applies the move."""
    if frame["mode"] == "skill_choice":
        cards = [move for move in moves if move["kind"] == "special_choose_card"]
        if not cards:
            return moves[0]
        return max(cards, key=lambda move: card_value(card) if (card := move["effect_target"].get("card")) else 0)

    side = frame["viewer_side"]
    player = next(player for player in frame["players"] if player["side"] == side)
    hand = {card["action_key"]: card for card in player["hand"]}
    shared = max(0, player["cost"]["available"])
    personal = {c["id"]: max(0, c["cost"]["available"]) for c in player["characters"]}

    def affordable(move):
        card = hand[move["card_id"]]
        return card["cost"] <= shared + personal[card["character_id"]]

    if frame["mode"] == "instant_response":
        return _response(moves, hand, affordable, "special_intercept", "special_pass_intercept")

    pending = (*frame["duels"], *frame["pre_reveal"]["duels"], *frame["special_duels"])
    committed = Counter()
    for slot in pending:
        for member in slot["sides"]:
            if member["side"] == side:
                for card in member["cards"]:
                    if card["state"] != "negated":
                        committed[card["character_id"]] += card["cost"]
    for actor, cost in committed.items():
        shared -= max(0, cost - personal[actor])
        personal[actor] = max(0, personal[actor] - cost)
    if frame["mode"] == "placement":
        slots = {c["id"]: c["duels"]["max"] - c["duels"]["used"] for c in player["characters"]}
        return _placement(moves, hand, shared, personal, slots) or next(move for move in moves if move["kind"] == "end")

    response = _response(moves, hand, affordable, "intercept", "let_through")
    if response is not None:
        return response
    attacks = (move for move in moves if move["kind"] == "attack" and affordable(move))
    end = next((move for move in moves if move["kind"] == "end_attack"), None)
    enemy = next(p for p in frame["players"] if p["side"] != side)
    targets = {c["id"]: (c["hp"], c["lightcore_hp"]) for c in enemy["characters"]}

    def attack_value(move):
        hp, lightcore = targets.get(move.get("character_id"), (0, 0))
        return card_value(hand[move["card_id"]]), "character_id" in move, -hp, -lightcore

    return max(attacks, key=attack_value, default=end)
