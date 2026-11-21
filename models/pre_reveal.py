"""开牌前的公开声明和延迟牵制。牌进入同一套双方交锋管线结算。"""

from models.card import CardState, allows_interception
from models.duel import DuelSlot, DuelSpace


class PreRevealDuel(DuelSlot):
    def __init__(self, game, attack_card, character, duel_index, *, pre_reveal=True):
        super().__init__(game)
        self.attack_card = attack_card
        self.attacking_side = attack_card.player.side
        self.target_character = character
        self.target_duel_index = duel_index
        self.intercept_card = None
        self.pulled_card = None
        self.resolved_target = None
        self.origin = "pre_reveal" if pre_reveal else "instant"
        self.required_card = None
        self.interceptable = allows_interception(attack_card.data, pre_reveal=pre_reveal)
        self.ready = not self.interceptable

    def play_mode(self, card):
        if card is not None:
            if card is self.attack_card:
                return "active"
            if card is self.intercept_card:
                return "passive"
            if card is self.pulled_card:
                return "pulled"
        return None

    def prepare(self, phase):
        """在本场交锋真正开始时按位置查牌，上一场的牵制、回手及死亡均已生效。"""
        if not self.ready or self.next_playable_card(self.attacking_side) is not self.attack_card:
            return False
        defender = phase.opponent(self.attack_card.player)
        if self.intercept_card is not None:
            if self.next_playable_card(defender.side) is not self.intercept_card:
                return False
            self.resolved_target = self.intercept_card.character
        elif self.target_duel_index is not None:
            index = self.target_duel_index
            slot = self.game.duelspace.space[index]
            # An immediate attack can point at a regular slot already running.
            # Only unstarted skills can be pulled into a second battlefield.
            remaining = slot.get_content(defender.side)[slot.current_card_index.get(defender.side, 0):]
            candidates = [c for c in remaining if c.character.is_alive and not c.destroyed
                          and c.state != CardState.NEGATED]
            card = next((c for c in candidates if not self.game.pipeline.in_use(slot, c)), None)
            if self.required_card is not None:
                if self.required_card not in candidates or self.game.pipeline.in_use(slot, self.required_card):
                    return False
                card = self.required_card
            key = (index, defender.side)
            if card is not None:
                slot.remove_card(card)
                self.add_content(defender.side, card)
                card.state = CardState.PLACED_FACE_UP
                self.pulled_card = card
                phase.pulled_owners[key] = card.character
                print(f"常规交锋 {index + 1} 的「{card.name}」被牵制。")
            if card is None and candidates:
                self.resolved_target = candidates[0].character
            else:
                self.resolved_target = phase.pulled_owners.get(key)
        else:
            self.resolved_target = self.target_character
        return self.resolved_target is not None and self.resolved_target.is_alive

    def resolve_target_character(self, attacking_side, clash_pair=None, previous_opponent=None):
        opposing = self.get_current_opposing_card(attacking_side)
        if opposing is not None and opposing.character.is_alive:
            return opposing.character
        target = self.resolved_target if attacking_side == self.attacking_side else self.attack_card.character
        return target if target is not None and target.is_alive else None


