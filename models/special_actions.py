"""Player decisions at the boundary between two resolved game actions."""

from dataclasses import dataclass, field, replace

from entry.entry import Entry, TriggerType, character_of
from entry.effects import run_effect
from models.card import Card, CardState
from models.character import Character
from models.opcode import OpCode
from models.pre_reveal import PreRevealDuel


@dataclass(frozen=True)
class SpecialAction:
    kind: str
    card: Card | None = None
    target_card: Card | None = None
    character: Character | None = None
    duel_index: int | None = None
    response_number: int | None = None
    ability_id: str | None = None
    label: str | None = field(default=None, compare=False)
    duel_kind: str | None = None


@dataclass(frozen=True)
class SkillCopy:
    """A printed skill to instantiate only when an insertion is attempted."""
    owner: Character
    data: dict


@dataclass(frozen=True)
class SkillUse:
    card: Card | SkillCopy
    discount: int = 0
    prepaid: bool = False

    def set_price(self):
        self.card.use_state["use_discount"] = max(0, self.discount)
        if self.prepaid:
            self.card.use_state["cost_prepaid"] = True


@dataclass
class CardDecision:
    player: object
    candidates: tuple
    origins: dict
    optional: bool
    operation: object
    invocation: object
    event: dict
    require_playable_hand: bool
    specification: dict


@dataclass
class SlotDecision:
    actor: Character
    subject: object
    candidates: tuple
    continuation: list
    invocation: object
    event: dict


