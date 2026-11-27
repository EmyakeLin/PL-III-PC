from models.card import CardState
from models.opcode import OpCode


class DuelSpace:
    def __init__(self, game):
        self.game = game
        self.space = []
        self.current_duel_index = 0

    def __str__(self):
        return "\n".join(f"交锋 {i + 1}：{slot}" for i, slot in enumerate(self.space))

    def append_new_duel(self, duel_slot_instance):
        duel_slot_instance.game = self.game
        duel_slot_instance.settled = True
        self.space.append(duel_slot_instance)

    def is_empty_duel(self, target_side, target_duel_index):
        return (target_duel_index >= len(self.space)
                or not self.space[target_duel_index].content.get(target_side))

    def locate_nearest_empty_duel(self, target_side):
        return next((i for i in range(len(self.space)) if self.is_empty_duel(target_side, i)),
                    len(self.space))

    def has_next_duel(self):
        return any(
            any(slot.content.values())
            or any(slot.rear_content.values())
            or any(slot.tail_is_live(card) for card in slot.dice_tails)
            for slot in self.space[self.current_duel_index:]
        )


class DuelSlot:
    def __init__(self, game=None):
        self.game = game
        self.content = {}
        self.rear_content = {}
        self.settled = False
        self.end_requested = False
        self.current_card_index = {}
        self.rear_card_index = {}
        self.rear_capacity = {}
        self.used_skill_faces = {}
        # A continuation plays the original dice. The physical card stays in its own slot.
        self.dice_tails = {}
        self.damage_taken = {}
        self.status_lost = {}

    def add_content(self, side, content):
        self.content.setdefault(side, []).append(content)

    def get_content(self, side):
        return self.content.get(side, [])

    def get_rear_capacity(self, side):
        return self.rear_capacity.get(side, 1)

    def set_rear_capacity(self, side, capacity):
        value = max(0, int(capacity))
        self.rear_capacity[side] = value
        return value

    def add_rear_content(self, side, content):
        self.rear_content.setdefault(side, []).append(content)

    def get_rear_content(self, side):
        return self.rear_content.get(side, [])

    def all_side_cards(self, side):
        return [*self.get_content(side), *self.get_rear_content(side)]

    def all_cards(self):
        sides = list(dict.fromkeys([*self.content.keys(), *self.rear_content.keys()]))
        return [card for side in sides for card in self.all_side_cards(side)]

    def play_mode(self, card):
        if card is not None and card.player is not None and card in self.get_rear_content(card.player.side):
            return "rear"
        return None

    def has_valid_front_anchor(self, side):
        front_cursor = self.current_card_index.get(side, 0)
        used = set(self.game.used_cards) if self.game is not None else None
        for idx, card in enumerate(self.get_content(side)):
            if not card.character.is_alive or card.destroyed or card.state == CardState.NEGATED:
                continue
            if idx >= front_cursor or used is None or card in used or card.use_effects_resolved:
                return True
        return any(card.player.side == side and self.tail_is_live(card) for card in self.dice_tails)

    def has_started_front(self, side):
        if not self.has_valid_front_anchor(side):
            return False
        used = set(self.game.used_cards) if self.game is not None else set()
        for card in self.get_content(side):
            if not card.character.is_alive or card.destroyed or card.state == CardState.NEGATED:
                continue
            if card in used or card.use_effects_resolved:
                return True
        return any(card.player.side == side and self.tail_is_live(card) for card in self.dice_tails)

    def can_accept_rear(self, side):
        return self.has_valid_front_anchor(side) and len(self.get_rear_content(side)) < self.get_rear_capacity(side)

    def sync_rear_validity(self, side, ctx=None):
        if self.has_valid_front_anchor(side):
            return
        from models.opcodes import publish_disabled_skill

        context = ctx or (self.game.context if self.game is not None else None)
        pipeline = getattr(self.game, "pipeline", None) if self.game is not None else None
        for rc in tuple(self.get_rear_content(side)):
            if rc.destroyed or rc.state == CardState.NEGATED:
                continue
            if pipeline is not None and pipeline.in_use(self, rc):
                pipeline.withdraw_skill(self, rc)
            rc.state = CardState.NEGATED
            if context is not None:
                context.record("rear_card_invalidated", side=side, card=rc.name, card_id=rc.id)
                publish_disabled_skill(context, rc, "rear_anchor_lost")

    def get_current_card(self, side):
        cards = self.get_content(side)
        index = self.current_card_index.get(side, 0)
        return cards[index] if index < len(cards) else None

    def get_current_rear_card(self, side):
        cards = self.get_rear_content(side)
        index = self.rear_card_index.get(side, 0)
        return cards[index] if index < len(cards) else None

    def has_next_card(self, side):
        return self.get_current_card(side) is not None

    def playable_cards(self, side):
        """Inspect the remaining live cards without advancing this side's cursor."""
        for card in self.get_content(side)[self.current_card_index.get(side, 0):]:
            if card.character.is_alive and not card.destroyed and card.state != CardState.NEGATED:
                yield card

    def playable_rear_cards(self, side):
        if not self.has_valid_front_anchor(side):
            return
        for card in self.get_rear_content(side)[self.rear_card_index.get(side, 0):]:
            if card.character.is_alive and not card.destroyed and card.state != CardState.NEGATED:
                yield card

    def next_playable_card(self, side):
        while (card := self.get_current_card(side)) is not None:
            if card.character.is_alive and not card.destroyed and card.state != CardState.NEGATED:
                return card
            self.advance_card(side)
        return None

    def next_playable_rear_card(self, side, *, advance=True):
        if not self.has_valid_front_anchor(side):
            return None
        if not advance:
            return next(self.playable_rear_cards(side), None)
        while (card := self.get_current_rear_card(side)) is not None:
            if card.character.is_alive and not card.destroyed and card.state != CardState.NEGATED:
                return card
            self.advance_rear_card(side)
        return None

    def tail_is_live(self, card):
        if card not in self.dice_tails:
            return False
        origin, instances = self.dice_tails[card]
        return (not card.destroyed and card.character.is_alive and card.instantiated_dice is instances
                and card in origin.get_content(card.player.side))

    def next_combat_card(self, side, *, advance=True):
        ordinary = self.next_playable_card(side) if advance else next(self.playable_cards(side), None)
        if ordinary is not None:
            return ordinary
        return next((card for card in self.dice_tails
                     if card.player.side == side and self.tail_is_live(card)), None)

    def get_current_opposing_card(self, attacking_side):
        if self.game:
            side = next(p.side for p in self.game.players if p.side != attacking_side)
        else:
            side = next((side for side in (*self.content, *self.rear_content) if side != attacking_side), None)
        return self.get_current_card(side) or self.get_current_rear_card(side)

    def advance_card(self, side):
        self.current_card_index[side] = self.current_card_index.get(side, 0) + 1

    def advance_rear_card(self, side):
        self.rear_card_index[side] = self.rear_card_index.get(side, 0) + 1

    def finish_card(self, side, card):
        # Death may already have removed the current card and shifted its successor into place.
        if self.get_current_card(side) is card:
            self.advance_card(side)
        self.dice_tails.pop(card, None)
        self.sync_rear_validity(side)

    def finish_rear_card(self, side, card):
        if self.get_current_rear_card(side) is card:
            self.advance_rear_card(side)

    def remove_card(self, card):
        """Detach this exact card; keep the cursor pointing at the next playable card."""
        side = card.player.side
        cards = self.get_content(side)
        if card in cards:
            position = cards.index(card)
            cards.pop(position)
            if position < self.current_card_index.get(side, 0):
                self.current_card_index[side] -= 1
            self.sync_rear_validity(side)
            return True
        rear_cards = self.get_rear_content(side)
        if card in rear_cards:
            position = rear_cards.index(card)
            rear_cards.pop(position)
            if position < self.rear_card_index.get(side, 0):
                self.rear_card_index[side] -= 1
            return True
        return False

    def remove_character(self, character):
        removed = []
        for side, cards in self.content.items():
            index = self.current_card_index.get(side, 0)
            self.current_card_index[side] = sum(not card.belongs_to(character) for card in cards[:index])
            removed.extend(card for card in cards if card.belongs_to(character))
            cards[:] = [card for card in cards if not card.belongs_to(character)]
        for side, rear_cards in self.rear_content.items():
            index = self.rear_card_index.get(side, 0)
            self.rear_card_index[side] = sum(not card.belongs_to(character) for card in rear_cards[:index])
            removed.extend(card for card in rear_cards if card.belongs_to(character))
            rear_cards[:] = [card for card in rear_cards if not card.belongs_to(character)]
        return removed

    def resolve_target_character(self, attacking_side, clash_pair=None, previous_opponent=None):
        attacking_player = next(p for p in self.game.players if p.side == attacking_side)
        enemy = next(p for p in self.game.players if p is not attacking_player)
        if clash_pair and enemy.side in clash_pair.dice_dict:
            defender = clash_pair.dice_dict[enemy.side].card.character
            if defender.is_alive:
                return defender
        for card in (self.get_current_card(enemy.side), self.get_current_rear_card(enemy.side), previous_opponent):
            if card is not None and card.character.is_alive:
                return card.character
        return attacking_player.choose_one_sided_target(enemy)

    def __str__(self):
        def label(card):
            if card.state == CardState.PLACED_FACE_DOWN:
                return "扣置牌"
            return card.name
        sides = list(dict.fromkeys([*self.content.keys(), *self.rear_content.keys()]))
        parts = []
        for side in sides:
            front_str = "、".join(label(card) for card in self.get_content(side))
            rear_cards = self.get_rear_content(side)
            if rear_cards:
                rear_str = "、".join(label(card) for card in rear_cards)
                parts.append(f"{side} 方 {front_str}〔后置：{rear_str}〕")
            else:
                parts.append(f"{side} 方 {front_str}")
        return " / ".join(parts)


