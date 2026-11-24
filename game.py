import random
from types import SimpleNamespace

from context.context import Context
from gamerule import GameRule
from loader import base_effects
from models.card import CardState
from models.character import Character
from models.duel import DuelSpace
from models.opcode import OpCode
from models.pre_reveal import PreRevealPhase
from models.special_actions import SpecialActions
from models.turn_history import TurnHistory
from player.draw_choice import InvalidBottomSelection
from pipeline.pipeline import Pipeline
from pipeline.pipeline_steps import step_list


class Game:
    def __init__(self, players, rng=None):
        self.players = list(players)
        if len(self.players) != 2 or len({p.side for p in self.players}) != 2:
            raise ValueError("双人对局需要两名阵营不同的玩家。")
        self.rng = random if rng is None else rng
        self.gamerule = GameRule()
        for player in self.players:
            player.game = self
        self.first_player = None
        self.placing = None
        self.ended_player = []
        self.placed_this_window = 0
        self.placement_capacity = 1
        self.used_cards = []
        self.turn_history = TurnHistory()
        self.pending_draw = None
        self._drawing_players = None
        self.cards_revealed = False
        self.turn_count = 0
        self.turn_number = 0
        self.turn_ending = False
        self.card_serial = 0
        self._prepared_turn = -1
        self._battle_started = False
        effects = base_effects()
        self.status_entries = dict(effects.status_entries)
        self.status_rules = dict(effects.status_rules)
        self.ability_rules = dict(effects.ability_rules)
        self.turn_end_statuses = set(effects.turn_end_statuses)
        self.is_over = False
        self.winner = None
        self.context = Context(game=self)
        self.context.register_status_programs(self.status_rules)
        self.context.register_status_programs(self.ability_rules)
        self.duelspace = DuelSpace(self)
        self.pre_reveal = PreRevealPhase(self)
        self.pipeline = Pipeline(self, step_list)
        self.special = SpecialActions(self)
        self.last_step = None
        self.tmp = SimpleNamespace()

    def deploy_rosters(self, rosters):
        rosters = tuple(rosters)
        if len(rosters) != len(self.players) or any(not roster for roster in rosters):
            raise ValueError("每个席位都需要一份非空出战阵容")
        for player, roster in zip(self.players, rosters):
            for data in roster:
                character = Character(data, player)
                player.characters.append(character)
                character.init_cards()
                character.setup_deck()
            player.cardspace.draw.shuffle(self.rng)
            player.cardspace.decisive.shuffle(self.rng)
        self.start_battle()

    def start_battle(self):
        if not self._battle_started:
            self._battle_started = True
            self.context.dispatch_pipeline("on_battle_start", source=None, target=None, side=None)

    def next_step(self):
        if self.pending_draw is not None and not self.is_over:
            return "wait_draw_choice"
        if self.special.option_decision is not None and not self.is_over:
            return "wait_option_choice"
        if self.special.card_decision is not None and not self.is_over:
            return "wait_card_choice"
        if self.special.placement_owner is not None and not self.is_over:
            return "wait_queued_placement"
        if self.special.pending_attack is not None and not self.is_over:
            return "wait_special_intercept"
        # An extra placement can reopen the regular sequence after its last slot.
        # Its cursor still points after all settled slots.
        if (self.cards_revealed and not self.is_over and not self.pipeline.in_duel_phase
                and self.pipeline.current_step_index >= 0
                and self.pipeline.step_list[self.pipeline.current_step_index].id in
                ("logic_start_duel_combat", "before_turn_end")
                and self.duelspace.has_next_duel()):
            self.pipeline.start_duel_combat()
        self.last_step = self.pipeline.next_step()
        return self.last_step

    @property
    def active_duelspace(self):
        if self.pipeline.interrupt_space is not None:
            return self.pipeline.interrupt_space
        if self.pre_reveal.phase == "resolving":
            return self.pre_reveal.space
        return self.duelspace

    def board_slots(self):
        yield from self.duelspace.space
        yield from self.pre_reveal.space.space
        yield from self.special.duels

    @property
    def resolving_duel(self):
        if self.pipeline.in_duel_phase:
            return self.pipeline._get_current_duel()
        return None

    def duel_position(self):
        """The series and zero-based public number of the currently resolving duel."""
        space = self.active_duelspace
        index = space.current_duel_index
        if self.pipeline.interrupt_space is not None and 0 <= index < len(space.space):
            return self.special, self.special.duels.index(space.space[index])
        return space, index

    def start_pre_reveal_declarations(self):
        self.pre_reveal.start()

    def open_turn(self):
        if self.turn_count == 0:
            self.start_battle()
        number = self.turn_count + 1
        if self.turn_number != number:
            self.turn_number = number
            self.turn_ending = False
            for player in self.players:
                for character in player.characters:
                    character.turn_state.clear()
            self.context.record("turn_opened", number=number)
            self.context.turn_entry_uses.clear()
            self.turn_history.clear()
            self.context.dispatch_pipeline("on_turn_limits_reset", source=None, target=None, side=None)

    def prepare_turn(self):
        self.open_turn()
        if self._prepared_turn == self.turn_count:
            return
        self._prepared_turn = self.turn_count
        for player in self.players:
            player.turn_common_cost_bonus, player.next_turn_common_cost = player.next_turn_common_cost, 0
            for char in player.characters:
                char.turn_duel_bonus, char.next_turn_duels = char.next_turn_duels, 0
        self.context.dispatch_pipeline("on_turn_prepared", turn_number=self.turn_number)

    def record_clash_result(self, character, result):
        self.turn_history.record_clash(self.duel_position(), character, result)

    def draw_phase(self):
        self.prepare_turn()
        self.context.record("turn_started", turn=self.turn_count + 1)
        self.cards_revealed = False
        self._drawing_players = iter(self.players)
        self._continue_drawing()

    def _continue_drawing(self):
        for player in self._drawing_players:
            if self.is_over:
                break
            self.pending_draw = player.draw_for_turn()
            if self.pending_draw is not None:
                return
        self._drawing_players = None

    def complete_draw(self, choice, bottom):
        if self.is_over or choice is None or choice is not self.pending_draw:
            raise ValueError("此次选牌已经结束。")
        self.pending_draw = None
        try:
            choice.settle(bottom)
        except InvalidBottomSelection:
            self.pending_draw = choice
            raise
        self._continue_drawing()

    def start_turn(self):
        self.prepare_turn()
        for player in sorted(self.players, key=lambda p: p is not self.first_player):
            player.reset_on_turn_start()

    def determine_first_player(self):
        self.prepare_turn()
        left, right = self.players
        while True:
            for player in self.players:
                player.calculate_speed()
                self.context.record("speed_rolled", player=player.name, speed=player.speed,
                                    members=tuple((c.name, c.speed) for c in player.characters if c.is_alive))
            if left.speed != right.speed:
                self.first_player = left if left.speed > right.speed else right
                self.context.record("initiative", player=self.first_player.name, side=self.first_player.side)
                return
            self.context.record("speed_tied")

    def switch_place_right(self):
        self.placing = next(
            (p for p in self.players if p is not self.placing and p not in self.ended_player),
            self.placing if self.placing not in self.ended_player else None,
        )

    def run_placement(self):
        self.placing = self.first_player
        self.placement_capacity = 1
        self.placed_this_window = 0

    @staticmethod
    def may_place_rear(card):
        owner = card.character
        if owner is None or not owner.is_alive:
            return False
        return bool(
            card.data.get("rear_duel")
            or owner.data.get("rear_duel")
            or owner.ability_permission("rear_duel") is not None
        )

    def legal_rear_placements(self):
        if self.placing is None or self.pre_reveal.phase != "idle":
            return {}
        side = self.placing.side
        result = {}
        for card in self.placing.cardspace.hand.content:
            if (card.destroyed or card.state == CardState.NEGATED
                    or card.player is not self.placing or not card.character.is_alive
                    or not card.meets_use_requirements() or not self.may_place_rear(card)):
                continue
            slots = [
                idx for idx, slot in enumerate(self.duelspace.space)
                if slot.can_accept_rear(side)
                and (any(c.character is card.character for c in slot.all_side_cards(side))
                     or card.character.used_duels < card.character.max_duels)
            ]
            if slots:
                result[card] = slots
        return result

    def legal_placements(self):
        if self.placing is None:
            return []
        return [card for card in self.placing.cardspace.hand.content
                if not card.destroyed and card.state != CardState.NEGATED
                and card.player is self.placing and card.character.is_alive
                and card.character.used_duels < card.character.max_duels
                and card.meets_use_requirements()]

    def submit_placement(self, player, card=None, *, after="continue", rear_duel_index=None):
        """Apply a seat's decision; return whether a card actually entered the slot."""
        if self.is_over or player is None or player is not self.placing:
            raise ValueError("当前不属于该玩家的常规置卡窗口。")
        if after not in ("continue", "pass", "end"):
            raise ValueError("未知的置卡后决定。")
        if card is None and (after == "continue" or after == "pass" and not self.placed_this_window):
            raise ValueError("先置入一张牌才能交出此次置卡权。")
        placed = False
        if card is not None:
            if rear_duel_index is not None:
                rear_legal = self.legal_rear_placements()
                if card not in rear_legal or rear_duel_index not in rear_legal[card]:
                    raise ValueError("这张手牌当前无法扣置到该后置交锋。")
                owner = card.character
                if not card.data.get("rear_duel") and not owner.data.get("rear_duel"):
                    if not owner.spend_ability_effect(owner.ability_permission("rear_duel")):
                        raise ValueError("当前无法开启后置交锋。")
                placed = self.place_in_duel(player.side, card, rear_duel_index, rear=True, regular=True)
            else:
                if card not in self.legal_placements():
                    raise ValueError("这张手牌当前无法扣置。")
                placed = self.auto_place_in_duel(player.side, card)
            self.placed_this_window += int(placed)
            if self.is_over:
                return placed
        if after != "continue" or not placed or self.placed_this_window >= self.placement_capacity:
            self.finish_placement_window(end=after == "end")
        return placed

    def finish_placement_window(self, *, end=False):
        if end:
            self.ended_player.append(self.placing)
        self.switch_place_right()
        self.placement_capacity = self.gamerule.PLACE_CAPACITY
        self.placed_this_window = 0

    def auto_place_in_duel(self, side, content):
        owner = content.character
        if self.pre_reveal.phase != "idle" or owner is None or owner.used_duels >= owner.max_duels:
            return False
        return self.place_in_duel(side, content, self.duelspace.locate_nearest_empty_duel(side))

    def sync_rear_duels(self, slot=None, side=None):
        slots = (slot,) if slot is not None else tuple(self.board_slots())
        sides = (side,) if side is not None else tuple(p.side for p in self.players)
        for s in slots:
            for sd in sides:
                s.sync_rear_validity(sd, self.context)

    def place_in_duel(self, side, content, duel_idx, *, special=False, queued=False, regular=False, rear=False):
        # Once regular placement closes, only an executing rule effect may insert a card.
        if self.pre_reveal.phase != "idle" and not special and not queued and not self.context.executions:
            return False
        player = content.player
        owner = content.character
        if player.side != side or duel_idx < 0 or not owner.is_alive:
            return False
        if any(content in slot.all_side_cards(side) for slot in self.board_slots()):
            return False
        zones = player.cardspace
        old_zone = next((zone for zone in zones.piles() if content in zone.content), None)
        event = dict(side=side, source=owner, card=content, lane="rear" if rear else "front")
        self.context.dispatch_pipeline("before_place", **event)
        if not owner.is_alive or content.state == CardState.NEGATED:
            return False
        if old_zone is not None and content not in old_zone.content:
            return False
        space = self.duelspace if special or queued or regular else self.active_duelspace
        if queued and ((content not in zones.hand.content and not content.temporary) or duel_idx >= len(space.space)
                       or not self.pipeline.can_join(space.space[duel_idx])):
            return False
        if rear and (duel_idx >= len(space.space) or not space.space[duel_idx].can_accept_rear(side)):
            return False
        with self.context.binding(special_placement=content if special else None,
                                  queued_placement=content if queued else None,
                                  regular_placement=regular,
                                  rear_placement=content if rear else None):
            placed = self.context.eval_block([side, duel_idx, content, OpCode.PLACE])
        if not placed or duel_idx >= len(space.space):
            return False
        slot = space.space[duel_idx]
        target_list = slot.get_rear_content(side) if rear else slot.get_content(side)
        if content not in target_list:
            return False
        event["duel"] = slot
        self.context.dispatch_pipeline("on_place", **event)
        self.context.dispatch_pipeline("after_place", **event)
        return True

    def reveal_cards(self):
        if self.cards_revealed:
            return
        self.cards_revealed = True
        if not self.duelspace.space:
            self.context.record("empty_board")
            return
        revealed = []
        for number, slot in enumerate(self.duelspace.space, 1):
            sides = {p.side: [] for p in self.players}
            for p in self.players:
                for card in slot.all_side_cards(p.side):
                    if card.state == CardState.PLACED_FACE_DOWN:
                        card.state = CardState.PLACED_FACE_UP
                        sides[p.side].append(card.id)
            revealed.append({"number": number, "sides": sides})
        self.context.record("cards_revealed", duels=revealed)
        for slot in self.duelspace.space:
            for player in sorted(self.players, key=lambda p: p is not self.first_player):
                for card in tuple(slot.get_content(player.side)):
                    if card.character.is_alive and not card.destroyed and card.state != CardState.NEGATED:
                        self.context.dispatch_pipeline("on_card_reveal", source=card.character, side=player.side,
                                                       card=card, duel=slot, lane="front")
                self.sync_rear_duels(slot, player.side)
                for card in tuple(slot.get_rear_content(player.side)):
                    if card.character.is_alive and not card.destroyed and card.state != CardState.NEGATED:
                        self.context.dispatch_pipeline("on_card_reveal", source=card.character, side=player.side,
                                                       card=card, duel=slot, lane="rear")
        for number, slot in enumerate(self.duelspace.space, 1):
            sides = tuple((p.name, tuple(card.name for card in slot.all_side_cards(p.side))) for p in self.players)
            self.context.record("slot_revealed", number=number, sides=sides)

    def finish_turn(self):
        if not self.turn_ending:
            self.context.dispatch_pipeline("before_turn_end")
        if self.is_over or self.special.decision_owner is not None:
            return
        ordered = sorted(self.players, key=lambda player: player is not self.first_player)
        for player in ordered:
            for character in player.characters:
                if character.is_alive and not self.is_over:
                    character.on_turn_end()
        for player in ordered:
            for character in player.characters:
                if not character.data.get("retain_shields"):
                    character.reset_shields()
                character.expire_die_responses(self.turn_number)
                character.used_duels = 0
                character.turn_duel_bonus = 0
                for status in self.turn_end_statuses:
                    character.clear_status(status)
                character.expire_turn_abilities()
                character.check_death()
            player.turn_common_cost_bonus = 0
            self.context.eval_block([player, 0, 0, OpCode.RESET_COST])

        on_board = [card for slot in self.board_slots() for card in slot.all_cards()]
        remaining = set(on_board)
        used = set(self.used_cards)
        recycled = {p.side: {"side": p.side, "used_count": 0, "board_count": 0} for p in self.players}
        for card in [*self.used_cards, *on_board]:
            if card in remaining and card.character.is_alive:
                remaining.remove(card)
                recycled[card.player.side]["used_count" if card in used else "board_count"] += 1
                if card in used:
                    # Turn-end entries run after recycling; keep this use's caster
                    # and local state even if the physical card is returned to its owner.
                    self.context.withdraw_card_use(card, None, used=True, scopes=("turn",))
                card.return_to_printed_owner()
                card.home_deck.add_card(card)
        for player in self.players:
            recycled[player.side]["discard_count"] = len(player.cardspace.delayed_discard.content)
            player.cardspace.delayed_discard.push_to_draw()
        self.used_cards.clear()
        self.duelspace.space.clear()
        self.duelspace.current_duel_index = 0
        self.pre_reveal = PreRevealPhase(self)
        self.special.clear()
        self.ended_player.clear()
        self.cards_revealed = False
        self.turn_count += 1
        self.context.record("turn_ended", turn=self.turn_count, recycled=list(recycled.values()))
        self.check_game_over()

    def init_dice(self, data):
        from models.dice import Dice
        return Dice(data, game=self)

    def check_game_over(self):
        if self.is_over:
            return True
        alive = [p for p in self.players if any(c.is_alive for c in p.characters)]
        if len(alive) == len(self.players):
            return False
        self.is_over = True
        self.winner = alive[0] if alive else None
        self.pipeline.end_battle()
        return True
