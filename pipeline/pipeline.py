from collections import deque
from contextlib import contextmanager
from weakref import WeakSet

from models.card import CardState
from models.duel import ClashPair, DuelSpace
from models.opcode import OpCode
from models.pack_types import PackType
from . import combat_steps as steps
from .pipeline_errors import PipelineFinished


BEFORE_ATTACK_TARGET = "before_attack_target"
BEFORE_ONE_SIDED_ATTACK = "before_one_sided_attack"


class DuelEnded(Exception):
    """An effect ended the currently executing slot between combat nodes."""


class SidePipeline:
    """Only a dispatched packet or an explicit release can resume a waiting side."""

    def __init__(self, side, game=None, *, lane="front"):
        self.side = side
        self.lane = lane
        self.key = (side, lane)
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
        self.sides = {p.side: SidePipeline(p.side, space.game, lane="front") for p in players}
        self.rear_sides = {p.side: SidePipeline(p.side, space.game, lane="rear") for p in players}
        self.pair = None
        self.results = {}
        self.lane_results = {}
        self.lane_step_nodes = {}
        self.started = False
        self.round_id = 0
        self.before_use_sides = set()
        self.before_use_lanes = set()
        self.move_after_die = {}
        self.pairing_copies = {}
        self.skill_responses = {}
        self.active_cards = {}
        self.active_dice = {}
        self.rear_active_cards = {}
        self.rear_active_dice = {}
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
    def rear_side_pipelines(self):
        return self._frame.rear_sides if self._frames else {}

    @property
    def current_clash_pair(self):
        return self._frame.pair if self._frames else None

    @property
    def current_clash_results(self):
        return self._frame.results if self._frames else {}

    @property
    def current_lane_clash_results(self):
        return self._frame.lane_results if self._frames else {}

    @property
    def last_lane_step_nodes(self):
        return self._frame.lane_step_nodes if self._frames else {}

    def _all_frame_pipes(self, frame=None):
        f = frame or (self._frame if self._frames else None)
        if f is None:
            return []
        result = []
        for p in self._ordered_players():
            result.append(f.sides[p.side])
            result.append(f.rear_sides[p.side])
        return result

    def _ordered_pipes(self, pipes):
        first_side = self.game.first_player.side if self.game.first_player else None
        return sorted(pipes, key=lambda p: (p.side != first_side, 0 if p.lane == "front" else 1))

    def _pipe_for_card(self, card):
        if card is None or not self._frames:
            return None
        side = card.player.side
        for p in (self._frame.sides.get(side), self._frame.rear_sides.get(side)):
            if p is not None and p.card is card:
                return p
        return None

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
        pipe = self._pipe_for_card(card)
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
        cards = list(slot.get_content(side)[slot.current_card_index.get(side, 0):])
        cards.extend(card for card in slot.dice_tails if card.player.side == side and slot.tail_is_live(card))
        if slot.has_valid_front_anchor(side):
            cards.extend(slot.get_rear_content(side)[slot.rear_card_index.get(side, 0):])
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
        for cards in (*slot.content.values(), *slot.rear_content.values()):
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
        self.game.context.rear_active_cards = frame.rear_active_cards
        self.game.context.rear_active_dice = frame.rear_active_dice
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
        if at == "respond_to_die":
            die = event.get("die")
            slot = event.get("duel")
            if (not self.in_duel_phase or not die or not die.can_attack_alone
                    or card.character is not event.get("target") or die in self._frame.skill_responses):
                return False
        elif at in ("slot_tail", "rear_duel"):
            slot = subject or event.get("duel")
        else:
            if at not in ("before_die", "after_die", "before_skill", "after_skill", "replace_position"):
                raise ValueError(f"未知的技能插入位置 {at!r}")
            is_die = at.endswith("_die")
            subject = subject or event.get("die" if is_die else "card")
            parent = getattr(subject, "card", None) if is_die else subject
            slot = next((s for s in self.game.board_slots() if parent in s.get_content(side)), None)
            if slot is None or parent.destroyed and at != "replace_position":
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
        if not self.game.place_in_duel(side, card, space.space.index(slot), queued=regular, rear=(at == "rear_duel")):
            return False
        use.set_price()
        if at == "respond_to_die":
            self._frame.skill_responses[die] = card
            return True
        if at in ("slot_tail", "rear_duel"):
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
            if at == "replace_position":
                for field in ("attack_card", "pulled_card", "intercept_card"):
                    if getattr(slot, field, None) is parent:
                        setattr(slot, field, card)
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
            if pipe.lane != "front":
                continue
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
            for active in (frame.sides[side], frame.rear_sides[side]):
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
        in_front = card in slot.get_content(side)[slot.current_card_index.get(side, 0):]
        in_rear = (slot.has_valid_front_anchor(side)
                   and card in slot.get_rear_content(side)[slot.rear_card_index.get(side, 0):])
        if not in_front and not in_rear:
            return False
        if binding := self._bound_use(slot, card):
            pipe = binding[1]
            return pipe.paid is not False and pipe.current_node.id not in ("after_skill_use", steps.NEXT_CARD)
        return True

    def before_use(self, slot, card):
        if not self._frames or slot is not self._get_current_duel():
            return False
        side = card.player.side
        if (side, "front") in self._frame.before_use_lanes and slot.get_current_card(side) is card:
            return True
        return (side, "rear") in self._frame.before_use_lanes and slot.get_current_rear_card(side) is card

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
            cards_map = frame.rear_active_cards if pipe.lane == "rear" else frame.active_cards
            dice_map = frame.rear_active_dice if pipe.lane == "rear" else frame.active_dice
            if cards_map.get(side) is card:
                cards_map.pop(side, None)
            if dice_map.get(side) is pipe.die:
                dice_map.pop(side, None)

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
        self.game.context.rear_active_cards = parent.rear_active_cards if parent else {}
        self.game.context.rear_active_dice = parent.rear_active_dice if parent else {}
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
            for pipe in self._all_frame_pipes():
                pipe.opposing_card = pipe.target = None
            self.game.sync_rear_duels(slot)
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
                        pipe.push_pack(steps.DUEL_END if pipe.lane == "front"
                                       else steps.section(PackType.DUEL, steps.NEXT_DUEL))
                    self._frame.pair = None
                    self._frame.results = {}
                    self._frame.lane_results = {}
                    yield from self._run_to(pipes, steps.NEXT_DUEL)
                    for card in slot.all_cards():
                        card.set_range_opponent(None)
                self.game.context.expire_lasting_entries(slot)
            self.release_temporary_skills(slot)
            self._closed_slots.add(slot)
            space.current_duel_index += 1

    def _ordered_players(self):
        return sorted(self.game.players, key=lambda p: p is not self.game.first_player)

    def _slot_next_card(self, slot, pipe, *, advance=False):
        if pipe.lane == "front":
            return slot.next_combat_card(pipe.side, advance=advance)
        if not slot.has_started_front(pipe.side):
            return None
        return slot.next_playable_rear_card(pipe.side, advance=advance)

    def _opposing_pipe_in(self, pipes, side):
        enemies = [p for p in pipes if p.side != side]
        if not enemies:
            return None
        return next((p for p in enemies if p.lane == "front"), enemies[0])

    def _play_slot(self, slot, pipes):
        for pipe in pipes:
            pipe.push_pack(steps.DUEL if pipe.lane == "front" else steps.REAR_DUEL)
        yield from self._run_to(pipes, steps.NEXT_CARD)

        while True:
            self.game.sync_rear_duels(slot)
            if self._resume_inserted(slot, pipes):
                yield from self._start_skills(pipes, [])
            # The remaining die waits here while its opponent changes skills.
            # A side with no skill left is idle, so it cannot block a solo die.
            # An effect may have placed a skill for a previously empty side or rear track.
            joiners = [p for p in self._all_frame_pipes()
                       if p not in pipes and self._slot_next_card(slot, p)]
            if joiners:
                for pipe in joiners:
                    pipe.push_pack(steps.DUEL if pipe.lane == "front" else steps.REAR_DUEL)
                yield from self._run_to(joiners, steps.NEXT_CARD)
                pipes[:] = self._ordered_pipes([p for p in self._all_frame_pipes() if p in pipes or p in joiners])
            entering = [p for p in pipes if p.is_blocked_at(steps.NEXT_CARD) and self._slot_next_card(slot, p)]
            if entering and any(p.lane == "front" for p in entering):
                entering = [p for p in entering if p.lane == "front"]
            if entering:
                frame = self._frame
                frame.before_use_lanes = {
                    (p.side, p.lane) for p in entering
                    if (cur := (slot.get_current_card(p.side) if p.lane == "front" else slot.get_current_rear_card(p.side))) is not None
                    and cur not in frame.pairing_copies.values()
                }
                frame.before_use_sides = {s for s, _ in frame.before_use_lanes}
                if frame.before_use_sides:
                    yield tuple("before_skill_choice" if p.side in frame.before_use_sides else None
                                for p in self.game.players)
                frame.before_use_sides.clear()
                frame.before_use_lanes.clear()
                declared_target = None
                attack = None
                defender = None
                if (len(entering) == 1 and entering[0].lane == "front"
                        and any(e.trigger == "before_unopposed_ranged_skill" for e in self.game.context.entries)):
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
                            pipes[:] = self._ordered_pipes(pipes)
                        entering.append(defender)
                entrants = []
                for pipe in entering:
                    card = self._slot_next_card(slot, pipe, advance=True)
                    if card is None:
                        continue
                    pipe.card = card
                    pipe.paid = None
                    pipe.payment = None
                    pipe.withdrawn = pipe.used = False
                    pipe.opposing_card = None
                    inherited_target = None
                    if pipe.lane == "front" and frame.suspended_skills[pipe.side]:
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
                    if pipe.lane == "front" and (card in frame.pairing_copies.values() or slot.tail_is_live(card)):
                        pipe.paid = pipe.used = True
                        frame.active_cards[pipe.side] = card
                        pipe.push_pack(steps.REMAINING_SKILL)
                        pipe.step()
                        continue
                    pipe.push_pack(steps.SKILL)
                    entrants.append(pipe)
                if entrants:
                    yield from self._start_skills(pipes, entrants)
                self.game.sync_rear_duels(slot)
                # Skill-use effects can insert a card into an empty opposing side or rear track.
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
                        if pipe.lane == "rear":
                            slot.finish_rear_card(pipe.side, pipe.card)
                        else:
                            slot.finish_card(pipe.side, pipe.card)
                    pipe.card = pipe.die = None
                self.game.sync_rear_duels(slot)
                continue
            if not ready:
                break

            inserted = [self._start_inserted(slot, pipes, p.side, p.die, "before_die")
                        for p in ready if p.lane == "front"]
            if any(inserted):
                continue

            # Refill both sides before forming a pair. A rejected die consumes no
            # round and gives neither side a clash or skip result.
            live = [p for p in ready if not p.die.destroyed]
            waiting = [p for p in live if p.card.use_state.get("delay_rounds", 0) > 0]
            for p in waiting:
                p.card.use_state["delay_rounds"] -= 1
                p.card.use_state["delaying_round"] = True
            if waiting:
                ready = [p for p in ready if p not in waiting]
                live = [p for p in live if p not in waiting]
                if not live:
                    yield from self._play_round([])
                    for p in waiting:
                        p.card.use_state.pop("delaying_round", None)
                    continue
            # A printed skip die on a rear track does not trigger or skip the round;
            # it sits out this round and advances its cursor alongside the round.
            rear_skips = [p for p in live if p.lane == "rear" and p.die.type == "skip"]
            active_live = [p for p in live if p not in rear_skips]
            if not active_live:
                yield from self._play_round([])
            else:
                if not self._pay_dice_costs(active_live):
                    continue
                for pipe in active_live:
                    pipe.die.register_entries()
                yield from self._play_round(active_live)
            for pipe in waiting:
                pipe.card.use_state.pop("delaying_round", None)
            for pipe in ready:
                die = pipe.die
                if self._card_live(pipe):
                    pipe.card.advance_die()
                destination = self._frame.move_after_die.pop(pipe.card, None) if pipe.lane == "front" else None
                if destination is not None and self._card_live(pipe) and pipe.card.has_next_die():
                    destination.dice_tails[pipe.card] = slot.dice_tails.get(
                        pipe.card, (slot, pipe.card.instantiated_dice))
                    slot.finish_card(pipe.side, pipe.card)
                    pipe.withdrawn = True
                pipe.die = None
                if pipe.lane == "front":
                    self._start_inserted(slot, pipes, pipe.side, die, "after_die")
            self._frame.pair = None
            self._frame.results = {}
            self._frame.lane_results = {}

        self._closed_slots.add(slot)
        yield from self._run_to(pipes, steps.NEXT_DUEL)
        for card in slot.all_cards():
            card.set_range_opponent(None)

    def _start_skills(self, pipes, entrants):
        current = [p for p in pipes if self._card_live(p)]
        by_side = {}
        for p in current:
            by_side.setdefault(p.side, []).append(p)
        both_sides = len(by_side) == 2
        if any(effect.terms.event == "before_skill_start" for effect in self.game.context.scheduled_effects):
            for pipe in entrants:
                self.game.context.dispatch_pipeline("before_skill_start", **self._event(pipe))
        if both_sides and len(current) == 2 and any(e.trigger == "before_skill_pair" for e in self.game.context.entries):
            for pipe, other in (current, tuple(reversed(current))):
                if self._card_live(pipe) and self._card_live(other):
                    event = dict(self._event(pipe), opponent_card=other.card, target=other.card.character)
                    self.game.context.dispatch_pipeline("before_skill_pair", **event)
            withdrawn = [p for p in current if not self._card_live(p)]
            if withdrawn:
                slot = self._get_current_duel()
                for p in withdrawn:
                    replacement = self._slot_next_card(slot, p, advance=False)
                    if replacement is None:
                        continue
                    if p not in entrants:
                        p.push_pack(steps.SKILL[:steps.SKILL.index(steps.REMAINING_SKILL[0]) + 1])
                        entrants.append(p)
                    p.card, p.die = replacement, None
                    p.withdrawn = p.used = False
                    p.paid = p.payment = p.range_pairing = None
                if all(self._card_live(p) for p in current):
                    yield from self._start_skills(pipes, entrants)
                else:
                    yield from self._run_to(entrants, steps.NEXT_DIE)
                return
        elif both_sides and any(e.trigger == "before_skill_pair" for e in self.game.context.entries):
            for pipe in entrants:
                other = self._opposing_pipe_in(current, pipe.side)
                if other and self._card_live(pipe) and self._card_live(other):
                    event = dict(self._event(pipe), opponent_card=other.card, target=other.card.character)
                    self.game.context.dispatch_pipeline("before_skill_pair", **event)
        for pipe in entrants:
            pipe.card.use_effects_resolved = False
        for pipe in current:
            pipe.card.set_range_opponent(None)
            pipe.range_pairing = None
        if both_sides and len(current) == 2:
            far, near = current
            far_range, near_range = far.card.paired_ranges(near.card)
            if near_range > far_range:
                far, near = near, far
                far_range, near_range = near_range, far_range
            far.opposing_card, near.opposing_card = near.card, far.card
            if far_range > near_range + near.card.range_ignored(near.card.data, far.card):
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
        elif both_sides:
            for pipe in current:
                opp = self._opposing_pipe_in(current, pipe.side)
                if opp is not None:
                    pipe.opposing_card = opp.card
            for pipe in entrants:
                opp = self._opposing_pipe_in(current, pipe.side)
                if opp is not None and opp.paid and self._card_live(opp) and self._card_live(pipe):
                    own_r, opp_r = pipe.card.paired_ranges(opp.card)
                    if opp_r > own_r + pipe.card.range_ignored(pipe.card.data, opp.card):
                        self._refresh_skill_range(pipe, opp.card)
            pending = [p for p in entrants if p.paid is None]
            if pending:
                yield from self._run_to(pending, "logic_skill_use")
            paid_live = [p for p in current if p.paid and self._card_live(p)]
            for pipe in paid_live:
                opp = self._opposing_pipe_in(paid_live, pipe.side)
                if opp is not None:
                    pipe.opposing_card = opp.card
                    self._refresh_skill_range(pipe, opp.card)
        yield from self._run_to(entrants, steps.NEXT_DIE)

    def _refresh_skill_range(self, pipe, opponent):
        card = pipe.card
        signature = (opponent, card.effective_range, opponent.effective_range,
                     card.range_ignored(card.data, opponent), card.paired_ranges(opponent))
        if pipe.range_pairing == signature:
            return
        pipe.range_pairing = signature
        card.set_range_opponent(opponent, own_range=signature[1], opposing_range=signature[2],
                                ignore_range=signature[3])
        if card.range_deficit:
            self.game.context.record("range_advantage", card=opponent.name, opposing=card.name, amount=card.range_deficit)

    def _card_live(self, pipe):
        if (pipe.card is None or pipe.withdrawn or not pipe.card.character.is_alive
                or pipe.card.destroyed or pipe.card.state == CardState.NEGATED):
            return False
        if pipe.is_response:
            return True
        slot = self._get_current_duel()
        if pipe.lane == "rear":
            return slot.has_valid_front_anchor(pipe.side) and pipe.card in slot.get_rear_content(pipe.side)
        return pipe.card in slot.get_content(pipe.side) or slot.tail_is_live(pipe.card)

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
        skipping = any(p.lane == "front" and p.die.type == "skip" for p in ready)
        for p in self._ordered_pipes(ready):
            if not self._die_live(p):
                return False
            if not p.die.data.get("resource_cost") or p.die.resource_paid:
                continue
            with self.game.context.binding(**self._event(p)):
                opp = self._opposing_pipe_in(ready, p.side)
                other = opp.die if opp is not None else None
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
            if die.range_deficit >= 3:
                return True
            return die.can_afford_use() if skipping else die.pay_use_cost()

    @staticmethod
    @contextmanager
    def _die_range(die, opponent):
        card = die.card
        previous = card.range_opponent, card.range_deficit
        previous_die_deficit = die.paired_range_deficit
        try:
            if opponent is not None:
                card.set_range_opponent(opponent.card, own_range=die.effective_range,
                                        opposing_range=opponent.effective_range,
                                        ignore_range=die.ignore_against(opponent.card))
            die.paired_range_deficit = card.range_deficit
            yield
        finally:
            die.paired_range_deficit = previous_die_deficit
            if opponent is not None:
                card.range_opponent, card.range_deficit = previous

    def _play_round(self, ready):
        self._rounds_started += 1
        self._frame.round_id = self._rounds_started
        for player in self._ordered_players():
            for char in player.characters:
                if char.is_alive:
                    char.begin_dice_round()

        if not ready:
            return

        sides_present = {p.side for p in ready}
        if len(sides_present) == 2:
            for pipe in ready:
                opp = self._opposing_pipe_in(ready, pipe.side)
                if opp is not None:
                    pipe.opposing_card = opp.card
                    pipe.target = opp.card.character
        for pipe in ready:
            if pipe.range_pairing:
                self._refresh_skill_range(pipe, pipe.range_pairing[0])
        if any(p.lane == "front" and p.die.type == "skip" for p in ready):
            self.game.context.record("round_skipped", reason="printed")
            for pipe in ready:
                pipe.die.clash_result = "skip"
            front_ready = [p for p in ready if p.lane == "front"]
            for pipe in front_ready:
                pipe.push_pack(steps.SKIPPED_DICE)
            if front_ready:
                yield from self._run_to(front_ready, steps.NEXT_DIE)
            return

        # A die's range lasts through its whole use (including additional hits),
        # then the skills resume their original relationship.
        saved_ranges = []
        if any(p.die.effective_range != p.card.effective_range
               or p.die.effective_ignore_range != p.card.effective_ignore_range for p in ready):
            for pipe in ready:
                other = self._opposing_pipe_in(ready, pipe.side)
                opposing = other.card if other else pipe.opposing_card
                if opposing is None:
                    continue
                card = pipe.card
                saved_ranges.append((pipe, card, card.range_opponent, card.range_deficit))
                card.set_range_opponent(opposing, own_range=pipe.die.effective_range,
                                        ignore_range=pipe.die.ignore_against(opposing),
                                        opposing_range=other.die.effective_range if other else opposing.effective_range)
        try:
            yield from self._pair_dice(ready)
        finally:
            for pipe, card, opponent, deficit in saved_ranges:
                if pipe.card is card and not pipe.withdrawn:
                    card.range_opponent, card.range_deficit = opponent, deficit

    def _pair_dice(self, ready):
        sides_present = {p.side for p in ready}
        solo_side = len(sides_present) == 1
        solo = solo_side and len(ready) == 1 and ready[0].die.can_attack_alone
        if solo:
            solo_target = yield from self._resolve_attack_target(ready[0])
            if not self._die_live(ready[0]) or not ready[0].die.can_attack_alone or (
                    ready[0].die.attack_redirected and solo_target is None):
                solo = False
        one_sided = solo_side and any(p.die.can_attack_alone for p in ready)
        attempted_responses = set()
        response = self._pending_response_die(ready[0]) if solo else None
        blank_at = 2 if solo_side else 3
        for pipe in ready:
            pipe.die.apply_paired_range(blank_at=blank_at if response is None else None)
        for pipe in ready:
            if pipe.die.is_attack and (len(sides_present) == 2 or one_sided) and self._die_live(pipe):
                with self._die_range(pipe.die, response):
                    self.game.context.dispatch_pipeline("before_dice_pair", **self._event(pipe))
        routed = any(p.die.attack_redirected for p in ready)
        if routed:
            for pipe in ready:
                if pipe.die.range_deficit >= 2 and pipe.die.is_attack and not self._reserved_target(pipe):
                    pipe.die.blanked_by_range = True
        if solo and ready[0].die.can_attack_alone:
            attacker = ready[0]
            target = self._response_target(attacker)
            if target and (yield from self._contest_solo(attacker, target, start_attacker=True,
                                                        attempted=attempted_responses)):
                return
        clash_candidates = [p for p in ready if not p.die.attack_redirected]
        clash_sides = {p.side for p in clash_candidates}
        can_pair = len(clash_sides) == 2 and not all(p.die.is_passive for p in clash_candidates)
        if can_pair:
            primary_dice = {}
            for player in self._ordered_players():
                sps = [p for p in clash_candidates if p.side == player.side]
                if sps:
                    front_p = next((p for p in sps if p.lane == "front"), sps[0])
                    primary_dice[player.side] = front_p.die
            lane_dice = {p.key: p.die for p in clash_candidates}
            self._frame.pair = ClashPair(primary_dice, lane_dice=lane_dice)
        active = []
        stops = {}
        for pipe in ready:
            die = pipe.die
            in_clash = can_pair and pipe in clash_candidates
            can_solo = (not in_clash) and die.can_attack_alone and (
                not die.attack_redirected or (die.attack_target and die.attack_target.is_alive)
            )
            if in_clash or can_solo:
                pipe.push_pack(steps.DICE)
                active.append(pipe)
                stops[pipe] = steps.CAN_CLASH
            elif pipe.lane == "front":
                die.clash_result = "skip"
                pipe.push_pack(steps.SKIPPED_DICE)
                stops[pipe] = steps.NEXT_DIE
        if not active:
            self.game.context.record("round_skipped", reason="passive")
        run_pipes = [p for p in ready if p in stops]
        if run_pipes:
            yield from self._run_to(run_pipes, stops)
        if can_pair:
            clash_active = [p for p in active if p in clash_candidates]
            yield from self._clash(clash_active)
            for pipe in active:
                if pipe not in clash_candidates and self._die_live(pipe):
                    yield from self._solo(pipe)
        else:
            for pipe in active:
                if self._die_live(pipe):
                    yield from self._solo(pipe, attempted=attempted_responses if solo else None)
        if active:
            yield from self._run_to(active, steps.NEXT_DIE)

    def _resolve_attack_target(self, attacker):
        if attacker.die.attack_redirected:
            target = attacker.die.attack_target
        elif attacker.target is not None and attacker.target.is_alive:
            target = attacker.target
        else:
            target = self.resolve_skill_target(attacker.card)
        if target is not None and not target.is_alive:
            target = None
        ctx = self.game.context
        if (not attacker.die.use_state.get("attack_target_resolved")
                and any(e.trigger == BEFORE_ATTACK_TARGET for e in ctx.entries)):
            attacker.die.use_state["attack_target_resolved"] = True
            ctx.dispatch_pipeline(BEFORE_ATTACK_TARGET, **dict(self._event(attacker), target=target))
            if self.game.special.decision_owner:
                yield tuple(BEFORE_ATTACK_TARGET if p is self.game.special.decision_owner else None
                            for p in self.game.players)
            if attacker.die.attack_redirected:
                target = attacker.die.attack_target
        return target if target and target.is_alive else None

    def _reserved_target(self, pipe):
        def eligible(actor):
            return actor and actor.is_alive and actor.available_die_responses(
                BEFORE_ONE_SIDED_ATTACK, self.game.turn_number)

        if not any(eligible(actor) for player in self.game.players if player.side != pipe.side
                   for actor in player.characters):
            return None
        target = pipe.die.attack_target if pipe.die.attack_redirected else self.resolve_skill_target(pipe.card)
        return target if eligible(target) else None

    def _response_target(self, attacker):
        if not attacker.die.can_attack_alone:
            return None
        if not any(e.trigger == BEFORE_ONE_SIDED_ATTACK for e in self.game.context.entries):
            return self._reserved_target(attacker)
        target = attacker.die.attack_target if attacker.die.attack_redirected else self.resolve_skill_target(attacker.card)
        return target if target and target.is_alive else None

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
        ctx = self.game.context
        if (not attacker.die.use_state.get("offered_skill_response")
                and any(e.trigger == BEFORE_ONE_SIDED_ATTACK for e in ctx.entries)):
            attacker.die.use_state["offered_skill_response"] = True
            ctx.dispatch_pipeline(BEFORE_ONE_SIDED_ATTACK, **dict(self._event(attacker), target=target))
            if self.game.special.decision_owner:
                yield tuple(BEFORE_ONE_SIDED_ATTACK if p is target.player else None for p in self.game.players)
        skill = self._frame.skill_responses.pop(attacker.die, None)
        die = None if skill else self._accept_die_response(attacker, target, BEFORE_ONE_SIDED_ATTACK, attempted=attempted)
        if skill is None and die is None:
            return False
        reply = SidePipeline(target.player.side, self.game)
        reply.card, reply.die = skill or die.card, die
        reply.is_response = skill is None
        reply.paid = True if skill is None else None

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
            if skill:
                frame.pair, frame.results = None, {}
                reply.push_pack(steps.SKILL)
                yield from self._start_skills(participants, [reply])
                while (die := self._next_live_die(reply)) is not None:
                    if self._pay_die_against(die, attacker.die):
                        break
                    skill.skip_unpaid_die()
                if die is None:
                    yield from self._run_to([reply], steps.NEXT_CARD)
                    self._get_current_duel().finish_card(reply.side, skill)
                    return False
                reply.die = die
                die.register_entries()
            frame.pair = ClashPair({p.side: p.die for p in participants})
            frame.results = {}
            for pipe, other in ((attacker, reply), (reply, attacker)):
                pipe.card.set_range_opponent(other.card, own_range=pipe.die.effective_range,
                                             opposing_range=other.die.effective_range,
                                             ignore_range=pipe.die.ignore_against(other.card))
                pipe.die.apply_paired_range(blank_at=3)
            self.game.context.record("skill_intercept" if skill else "reserved_intercept",
                                     target=target.combat_name, card=reply.card.name, position=die.position)
            starters = participants if start_attacker else [reply]
            for p in starters:
                p.push_pack(steps.DICE)
            yield from self._run_to(starters, steps.CAN_CLASH)
            yield from self._clash(participants)
            yield from self._run_to(starters, steps.NEXT_DIE)
            if skill and self._card_live(reply):
                skill.advance_die()
                slot = self._get_current_duel()
                # The remainder is the same paid use. Resume an interrupted friendly
                # skill at its own cursor after the response has finished.
                slot.dice_tails[skill] = (slot, skill.instantiated_dice)
                if previous_side.card and previous_side.die and previous_side.card in slot.get_content(side):
                    anchor = "before_die" if previous_side.card.use_state.get("delaying_round") else "after_die"
                    skill.use_state["die_anchor"] = (anchor, previous_side.die)
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
            if skill is None:
                reply.card._release_dice()

    def _solo(self, pipe, *, attempted=None):
        if pipe.die.can_attack_alone:
            resolved = yield from self._resolve_attack_target(pipe)
            if pipe.die.attack_redirected and resolved is None:
                return
            target = self._response_target(pipe)
            if target and (yield from self._contest_solo(pipe, target, attempted=attempted)):
                return
        if pipe.die.range_deficit >= 2 and pipe.die.is_attack:
            pipe.die.blanked_by_range = True
        if not pipe.die.can_attack_alone:
            if pipe.lane == "front":
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

        lane_results = None
        live = [p for p in participants if self._die_live(p)]
        live_sides = {p.side for p in live}
        if len(live_sides) == 2:
            pair = self.current_clash_pair
            primary_dice = {}
            for player in self._ordered_players():
                sps = [p for p in live if p.side == player.side]
                if sps:
                    front_p = next((p for p in sps if p.lane == "front"), sps[0])
                    primary_dice[player.side] = front_p.die
            pair.dice_dict = primary_dice
            pair.lane_dice = {p.key: p.die for p in live}
            actors = tuple(dict.fromkeys(p.card.character for p in live))
            with self.game.context.binding(duel=self._get_current_duel(), round_id=self.round_id,
                                           participants=actors):
                side_results = self.game.context.eval_block([pair, OpCode.CLASH])
            lane_results = dict(pair.lane_results) if side_results else None
            if lane_results and any(e.trigger == "on_clash_scores_ready" for e in self.game.context.entries):
                while not self.game.is_over:
                    revision = pair.rerolls
                    for pipe in live:
                        if not all(self._die_live(p) for p in live):
                            break
                        enemy_score, _ = pair.opposing_threshold(pipe.side, pipe.lane)
                        self.game.context.dispatch_pipeline("on_clash_scores_ready", **self._event(pipe),
                                                            clash_pair=pair, opposing_score=enemy_score)
                        while self.game.special.decision_owner is not None:
                            yield tuple("clash_scores_ready" for _ in self.game.players)
                        if pair.rerolls != revision:
                            break
                    if pair.rerolls == revision:
                        break
                lane_results = dict(pair.lane_results)
            if (self.pause_on_clash_scores and lane_results and not self.game.is_over
                    and all(self._die_live(p) and p.die.clash_score is not None for p in live)):
                # Scores have settled. Leave the result branches uncommitted until
                # the next step; a replacement during this window withdraws its die.
                yield tuple("clash_scores_ready" for _ in self.game.players)
            live = [p for p in participants if self._die_live(p)]
            live_sides = {p.side for p in live}
            if lane_results and len(live_sides) == 2:
                for p in live:
                    if (pair.drawn or pair.split or pair.skipped
                            or len({other.side for other in live if self._die_live(other)}) < 2):
                        break
                    if not self._die_live(p) or p.key not in lane_results:
                        continue
                    enemy_score, _ = pair.opposing_threshold(p.side, p.lane)
                    difference = abs(p.die.clash_score - enemy_score)
                    self.game.context.dispatch_pipeline("before_clash_result", **self._event(p),
                                                        prospective_result=lane_results[p.key],
                                                        clash_difference=difference)
                if pair.drawn:
                    lane_results = {p.key: "draw" for p in live if self._die_live(p)}
                elif pair.skipped:
                    self.game.context.record("round_skipped", reason="effect")
                    front_live = [p for p in live if self._die_live(p) and p.lane == "front"]
                    for p in live:
                        if self._die_live(p):
                            p.die.clash_result = "skip"
                    for p in front_live:
                        p.push_pack(steps.PASSIVE_SKIP)
                    if front_live:
                        yield from self._run_to(front_live, "on_clash_skip")
                    lane_results = None
                elif pair.split:
                    self.game.context.record("clash_split")
                    # The pipes are already in initiative order, which breaks score ties.
                    for p in sorted(live, key=lambda p: p.die.clash_score, reverse=True):
                        if self._die_live(p):
                            target = self._response_target(p)
                            if target and (yield from self._contest_solo(p, target)):
                                continue
                            if p.die.range_deficit >= 2 and p.die.is_attack:
                                p.die.blanked_by_range = True
                            yield from self._hit(p)
                    lane_results = None
                live = [p for p in live if self._die_live(p)]
                live_sides = {p.side for p in live}
        if len(live_sides) == 1 and live and not (self.current_clash_pair.split or self.current_clash_pair.skipped):
            # A formed pair lost its opposing side before a result. The vanished side has
            # no result at all, including skip. Only the surviving side enters a branch.
            lane_results = {}
            for survivor in live:
                result = self.current_clash_pair.unopposed_results.get(survivor.die, "win")
                lane_results[survivor.key] = result
                self.game.context.record(f"unopposed_clash_{result}", actor=survivor.card.character.combat_name)
        if lane_results and live:
            yield from self._resolve_results(live, lane_results)
        yield from self._run_to(participants, "after_dice_clash")

    def _resolve_results(self, live, lane_results):
        self._frame.lane_results = dict(lane_results)
        side_summary = {}
        for p in live:
            res = lane_results.get(p.key)
            if res is not None and (p.side not in side_summary or p.lane == "front"):
                side_summary[p.side] = res
        self._frame.results = side_summary
        live_sides = {p.side for p in live}
        winners = [p for p in live if lane_results.get(p.key) == "win"]
        for winner in winners:
            if winner.die.range_deficit >= 2:
                winner.die.win_branch_skipped = True
                if len(live_sides) == 1:
                    self.game.context.record("clash_win_suppressed", actor=winner.card.character.combat_name)
        if len(live_sides) == 2:
            self.game.context.record("clash_scored", sides=tuple(
                (p.card.character.combat_name, p.die.type, p.die.final_score, p.die.clash_score,
                 lane_results[p.key], p.die.win_branch_skipped) for p in live))
        stops = {}
        result_pipes = []
        for p in live:
            result = lane_results[p.key]
            self.game.record_clash_result(p.card.character, result)
            p.die.clash_result = result
            if p.die.win_branch_skipped:
                continue
            p.push_pack(steps.result_section(result))
            stops[p] = f"on_clash_{result}"
            result_pipes.append(p)
        if result_pipes:
            yield from self._run_to(result_pipes, stops)
        active_winners = [w for w in winners if not w.die.win_branch_skipped]
        for winner in active_winners:
            yield from self._run_to([winner], steps.CAN_HIT)
            if self._die_live(winner) and not self.game.is_over:
                yield from self._hit(winner)
        for p in live:
            if p not in active_winners and p.die.queued_hits:
                yield from self._hit(p, automatic=False)

    def _hit(self, pipe, *, automatic=True):
        split = self.current_clash_pair and self.current_clash_pair.split
        passive_split = bool(split and pipe.lane == "front" and pipe.die.is_passive)
        if (not self._die_live(pipe) or pipe.die.range_deficit
                or not (pipe.die.is_attack or passive_split)):
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
                if not die.hit_target.is_alive or self.game.context.has_no_hit_carrier(die.hit_target):
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
            lane_nodes = {}
            for pipe in list(remaining):
                if self._get_current_duel().end_requested:
                    raise DuelEnded()
                if isinstance(stops, dict):
                    stop = stops[pipe] if pipe in stops else stops.get(pipe.key, stops.get(pipe.side))
                else:
                    stop = stops
                node = pipe.step()
                act = self._execute(node, pipe)
                lane_nodes[pipe.key] = act
                if act is not None or pipe.side not in actions:
                    if pipe.side not in actions or actions[pipe.side] is None or pipe.lane == "front":
                        actions[pipe.side] = act
                if node.id == stop:
                    remaining.remove(pipe)
                elif node.is_wait:
                    raise RuntimeError(f"交锋包抵达意外检查点 {node.id}，预期 {stop}")
                if self.game.is_over:
                    break
            if self._frames:
                self._frame.lane_step_nodes = lane_nodes
            yield tuple(actions.get(p.side) for p in self.game.players)
            if self.game.is_over:
                return

    def _opposing_pipe_for_event(self, side):
        enemy_side = next(p.side for p in self.game.players if p.side != side)
        front_enemy = self.side_pipelines[enemy_side]
        rear_enemy = self.rear_side_pipelines[enemy_side]
        if front_enemy.card is not None or front_enemy.die is not None:
            return front_enemy
        if rear_enemy.card is not None or rear_enemy.die is not None:
            return rear_enemy
        return front_enemy

    def _event(self, pipe):
        other = self._opposing_pipe_for_event(pipe.side)
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
        return dict(side=pipe.side, lane=pipe.lane,
                    source=pipe.card.character if pipe.card else None,
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
            live_clash_sides = {
                s for (s, lane) in self.current_clash_pair.lane_dice
                if self._die_live(self.rear_side_pipelines[s] if lane == "rear" else self.side_pipelines[s])
            }
            if len(live_clash_sides) < 2:
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