class PreRevealPhase:
    def __init__(self, game):
        self.game = game
        self.space = DuelSpace(game)
        self.phase = "idle"
        self.actor = self.attacker = None
        self.pulled_owners = {}

    def opponent(self, player):
        return next(other for other in self.game.players if other is not player)

    def start(self):
        if self.phase != "idle" or self.game.first_player is None:
            raise ValueError("当前无法开始开牌前声明。")
        self.attacker = self.game.first_player
        self.phase = "attack"
        self._refresh()

    def pending_for(self, player):
        """Public, stable (one-based) numbers awaiting this player's answer."""
        if player not in self.game.players:
            return []
        return [number for number, slot in enumerate(self.space.space, 1)
                if not slot.ready and slot.attacking_side != player.side]

    def can_attack(self, player):
        return (player is not None and player is self.attacker and not self.game.is_over
                and self.phase in ("attack", "intercept"))

    @staticmethod
    def playable_hand(player, *, for_use=True):
        return [c for c in player.cardspace.hand.content
                if c.character.is_alive and not c.destroyed and c.state != CardState.NEGATED
                and (not for_use or c.meets_use_requirements())]

    def attack_cards(self, player):
        return ([c for c in self.playable_hand(player)
                 if (c.can_open_pre_reveal or "attack" in c.data.get("anytime_play", ()))
                 and self.attack_targets(c)]
                if self.can_attack(player) else [])

    def attack_targets(self, card):
        enemy = self.opponent(card.player)
        if card.data.get("pre_reveal_target") == "occupied_enemy_slot":
            return [(None, i) for i, slot in enumerate(self.game.duelspace.space)
                    if any(c.character.is_alive and not c.destroyed and c.state != CardState.NEGATED
                           for c in slot.get_content(enemy.side))]
        return ([(c, None) for c in enemy.characters if c.is_alive]
                + [(None, i) for i in range(len(self.game.duelspace.space))])

    def intercept_cards(self, player):
        if self.game.is_over or not self.pending_for(player):
            return []
        return self.playable_hand(player)

    def eligible_players(self):
        if self.game.is_over:
            return []
        return [p for p in self.game.players if self.can_attack(p) or self.pending_for(p)]

    def legal_cards(self):
        """Cards for the suggested hot-seat prompt. The other player may still act."""
        if self.phase == "intercept":
            return self.intercept_cards(self.actor)
        return self.attack_cards(self.actor)

    def _advance_attack_right(self):
        self.attacker = (self.opponent(self.attacker)
                         if self.attacker is self.game.first_player else None)

    def _refresh(self, offer_interception_to=None):
        pending = [p for p in self.game.players if self.pending_for(p)]
        # A response can draw more cards. Leave the attack right open until the
        # player ends it or the table is settled and there is no attack to make.
        def may_declare():
            return self.attack_cards(self.attacker) or self.game.special.ability_options(self.attacker)

        while self.attacker is not None and not pending and not may_declare():
            self._advance_attack_right()
        if self.game.is_over:
            self.actor = self.attacker = None
            self.phase = "done"
        elif offer_interception_to in pending:
            self.actor, self.phase = offer_interception_to, "intercept"
        elif self.attacker is not None and may_declare():
            self.actor, self.phase = self.attacker, "attack"
        elif pending:
            self.actor, self.phase = pending[0], "intercept"
        elif self.attacker is None:
            self.actor, self.phase = None, "ready"

    def end_attack(self, player=None):
        if player is None:
            player = self.attacker
        if not self.can_attack(player):
            raise ValueError("这名玩家当前没有进攻权。")
        self._advance_attack_right()
        self._refresh()

    def declare_attack(self, card, *, character=None, duel_index=None):
        if card not in self.attack_cards(self.attacker):
            raise ValueError("这张牌当前不能发起开牌前交锋。")
        enemy = self.opponent(card.player)
        if (character is None) == (duel_index is None):
            raise ValueError("须指定一名敌方角色或一个常规交锋。")
        if character is not None and (character not in enemy.characters or not character.is_alive):
            raise ValueError("目标须为存活的敌方角色。")
        if duel_index is not None and (type(duel_index) is not int
                                       or not 0 <= duel_index < len(self.game.duelspace.space)):
            raise ValueError("指定的常规交锋不存在。")
        if (character, duel_index) not in self.attack_targets(card):
            raise ValueError("此牌只能指定对方已置牌的常规交锋。")
        slot = PreRevealDuel(self.game, card, character, duel_index, pre_reveal=True)
        if card.data.get("pre_reveal_target") == "occupied_enemy_slot":
            slot.required_card = self.game.duelspace.space[duel_index].next_playable_card(enemy.side)
        self.space.append_new_duel(slot)
        label = character.name if character is not None else f"常规交锋 {duel_index + 1}"
        print(f"开牌前交锋 {len(self.space.space)}：{card.player.name} 声明「{card.name}」→ {label}。")
        self.play_declared_skill(slot, card, character)
        self._refresh(offer_interception_to=enemy)
        return slot

    def _pending_slot(self, player, duel_number):
        pending = self.pending_for(player)
        if duel_number is None:
            if len(pending) != 1:
                raise ValueError("请选择一个待迎击的开牌前交锋编号。")
            duel_number = pending[0]
        if type(duel_number) is not int or duel_number not in pending:
            raise ValueError("这个交锋当前无法由该玩家迎击或放行。")
        return self.space.space[duel_number - 1]

    def intercept(self, card, duel_number=None):
        player = getattr(card, "player", None)
        if card not in self.intercept_cards(player):
            raise ValueError("这张牌当前不能拦截。")
        slot = self._pending_slot(player, duel_number)
        slot.intercept_card = card
        slot.target_character = slot.target_duel_index = None
        slot.ready = True
        print(f"{player.name} 用「{card.name}」拦截，开牌前交锋 {self.space.space.index(slot) + 1} 转火。")
        self.play_declared_skill(slot, card, slot.attack_card.character)
        self._refresh()

    def pass_intercept(self, duel_number=None, player=None):
        if self.game.is_over or self.phase not in ("attack", "intercept"):
            raise ValueError("当前不在拦截时点。")
        if player is None:
            player = self.actor
        slot = self._pending_slot(player, duel_number)
        slot.ready = True
        self._refresh()

    def play_declared_skill(self, slot, card, target):
        # Settle the new zone before publishing the change in hand size.
        slot.add_content(card.player.side, card)
        card.state = CardState.PLACED_FACE_UP
        if not card.temporary:
            hand = card.player.cardspace.hand
            hand.remove_card(hand.content.index(card))
        self.game.context.dispatch_pipeline(
            "on_pre_reveal_play", side=card.player.side, source=card.character, card=card,
            target=target, target_duel_index=slot.target_duel_index, duel=slot,
            play_mode=slot.play_mode(card))

    play_from_hand = play_declared_skill

    def begin_resolution(self):
        if self.phase != "ready" or any(not slot.ready for slot in self.space.space):
            raise ValueError("双方结束开牌前声明后才能结算。")
        self.game.close_private_view()
        if self.space.space:
            self.phase = "resolving"
            self.game.pipeline.start_duel_combat()
        else:
            self.phase = "done"
