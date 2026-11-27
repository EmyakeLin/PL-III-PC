"""Fixed-seat adapter around the game table. The room owns all scheduling."""

from secrets import token_hex

from battle_ui.match import BattleMatch
from displayer import board_location_label, hand_key, seat_action_view


def action_fields(move):
    """Private card faces, descriptions and cost estimates describe a choice without identifying it."""
    ignored = ("label", "effect_target", "use_preview", "description", "preview", "hp", "max_hp")
    return {k: v for k, v in move.items() if k not in ignored}


def hand_card_label(card):
    if card.printed_owner is not card.character:
        return f"{card.name}（取自对手）"
    return card.name


class ArenaEngine(BattleMatch):
    def __init__(self, roster=None, seed=None, *, bot_side=None, open_rosters=False, extra_packs=(), ruleset=None,
                 fixed_opponent=False):
        super().__init__(roster=roster, seed=seed, open_rosters=open_rosters, extra_packs=extra_packs,
                         ruleset=ruleset, fixed_opponent=fixed_opponent)
        for player in self.game.players:
            if player.side == bot_side:
                player.target_priority = (("hp", 1), ("lightcore_hp", 1))
        self.game.pipeline.pause_on_clash_scores = True
        self.auto_claim_sides = {1, 2}
        self.event = {"kind": "setup", "turn": 0}
        self._hidden_ability_targets = {player.side: {} for player in self.game.players}

    def _auto_skip_unclaimed_pre_attack(self):
        phase = self.game.pre_reveal
        while (phase.phase == "attack" and phase.actor is not None
               and phase.can_attack(phase.actor)
               and not self._pre_reveal_claimed.get(phase.actor.side)
               and not self._pre_reveal_plans.get(phase.actor.side)):
            if phase.actor.side in self.auto_claim_sides and phase.attack_cards(phase.actor):
                break
            phase.end_attack(phase.actor)

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
        self._inject_dissolved_clashes(frame)
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

    def catalog(self, rosters=None):
        return self._views[None].catalog(rosters)

    def options(self, side):
        if side is None or self.game_over or self._mode() == "draw_select":
            return []
        player = self._choose_seat(side, self.game.players)
        mode = self._mode()
        choices = []
        if mode == "placement" and player is self.game.placing:
            staged_keys = {entry["card_id"] for entry in self._pre_reveal_plans.get(side, ())}
            choices.extend({"kind": "place", "card_id": hand_key(c), "label": f"扣置{hand_card_label(c)}"}
                           for c in self._legal_cards() if hand_key(c) not in staged_keys)
            for card, duel_indices in self.game.legal_rear_placements().items():
                key, name = hand_key(card), hand_card_label(card)
                if key in staged_keys:
                    continue
                for idx in duel_indices:
                    choices.append({
                        "kind": "place_rear",
                        "card_id": key,
                        "duel_number": idx + 1,
                        "label": f"将{name}扣置到常规交锋 {idx + 1} 后置",
                    })
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
                for card in phase.intercept_cards(player, number):
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
            if kind in ("choose_card", "decline_card", "choose_slot", "choose_option",
                        "decline_option", "choose_character", "decline_character"):
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
        elif kind == "place_rear":
            self._place_action("place_rear", legal.get("card_id"), duel_number=legal.get("duel_number"))
            public_text = f"{player.name}在常规交锋 {legal['duel_number']} 扣置后置技能。"
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

    def canvas_extras(self, side):
        card_owners = {
            "duels": {
                f"{num}:{p.side}": [
                    {
                        "character_id": c.character.id,
                        "printed_id": c.character.data.get("id"),
                        "character_name": c.character.name,
                        "character_color": self._character_colors.get(c.character.id) or self._character_colors.get(c.character.data.get("id")),
                        "card_back": self._character_card_backs.get(c.character.id) or self._character_card_backs.get(c.character.data.get("id")),
                    }
                    for c in slot.get_content(p.side)
                ]
                for num, slot in enumerate(self.game.duelspace.space, 1)
                for p in self.game.players
            },
            "duels_rear": {
                f"{num}:{p.side}": [
                    {
                        "character_id": c.character.id,
                        "printed_id": c.character.data.get("id"),
                        "character_name": c.character.name,
                        "character_color": self._character_colors.get(c.character.id) or self._character_colors.get(c.character.data.get("id")),
                        "card_back": self._character_card_backs.get(c.character.id) or self._character_card_backs.get(c.character.data.get("id")),
                    }
                    for c in slot.get_rear_content(p.side)
                ]
                for num, slot in enumerate(self.game.duelspace.space, 1)
                for p in self.game.players
            },
            "pre_reveal": {
                f"{num}:{p.side}": [
                    {
                        "character_id": c.character.id,
                        "printed_id": c.character.data.get("id"),
                        "character_name": c.character.name,
                        "character_color": self._character_colors.get(c.character.id) or self._character_colors.get(c.character.data.get("id")),
                        "card_back": self._character_card_backs.get(c.character.id) or self._character_card_backs.get(c.character.data.get("id")),
                    }
                    for c in slot.get_content(p.side)
                ]
                for num, slot in enumerate(self.game.pre_reveal.space.space, 1)
                for p in self.game.players
            },
        }
        mode = self._mode()
        pre_claimed = False
        pre_plan = []
        pre_elig = []
        pre_targets = {}
        if side in (1, 2) and mode in ("placement", "pre_reveal"):
            player = self._choose_seat(side, self.game.players)
            early = self.game.pre_reveal
            pre_claimed = bool(self._pre_reveal_claimed.get(side, False))
            pre_plan = self._validate_pre_reveal_plans(player)
            if mode == "placement" and player is self.game.placing:
                staged_keys = {entry["card_id"] for entry in self._pre_reveal_plans.get(side, ())}
                for c in self._pre_reveal_eligible_hand(player):
                    k = hand_key(c)
                    if k in staged_keys:
                        continue
                    pre_elig.append(k)
                    pre_targets[k] = [
                        {"kind": "character", "id": actor.id} if actor is not None else {"kind": "duel", "number": i + 1}
                        for actor, i in early.attack_targets(c)
                    ]
        return {
            "card_owners": card_owners,
            "speed_rolls": list(self.presentation.speed_rolls),
            "pre_reveal_claimed": pre_claimed,
            "pre_reveal_plan": pre_plan,
            "pre_reveal_eligible_cards": pre_elig,
            "pre_reveal_stage_targets": pre_targets,
            "chronicle": self.chronicle.snapshot(viewer_side=side),
        }

    def pre_reveal_plan_command(self, side, action, *, card_id=None, target=None):
        player = self._choose_seat(side, self.game.players)
        mode = self._mode()
        if action in ("claim_pre_reveal", "stage_pre_reveal"):
            if mode != "placement" or player is not self.game.placing:
                raise ValueError("当前不在本席的常规置卡窗口。")
        elif action == "unstage_pre_reveal":
            if mode not in ("placement", "pre_reveal"):
                raise ValueError("当前阶段无法修改开牌前预排。")
        elif action == "commit_pre_reveal_plan":
            if mode != "pre_reveal":
                raise ValueError("当前不在开牌前交锋主动进攻阶段。")
        else:
            raise ValueError("未知的预排操作。")
        self._pre_reveal_plan_action(action, player, card_id, target)
        self.revision += 1
        if action == "commit_pre_reveal_plan":
            self.event = self._event("finished" if self.game_over else "action")
            self.event.update(actor_side=side, action_kind="attack", text=self._history[-1])
        return self.event

    def forfeit_match(self, side, *, reason="宣布认输"):
        super().forfeit(side, reason=reason)
        self.revision += 1
        self.event = self._event("finished")
        self.event.update(actor_side=side, action_kind="concede", text=self._history[-1])
        return self.event
