"""Player decisions at the boundary between two resolved game actions."""

from dataclasses import dataclass, replace

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
    label: str | None = None


@dataclass(frozen=True)
class SkillUse:
    card: Card
    discount: int = 0


@dataclass
class CardDecision:
    player: object
    candidates: tuple
    origins: dict
    optional: bool
    operation: object
    invocation: object
    event: dict


class SpecialActions:
    def __init__(self, game):
        self.game = game
        self.duels = []
        self._declarations = []
        self.ability_uses = {}
        self.locked_cards = set()
        self._placement_choices = []
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
        self._card_choices.append(CardDecision(chooser.player, cards, origins, bool(spec.get("optional")),
                                               spec["then"], invocation, ctx.event.copy()))
        return True

    def _candidate_label(self, card, viewer):
        for group, slots in (("常规交锋", self.game.duelspace.space),
                             ("开牌前交锋", self.game.pre_reveal.space.space), ("即时交锋", self.duels)):
            for index, slot in enumerate(slots, 1):
                cards = slot.get_content(card.player.side)
                if card in cards:
                    name = ("扣置技能" if card.state == CardState.PLACED_FACE_DOWN and card.player is not viewer
                            else card.name)
                    return f"{group} {index} · 第 {cards.index(card) + 1} 张 · {name}"
        if viewer is not card.player:
            return f"对方第 {card.player.cardspace.hand.content.index(card) + 1} 张手牌"
        return f"{card.name}（{card.cost} 费）"

    def _valid_candidates(self, decision):
        board = {card for slot in self.game.board_slots() for cards in slot.content.values() for card in cards}
        cards = []
        for card in decision.candidates:
            actor, in_hand = decision.origins[card]
            if card.character is not actor or not actor.is_alive or card.destroyed:
                continue
            if in_hand:
                if card not in card.player.cardspace.hand.content or actor.skill_restricted(card):
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
        if isinstance(use, Card):
            use = SkillUse(use)
        if not isinstance(use, SkillUse) or not isinstance(use.card, Card):
            return False
        return self.game.pipeline.insert_skill(use, anchor, ctx.event)

    @property
    def placement_owner(self):
        # Another effect in the triggering node may already have removed the card.
        while self._placement_choices:
            card, actor, _ = self._placement_choices[0]
            if actor.is_alive and card in actor.player.cardspace.hand.content and not card.destroyed:
                return actor.player
            self._placement_choices.pop(0)
        return None

    def queue_placement(self, card, owner, slot_indices):
        indices = tuple(slot_indices)
        if indices:
            self._placement_choices.append((card, owner, indices))

    def is_locked(self, card):
        return self.window_open("placement") and card in self.locked_cards

    def window_open(self, window):
        game = self.game
        if game.is_over or game.turn_number <= game.turn_count:
            return False
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
            for spec in actor.data.get("actions", ()):
                key = actor, spec["id"]
                if not self.window_open(spec["window"]) or self.ability_uses.get(key, 0) >= spec.get("per_turn", float("inf")):
                    continue
                if any(actor.statuses.get(name, 0) < count for name, count in spec.get("cost", {}).items()):
                    continue
                if spec.get("requires_draw_pile") and not player.cardspace.draw.content:
                    continue
                choice = SpecialAction("ability", character=actor, ability_id=spec["id"])
                if spec["target"] == "self":
                    choices.append(choice)
                elif spec["target"] == "own_hand":
                    choices.extend(replace(choice, target_card=c) for c in self.game.pre_reveal.playable_hand(player))
                elif spec["target"] == "enemy_facedown":
                    enemy = self.game.pre_reveal.opponent(player)
                    choices.extend(replace(choice, duel_index=i, target_card=c)
                                   for i, slot in enumerate(self.game.duelspace.space)
                                   for c in slot.get_content(enemy.side) if c.state == CardState.PLACED_FACE_DOWN)
        return choices

    def _use_ability(self, action):
        actor = action.character
        spec = next(s for s in actor.data["actions"] if s["id"] == action.ability_id)
        ctx = self.game.context
        target = action.target_card or actor
        with ctx.binding(source=actor, side=actor.player.side, target=target):
            for status, count in spec.get("cost", {}).items():
                ctx.stack.extend((actor, status, count))
                if not ctx.execute_op(OpCode.SPEND_STATUS, result_field="paid_in_full"):
                    return False
            key = actor, action.ability_id
            self.ability_uses[key] = self.ability_uses.get(key, 0) + 1
            print(f"{actor.name} 使用「{spec['name']}」。")
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
        self._placement_choices.clear()
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
            "place" in card.data.get("anytime_play", ()) or owner.statuses.get("置卡机会", 0) > 0)

    @staticmethod
    def printed_replace(card, target):
        targets = card.data.get("replace_targets")
        if targets is not None:
            return target.id in targets and card.player is target.player
        return card.data.get("anytime_replace", False) and card.character is target.character

    def may_replace(self, card, slot, target):
        if (self.is_locked(target) or target.destroyed or not target.character.is_alive
                or not self.game.pipeline.can_replace(slot, target)):
            return False
        return (self.printed_replace(card, target)
                or card.character is target.character and card.character.statuses.get("换卡机会", 0) > 0
                and self.game.pipeline.before_use(slot, target))

    def options(self, player):
        game = self.game
        if game.is_over or game.turn_number <= game.turn_count or player not in game.players:
            return []
        decision = self.card_decision
        if decision:
            if player is not decision.player:
                return []
            choices = [SpecialAction("choose_card", target_card=card, label=self._candidate_label(card, player))
                       for card in self._valid_candidates(decision)]
            if decision.optional:
                choices.append(SpecialAction("decline_card", label="放弃此次选牌"))
            return choices
        if self.placement_owner is not None:
            card, actor, indices = self._placement_choices[0]
            return ([SpecialAction("queue_card", card=card, duel_index=i) for i in indices]
                    if player is actor.player else [])
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
                    or card.character.statuses.get("换卡机会")):
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
        if action.kind == "queue_card":
            self._placement_choices.pop(0)
            slot = game.duelspace.space[action.duel_index]
            with game.context.binding(source=card.character, side=player.side):
                placed = game.context.eval_block([card, {"at": "slot_tail", "target": slot}, OpCode.INSERT_SKILL])
            if placed:
                card.use_state["cost_prepaid"] = True
            return placed
        if action.kind == "ability":
            return self._use_ability(action)
        if action.kind == "place":
            if not game.place_in_duel(player.side, card, action.duel_index, special=True):
                return False
            print(f"{player.name} 特殊置卡至常规交锋 {action.duel_index + 1}。")
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
                print(f"{player.name} 用「{card.name}」迎击即时交锋 {action.response_number}。")
                game.pre_reveal.play_from_hand(slot, card, slot.attack_card.character)
            else:
                print(f"{player.name} 放行即时交锋 {action.response_number}。")
            self._resolve_ready()
        else:
            # A custom play is a declaration. The pack owns the ensuing use,
            # costs and destination via the normal entry/OpCode machinery.
            if not game.context.eval_block([card, "delayed_discard", OpCode.MOVE_CARD]):
                return False
            print(f"{player.name} 打出「{card.name}」，依卡面结算。")
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
        slot = PreRevealDuel(game, card, action.character, action.duel_index, pre_reveal=False)
        if self.window_open("before_duel"):
            slot.origin = "before_duel"
        self.duels.append(slot)
        self._declarations.append(slot)
        label = action.character.name if action.character else f"常规交锋 {action.duel_index + 1}"
        print(f"即时交锋 {len(self.duels)}：{card.player.name} 以「{card.name}」进攻 {label}。")
        phase.play_from_hand(slot, card, action.character)
        self._resolve_ready()

    def _resolve_ready(self):
        if not self.game.is_over and self._declarations and self.pending_attack is None:
            slots, self._declarations = self._declarations, []
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
            old.character.apply_status_delta("换卡机会", -1)
        self.game.pipeline.withdraw_skill(slot, old)
        cards = slot.get_content(player.side)
        cards[cards.index(old)] = card
        hand.remember_play_rank(card)
        hand.content[hand.content.index(card)] = old
        card.state = old.state
        if isinstance(slot, PreRevealDuel):
            for field in ("attack_card", "intercept_card", "pulled_card"):
                if getattr(slot, field) is old:
                    setattr(slot, field, card)
        self.game.used_cards[:] = [used for used in self.game.used_cards if used is not old]
        old.reset_for_draw()
        if card.state == CardState.PLACED_FACE_DOWN:
            print(f"{player.name} 调换了一张扣置技能，原牌回手。")
        else:
            print(f"{card.character.name} 换入「{card.name}」，「{old.name}」回手。")
        self.game.context.dispatch_pipeline("on_skill_replaced", source=card.character, side=player.side,
                                            card=card, replaced_card=old, duel=slot)
        return True
