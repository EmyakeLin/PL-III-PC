"""澜清单角色席位策略。运行 python -m bots.lan_qing 开始本机对战。"""

import argparse
from functools import cache
from itertools import permutations
from threading import Thread
from uuid import uuid4

from loader import load_characters_from_packs


DANCE = "电叉·回环舞·活化"
SPIKE = "电叉·极锐刺·活化"
LEAF = "深秋·风卷残叶·活化"
LIGHT = "残雪·幽蓝流光·活化"
FAMILIES = {DANCE, SPIKE, LEAF}
STARTERS = {"lan_open": DANCE, "lan_turn": SPIKE, "lan_close": LEAF, "lan_end": LIGHT}
PAIRS = {"lan_dance_2": DANCE, "lan_dance_3": DANCE, "lan_spike_2": SPIKE,
         "lan_spike_3": SPIKE, "lan_leaf_3": LEAF, "lan_leaf_4": LEAF}

# Tactical weights for the normal and active faces of each skill.
FACE_VALUE = {
    "lan_open": (1.4,), "lan_turn": (3.5,), "lan_close": (2.7,), "lan_end": (3.7,),
    "lan_light": (5.6, 8.8), "lan_dance_2": (3.1, 4.1), "lan_dance_3": (3.7, 5.8),
    "lan_spike_2": (2.8, 4.4), "lan_spike_3": (2.5, 6.7),
    "lan_leaf_3": (3.2, 7.5), "lan_leaf_4": (5.4, 7.8),
}


@cache
def _printed_dice_traits():
    # The compact seat frame omits dice. Read only the public printed faces.
    actor = next(c for c in load_characters_from_packs() if c["id"] == "lan_qing")
    traits = {}
    for skill in actor["skills"]:
        for active, face in ((False, skill), (True, skill.get("forms", {}).get("active", skill))):
            dice = face["dice"]
            attacks = sum(d["type"] in ("slash", "pierce", "blunt") for d in dice)
            traits[skill["id"], active] = attacks, any(not d.get("fixed_scores") for d in dice)
    return traits


def _cards(slot, side):
    return next(s["cards"] for s in slot["sides"] if s["side"] == side)


def _use_face(key, active):
    """Advance the projected shared charges and return this use's chosen face."""
    if key == "lan_light":
        primed = LIGHT in active
        active.discard(LIGHT)
        if not primed and len(active) >= 2:
            active.clear()
            return True
        active.update(FAMILIES)
        return primed
    if key in PAIRS:
        family = PAIRS[key]
        enhanced = family in active
        active.discard(family)
        return enhanced
    if key in STARTERS:
        active.add(STARTERS[key])
    return False


