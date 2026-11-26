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
        picked = _placement(moves, hand, shared, personal, slots)
        if picked is not None:
            return picked
        rear_moves = [
            m for m in moves
            if m["kind"] == "place_rear" and affordable(m) and not hand[m["card_id"]].get("pre_reveal")
        ]
        if rear_moves:
            return max(rear_moves, key=lambda m: card_value(hand[m["card_id"]]))
        return next(move for move in moves if move["kind"] == "end")

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


@avoid_restricted_plays
def choose_inturn_move(frame, moves):
    """Evaluate fair, fog-of-war mid-turn special moves (`place`, `replace`, `ability`) for AI Bot."""
    if not moves or frame.get("is_over"):
        return None
    side = frame.get("viewer_side")
    if side not in (1, 2):
        return None
    player = next((p for p in frame["players"] if p["side"] == side), None)
    if not player or not isinstance(player.get("hand"), list):
        return None

    hand = {card.get("action_key") or card["id"]: card for card in player["hand"]}
    shared = max(0, player["cost"]["available"])
    personal = {c["id"]: max(0, c["cost"]["available"]) for c in player["characters"]}

    # Reserve cost for already-revealed unused cards sitting in upcoming regular duels
    combat = frame.get("combat")
    active_duel_num = combat["duel_number"] if combat and combat.get("kind") == "regular" else 0
    reserved_by_actor = Counter()
    for d in frame.get("duels") or []:
        if d["number"] <= active_duel_num:
            continue
        se = next((s for s in d["sides"] if s["side"] == side), None)
        for card in (se or {}).get("cards") or []:
            if not card.get("used") and not card.get("destroyed") and not card.get("skipped") and card.get("state") != "negated":
                cid = card.get("character_id")
                if cid:
                    reserved_by_actor[cid] += max(0, int(card.get("cost") or 0))

    free_shared = shared
    free_personal = dict(personal)
    for actor, rcost in reserved_by_actor.items():
        used_p = min(free_personal.get(actor, 0), rcost)
        free_personal[actor] = free_personal.get(actor, 0) - used_p
        free_shared = max(0, free_shared - (rcost - used_p))

    def can_afford_surplus(card):
        cost = max(0, int(card.get("cost") or 0))
        return cost <= free_shared + free_personal.get(card.get("character_id"), 0)

    # 1. Untargeted character active abilities at safe combat/before_duel windows
    timing = frame.get("timing") or ""
    if timing in ("交锋开始前", "骰子使用后") or frame.get("mode") == "reveal":
        self_abilities = [
            m for m in moves
            if m["kind"] == "special_ability"
            and not m.get("target_card_id")
            and not m.get("effect_target")
        ]
        if self_abilities:
            return self_abilities[0]

    if not combat or combat.get("kind") != "regular":
        return None

    opp_side = 3 - side
    my_cs = next((s for s in combat.get("sides", ()) if s["side"] == side), None)
    opp_cs = next((s for s in combat.get("sides", ()) if s["side"] == opp_side), None)
    duel_entry = next((d for d in (frame.get("duels") or ()) if d["number"] == combat["duel_number"]), None)
    my_duel_cards = []
    opp_duel_cards = []
    if duel_entry:
        ms = next((s for s in duel_entry["sides"] if s["side"] == side), None)
        os_ = next((s for s in duel_entry["sides"] if s["side"] == opp_side), None)
        my_duel_cards = [c for c in (ms or {}).get("cards", ()) if not c.get("used") and not c.get("destroyed") and not c.get("skipped")]
        opp_duel_cards = [c for c in (os_ or {}).get("cards", ()) if not c.get("used") and not c.get("destroyed") and not c.get("skipped")]

    # 2. Mid-duel Cut-In Placement: Opponent still has an active card/dice in this duel, while our slot is empty!
    if not my_duel_cards and opp_duel_cards:
        place_moves = [
            m for m in moves
            if m["kind"] == "special_place"
            and m.get("card_id") in hand
            and can_afford_surplus(hand[m["card_id"]])
        ]
        if place_moves:
            # Verify first empty regular duel is indeed the active duel
            first_empty = next(
                (d["number"] for d in (frame.get("duels") or ())
                 if not next((s for s in d["sides"] if s["side"] == side), {}).get("cards")
                 and not next((s for s in d["sides"] if s["side"] == side), {}).get("resolved_cards")),
                None,
            )
            if first_empty == combat["duel_number"]:
                return max(place_moves, key=lambda m: card_value(hand[m["card_id"]]))

    # 3. Tactical Mid-Duel Card Replacement (`scores_ready` losing badly to offensive die, or `after_dice_use` against remaining enemy dice)
    if timing == "拼点点数已确定，尚未判胜负" and my_cs and opp_cs:
        my_die = my_cs.get("die")
        opp_die = opp_cs.get("die")
        if (my_die and opp_die and opp_die.get("type") in ("slash", "pierce", "blunt")
                and my_die.get("clash_score") is not None and opp_die.get("clash_score") is not None
                and opp_die["clash_score"] - my_die["clash_score"] >= 3):
            rep_moves = [
                m for m in moves
                if m["kind"] == "special_replace"
                and m.get("card_id") in hand
                and can_afford_surplus(hand[m["card_id"]])
                and (m.get("effect_target") or {}).get("kind") == "regular"
                and (m.get("effect_target") or {}).get("number") == combat["duel_number"]
            ]
            if rep_moves:
                cur_card = my_duel_cards[0] if my_duel_cards else None
                cur_val = card_value(cur_card) if cur_card and "dice" in cur_card else 0
                best_rep = max(rep_moves, key=lambda m: card_value(hand[m["card_id"]]))
                if card_value(hand[best_rep["card_id"]]) > cur_val + 2:
                    return best_rep

    return None
