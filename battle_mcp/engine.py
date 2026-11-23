"""Fixed-seat adapter around the game table. The room owns all scheduling."""

from secrets import token_hex

from battle_ui.match import BattleMatch
from displayer import board_location_label, hand_key, seat_action_view


def action_fields(move):
    """Private card faces and cost estimates describe a choice without identifying it."""
    return {k: v for k, v in move.items() if k not in ("label", "effect_target", "use_preview")}


def hand_card_label(card):
    if card.printed_owner is not card.character:
        return f"{card.name}（取自对手）"
    return card.name


class ArenaEngine(BattleMatch):
    def __init__(self, roster=None, seed=None, *, bot_side=None, open_rosters=False):
        super().__init__(roster=roster, seed=seed, open_rosters=open_rosters)
        for player in self.game.players:
            if player.side == bot_side:
                player.target_priority = (("hp", 1), ("lightcore_hp", 1))
        self.game.pipeline.pause_on_clash_scores = True
        self.event = {"kind": "setup", "turn": 0}
        self._hidden_ability_targets = {player.side: {} for player in self.game.players}

    def _advance(self):
        # BattleMatch normally moves to the next window immediately after an
        # action. Let the room publish that action and check declarations first.
        self.mode = "advance"

    def _pause_at_timing(self):
        return True

    @property
    def game_over(self):
        return self.game.is_over

    def _mode(self):
        if self.game_over:
            return "finished"
        if self.game.special.decision_owner is not None:
            return "skill_choice"
        if self.game.special.pending_attack is not None:
            return "instant_response"
        if self._draw_seat is not None:
            return "draw_select"
        if self.mode == "handoff":
            return "pre_reveal" if self._pre_seat else "placement"
        if self.mode in ("pre_attack", "intercept"):
            return "pre_reveal"
        return self.mode

    def required_sides(self):
        """Seats with outstanding decisions. Other seats may still have actions."""
        mode = self._mode()
        if mode == "skill_choice":
            return [self.game.special.decision_owner.side]
        if mode == "draw_select":
            return [self._draw_seat.side]
        if mode == "placement":
            return [self.game.placing.side]
        if mode == "pre_reveal":
            return [p.side for p in self.game.pre_reveal.eligible_players()]
        if mode == "instant_response":
            return sorted({3 - s.attacking_side for s in self.game.special.pending_attacks})
        return []

    def state(self, side=None):
        if side is not None:
            self._choose_seat(side, self.game.players)
        frame = self._views[side].snapshot()
        frame.update(mode=self._mode(), timing=self._timing,
                     response_times=[dict(t) for t in self._response_times])
        effect_choice = self._views[side].effect_choice()
        if effect_choice:
            frame["effect_choice"] = effect_choice
        if side is not None and self._mode() == "draw_select":
            draw = self._current_draw_prompt(viewer_side=side)
            if draw is not None:
                frame["draw_select"] = draw
        return frame

    def catalog(self):
        return self._views[None].catalog()

    def options(self, side):
        if side is None or self.game_over or self._mode() == "draw_select":
            return []
        player = self._choose_seat(side, self.game.players)
        mode = self._mode()
        choices = []
        if mode == "placement" and player is self.game.placing:
            choices.extend({"kind": "place", "card_id": hand_key(c), "label": f"扣置{hand_card_label(c)}"}
                           for c in self._legal_cards())
            if self.game.placed_this_window:
                choices.append({"kind": "pass", "label": "交出本次置卡权"})
            choices.append({"kind": "end", "label": "结束本回合常规置卡"})
        if mode == "pre_reveal":
            phase = self.game.pre_reveal
            for card in phase.attack_cards(player):
                key, name = hand_key(card), hand_card_label(card)
                for target, index in phase.attack_targets(card):
                    if target is not None:
                        choices.append({"kind": "attack", "card_id": key, "character_id": target.id,
                                        "label": f"用{name}进攻{target.name}"})
                    else:
                        choices.append({"kind": "attack", "card_id": key, "duel_number": index + 1,
                                        "label": f"用{name}进攻常规交锋 {index + 1}"})
            if phase.can_attack(player):
                choices.append({"kind": "end_attack", "label": "结束主动进攻"})
            for number in phase.pending_for(player):
                for card in phase.intercept_cards(player):
                    choices.append({"kind": "intercept", "card_id": hand_key(card), "response_number": number,
                                    "label": f"用{hand_card_label(card)}迎击开牌前交锋 {number}"})
                choices.append({"kind": "let_through", "response_number": number,
                                "label": f"放行开牌前交锋 {number}"})
        special = self._special_options(side)
        if mode == "pre_reveal" and self.game.pre_reveal.can_attack(player):
            # An anytime attack with pre-reveal initiative is the very same
            # declaration listed above, with the usual interception rights.
            special = [a for a in special if a["kind"] != "special_attack"]
        choices.extend(special)
        return choices

    def _special_options(self, side):
        options = []
        player = self._choose_seat(side, self.game.players)
        hidden_targets = {}
        for index, action in enumerate(self.game.special.options(player)):
            move = seat_action_view(action, player)
            option = {k: v for k, v in move.items() if v is not None}
            kind = action.kind
            if kind in ("choose_card", "decline_card", "choose_slot"):
                # Only the chooser can act; a new prompt must invalidate the previous positions.
                option["choice_key"] = f"{self.revision}.{index}"
            elif kind == "replace":
                target = action.target_card
                # Keep the original printed target's legacy ID. A borrowed or copied entity
                # remains independently addressable even if its board position later changes.
                original = next((c for actor in player.characters for c in actor.skills if c.id == target.id), None)
                if target is not original:
                    option["choice_key"] = f"instance:{target.instance_id}"
                option["label"] += " · " + board_location_label(option["effect_target"])
            elif kind == "ability" and action.target_card and action.target_card.player is not player:
                # Two seats may reserve abilities concurrently. Keep a concealed candidate's token
                # while that exact target stays eligible, even if a different seat has acted.
                key = (self.game.turn_number, action)
                hidden_targets[key] = self._hidden_ability_targets[side].get(key) or token_hex(8)
                option["choice_key"] = hidden_targets[key]
            option["kind"] = "special_" + kind
            options.append(option)
        self._hidden_ability_targets[side] = hidden_targets
        return options

    def _event(self, kind):
        self.presentation.flush()
        event = {"kind": kind, "turn": self.game.turn_number, "timing": self._timing}
        if self.game.pipeline.in_duel_phase:
            combat = self._views[None].snapshot()["combat"]
            if combat:
                event.update(duel_kind=combat["kind"], duel_number=combat["duel_number"],
                             round_id=combat["round_id"])
        return event

    def advance(self):
        if self.game_over or self.required_sides():
            raise ValueError("当前等待席位决策或对局已结束。")
        previous_history = tuple(self._history)
        super()._advance()
        self.revision += 1
        self.event = self._event(self._mode())
        if self._history and tuple(self._history) != previous_history:
            self.event["text"] = self._history[-1]
        if self.game_over:
            return self.event
        nodes = self.game.last_step
        nodes = list(nodes) if isinstance(nodes, tuple) else [nodes]
        self.event["nodes"] = [n for n in nodes if n]
        if "logic_dice_clash" in nodes or "clash_scores_ready" in nodes:
            combat = self._views[None].snapshot()["combat"]
            if combat:
                dice = [s["die"] for s in combat["sides"]]
                if all(d and d["rolled_value"] is not None and d["result"] is None for d in dice):
                    self.event["rolls"] = [d["rolled_value"] for d in dice]
                    if "clash_scores_ready" in nodes:
                        self.event["kind"] = "scores_ready"
                        self.event["scores"] = [d["clash_score"] for d in dice]
                    else:
                        self.event["kind"] = "roll"
        return self.event

    def current_move(self, side, move):
        requested = action_fields(move)
        return next((a for a in self.options(side) if action_fields(a) == requested), None)

    def draw_bottom(self, side, card_ids):
        if self._mode() != "draw_select" or side != self._draw_seat.side:
            raise ValueError("当前未轮到本席选择置底牌。")
        self._draw_bottom_action(card_ids)
        self.revision += 1
        self.event = self._event("action")
        self.event.update(actor_side=side, action_kind="draw_bottom", text=self._history[-1])

    def apply(self, side, move):
        player = self._choose_seat(side, self.game.players)
        if not isinstance(move, dict):
            raise ValueError("动作必须来自本席位的当前合法选项。")
        legal = self.current_move(side, move)
        if legal is None:
            raise ValueError("动作不在本席当前的合法选项中。")
        kind = legal["kind"]
        public_fields = {}
        if kind in ("attack", "intercept", "let_through", "special_intercept", "special_pass_intercept",
                    "special_attack", "special_custom"):
            public_fields = {key: legal[key] for key in ("character_id", "duel_number", "response_number")
                             if key in legal}
            if "card_id" in legal:
                # The hand key can reveal another copy. Resolve it before the played card leaves the hand.
                card = next(c for c in player.cardspace.hand.content if hand_key(c) == legal["card_id"])
                public_fields["card_id"] = card.id
        if kind.startswith("special_"):
            index = self._special_options(side).index(legal)
            self._special_seat = player
            self._special_action("use_special", side, index)
            public_text = self._history[-1]
        elif kind in ("end", "pass", "place"):
            self._place_action(kind, legal.get("card_id"))
            public_text = f"{player.name}{'扣置常规技能' if kind == 'place' else legal['label']}。"
        else:
            self._pre_seat = player
            target = None
            if "character_id" in legal:
                target = {"kind": "character", "id": legal["character_id"]}
            elif "duel_number" in legal:
                target = {"kind": "duel", "number": legal["duel_number"]}
            self._pre_action(kind, legal.get("card_id"), target, legal.get("response_number"))
            public_text = f"{player.name}{legal['label']}。"
        self.revision += 1
        self.event = self._event("finished" if self.game_over else "action")
        self.event.update(actor_side=side, action_kind=kind, text=public_text)
        self.event.update(public_fields)
        return self.event