class _Turn:
    """Score alternative declarations from the same private seat snapshot."""

    def __init__(self, frame):
        self.side = frame["viewer_side"]
        own = next(p for p in frame["players"] if p["side"] == self.side)
        opponent = next(p for p in frame["players"] if p["side"] != self.side)
        self.actor, = own["characters"]
        self.enemies = {c["id"]: c for c in opponent["characters"] if c["alive"]}
        self.hand = {c.get("action_key", c["id"]): c for c in own["hand"]}
        self.budget = own["cost"]["available"] + self.actor["cost"]["available"]
        self.free_slots = self.actor["duels"]["max"] - self.actor["duels"]["used"]
        self.regular = frame["duels"]
        self.early = frame["pre_reveal"]["duels"]
        self.opponent_ended = opponent["placement_ended"]

    def _sequence(self, extra=(), response=None):
        """Build the actual payment order, including cards pulled from regular slots."""
        other = 3 - self.side
        regular = [list(_cards(slot, self.side)) for slot in self.regular]
        for card in extra:
            empty = next((i for i, cards in enumerate(regular) if not cards), len(regular))
            if empty == len(regular):
                regular.append([])
            regular[empty].append(card)
        for slot in self.early:
            own = list(_cards(slot, self.side))
            opposing = _cards(slot, other)
            if response and response.get("response_number") == slot["number"] and response["kind"] == "intercept":
                own.append(self.hand[response["card_id"]])
            target = slot["target"]
            if not own and slot["attacking_side"] == other and target["kind"] == "duel":
                index = target["number"] - 1
                if index < len(regular) and regular[index]:
                    own.append(regular[index].pop(0))
            yield own, opposing, bool(opposing)
        for index, own in enumerate(regular):
            opposing = _cards(self.regular[index], other) if index < len(self.regular) else []
            yield own, opposing, bool(opposing) or not self.opponent_ended

    def score(self, extra=(), response=None):
        status = self.actor["statuses"]
        active = {s for s in FAMILIES | {LIGHT} if status.get(s, 0)}
        hp = self.actor["hp"]
        budget = self.budget
        shock = {key: e["statuses"].get("电击", 0) for key, e in self.enemies.items()}
        stagger = sum(e["statuses"].get("失衡", 0) + 4 * e["statuses"].get("致命失衡", 0)
                      for e in self.enemies.values())
        strength = self.actor["passive_values"].get("涌流灌注", 0)
        played = 0
        value = 0.0
        for own, opposing, contested in self._sequence(extra, response):
            enemy_id = next((c["character_id"] for c in opposing if c.get("character_id") in shock),
                            next(iter(self.enemies)))
            # An unopposed declared attack still threatens us if we let it through.
            if opposing and not own:
                value -= sum(0.4 + 0.35 * c.get("cost", 1) for c in opposing)
            for card in own:
                key = card["id"]
                played += 1
                if card["cost"] > budget or card.get("use_restricted"):
                    # The hand play counts, but a skipped skill has no use effects.
                    value -= 2.6
                    continue
                budget -= card["cost"]
                enhanced = _use_face(key, active)
                attacks, benefits_from_infusion = _printed_dice_traits().get((key, enhanced), (1, True))
                value += FACE_VALUE.get(key, (2.0,))[enhanced]
                if key == "lan_open":
                    hp -= 1
                    if hp <= 0:
                        return -1000.0
                    value -= 1.8 if hp <= 3 else 0.3
                if key == "lan_turn":
                    strength += 2
                if benefits_from_infusion:
                    value += min(4, strength) * 0.35
                value += min(4, shock[enemy_id]) * attacks * 0.31
                if not contested:
                    value += 0.35 * attacks
                    if key == "lan_close" or (key == "lan_dance_3" and not enhanced):
                        value -= 2.2  # Defensive dice need an opponent to win a clash.
                if key == "lan_end":
                    value += min(8, stagger // 8) * 0.45
                heavy_hit = (key in ("lan_light", "lan_leaf_3", "lan_leaf_4")
                             or enhanced and (key == "lan_dance_3" or key == "lan_spike_3" and contested))
                if heavy_hit and self.enemies[enemy_id]["statuses"].get("致命失衡"):
                    value += 1.5
                if key == "lan_light" or (enhanced and key in ("lan_leaf_4", "lan_dance_3")):
                    value += 1.3 * (len(self.enemies) - 1)
                if key == "lan_end" or (key == "lan_light" and not enhanced):
                    for identifier in shock:
                        shock[identifier] += 2
                elif key == "lan_open" and contested:
                    shock[enemy_id] += 1
                elif key == "lan_dance_2":
                    shock[enemy_id] += 3 if enhanced and contested else 1
                elif key == "lan_spike_2" and not enhanced:
                    shock[enemy_id] += 1
                elif key == "lan_spike_3" and enhanced:
                    shock[enemy_id] += 4
                elif key == "lan_dance_3" and enhanced:
                    shock[enemy_id] += 2

        # Activation survives the turn. A charged name is worth more when its card
        # is already in hand. Count the name once across the two cost variants.
        consumed = {c["instance_id"] for c in extra}
        if response and response["kind"] == "intercept":
            consumed.add(self.hand[response["card_id"]]["instance_id"])
        held = {PAIRS.get(c["id"], LIGHT if c["id"] == "lan_light" else None)
                for c in self.hand.values() if c["instance_id"] not in consumed}
        value += sum(0.9 + (0.65 if family in held else 0) for family in active)
        if played >= 3:
            value += 2.2 if hp < self.actor["max_hp"] else 1.35
        return value

    def place(self, moves):
        choices = {m["card_id"]: m for m in moves if m["kind"] == "place"}
        end = next((m for m in moves if m["kind"] == "end"), None)
        best, best_value = end, self.score() if end else float("-inf")
        # Her ordinary allowance is three. Replan after each placement even when
        # another effect grants a larger number of slots.
        for length in range(1, min(3, self.free_slots, len(choices)) + 1):
            for keys in permutations(choices, length):
                cards = [self.hand[k] for k in keys]
                value = self.score(cards)
                if value > best_value:
                    best, best_value = choices[keys[0]], value
        return best


def choose_move(frame, moves):
    """Return an offered move for a solo Lan Qing seat, or None when waiting."""
    if not moves:
        return None
    turn = _Turn(frame)
    if any(m["kind"] == "place" for m in moves):
        return turn.place(moves)
    responses = [m for m in moves if m["kind"] in ("intercept", "let_through")]
    if responses:
        return max(responses, key=lambda m: turn.score(response=m))
    choices = [m for m in moves if m["kind"] == "special_choose_card"]
    if choices:
        # Lan Qing's own forced hand choice is overflow discard. Keep charged
        # finishers and starters with a matching payoff still in hand.
        def keep_value(move):
            card = (move.get("effect_target") or {}).get("card") or turn.hand.get(move.get("target_card_id"), {})
            key = card.get("id")
            family = LIGHT if key == "lan_light" else PAIRS.get(key)
            active = bool(turn.actor["statuses"].get(family, 0))
            score = FACE_VALUE.get(key, (2.0,))[active]
            partners = {c["id"] for c in turn.hand.values()} - {key}
            can_activate = {PAIRS[k] for k in partners if k in PAIRS}
            if "lan_light" in partners:
                can_activate.add(LIGHT)
            if STARTERS.get(key) in can_activate:
                score += 2
            if key == "lan_open" and turn.actor["hp"] == 1:
                score = -1
            return score
        return min(choices, key=keep_value)
    return next((m for m in moves if m["kind"] in ("end_attack", "end")), moves[0])


def play_seat(room, side):
    """Drive the same revision-checked, private seat interface used by players."""
    from battle_mcp.room import RoomConflict

    view = room.observe(side)
    while not view["finished"]:
        try:
            if side not in view["ready_sides"]:
                view = room.ready(side, revision=view["revision"], request_id=uuid4().hex)
            elif move := choose_move(view["frame"], view["options"]):
                view = room.act(side, option_id=move["id"], revision=view["revision"], request_id=uuid4().hex)
            else:
                update = room.wait(side, view["cursor"], 1)
                if not update.get("timeout"):
                    view = update
        except RoomConflict:
            view = room.observe(side)
    return view["winner_side"]


def main():
    from battle_mcp.room import Room
    from battle_mcp.transport import ArenaServer

    parser = argparse.ArgumentParser(description="本机挑战幽兰残雪·澜清")
    parser.add_argument("--opponent", default="plan_b_annolin", help="真人席位的角色 ID，默认安诺琳")
    parser.add_argument("--seed", type=int, help="固定洗牌与掷骰种子")
    parser.add_argument("--port", type=int, default=0, help="房间端口，默认自动分配")
    args = parser.parse_args()
    room = Room((args.opponent, "lan_qing"), seed=args.seed)
    try:
        with ArenaServer(room, port=args.port) as server:
            server_thread = Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                table = "canvas/" if hasattr(room, "canvas_state") else ""
                print(f"玩家 1 私人邀请  http://127.0.0.1:{server.server_port}/{table}#token={server.tokens[1]}", flush=True)
                winner = play_seat(room, 2)
                result = {1: "你获胜了。", 2: "澜清获胜。", None: "平局。"}[winner]
                print(f"{result} 按 Ctrl+C 关闭房间，再次运行命令可重新挑战。", flush=True)
                server_thread.join()
            finally:
                server.shutdown()
                server_thread.join()
    finally:
        room.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