class SpecialActions:
    def __init__(self, game):
        self.game = game
        self.duels = []
        self._declarations = []
        self.ability_uses = {}
        self.locked_cards = set()
        self._slot_choices = []
        self._card_choices = []

    @staticmethod
    def own_hand_skills(actor):
        return [card for card in actor.player.cardspace.hand.content
                if card.character is actor and actor.is_alive and not card.destroyed
                and not actor.skill_restricted(card)]

    def board_skills(self, target):
        if target is None:
            return []
        return [card for slot in self.game.board_slots() for card in slot.get_content(target.player.side)
                if card.character is target and not card.destroyed and target.is_alive]

    def choose_card(self, ctx, candidates, spec):
        """Suspend a printed choice until its controller supplies an answer."""
        if not ctx.executions or self.game.is_over:
            return False
        invocation = ctx.executions[-1]
        actor = character_of(invocation.entry.owner)
        chooser = ctx.event.get("target") if spec.get("chooser") == "target" else actor
        if chooser is None or not chooser.is_alive:
            return False
        cards = tuple(dict.fromkeys(card for card in candidates if isinstance(card, Card) and not card.destroyed))
        if not cards:
            return False
        origins = {card: (card.character, card in card.player.cardspace.hand.content) for card in cards}
        event = ctx.event.copy()
        if "use_discount" in spec:
            event["choice_discount"] = spec["use_discount"]  # Older continuations read this event field.
        event["bindings"] = {**event.get("bindings", {}), **spec.get("bindings", {})}
        self._card_choices.append(CardDecision(chooser.player, cards, origins, bool(spec.get("optional")),
                                               spec["then"], invocation, event,
                                               spec.get("require_playable_hand", True), spec))
        return True

    def _valid_candidates(self, decision):
        board = {card for slot in self.game.board_slots() for cards in slot.content.values() for card in cards}
        cards = []
        for card in decision.candidates:
            actor, in_hand = decision.origins[card]
            if card.character is not actor or not actor.is_alive or card.destroyed:
                continue
            if in_hand:
                if (card not in card.player.cardspace.hand.content
                        or decision.require_playable_hand and actor.skill_restricted(card)):
                    continue
            elif card not in board:
                continue
            cards.append(card)
        return cards

    @property
    def card_decision(self):
        while self._card_choices:
            choice = self._card_choices[0]
            actor = character_of(choice.invocation.entry.owner)
            if (actor is not None and actor.is_alive and not choice.invocation.cancelled
                    and not choice.invocation.entry.blanked and self._valid_candidates(choice)):
                return choice
            self._card_choices.pop(0)
        return None

    @property
    def decision_owner(self):
        decision = self.card_decision
        return decision.player if decision else self.placement_owner

    def _resolve_card_choice(self, action):
        decision = self._card_choices.pop(0)
        if action.kind == "decline_card":
            return True
        ctx = self.game.context
        fields = dict(decision.event, chosen_card=action.target_card)
        ctx.executions.append(decision.invocation)
        try:
            with ctx.binding(**fields):
                run_effect(ctx, decision.invocation.entry, decision.operation)
        finally:
            ctx.executions.pop()
        return True

    def insert_skill(self, use, anchor, ctx):
        if isinstance(use, (Card, SkillCopy)):
            use = SkillUse(use)
        if not isinstance(use, SkillUse):
            return False
        if isinstance(use.card, SkillCopy):
            spec = use.card
            if not spec.owner.is_alive or self.game.is_over:
                return False
            copy = Card(spec.owner.player, spec.data, spec.owner, temporary=True)
            inserted = self.game.pipeline.insert_skill(replace(use, card=copy), anchor, ctx.event)
            if not inserted:
                copy.dissolve()
            return inserted
        if not isinstance(use.card, Card):
            return False
        return self.game.pipeline.insert_skill(use, anchor, ctx.event)

    @property
    def slot_decision(self):
        while self._slot_choices:
            choice = self._slot_choices[0]
            if self._slot_options(choice):
                return choice
            self._slot_choices.pop(0)
        return None

    @property
    def placement_owner(self):
        choice = self.slot_decision
        return choice.actor.player if choice else None

    def choose_slot(self, ctx, subject, candidates, continuation):
        """Suspend a program and resume its captured block with the chosen duel."""
        if not ctx.executions or self.game.is_over:
            return False
        invocation = ctx.executions[-1]
        actor = character_of(invocation.entry.owner)
        if actor is None:
            return False
        choice = SlotDecision(actor, subject, tuple(dict.fromkeys(candidates)), continuation, invocation, ctx.event.copy())
        if not self._slot_options(choice):
            return False
        self._slot_choices.append(choice)
        return True

    def _slot_options(self, choice):
        if (not choice.actor.is_alive or choice.invocation.cancelled or choice.invocation.entry.blanked):
            return {}
        use = choice.subject if isinstance(choice.subject, SkillUse) else None
        if use and use.card not in self.own_hand_skills(choice.actor):
            return {}
        options = {}
        for kind, slots in (("regular", self.game.duelspace.space), ("pre_reveal", self.game.pre_reveal.space.space),
                            ("instant", self.duels)):
            for index, slot in enumerate(slots):
                if slot in choice.candidates and self.game.pipeline.can_join(slot):
                    options[SpecialAction("choose_slot", card=use.card if use else None,
                                          duel_index=index, duel_kind=kind)] = slot
        return options

    def _resolve_slot_choice(self, action):
        from entry.program import execute_program_block

        choice = self._slot_choices.pop(0)
        slot = self._slot_options(choice)[action]
        ctx = self.game.context
        fields = dict(choice.event, choice_subject=choice.subject, chosen_slot=slot)
        ctx.executions.append(choice.invocation)
        try:
            with ctx.binding(**fields):
                return execute_program_block(ctx, choice.continuation) is not False
        finally:
            ctx.executions.pop()

    def is_locked(self, card):
        return self.window_open("placement") and card in self.locked_cards

    def window_open(self, window):
        game = self.game
        if game.is_over or game.turn_number <= game.turn_count:
            return False
        if window == "turn_start":
            pipe = game.pipeline
            index = pipe.current_step_index
            return (not pipe.in_duel_phase and 0 <= index < len(pipe.step_list)
                    and pipe.step_list[index].id == "on_turn_start")
        if window == "before_reveal":
            return not game.cards_revealed
        if window == "placement":
            return game.placing is not None and game.pre_reveal.phase == "idle"
        if window == "before_duel":
            return game.pipeline.before_duel_start
        return False

    def ability_options(self, player):
        choices = []
        for actor in player.characters:
            if not actor.is_alive:
                continue
            for spec in actor.action_specs():
                key = actor, spec["id"]
                if not self.window_open(spec["window"]) or self.ability_uses.get(key, 0) >= spec.get("per_turn", float("inf")):
                    continue
                if any(actor.statuses.get(name, 0) < count for name, count in spec.get("cost", {}).items()):
                    continue
                if any(actor.ability_effects.get(name, 0) < count for name, count in spec.get("ability_cost", {}).items()):
                    continue
                if spec.get("requires_draw_pile") and not player.cardspace.draw.content:
                    continue
                choice = SpecialAction("ability", character=actor, ability_id=spec["id"])
                if spec["target"] == "self":
                    choices.append(choice)
                elif spec["target"] == "own_hand":
                    choices.extend(replace(choice, target_card=c)
                                   for c in self.game.pre_reveal.playable_hand(player, for_use=False))
                elif spec["target"] == "enemy_facedown":
                    enemy = self.game.pre_reveal.opponent(player)
                    choices.extend(replace(choice, duel_index=i, target_card=c)
                                   for i, slot in enumerate(self.game.duelspace.space)
                                   for c in slot.get_content(enemy.side) if c.state == CardState.PLACED_FACE_DOWN)
        return choices

    def _use_ability(self, action):
        actor = action.character
        spec = next(s for s in actor.action_specs() if s["id"] == action.ability_id)
        ctx = self.game.context
        target = action.target_card or actor
        with ctx.binding(source=actor, side=actor.player.side, target=target):
            if not ctx.pay_action_costs(actor, spec.get("ability_cost", {}), spec.get("cost", {})):
                return False
            key = actor, action.ability_id
            self.ability_uses[key] = self.ability_uses.get(key, 0) + 1
            ctx.record("ability_used", actor=actor.name, ability=spec["name"])
            ctx._invoke(Entry(actor, TriggerType.PIPELINE, "on_player_action", spec["operation"]))
        return True

    @property
    def pending_attacks(self):
        return [s for s in self._declarations if not s.ready]

    @property
    def pending_attack(self):
        return next((s for s in self._declarations if not s.ready), None)

    def clear(self):
        self.duels.clear()
        self._declarations.clear()
        self.ability_uses.clear()
        self.locked_cards.clear()
        self._slot_choices.clear()
        self._card_choices.clear()

    def first_open_slot(self, side):
        space = self.game.duelspace
        for index in range(space.current_duel_index, len(space.space)):
            slot = space.space[index]
            if not slot.get_content(side) and self.game.pipeline.can_join(slot):
                return index
        return len(space.space)

    def may_place(self, card):
        owner = card.character
        return owner.used_duels < owner.max_duels and (
            "place" in card.data.get("anytime_play", ()) or owner.ability_permission("place") is not None)

    @staticmethod
    def printed_replace(card, target):
        targets = card.data.get("replace_targets")
        if targets is not None:
            return target.id in targets and card.player is target.player
        return card.data.get("anytime_replace", False) and card.character is target.character

    def may_replace(self, card, slot, target):
        if (not card.meets_use_requirements() or self.is_locked(target) or target.destroyed or not target.character.is_alive
                or not self.game.pipeline.can_replace(slot, target)):
            return False
        return (self.printed_replace(card, target)
                or card.character is target.character and card.character.ability_permission("replace") is not None
                and self.game.pipeline.before_use(slot, target))

    def options(self, player):
        game = self.game
        if game.is_over or player not in game.players:
            return []
        decision = self.card_decision
        if decision:
            if player is not decision.player:
                return []
            choices = [SpecialAction("choose_card", target_card=card) for card in self._valid_candidates(decision)]
            if decision.optional:
                choices.append(SpecialAction("decline_card"))
            return choices
        if self.placement_owner is not None:
            choice = self._slot_choices[0]
            return list(self._slot_options(choice)) if player is choice.actor.player else []
        if game.turn_number <= game.turn_count:
            return []
        phase = game.pre_reveal
        cards = phase.playable_hand(player)
        enemy = phase.opponent(player)
        choices = self.ability_options(player)
        for slot in self.pending_attacks:
            if slot.attacking_side != player.side:
                number = self.duels.index(slot) + 1
                choices.extend(SpecialAction("intercept", card, response_number=number) for card in cards)
                choices.append(SpecialAction("pass_intercept", response_number=number))
        for card in cards:
            modes = card.data.get("anytime_play", ())
            if self.may_place(card):
                choices.append(SpecialAction("place", card, duel_index=self.first_open_slot(player.side)))
            if "attack" in modes or card.data.get("before_duel_attack") and self.window_open("before_duel"):
                choices.extend(SpecialAction("attack", card, character=c) for c in enemy.characters if c.is_alive)
                choices.extend(SpecialAction("attack", card, duel_index=index)
                               for index, slot in enumerate(game.duelspace.space)
                               if index >= game.duelspace.current_duel_index and game.pipeline.can_join(slot))
            if "custom" in modes and not card.character.skill_restricted(card):
                choices.append(SpecialAction("custom", card))
            if (card.data.get("anytime_replace") or card.data.get("replace_targets")
                    or card.character.ability_permission("replace") is not None):
                for slot in game.board_slots():
                    for target in slot.get_content(player.side):
                        if self.may_replace(card, slot, target):
                            choices.append(SpecialAction("replace", card, target_card=target))
        return choices

    def apply(self, player, action):
        choices = self.options(player)
        if isinstance(action, SpecialAction) and action.kind in ("intercept", "pass_intercept") and action.response_number is None:
            matches = [c for c in choices if replace(c, response_number=None) == action]
            if len(matches) == 1:
                action = matches[0]
        if action not in choices:
            raise ValueError("这个特殊置卡或换卡操作在当前时点无效。")
        game, card = self.game, action.card
        if action.kind in ("choose_card", "decline_card"):
            return self._resolve_card_choice(action)
        if action.kind == "choose_slot":
            return self._resolve_slot_choice(action)
        if action.kind == "ability":
            return self._use_ability(action)
        if action.kind == "place":
            if not game.place_in_duel(player.side, card, action.duel_index, special=True):
                return False
            game.context.record("special_placement", player=player.name, number=action.duel_index + 1)
        elif action.kind == "replace":
            with game.context.binding(source=card.character, side=player.side):
                return game.context.eval_block([card, action.target_card, OpCode.REPLACE_SKILL])
        elif action.kind == "attack":
            self._attack(action)
        elif action.kind in ("intercept", "pass_intercept"):
            slot = self.duels[action.response_number - 1]
            slot.ready = True
            if card is not None:
                slot.intercept_card = card
                slot.target_character = slot.target_duel_index = None
                game.context.record("intercepted", series="instant", number=action.response_number,
                                    player=player.name, card=card.name)
                game.pre_reveal.play_declared_skill(slot, card, slot.attack_card.character)
            else:
                game.context.record("passed_intercept", player=player.name, number=action.response_number)
            self._resolve_ready()
        else:
            # A custom play is a declaration. The pack owns the ensuing use,
            # costs and destination via the normal entry/OpCode machinery.
            if not game.context.eval_block([card, "delayed_discard", OpCode.MOVE_CARD]):
                return False
            game.context.record("card_played", player=player.name, card=card.name)
            if card.character.is_alive and not game.is_over:
                game.context.dispatch_pipeline("on_anytime_play", side=player.side, source=card.character,
                                               card=card, die=None, play_mode="custom")
        return True

    def _attack(self, action):
        game, card = self.game, action.card
        phase = game.pre_reveal
        if phase.can_attack(card.player) and game.pipeline.interrupt_space is None and not self._declarations:
            phase.declare_attack(card, character=action.character, duel_index=action.duel_index)
            return
        self.declare_field_attack(card, action.character, action.duel_index)

    def declare_field_attack(self, card, target, duel_index=None, *, deferred=False):
        game = self.game
        slot = PreRevealDuel(game, card, target, duel_index, pre_reveal=False)
        if deferred and game.context.executions:
            rule = game.context.executions[-1].entry
            slot.trigger_die = game.context.event.get("die")
            slot.trigger_card = getattr(slot.trigger_die, "card", None) or game.context.event.get("card")
            slot.trigger_name = getattr(rule, "_passive_name", None)
        if self.window_open("before_duel"):
            slot.origin = "before_duel"
        self.duels.append(slot)
        self._declarations.append(slot)
        game.context.record("attack_declared", series="instant", number=len(self.duels), player=card.player.name,
                            card=card.name, target=getattr(target, "name", None), duel_index=duel_index)
        game.pre_reveal.play_declared_skill(slot, card, target)
        self._resolve_ready(deferred=deferred)

    def _resolve_ready(self, *, deferred=False):
        if not self.game.is_over and self._declarations and self.pending_attack is None:
            slots, self._declarations = self._declarations, []
            if deferred:
                self.game.pipeline.queue_special_duels(slots)
            else:
                self.game.pipeline.start_special_duels(slots)

    def exchange(self, card, old):
        """Commit both zone changes together; hand size never crosses a threshold."""
        player = card.player
        hand = player.cardspace.hand
        if (self.game.is_over or self.game.turn_number <= self.game.turn_count
                or card not in hand.content or not card.character.is_alive or card.destroyed
                or card.state == CardState.NEGATED or old.player is not player):
            return False
        slot = next((s for s in self.game.board_slots() if old in s.get_content(player.side)), None)
        if slot is None or not self.may_replace(card, slot, old):
            return False
        if not self.printed_replace(card, old):
            owner = old.character
            if not owner.spend_ability_effect(owner.ability_permission("replace")):
                return False
            if (not owner.is_alive or card.destroyed or old.destroyed or card not in hand.content
                    or old not in slot.get_content(player.side) or self.is_locked(old)
                    or not self.game.pipeline.before_use(slot, old)):
                return False
        self.game.pipeline.withdraw_skill(slot, old)
        cards = slot.get_content(player.side)
        cards[cards.index(old)] = card
        hand.remember_play_rank(card)
        if old.temporary:
            hand.content.remove(card)
        else:
            hand.content[hand.content.index(card)] = old
        card.state = old.state
        if isinstance(slot, PreRevealDuel):
            for field in ("attack_card", "intercept_card", "pulled_card"):
                if getattr(slot, field) is old:
                    setattr(slot, field, card)
        self.game.used_cards[:] = [used for used in self.game.used_cards if used is not old]
        if old.temporary:
            old.dissolve()
            hand._on_size_changed(len(hand.content) + 1, len(hand.content))
        else:
            old.reset_for_draw()
        if card.state == CardState.PLACED_FACE_DOWN:
            self.game.context.record("hidden_card_replaced", player=player.name, dissolved=old.temporary)
        else:
            self.game.context.record("card_replaced", actor=card.character.name, card=card.name,
                                     replaced=old.name, dissolved=old.temporary)
        self.game.context.dispatch_pipeline("on_skill_replaced", source=card.character, side=player.side,
                                            card=card, replaced_card=old, duel=slot)
        return True
