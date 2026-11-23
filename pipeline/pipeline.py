from collections import deque
from contextlib import contextmanager
from weakref import WeakSet

from models.card import CardState
from models.duel import ClashPair, DuelSpace
from models.opcode import OpCode
from models.pack_types import PackType
from . import combat_steps as steps
from .pipeline_errors import PipelineFinished


BEFORE_ONE_SIDED_ATTACK = "before_one_sided_attack"


class DuelEnded(Exception):
    """An effect ended the currently executing slot between combat nodes."""


class SidePipeline:
    """Only a dispatched packet or an explicit release can resume a waiting side."""

    def __init__(self, side, game=None):
        self.side = side
        self.game = game
        self.queue = deque()
        self.current_node = None
        self.blocked_at = None
        self.card = None
        self.die = None
        self.paid = None
        self.payment = None
        self.withdrawn = False
        self.used = False
        self.opposing_card = None
        self.range_pairing = None
        self.target = None
        self.is_response = False

    @property
    def current_pack_type(self):
        node = self.blocked_at or (self.queue[0] if self.queue else None)
        return node.pack_type if node else PackType.NONE

    def push_pack(self, packet):
        self.unblock()
        self.queue.extendleft(reversed(packet))

    def unblock(self):
        self.blocked_at = None

    def is_blocked_at(self, node_id):
        return self.blocked_at is not None and self.blocked_at.id == node_id

    def step(self):
        if self.blocked_at or not self.queue:
            raise RuntimeError("试图推进等待中或队列为空的阵营")
        self.current_node = self.queue.popleft()
        if self.current_node.is_wait:
            self.blocked_at = self.current_node
        return self.current_node


class CombatFrame:
    """One resumable sequence of duels, including its currently bound card and die scopes."""

    def __init__(self, space, players, *, interrupt):
        self.space = space
        self.interrupt = interrupt
        self.sides = {p.side: SidePipeline(p.side, space.game) for p in players}
        self.pair = None
        self.results = {}
        self.started = False
        self.round_id = 0
        self.before_use_sides = set()
        self.move_after_die = {}
        self.pairing_copies = {}
        self.active_cards = {}
        self.active_dice = {}
        self.runner = None
        self.parent_round_triggers = {}
        self.suspended_skills = {p.side: [] for p in players}