class ClashPair:
    def __init__(self, dice_dict, *, lane_dice=None):
        if len(dice_dict) > 2:
            raise ValueError("每次拼点最多两方")
        self.dice_dict = dict(dice_dict)
        self.lane_dice = (
            dict(lane_dice)
            if lane_dice is not None
            else {(side, "front"): die for side, die in self.dice_dict.items()}
        )
        self.lane_results = {}
        self.rerolls = 0
        self.split = False
        self.skipped = False
        self.drawn = False
        self.unopposed_results = {}

    def all_dice(self):
        return tuple(self.lane_dice.values())

    def opposing_threshold(self, side, lane):
        enemy = next((s for s in self.dice_dict if s != side), None)
        if enemy is None:
            return 0, False
        ef = self.lane_dice.get((enemy, "front"))
        er = self.lane_dice.get((enemy, "rear"))
        if lane == "front":
            score = (ef.clash_score if ef is not None else 0) + (er.clash_score if er is not None else 0)
            rev = bool((ef and ef.reverses_clash) or (er and er.reverses_clash))
            return score, rev
        opp = ef if ef is not None else er
        return (opp.clash_score if opp is not None else 0), bool(opp and opp.reverses_clash)

    def clash_roll(self):
        clashing = len(self.dice_dict) == 2
        for die in self.lane_dice.values():
            die.roll(clash=clashing)
        return self.clash_check()

    def clash_check(self):
        if len(self.dice_dict) != 2:
            self.lane_results = {}
            return {}
        a, b = self.dice_dict.keys()
        primary_a = self.lane_dice.get((a, "front")) or self.lane_dice.get((a, "rear")) or self.dice_dict[a]
        primary_b = self.lane_dice.get((b, "front")) or self.lane_dice.get((b, "rear")) or self.dice_dict[b]
        # Both final scores settle before either side derives a clash score.
        for opcode in (OpCode.RESOLVE_FINAL_SCORE, OpCode.RESOLVE_CLASH_SCORE):
            for (side, _lane), die in self.lane_dice.items():
                opposing = primary_b if side == a else primary_a
                initial = die.calculate_final_score() if opcode == OpCode.RESOLVE_FINAL_SCORE else die.final_score
                target = getattr(opposing.card, "character", None)
                if die.resolve_value(opcode, initial, target=target,
                                     opponent_card=opposing.card, opponent_die=opposing) is None:
                    return None
        return self.compare_scores()

    def compare_scores(self):
        a, b = self.dice_dict
        lane_results = {}
        for (side, lane), die in self.lane_dice.items():
            my_score = die.clash_score
            enemy_score, enemy_reverses = self.opposing_threshold(side, lane)
            if my_score == enemy_score:
                lane_results[(side, lane)] = "draw"
            else:
                lower_wins = die.reverses_clash or enemy_reverses
                won = (my_score < enemy_score) if lower_wins else (my_score > enemy_score)
                lane_results[(side, lane)] = "win" if won else "lose"
        self.lane_results = lane_results
        return {
            side: lane_results[(side, "front")] if (side, "front") in lane_results else lane_results[(side, "rear")]
            for side in (a, b)
        }
