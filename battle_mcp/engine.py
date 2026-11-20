"""Fixed-seat adapter around the game table. The room owns all scheduling."""

from battle_ui.match import BattleMatch


class ArenaEngine(BattleMatch):
    def __init__(self, roster=None, seed=None):
        super().__init__(roster=roster, seed=seed)
        self.game.pipeline.pause_on_clash_scores = True
        self.event = {"kind": "setup", "turn": 0}

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
        if self.game.special.pending_attack is not None:
            return "instant_response"
        if self.mode == "handoff":
            return "pre_reveal" if self._pre_seat else "placement"
        if self.mode in ("pre_attack", "intercept"):
            return "pre_reveal"
        return self.mode

    def required_sides(self):
        """Seats with outstanding decisions. Other seats may still have actions."""
        mode = self._mode()
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
        return frame

    def catalog(self):
        return self._views[None].catalog()

    def options(self, side):
        if side is None or self.game_over:
            return []
        player = self._choose_seat(side, self.game.players)
        mode = self._mode()
        choices = []
        if mode == "placement" and player is self.game.placing:
            choices.extend({"kind": "place", "card_id": c.id, "label": f"扣置{c.name}"}
                           for c in self._legal_cards())
            if self.game.placed_this_window:
                choices.append({"kind": "pass", "label": "交出本次置卡权"})
            choices.append({"kind": "end", "label": "结束本回合常规置卡"})
        if mode == "pre_reveal":
            phase = self.game.pre_reveal
            for card in phase.attack_cards(player):
                for target in phase.opponent(player).characters:
                    if target.is_alive:
                        choices.append({"kind": "attack", "card_id": card.id, "character_id": target.id,
                                        "label": f"用{card.name}进攻{target.name}"})
                for number in range(1, len(self.game.duelspace.space) + 1):
                    choices.append({"kind": "attack", "card_id": card.id, "duel_number": number,
                                    "label": f"用{card.name}进攻常规交锋 {number}"})
            if phase.can_attack(player):
                choices.append({"kind": "end_attack", "label": "结束主动进攻"})
            for number in phase.pending_for(player):
                for card in phase.intercept_cards(player):
                    choices.append({"kind": "intercept", "card_id": card.id, "response_number": number,
                                    "label": f"用{card.name}迎击开牌前交锋 {number}"})
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
        options = self._views[side].special_actions()
        return [{**{k: v for k, v in move.items() if v is not None}, "kind": "special_" + move["kind"]}
                for move in options]

    def _event(self, kind):
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

    def apply(self, side, move):
        player = self._choose_seat(side, self.game.players)
        if not isinstance(move, dict):
            raise ValueError("动作必须来自本席位的当前合法选项。")
        requested = {k: v for k, v in move.items() if k != "label"}
        legal = next((a for a in self.options(side)
                      if {k: v for k, v in a.items() if k != "label"} == requested), None)
        if legal is None:
            raise ValueError("动作不在本席当前的合法选项中。")
        kind = legal["kind"]
        if kind.startswith("special_"):
            index = self._special_options(side).index(legal)
            self._special_seat = player
            self._special_action("use_special", side, index)
        elif kind in ("end", "pass", "place"):
            self._place_action(kind, legal.get("card_id"))
        else:
            self._pre_seat = player
            target = None
            if "character_id" in legal:
                target = {"kind": "character", "id": legal["character_id"]}
            elif "duel_number" in legal:
                target = {"kind": "duel", "number": legal["duel_number"]}
            self._pre_action(kind, legal.get("card_id"), target, legal.get("response_number"))
        self.revision += 1
        self.event = self._event("finished" if self.game_over else "action")
        hidden_labels = {"place": "扣置常规技能", "special_place": "特殊置卡", "special_replace": "替换技能"}
        self.event.update(actor_side=side, action_kind=kind,
                          text=f"{player.name}{hidden_labels.get(kind, legal['label'])}。")
        if kind in ("attack", "intercept", "let_through", "special_intercept", "special_pass_intercept",
                    "special_attack", "special_custom"):
            self.event.update({k: v for k, v in requested.items() if k != "kind"})
        return self.event