class Pipeline:
    def __init__(self, game=None, step_list=None):
        self.game = game
        self.pause_on_clash_scores = False
        self.step_list = [node.bind(game) for node in (step_list or ())]
        self.current_step_index = -1
        self.is_finished = False
        self._frames = []
        self._rounds_started = 0
        self._closed_slots = WeakSet()
        self._pending_special_duels = []

    @property
    def in_duel_phase(self):
        return bool(self._frames)

    @property
    def _frame(self):
        return self._frames[-1]

    @property
    def side_pipelines(self):
        return self._frame.sides if self._frames else {}

    @property
    def current_clash_pair(self):
        return self._frame.pair if self._frames else None

    @property
    def current_clash_results(self):
        return self._frame.results if self._frames else {}

    @property
    def round_id(self):
        return self._frame.round_id if self._frames else self._rounds_started

    @property
    def interrupt_space(self):
        return self._frame.space if self._frames and self._frame.interrupt else None

    def suspended_uses(self):
        """Describe the paused plays from the outermost duel to the active insertion."""
        parent = None
        for frame in self._frames:
            index = frame.space.current_duel_index
            slot = frame.space.space[index] if 0 <= index < len(frame.space.space) else None
            if slot and frame.interrupt:
                side = slot.attacking_side
                pipe = parent.sides[side] if parent else None
                if parent and (pipe.card is None or pipe.die is None):
                    pipe = next((p for p in parent.sides.values() if p.die is not None), pipe)
                card = slot.trigger_card or (pipe.card if pipe else None)
                die = slot.trigger_die or (pipe.die if pipe and pipe.card is card else None)
                yield parent.space if parent else None, card, die, slot.trigger_name or slot.attack_card.name
            for stack in frame.suspended_skills.values():
                for paused, _, die in stack:
                    yield frame.space, paused.card, die, None
            parent = frame

    @property
    def before_duel_start(self):
        return bool(self._frames and not self._frame.started and any(
            pipe.current_node and pipe.current_node.id == "before_duel_start"
            for pipe in self.side_pipelines.values()))

    def next_step(self):
        if self.in_duel_phase or (self._pending_special_duels and not self.game.is_over):
            return self.step_duel_combat()
        if self.is_finished or self.current_step_index + 1 >= len(self.step_list):
            self.is_finished = True
            raise PipelineFinished("回合管线结束", step_index=self.current_step_index)
        node = self.step_list[self.current_step_index + 1]
        if node.ready is not None and not node.ready(node):
            return "wait_" + node.id.removeprefix("logic_")
        self.current_step_index += 1
        node.execute()
        return node.id

    def _get_current_duel(self):
        space = self._frame.space
        if 0 <= space.current_duel_index < len(space.space):
            return space.space[space.current_duel_index]
        return None

    def resolve_skill_target(self, card):
        """Choose once when a skill reads its target before its first solo attack."""
        if card is None:
            return None
        pipe = self.side_pipelines.get(card.player.side)
        if pipe is None or pipe.card is not card:
            return None
        if pipe.target is None or not pipe.target.is_alive:
            pipe.target = self._get_current_duel().resolve_target_character(
                pipe.side, self.current_clash_pair, pipe.opposing_card)
        return pipe.target

    def next_planned_die(self, target):
        """The next concrete die belonging to this target, in the order already on the board."""
        if target is None or not target.is_alive:
            return None
        spaces = [frame.space for frame in reversed(self._frames)]
        if self.game.pre_reveal.phase == "resolving":
            spaces.append(self.game.pre_reveal.space)
        spaces.append(self.game.duelspace)
        for space in dict.fromkeys(spaces):
            for slot in space.space[space.current_duel_index:]:
                if self.can_join(slot):
                    die = next(self._planned_slot_dice(slot, target), None)
                    if die is not None:
                        return die
        return None

    def _planned_slot_dice(self, slot, target):
        side = target.player.side
        cards = slot.get_content(side)[slot.current_card_index.get(side, 0):]
        cards.extend(card for card in slot.dice_tails if card.player.side == side and slot.tail_is_live(card))
        anchored = {}
        for card in cards:
            anchor = card.use_state.get("die_anchor")
            if anchor:
                anchored.setdefault(anchor, []).append(card)
        visited = set()

        def uses(card):
            if card in visited or card.destroyed or not card.character.is_alive or card.state == CardState.NEGATED:
                return
            visited.add(card)
            bound = self._bound_use(slot, card)
            pipe = bound[1] if bound else None
            if pipe and pipe.paid is False:
                return
            current = pipe.die if pipe else None
            after_current = current is not None and (current.clash_result is not None
                                                     or not pipe.is_blocked_at(steps.NEXT_DIE))
            if after_current:
                for child in anchored.get(("after_die", current), ()):
                    yield from uses(child)
            if card.character is not target and not anchored:
                return
            for die in card.planned_dice(self.game, after_current=after_current):
                for child in anchored.get(("before_die", die), ()):
                    yield from uses(child)
                if card.character is target:
                    yield die
                for child in anchored.get(("after_die", die), ()):
                    yield from uses(child)

        for card in cards:
            if not card.use_state.get("die_anchor"):
                yield from uses(card)
        # Anchors whose die was already destroyed fall back to ordinary slot order.
        for card in cards:
            if card not in visited:
                yield from uses(card)

    def start_duel_combat(self):
        if self.in_duel_phase:
            raise RuntimeError("交锋已经开始")
        self._push_combat(self.game.active_duelspace, interrupt=False)

    def start_special_duel(self, slot):
        self.start_special_duels([slot])

    def queue_special_duels(self, slots):
        """Hooks finish in their originating frame; the next step starts their attacks in order."""
        self._pending_special_duels.extend(slots)

    def release_temporary_skills(self, slot):
        for cards in slot.content.values():
            for card in tuple(cards):
                if card.temporary:
                    if not self.game.is_over and card in self.game.used_cards:
                        self.game.context.withdraw_card_use(card, slot, used=True, scopes=("turn",))
                    slot.remove_card(card)
                    card.dissolve()

    def end_battle(self):
        self._pending_special_duels.clear()
        for slot in self.game.board_slots():
            self.release_temporary_skills(slot)

    def start_special_duels(self, slots):
        """Suspend the current turn or duel and resolve this group in declaration order."""
        slots = list(slots)
        if not slots or len(set(slots)) != len(slots):
            raise ValueError("请提供一组未重复的即时交锋。")
        for slot in slots:
            if not slot.ready or slot in self._closed_slots:
                raise ValueError("即时交锋尚未就绪或已结算。")
            if any(slot in f.space.space for f in self._frames):
                raise ValueError("该交锋正在结算。")
        space = DuelSpace(self.game)
        for slot in slots:
            space.append_new_duel(slot)
        self._push_combat(space, interrupt=True)

    def _push_combat(self, space, *, interrupt):
        frame = CombatFrame(space, self._ordered_players(), interrupt=interrupt)
        if interrupt:
            for player in self.game.players:
                for char in player.characters:
                    frame.parent_round_triggers[char] = char.round_triggers
                    char.begin_dice_round()
        self._frames.append(frame)
        self.game.context.active_cards = frame.active_cards
        self.game.context.active_dice = frame.active_dice
        frame.runner = self._duels()

    def can_join(self, slot):
        return slot not in self._closed_slots

    def defer_remaining_dice(self, card, destination):
        if card is None or not self.in_duel_phase:
            return False
        space = self._frame.space
        if destination not in space.space[space.current_duel_index + 1:]:
            return False
        pipe = self.side_pipelines[card.player.side]
        if pipe.card is not card or not self._die_live(pipe):
            return False
        self._frame.move_after_die[card] = destination
        return True

    def pair_skill_copy(self, card, sample):
        from models.special_actions import SkillCopy

        if not self.in_duel_phase or card is None or not isinstance(sample, SkillCopy):
            return False
        slot = self._get_current_duel()
        if (not self.in_use(slot, card) or card in self._frame.pairing_copies
                or not sample.owner.is_alive or sample.owner.player is card.player or not sample.data.get("dice")):
            return False
        rival = sample.instantiate()
        side = rival.player.side
        cards = slot.content.setdefault(side, [])
        index = slot.current_card_index.get(side, 0)
        if index < len(cards) and cards[index] is self.side_pipelines[side].card:
            index += 1
        cards.insert(index, rival)
        self._frame.pairing_copies[card] = rival
        return True

    def insert_skill(self, use, anchor, event):
        """Commit the physical card; only its own side changes its use order."""
        at = anchor.get("at") if isinstance(anchor, dict) else anchor
        subject = anchor.get("target") if isinstance(anchor, dict) else None
        if isinstance(anchor, dict) and "target" in anchor and subject is None:
            return False
        card = use.card
        side = card.player.side
        if self.game.is_over or not card.character.is_alive or card.character.skill_restricted(card):
            return False
        if not card.temporary and card not in self.game.special.own_hand_skills(card.character):
            return False
        if at == "immediate_attack":
            if not any(subject in player.characters for player in self.game.players if player is not card.player):
                return False
            if not subject.is_alive:
                return False
            use.set_price()
            self.game.special.declare_field_attack(card, subject, deferred=True)
            return True
        if at == "slot_tail":
            slot = subject or event.get("duel")
        else:
            if at not in ("before_die", "after_die", "before_skill", "after_skill"):
                raise ValueError(f"未知的技能插入位置 {at!r}")
            is_die = at.endswith("_die")
            subject = subject or event.get("die" if is_die else "card")
            parent = getattr(subject, "card", None) if is_die else subject
            slot = next((s for s in self.game.board_slots() if parent in s.get_content(side)), None)
            if slot is None or parent.destroyed:
                return False
            index = slot.get_content(side).index(parent)
            if index < slot.current_card_index.get(side, 0):
                return False
            if is_die:
                instances = parent.instantiated_dice or ()
                if subject not in instances[parent.current_dice_index:]:
                    return False
                pipe = self.side_pipelines.get(side)
                if at == "before_die" and pipe is not None and pipe.die is subject:
                    return False
            elif at == "before_skill" and self.in_use(slot, parent):
                return False
        if slot is None or not self.can_join(slot):
            return False
        active = self.game.active_duelspace
        regular = slot in self.game.duelspace.space
        space = self.game.duelspace if regular else active
        if slot not in space.space:
            return False
        if not self.game.place_in_duel(side, card, space.space.index(slot), queued=regular):
            return False
        use.set_price()
        if at == "slot_tail":
            return True
        cards = slot.get_content(side)
        if at.endswith("_die"):
            card.use_state["die_anchor"] = (at, subject)
        elif parent in cards:
            cards.remove(card)
            index = cards.index(parent)
            if at == "after_skill":
                index += 1
                while index < len(cards) and cards[index].use_state.get("after_skill_anchor") is parent:
                    index += 1
                card.use_state["after_skill_anchor"] = parent
            cards.insert(index, card)
        return True

    def _start_inserted(self, slot, pipes, side, die, at):
        cards = slot.get_content(side)
        batch = [card for card in cards if card.use_state.get("die_anchor") == (at, die)
                 and not card.destroyed and card.character.is_alive]
        if not batch:
            return False
        for card in batch:
            card.use_state.pop("die_anchor")
            cards.remove(card)
        index = slot.current_card_index.get(side, 0)
        cards[index:index] = batch
        parent = self.side_pipelines[side]
        self._frame.suspended_skills[side].append((parent, batch, die))
        child = SidePipeline(side, self.game)
        child.blocked_at = steps.SKILL[-1]
        self._frame.sides[side] = child
        pipes[pipes.index(parent)] = child
        self._frame.active_cards.pop(side, None)
        self._frame.active_dice.pop(side, None)
        return True

    def _resume_inserted(self, slot, pipes):
        resumed = False
        for index, pipe in enumerate(pipes):
            pending = self._frame.suspended_skills[pipe.side]
            if not pending or pipe.card is not None or not pipe.is_blocked_at(steps.NEXT_CARD):
                continue
            parent, batch, _ = pending[-1]
            if slot.next_playable_card(pipe.side) in batch:
                continue
            pending.pop()
            pipes[index] = self._frame.sides[pipe.side] = parent
            if self._card_live(parent):
                self._frame.active_cards[pipe.side] = parent.card
            resumed = True
        return resumed

    def _bound_use(self, slot, card):
        side = card.player.side
        for frame in reversed(self._frames):
            pos = frame.space.current_duel_index
            if pos >= len(frame.space.space) or frame.space.space[pos] is not slot:
                continue
            active = frame.sides[side]
            if active.card is card and not active.withdrawn:
                return frame, active
            for suspended, _, _ in reversed(frame.suspended_skills[side]):
                if suspended.card is card and not suspended.withdrawn:
                    return frame, suspended
        return None

    def can_replace(self, slot, card):
        side = card.player.side
        if not self.can_join(slot) or not card.character.is_alive or card.destroyed or card.state == CardState.NEGATED:
            return False
        if card not in slot.get_content(side)[slot.current_card_index.get(side, 0):]:
            return False
        if binding := self._bound_use(slot, card):
            pipe = binding[1]
            return pipe.paid is not False and pipe.current_node.id not in ("after_skill_use", steps.NEXT_CARD)
        return True

    def before_use(self, slot, card):
        return (bool(self._frames) and card.player.side in self._frame.before_use_sides
                and slot is self._get_current_duel() and slot.get_current_card(card.player.side) is card)

    def in_use(self, slot, card):
        return self._bound_use(slot, card) is not None

    def withdraw_skill(self, slot, card):
        """Invalidate this use even if the same physical card is immediately played again."""
        side = card.player.side
        if binding := self._bound_use(slot, card):
            frame, pipe = binding
            pipe.withdrawn = True
            self.game.context.withdraw_card_use(card, slot, pipe.used)
            self.game.context.close_cancelled_use(side, card=card, die=pipe.die)
            if frame.active_cards.get(side) is card:
                frame.active_cards.pop(side)
            if frame.active_dice.get(side) is pipe.die:
                frame.active_dice.pop(side, None)

    def retire_moved_skill(self, slot, card):
        """Keep a departing use's lasting entries bound to their original slot or turn."""
        if self.in_use(slot, card):
            self.withdraw_skill(slot, card)
        elif card in self.game.used_cards:
            self.game.context.withdraw_card_use(card, slot, used=True)
            if slot in self._closed_slots:
                self.game.context.expire_lasting_entries(slot)

    def step_duel_combat(self):
        if not self.game.is_over:
            if self._pending_special_duels:
                slots, self._pending_special_duels = self._pending_special_duels, []
                self.start_special_duels(slots)
            try:
                return next(self._frame.runner)
            except StopIteration:
                pass
        finished = self._frames.pop()
        finished.runner.close()
        if self.game.is_over:
            while self._frames:
                self._frames.pop().runner.close()
        parent = self._frame if self._frames else None
        self.game.context.active_cards = parent.active_cards if parent else {}
        self.game.context.active_dice = parent.active_dice if parent else {}
        for char, triggers in finished.parent_round_triggers.items():
            char.round_triggers = triggers
        if not finished.interrupt and self.game.pre_reveal.phase == "resolving":
            self.game.pre_reveal.phase = "done"
        return ("FINISHED", "FINISHED")

    def _duels(self):
        space = self._frame.space
        pre_reveal = space is self.game.pre_reveal.space or self._frame.interrupt
        while (slot := self._get_current_duel()) is not None:
            if pre_reveal:
                self.game.context.record("duel_started", series="instant" if self._frame.interrupt else "pre_reveal",
                                         number=self.game.duel_position()[1] + 1)
                if not slot.prepare(self.game.pre_reveal):
                    self.game.context.record("duel_skipped")
                    self.release_temporary_skills(slot)
                    self._closed_slots.add(slot)
                    space.current_duel_index += 1
                    continue
            for pipe in self.side_pipelines.values():
                pipe.opposing_card = pipe.target = None
            pipes = [p for p in self.side_pipelines.values() if slot.next_combat_card(p.side)]
            if pipes:
                if not pre_reveal:
                    self.game.context.record("duel_started", series="regular", number=space.current_duel_index + 1)
                self._frame.started = False
                try:
                    yield from self._play_slot(slot, pipes)
                except DuelEnded:
                    slot.end_requested = False
                    for pipe in pipes:
                        self.game.context.close_cancelled_use(pipe.side, pipe.card, pipe.die)
                        pipe.queue.clear()
                        pipe.push_pack(steps.DUEL_END)
                    self._frame.pair = None
                    self._frame.results = {}
                    yield from self._run_to(pipes, steps.NEXT_DUEL)
                    for cards in slot.content.values():
                        for card in cards:
                            card.set_range_opponent(None)
                self.game.context.expire_lasting_entries(slot)
            self.release_temporary_skills(slot)
            self._closed_slots.add(slot)
            space.current_duel_index += 1

    def _ordered_players(self):
        return sorted(self.game.players, key=lambda p: p is not self.game.first_player)

    def _play_slot(self, slot, pipes):
        for pipe in pipes:
            pipe.push_pack(steps.DUEL)
        yield from self._run_to(pipes, steps.NEXT_CARD)

        while True:
            if self._resume_inserted(slot, pipes):
                yield from self._start_skills(pipes, [])
            # The remaining die waits here while its opponent changes skills.
            # A side with no skill left is idle, so it cannot block a solo die.
            # An effect may have placed a skill for a previously empty side.
            joiners = [p for p in self.side_pipelines.values()
                       if p not in pipes and slot.next_combat_card(p.side)]
            if joiners:
                for pipe in joiners:
                    pipe.push_pack(steps.DUEL)
                yield from self._run_to(joiners, steps.NEXT_CARD)
                pipes[:] = [p for p in self.side_pipelines.values() if p in pipes or p in joiners]
            entering = [p for p in pipes if p.is_blocked_at(steps.NEXT_CARD) and slot.next_combat_card(p.side)]
            if entering:
                frame = self._frame
                frame.before_use_sides = {p.side for p in entering
                                          if slot.get_current_card(p.side) is not None
                                          and slot.get_current_card(p.side) not in frame.pairing_copies.values()}
                if frame.before_use_sides:
                    yield tuple("before_skill_choice" if p.side in frame.before_use_sides else None
                                for p in self.game.players)
                frame.before_use_sides.clear()
                declared_target = None
                attack = None
                defender = None
                if len(entering) == 1 and any(e.trigger == "before_unopposed_ranged_skill" for e in self.game.context.entries):
                    attack = next(slot.playable_cards(entering[0].side), None)
                    if attack and attack.effective_range:
                        defender = self.side_pipelines[self.game.pre_reveal.opponent(attack.player).side]
                if defender and not slot.next_combat_card(defender.side, advance=False):
                    declared_target = slot.resolve_target_character(attack.player.side)
                    self.game.context.dispatch_pipeline("before_unopposed_ranged_skill", source=attack.character,
                                                        card=attack, target=declared_target, duel=slot, side=attack.player.side)
                    if slot.next_combat_card(defender.side, advance=False):
                        if defender not in pipes:
                            defender.push_pack(steps.DUEL)
                            yield from self._run_to([defender], steps.NEXT_CARD)
                            pipes.append(defender)
                            pipes.sort(key=lambda p: p.side != self.game.first_player.side)
                        entering.append(defender)
                entrants = []
                for pipe in entering:
                    card = slot.next_combat_card(pipe.side)
                    if card is None:
                        continue
                    pipe.card = card
                    pipe.paid = None
                    pipe.payment = None
                    pipe.withdrawn = pipe.used = False
                    pipe.opposing_card = None
                    inherited_target = None
                    if frame.suspended_skills[pipe.side]:
                        parent_pipe, batch, _ = frame.suspended_skills[pipe.side][-1]
                        if card in batch:
                            cand = parent_pipe.target or (
                                parent_pipe.opposing_card.character if parent_pipe.opposing_card is not None else None
                            )
                            if cand is not None and cand.is_alive:
                                inherited_target = cand
                    pipe.target = (declared_target if card is attack and declared_target is not None else
                                   inherited_target if inherited_target is not None else
                                   slot.resolve_target_character(pipe.side)
                                   if frame.interrupt or frame.space is self.game.pre_reveal.space else None)
                    if card in frame.pairing_copies.values() or slot.tail_is_live(card):
                        pipe.paid = pipe.used = True
                        frame.active_cards[pipe.side] = card
                        pipe.push_pack(steps.REMAINING_SKILL)
                        pipe.step()
                        continue
                    pipe.push_pack(steps.SKILL)
                    entrants.append(pipe)
                yield from self._start_skills(pipes, entrants)
                # Skill-use effects can insert a card into an empty opposing side.
                # Let it reach its first die before pairing this round.
                continue

            ready, spent = [], []
            for pipe in pipes:
                if pipe.is_blocked_at(steps.NEXT_DIE):
                    pipe.die = self._next_live_die(pipe)
                    (ready if pipe.die is not None else spent).append(pipe)
            if spent:
                for pipe in spent:
                    copy = self._frame.pairing_copies.pop(pipe.card, None)
                    if copy is not None:
                        copy.dissolve()
                yield from self._run_to(spent, steps.NEXT_CARD)
                for pipe in spent:
                    if not pipe.withdrawn:
                        slot.finish_card(pipe.side, pipe.card)
                    pipe.card = pipe.die = None
                continue
            if not ready:
                break

            inserted = [self._start_inserted(slot, pipes, p.side, p.die, "before_die") for p in ready]
            if any(inserted):
                continue

            # Refill both sides before forming a pair. A rejected die consumes no
            # round and gives neither side a clash or skip result.
            live = [p for p in ready if not p.die.destroyed]
            if not self._pay_dice_costs(live):
                continue

            for pipe in live:
                pipe.die.register_entries()
            yield from self._play_round(live)
            for pipe in ready:
                die = pipe.die
                if self._card_live(pipe):
                    pipe.card.advance_die()
                destination = self._frame.move_after_die.pop(pipe.card, None)
                if destination is not None and self._card_live(pipe) and pipe.card.has_next_die():
                    destination.dice_tails[pipe.card] = slot.dice_tails.get(
                        pipe.card, (slot, pipe.card.instantiated_dice))
                    slot.finish_card(pipe.side, pipe.card)
                    pipe.withdrawn = True
                pipe.die = None
                self._start_inserted(slot, pipes, pipe.side, die, "after_die")
            self._frame.pair = None
            self._frame.results = {}

        self._closed_slots.add(slot)
        yield from self._run_to(pipes, steps.NEXT_DUEL)
        for cards in slot.content.values():
            for card in cards:
                card.set_range_opponent(None)

    def _start_skills(self, pipes, entrants):
        current = [p for p in pipes if self._card_live(p)]
        for pipe in entrants:
            pipe.card.use_effects_resolved = False
        for pipe in current:
            pipe.card.set_range_opponent(None)
            pipe.range_pairing = None
        if len(current) == 2:
            far, near = current
            far_range, near_range = far.card.paired_ranges(near.card)
            if near_range > far_range:
                far, near = near, far
                far_range, near_range = near_range, far_range
            far.opposing_card, near.opposing_card = near.card, far.card
            if far_range > near_range + near.card.effective_ignore_range:
                # A card must actually pay before it can blank the opposing
                # pre-use and fee entries. Its price hooks can still alter or cancel payment.
                if far in entrants:
                    yield from self._run_to([far], "logic_skill_use")
                if far.paid and self._card_live(far) and self._card_live(near):
                    self._refresh_skill_range(near, far.card)
            pending = [p for p in entrants if p.paid is None]
            if pending:
                yield from self._run_to(pending, "logic_skill_use")
            if all(p.paid and self._card_live(p) for p in current):
                # Paying can remove a condition for range or immunity, including
                # reversing which side has the advantage before on-use effects.
                self._refresh_skill_range(far, near.card)
                self._refresh_skill_range(near, far.card)
        yield from self._run_to(entrants, steps.NEXT_DIE)

    def _refresh_skill_range(self, pipe, opponent):
        card = pipe.card
        signature = (opponent, card.effective_range, opponent.effective_range, card.effective_ignore_range)
        if pipe.range_pairing == signature:
            return
        pipe.range_pairing = signature
        card.set_range_opponent(opponent, own_range=signature[1], opposing_range=signature[2],
                                ignore_range=signature[3])
        if card.range_deficit:
            self.game.context.record("range_advantage", card=opponent.name, opposing=card.name, amount=card.range_deficit)

    def _card_live(self, pipe):
        return (pipe.card is not None and not pipe.withdrawn and pipe.card.character.is_alive
                and not pipe.card.destroyed and pipe.card.state != CardState.NEGATED
                and (pipe.is_response or pipe.card in self._get_current_duel().get_content(pipe.side)
                     or self._get_current_duel().tail_is_live(pipe.card)))

    def _die_live(self, pipe):
        return self._card_live(pipe) and pipe.die is not None and not pipe.die.destroyed

    def _next_live_die(self, pipe):
        if self._card_live(pipe) and pipe.paid:
            while (die := pipe.card.get_current_die(self.game, register=False)) is not None:
                if not die.destroyed or die.keep_position:
                    return die
                pipe.card.advance_die()
        return None

    def _pay_dice_costs(self, ready):
        skipping = any(p.die.type == "skip" for p in ready)
        for p in sorted(ready, key=lambda pipe: pipe.card.player is not self.game.first_player):
            if not self._die_live(p):
                return False
            if not p.die.data.get("resource_cost") or p.die.resource_paid:
                continue
            with self.game.context.binding(**self._event(p)):
                other = next((pipe.die for pipe in ready if pipe is not p), None)
                if other is None and p.die.can_attack_alone:
                    other = self._pending_response_die(p)
                paid = self._pay_die_against(p.die, other, skipping=skipping)
            if not paid:
                if self._die_live(p):
                    self.game.context.record("die_unpaid", card=p.card.name, position=p.die.position)
                    p.card.skip_unpaid_die()
                return False
        # A later payment may destroy an earlier paid die. Nothing has paired yet.
        return all(self._die_live(p) for p in ready)

    def _pay_die_against(self, die, opponent, *, skipping=False):
        if not die.data.get("resource_cost") or die.resource_paid:
            return True
        with self._die_range(die, opponent):
            return die.can_afford_use() if skipping else die.pay_use_cost()

    @staticmethod
    @contextmanager
    def _die_range(die, opponent):
        if opponent is None:
            yield
            return
        card = die.card
        previous = card.range_opponent, card.range_deficit
        try:
            card.set_range_opponent(opponent.card, own_range=die.effective_range,
                                    opposing_range=opponent.effective_range,
                                    ignore_range=die.effective_ignore_range)
            yield
        finally:
            card.range_opponent, card.range_deficit = previous

    def _play_round(self, ready):
        self._rounds_started += 1
        self._frame.round_id = self._rounds_started
        for player in self._ordered_players():
            for char in player.characters:
                if char.is_alive:
                    char.begin_dice_round()

        if len(ready) == 2:
            a, b = ready
            a.opposing_card, b.opposing_card = b.card, a.card
            a.target, b.target = b.card.character, a.card.character
        for pipe in ready:
            if pipe.range_pairing:
                self._refresh_skill_range(pipe, pipe.range_pairing[0])
        if any(p.die.type == "skip" for p in ready):
            self.game.context.record("round_skipped", reason="printed")
            for pipe in ready:
                pipe.die.clash_result = "skip"
                pipe.push_pack(steps.SKIPPED_DICE)
            yield from self._run_to(ready, steps.NEXT_DIE)
            return

        # A die's range lasts through its whole use (including additional hits),
        # then the two skills resume their original relationship.
        saved_ranges = []
        if any(p.die.effective_range != p.card.effective_range
               or p.die.effective_ignore_range != p.card.effective_ignore_range for p in ready):
            for pipe in ready:
                other = next((p for p in ready if p is not pipe), None)
                opposing = other.card if other else pipe.opposing_card
                if opposing is None:
                    continue
                card = pipe.card
                saved_ranges.append((pipe, card, card.range_opponent, card.range_deficit))
                card.set_range_opponent(opposing, own_range=pipe.die.effective_range,
                                        ignore_range=pipe.die.effective_ignore_range,
                                        opposing_range=other.die.effective_range if other else opposing.effective_range)
        try:
            yield from self._pair_dice(ready)
        finally:
            for pipe, card, opponent, deficit in saved_ranges:
                if pipe.card is card and not pipe.withdrawn:
                    card.range_opponent, card.range_deficit = opponent, deficit

    def _pair_dice(self, ready):
        solo = len(ready) == 1 and ready[0].die.can_attack_alone
        attempted_responses = set()
        response = self._pending_response_die(ready[0]) if solo else None
        for pipe in ready:
            blanks = pipe.card.range_deficit >= 3 or solo and pipe.card.range_deficit >= 2
            if blanks and response is None:
                pipe.die.make_blank()
        for pipe in ready:
            if pipe.die.is_attack and (len(ready) == 2 or solo) and self._die_live(pipe):
                with self._die_range(pipe.die, response):
                    self.game.context.dispatch_pipeline("before_dice_pair", **self._event(pipe))
        routed = any(p.die.attack_redirected for p in ready)
        if routed:
            for pipe in ready:
                if pipe.card.range_deficit >= 2 and pipe.die.is_attack and not self._reserved_target(pipe):
                    pipe.die.make_blank()
        if solo and ready[0].die.can_attack_alone:
            attacker = ready[0]
            target = self._reserved_target(attacker)
            if target and (yield from self._contest_solo(attacker, target, start_attacker=True,
                                                        attempted=attempted_responses)):
                return
        can_pair = len(ready) == 2 and not routed and not all(p.die.is_passive for p in ready)
        if can_pair:
            self._frame.pair = ClashPair({p.side: p.die for p in ready})
        active = []
        stops = {}
        for pipe in ready:
            die = pipe.die
            if can_pair or (die.can_attack_alone and (not die.attack_redirected
                                                     or die.attack_target and die.attack_target.is_alive)):
                pipe.push_pack(steps.DICE)
                active.append(pipe)
                stops[pipe.side] = steps.CAN_CLASH
            else:
                die.clash_result = "skip"
                pipe.push_pack(steps.SKIPPED_DICE)
                stops[pipe.side] = steps.NEXT_DIE
        if not active:
            self.game.context.record("round_skipped", reason="passive")
        yield from self._run_to(ready, stops)
        if can_pair:
            yield from self._clash(active)
        else:
            for pipe in active:
                if self._die_live(pipe):
                    yield from self._solo(pipe, attempted=attempted_responses if solo else None)
        yield from self._run_to(active, steps.NEXT_DIE)

    def _reserved_target(self, pipe):
        def eligible(actor):
            return actor and actor.is_alive and actor.available_die_responses(
                BEFORE_ONE_SIDED_ATTACK, self.game.turn_number)

        if not any(eligible(actor) for player in self.game.players if player.side != pipe.side
                   for actor in player.characters):
            return None
        if pipe.die.attack_redirected:
            target = pipe.die.attack_target
        else:
            target = self.resolve_skill_target(pipe.card)
        return target if eligible(target) else None

    def _pending_response_die(self, attacker):
        """Preview the first enabled offer. Pairing settles its actual price, including price hooks."""
        target = self._reserved_target(attacker)
        if target is None:
            return None
        for response in target.available_die_responses(BEFORE_ONE_SIDED_ATTACK, self.game.turn_number):
            die = response.template.create_die(self.game, target)
            if die is not None:
                return die
        return None

    def _accept_die_response(self, attacker, target, trigger, *, attempted=None):
        for response in target.available_die_responses(trigger, self.game.turn_number):
            if not target.is_alive:
                break
            if response not in target.reserved_dice or not response.available(trigger, self.game.turn_number):
                continue
            if attempted is not None:
                if response in attempted:
                    continue
                attempted.add(response)
            response.pending = True
            try:
                response.spend("attempt")
                die = response.template.create_die(self.game, target)
                if die is None:
                    continue
                if not self._pay_die_against(die, attacker.die) or not target.is_alive or die.destroyed:
                    die.card._release_dice()
                    continue
                response.spend("use")
                die.register_entries()
                return die
            finally:
                response.pending = False
                if response.remaining == 0 and response in target.reserved_dice:
                    target.reserved_dice.remove(response)
        return None

    def _contest_solo(self, attacker, target, *, start_attacker=False, attempted=None):
        # A response temporarily occupies one die position. It never enters a
        # card zone, triggers skill use, or advances the defending skill's cursor.
        die = self._accept_die_response(attacker, target, BEFORE_ONE_SIDED_ATTACK, attempted=attempted)
        if die is None:
            return False
        reply = SidePipeline(target.player.side, self.game)
        reply.card, reply.die = die.card, die
        reply.is_response = reply.paid = True

        frame, side = self._frame, reply.side
        previous_side, pair, results = frame.sides[side], frame.pair, frame.results
        previous_card, previous_die = frame.active_cards.pop(side, None), frame.active_dice.pop(side, None)
        original_opponent, original_target = attacker.opposing_card, attacker.target
        attack_card = attacker.card
        range_opponent, deficit = attack_card.range_opponent, attack_card.range_deficit
        frame.sides[side], frame.active_cards[side] = reply, reply.card
        reply.target, reply.opposing_card = attack_card.character, attack_card
        attacker.target, attacker.opposing_card = target, reply.card
        try:
            participants = [p for p in frame.sides.values() if p in (attacker, reply)]
            frame.pair = ClashPair({p.side: p.die for p in participants})
            frame.results = {}
            for pipe, other in ((attacker, reply), (reply, attacker)):
                pipe.card.set_range_opponent(other.card, own_range=pipe.die.effective_range,
                                             opposing_range=other.die.effective_range,
                                             ignore_range=pipe.die.effective_ignore_range)
                if pipe.card.range_deficit >= 3:
                    pipe.die.make_blank()
            self.game.context.record("reserved_intercept", target=target.combat_name, card=reply.card.name, position=die.position)
            starters = participants if start_attacker else [reply]
            for p in starters:
                p.push_pack(steps.DICE)
            yield from self._run_to(starters, steps.CAN_CLASH)
            yield from self._clash(participants)
            yield from self._run_to(starters, steps.NEXT_DIE)
            return True
        finally:
            frame.sides[side], frame.pair, frame.results = previous_side, pair, results
            attacker.opposing_card, attacker.target = original_opponent, original_target
            attack_card.range_opponent, attack_card.range_deficit = range_opponent, deficit
            frame.active_cards.pop(side, None)
            frame.active_dice.pop(side, None)
            if previous_card is not None:
                frame.active_cards[side] = previous_card
            if previous_die is not None:
                frame.active_dice[side] = previous_die
            reply.card._release_dice()

    def _solo(self, pipe, *, attempted=None):
        target = self._reserved_target(pipe) if pipe.die.can_attack_alone else None
        if target and (yield from self._contest_solo(pipe, target, attempted=attempted)):
            return
        if pipe.card.range_deficit >= 2 and pipe.die.is_attack:
            pipe.die.make_blank()
        if not pipe.die.can_attack_alone:
            pipe.die.clash_result = "skip"
            pipe.push_pack(steps.PASSIVE_SKIP)
            yield from self._run_to([pipe], "on_clash_skip")
        else:
            event = self._event(pipe)
            if not pipe.die.attack_redirected and event["target"] is None:
                event["target"] = self.resolve_skill_target(pipe.card)
            with self.game.context.binding(**event):
                score = pipe.die.roll()
                pipe.die.resolve_value(OpCode.RESOLVE_FINAL_SCORE, score)
            yield from self._hit(pipe)

    def _clash(self, participants):
        for p in participants:
            p.push_pack(steps.CLASH)
        yield from self._run_to(participants, steps.RESULT)

        results = None
        live = [p for p in participants if self._die_live(p)]
        if len(live) == 2:
            actors = tuple(p.card.character for p in live)
            with self.game.context.binding(duel=self._get_current_duel(), round_id=self.round_id,
                                           participants=actors):
                results = self.game.context.eval_block([self.current_clash_pair, OpCode.CLASH])
            if (self.pause_on_clash_scores and results and not self.game.is_over
                    and all(self._die_live(p) and p.die.clash_score is not None for p in live)):
                # Scores have settled. Leave the result branches uncommitted until
                # the next step; a replacement during this window withdraws its die.
                yield tuple("clash_scores_ready" for _ in self.game.players)
            live = [p for p in participants if self._die_live(p)]
            if results and len(live) == 2:
                pair = self.current_clash_pair
                difference = abs(live[0].die.clash_score - live[1].die.clash_score)
                for p in live:
                    if pair.split or pair.skipped or not all(self._die_live(other) for other in live):
                        break
                    self.game.context.dispatch_pipeline("before_clash_result", **self._event(p),
                                                        prospective_result=results[p.side],
                                                        clash_difference=difference)
                if pair.skipped:
                    self.game.context.record("round_skipped", reason="effect")
                    for p in live:
                        p.die.clash_result = "skip"
                        p.push_pack(steps.PASSIVE_SKIP)
                    yield from self._run_to(live, "on_clash_skip")
                    results = None
                elif pair.split:
                    self.game.context.record("clash_split")
                    # The pipes are already in initiative order, which breaks score ties.
                    for p in sorted(live, key=lambda p: p.die.clash_score, reverse=True):
                        if self._die_live(p):
                            target = self._reserved_target(p)
                            if target and (yield from self._contest_solo(p, target)):
                                continue
                            if p.card.range_deficit >= 2 and p.die.is_attack:
                                p.die.make_blank()
                            yield from self._hit(p)
                    results = None
                live = [p for p in live if self._die_live(p)]
        if len(live) == 1 and not (self.current_clash_pair.split or self.current_clash_pair.skipped):
            # A formed pair lost its die before a result. The vanished side has
            # no result at all, including skip. Only the survivor enters a branch.
            survivor = live[0]
            result = self.current_clash_pair.unopposed_results.get(survivor.die, "win")
            results = {survivor.side: result}
            self.game.context.record(f"unopposed_clash_{result}", actor=survivor.card.character.combat_name)
        if results and live:
            yield from self._resolve_results(live, results)
        yield from self._run_to(participants, "after_dice_clash")

    def _resolve_results(self, live, results):
        self._frame.results = results
        winner = next((p for p in live if results[p.side] == "win"), None)
        if winner and winner.card.range_deficit >= 2:
            winner.die.win_branch_skipped = True
            if len(live) == 1:
                self.game.context.record("clash_win_suppressed", actor=winner.card.character.combat_name)
        if len(live) == 2:
            self.game.context.record("clash_scored", sides=tuple(
                (p.card.character.combat_name, p.die.type, p.die.final_score, p.die.clash_score,
                 results[p.side], p.die.win_branch_skipped) for p in live))
        stops = {}
        result_pipes = []
        for p in live:
            result = results[p.side]
            self.game.record_clash_result(p.card.character, result)
            p.die.clash_result = result
            if p.die.win_branch_skipped:
                continue
            p.push_pack(steps.result_section(result))
            stops[p.side] = f"on_clash_{result}"
            result_pipes.append(p)
        yield from self._run_to(result_pipes, stops)
        if winner and not winner.die.win_branch_skipped:
            yield from self._run_to([winner], steps.CAN_HIT)
            yield from self._hit(winner)
        for p in live:
            if p is not winner and p.die.queued_hits:
                yield from self._hit(p, automatic=False)

    def _hit(self, pipe, *, automatic=True):
        split = self.current_clash_pair and self.current_clash_pair.split
        if (not self._die_live(pipe) or pipe.card.range_deficit
                or not (pipe.die.is_attack or split and pipe.die.is_passive)):
            return
        if pipe.die.attack_redirected:
            target = pipe.die.attack_target
        elif self.current_clash_pair:
            target = pipe.target
        else:
            target = self.resolve_skill_target(pipe.card)
        if target is None or not target.is_alive:
            return
        if not self.current_clash_pair:
            self.game.context.record("solo_attack", actor=pipe.card.character.combat_name, target=target.combat_name,
                                     rolled=pipe.die.value, final_score=pipe.die.final_score)
        die = pipe.die
        die.hit_target = target
        if automatic:
            die.queued_hits.appendleft(("full", None))
        try:
            while die.queued_hits and self._die_live(pipe) and not self.game.is_over:
                die.hit_mode, die.hit_origin, *recipient = die.queued_hits.popleft()
                die.hit_target = recipient[0] if recipient else target
                if not die.hit_target.is_alive:
                    continue
                die.hit_index = die.landed_hits + 1
                pipe.push_pack(steps.HIT)
                yield from self._run_to([pipe], "after_dice_hit")
                if die.landed_hits < die.hit_index and not recipient:
                    break
        finally:
            die.hit_mode = die.hit_origin = die.hit_target = None
            die.queued_hits.clear()

    def _run_to(self, pipes, stops):
        """Run selected sides in initiative order; others keep their exact position."""
        remaining = list(pipes)
        for pipe in remaining:
            pipe.unblock()
        while remaining:
            actions = {}
            for pipe in list(remaining):
                if self._get_current_duel().end_requested:
                    raise DuelEnded()
                stop = stops[pipe.side] if isinstance(stops, dict) else stops
                node = pipe.step()
                actions[pipe.side] = self._execute(node, pipe)
                if node.id == stop:
                    remaining.remove(pipe)
                elif node.is_wait:
                    raise RuntimeError(f"交锋包抵达意外检查点 {node.id}，预期 {stop}")
                if self.game.is_over:
                    break
            yield tuple(actions.get(p.side) for p in self.game.players)
            if self.game.is_over:
                return

    def _event(self, pipe):
        other = next(p for p in self.side_pipelines.values() if p is not pipe)
        opponent = other.card or pipe.opposing_card
        target = pipe.target
        if pipe.die is not None and pipe.die.hit_target is not None:
            target = pipe.die.hit_target
        elif pipe.die is not None and pipe.die.attack_redirected:
            target = pipe.die.attack_target
        elif target is None and opponent is not None and opponent.character.is_alive:
            target = opponent.character
        duel = self._get_current_duel()
        play_mode = duel.play_mode(pipe.card)
        combat_window = "regular"
        if play_mode == "active" and getattr(duel, "origin", None) == "before_duel":
            combat_window = "before_duel"
        elif play_mode in ("active", "passive") and self._frame.space is self.game.pre_reveal.space:
            combat_window = "pre_reveal"
        return dict(side=pipe.side, source=pipe.card.character if pipe.card else None,
                    card=pipe.card, die=pipe.die, target=target, duel=duel,
                    play_mode=play_mode, combat_window=combat_window,
                    simultaneous_solo=bool(self.current_clash_pair and self.current_clash_pair.split),
                    one_sided=self.current_clash_pair is None or self.current_clash_pair.split,
                    hit_mode=getattr(pipe.die, "hit_mode", None),
                    hit_origin=getattr(pipe.die, "hit_origin", None),
                    hit_index=getattr(pipe.die, "hit_index", 0),
                    clash_result=getattr(pipe.die, "clash_result", None),
                    is_repeat=getattr(pipe.die, "is_repeat", False),
                    opponent_card=opponent, opponent_die=other.die, round_id=self.round_id)

    def _execute(self, node, pipe):
        name = node.id
        cancelled_card = node.pack_type != PackType.DUEL and not self._card_live(pipe)
        cancelled_die = node.pack_type in (PackType.DICE, PackType.CLASH, PackType.HIT) and not self._die_live(pipe)
        unpaid = node.pack_type == PackType.SKILL and name not in ("before_skill_use", "logic_skill_use") and not pipe.paid
        if cancelled_card or cancelled_die or unpaid:
            if name == "after_skill_use":
                self.game.context.close_cancelled_use(pipe.side, card=pipe.card)
            elif name == "after_dice_use":
                self.game.context.close_cancelled_use(pipe.side, die=pipe.die)
            return None
        if name == "after_skill_use" and pipe.card in self._frame.pairing_copies.values():
            self.game.context.close_cancelled_use(pipe.side, card=pipe.card)
            return None
        # The skip packet's last wait is internal bookkeeping. A skipped die may
        # only trigger its explicit skip effect, not any other dice event.
        if pipe.die and pipe.die.clash_result == "skip" and name != "on_clash_skip":
            return None
        if name in ("logic_dice_clash", "on_dice_clash", steps.RESULT):
            if not all(self._die_live(self.side_pipelines[s]) for s in self.current_clash_pair.dice_dict):
                return None
        event = self._event(pipe)
        if (name in ("on_dice_hit", "after_dice_hit")
                and pipe.die.landed_hits < pipe.die.hit_index):
            return None
        if not name.startswith("logic_"):
            if name == "on_skill_use":
                pipe.used = True
                event["duel"].used_skill_faces.setdefault(pipe.side, []).append(pipe.card.data)
                self.game.turn_history.record_skill(pipe.card.character, pipe.card.id)
            valid = (lambda: self._die_live(pipe)) if name == "before_dice_use" else None
            self.game.context.dispatch_pipeline(name, valid=valid, **event)
        elif name == "logic_duel_start" and not self._frame.started:
            self._frame.started = True
            for player in self._ordered_players():
                for char in player.characters:
                    if char.is_alive and not self.game.is_over:
                        char.on_duel_start()
        elif name == "logic_skill_use":
            if (pipe.card.printed_data.get("form_when") or {}).get("snapshot") == "use":
                pipe.card.form_locked = True
            discount = pipe.card.use_state.pop("use_discount", 0)
            with self.game.context.binding(**event):
                pipe.payment = self.game.context.pay_skill_cost(pipe.card, discount)
            pipe.paid = pipe.payment["paid"]
            if pipe.paid:
                self.game.used_cards.append(pipe.card)
                self.game.context.record("skill_used", actor=pipe.card.character.combat_name, card=pipe.card.name, cost=pipe.card.cost)
            else:
                self.game.context.record("skill_unpaid", actor=pipe.card.character.combat_name, card=pipe.card.name,
                                         reason=pipe.payment["failure_reason"])
        elif name == "logic_dice_clash":
            with self.game.context.binding(**event):
                pipe.die.roll(clash=True)
        elif name == "logic_dice_hit" and event["target"] and event["target"].is_alive:
            if self.game.context.resolve_hit(**event):
                pipe.die.landed_hits += 1
        return name
