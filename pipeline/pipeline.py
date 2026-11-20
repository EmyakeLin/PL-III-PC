from collections import deque
from weakref import WeakSet

from models.card import CardState
from models.dice import TYPE_NAMES
from models.duel import ClashPair, DuelSpace
from models.opcode import OpCode
from models.pack_types import PackType
from . import combat_steps as steps
from .pipeline_errors import PipelineFinished


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
        self.withdrawn = False
        self.used = False
        self.opposing_card = None
        self.target = None

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
        self.active_cards = {}
        self.active_dice = {}
        self.runner = None
        self.parent_round_triggers = {}


class Pipeline:
    def __init__(self, game=None, step_list=None):
        self.game = game
        self.step_list = [node.bind(game) for node in (step_list or ())]
        self.current_step_index = -1
        self.is_finished = False
        self._frames = []
        self._rounds_started = 0
        self._closed_slots = WeakSet()

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

    @property
    def before_duel_start(self):
        return bool(self._frames and not self._frame.started and any(
            pipe.current_node and pipe.current_node.id == "before_duel_start"
            for pipe in self.side_pipelines.values()))

    def next_step(self):
        if self.in_duel_phase:
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

    def start_duel_combat(self):
        if self.in_duel_phase:
            raise RuntimeError("交锋已经开始")
        self._push_combat(self.game.active_duelspace, interrupt=False)

    def start_special_duel(self, slot):
        self.start_special_duels([slot])

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

    def can_replace(self, slot, card):
        side = card.player.side
        if not self.can_join(slot) or not card.character.is_alive or card.destroyed or card.state == CardState.NEGATED:
            return False
        if card not in slot.get_content(side)[slot.current_card_index.get(side, 0):]:
            return False
        for frame in self._frames:
            if slot not in frame.space.space:
                continue
            pipe = frame.sides[side]
            if pipe.card is card and not pipe.withdrawn and pipe.current_node:
                return pipe.paid is not False and pipe.current_node.id not in ("after_skill_use", steps.NEXT_CARD)
        return True

    def before_use(self, slot, card):
        return (bool(self._frames) and card.player.side in self._frame.before_use_sides
                and slot is self._get_current_duel() and slot.get_current_card(card.player.side) is card)

    def in_use(self, slot, card):
        for frame in self._frames:
            index = frame.space.current_duel_index
            if index < len(frame.space.space) and frame.space.space[index] is slot:
                pipe = frame.sides[card.player.side]
                return pipe.card is card and not pipe.withdrawn
        return False

    def withdraw_skill(self, slot, card):
        """Invalidate this use even if the same physical card is immediately played again."""
        side = card.player.side
        for frame in self._frames:
            if slot not in frame.space.space:
                continue
            pipe = frame.sides[side]
            if pipe.card is not card or pipe.withdrawn:
                continue
            pipe.withdrawn = True
            self.game.context.withdraw_card_use(card, slot, pipe.used)
            self.game.context.close_cancelled_use(side, card=card, die=pipe.die)
            if frame.active_cards.get(side) is card:
                frame.active_cards.pop(side)
            if frame.active_dice.get(side) is pipe.die:
                frame.active_dice.pop(side, None)

    def step_duel_combat(self):
        if not self.game.is_over:
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
                label = "即时交锋" if self._frame.interrupt else "开牌前交锋"
                print(f"\n结算{label} {self.game.duel_position()[1] + 1}")
                if not slot.prepare(self.game.pre_reveal):
                    print("进攻牌或目标已离场，本场交锋跳过。")
                    self._closed_slots.add(slot)
                    space.current_duel_index += 1
                    continue
            for pipe in self.side_pipelines.values():
                pipe.opposing_card = pipe.target = None
            pipes = [p for p in self.side_pipelines.values() if slot.next_playable_card(p.side)]
            if pipes:
                if not pre_reveal:
                    print(f"\n交锋 {space.current_duel_index + 1}")
                self._frame.started = False
                yield from self._play_slot(slot, pipes)
                self.game.context.expire_lasting_entries(slot)
            self._closed_slots.add(slot)
            space.current_duel_index += 1

    def _ordered_players(self):
        return sorted(self.game.players, key=lambda p: p is not self.game.first_player)

    def _play_slot(self, slot, pipes):
        for pipe in pipes:
            pipe.push_pack(steps.DUEL)
        yield from self._run_to(pipes, steps.NEXT_CARD)

        while True:
            # The remaining die waits here while its opponent changes skills.
            # A side with no skill left is idle, so it cannot block a solo die.
            # An effect may have placed a skill for a previously empty side.
            joiners = [p for p in self.side_pipelines.values()
                       if p not in pipes and slot.next_playable_card(p.side)]
            if joiners:
                for pipe in joiners:
                    pipe.push_pack(steps.DUEL)
                yield from self._run_to(joiners, steps.NEXT_CARD)
                pipes[:] = [p for p in self.side_pipelines.values() if p in pipes or p in joiners]
            entering = [p for p in pipes if p.is_blocked_at(steps.NEXT_CARD) and slot.next_playable_card(p.side)]
            if entering:
                frame = self._frame
                frame.before_use_sides = {p.side for p in entering}
                yield tuple("before_skill_choice" if p.side in frame.before_use_sides else None
                            for p in self.game.players)
                frame.before_use_sides.clear()
                entrants = []
                for pipe in entering:
                    card = slot.next_playable_card(pipe.side)
                    if card is None:
                        continue
                    pipe.card = card
                    pipe.paid = None
                    pipe.withdrawn = pipe.used = False
                    pipe.opposing_card = None
                    pipe.target = (slot.resolve_target_character(pipe.side)
                                   if frame.interrupt or frame.space is self.game.pre_reveal.space else None)
                    pipe.push_pack(steps.SKILL)
                    entrants.append(pipe)
                if entrants:
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
                yield from self._run_to(spent, steps.NEXT_CARD)
                for pipe in spent:
                    if not pipe.withdrawn:
                        slot.finish_card(pipe.side, pipe.card)
                    pipe.card = pipe.die = None
                continue
            if not ready:
                break

            yield from self._play_round(ready)
            for pipe in ready:
                if self._card_live(pipe):
                    pipe.card.advance_die()
                pipe.die = None
            self._frame.pair = None
            self._frame.results = {}

        self._closed_slots.add(slot)
        yield from self._run_to(pipes, steps.NEXT_DUEL)
        for cards in slot.content.values():
            for card in cards:
                card.set_range_opponent(None)

    def _start_skills(self, pipes, entrants):
        current = [p for p in pipes if self._card_live(p)]
        for pipe in current:
            pipe.card.set_range_opponent(None)
        if len(current) == 2:
            far, near = sorted(current, key=lambda p: p.card.range_level, reverse=True)
            if far.card.range_level > near.card.range_level + near.card.ignore_range:
                # A card must actually pay before it can blank the opposing
                # pre-use and fee entries. Its price hooks can still alter or cancel payment.
                if far in entrants:
                    yield from self._run_to([far], "logic_skill_use")
                if far.paid and self._card_live(far) and self._card_live(near):
                    near.card.set_range_opponent(far.card)
                    if near.card.range_deficit:
                        print(f"「{far.card.name}」对「{near.card.name}」有 {near.card.range_deficit} 级远程优势。")
                if near in entrants:
                    yield from self._run_to([near], "logic_skill_use")
        yield from self._run_to(entrants, steps.NEXT_DIE)

    def _card_live(self, pipe):
        return (pipe.card is not None and not pipe.withdrawn and pipe.card.character.is_alive
                and not pipe.card.destroyed and pipe.card.state != CardState.NEGATED
                and pipe.card in self._get_current_duel().get_content(pipe.side))

    def _die_live(self, pipe):
        return self._card_live(pipe) and pipe.die is not None and not pipe.die.destroyed

    def _next_live_die(self, pipe):
        if self._card_live(pipe) and pipe.paid:
            while (die := pipe.card.get_current_die(self.game)) is not None:
                if not die.destroyed:
                    return die
                pipe.card.advance_die()
        return None

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
            if pipe.card.range_deficit >= 3 or (len(ready) == 1 and pipe.die.is_attack
                                                and pipe.card.range_deficit >= 2):
                pipe.die.make_blank()
        for pipe in ready:
            if pipe.die.is_attack and self._die_live(pipe):
                self.game.context.dispatch_pipeline("before_dice_pair", **self._event(pipe))
        routed = any(p.die.attack_redirected for p in ready)
        if routed:
            for pipe in ready:
                if pipe.card.range_deficit >= 2 and pipe.die.is_attack:
                    pipe.die.make_blank()
        can_pair = len(ready) == 2 and not routed and not all(p.die.is_passive for p in ready)
        if can_pair:
            self._frame.pair = ClashPair({p.side: p.die for p in ready})
        active = []
        stops = {}
        for pipe in ready:
            die = pipe.die
            if can_pair or (die.is_attack and (not die.attack_redirected
                                               or die.attack_target and die.attack_target.is_alive)):
                pipe.push_pack(steps.DICE)
                active.append(pipe)
                stops[pipe.side] = steps.CAN_CLASH
            else:
                die.clash_result = "skip"
                pipe.push_pack(steps.SKIPPED_DICE)
                stops[pipe.side] = steps.NEXT_DIE
        if not active:
            print("本轮跳过拼点。")
        yield from self._run_to(ready, stops)
        if can_pair:
            yield from self._clash(active)
        else:
            for pipe in active:
                if self._die_live(pipe):
                    yield from self._solo(pipe)
        yield from self._run_to(active, steps.NEXT_DIE)

    def _solo(self, pipe):
        if pipe.card.range_deficit >= 2 and pipe.die.is_attack:
            pipe.die.make_blank()
        if not pipe.die.is_attack:
            pipe.die.clash_result = "skip"
            pipe.push_pack(steps.PASSIVE_SKIP)
            yield from self._run_to([pipe], "on_clash_skip")
        else:
            with self.game.context.binding(**self._event(pipe)):
                pipe.die.resolve_level()
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
            live = [p for p in participants if self._die_live(p)]
            if results and len(live) == 2:
                pair = self.current_clash_pair
                difference = abs(live[0].die.clash_score - live[1].die.clash_score)
                for p in live:
                    if pair.split or not all(self._die_live(other) for other in live):
                        break
                    self.game.context.dispatch_pipeline("before_clash_result", **self._event(p),
                                                        prospective_result=results[p.side],
                                                        clash_difference=difference)
                if pair.split:
                    print("双方改为单方面攻击，按拼点点数依次命中。")
                    # The pipes are already in initiative order, which breaks score ties.
                    for p in sorted(live, key=lambda p: p.die.clash_score, reverse=True):
                        if self._die_live(p):
                            if p.card.range_deficit >= 2 and p.die.is_attack:
                                p.die.make_blank()
                            yield from self._hit(p)
                    results = None
                live = [p for p in live if self._die_live(p)]
        if len(live) == 1 and not self.current_clash_pair.split:
            # A formed pair lost its die before a result. The vanished side has
            # no result at all, including skip. Only the survivor enters a branch.
            results = {live[0].side: "win"}
            print(f"空白轮：对位骰消失，{live[0].card.character.combat_name} 拼点胜利。")
        if results and live:
            yield from self._resolve_results(live, results)
        yield from self._run_to(participants, "after_dice_clash")

    def _resolve_results(self, live, results):
        self._frame.results = results
        labels = {"win": "胜", "lose": "负", "draw": "平"}
        winner = next((p for p in live if results[p.side] == "win"), None)
        if winner and winner.card.range_deficit >= 2:
            winner.die.win_branch_skipped = True
            labels["win"] = "胜，跳过胜利分支"
            if len(live) == 1:
                print(f"{winner.card.character.combat_name} 受远程压制，跳过拼赢分支。")
        if len(live) == 2:
            print("拼点 " + " · ".join(
                f"{p.card.character.combat_name} {TYPE_NAMES[p.die.type]} 最终 {p.die.final_score} → "
                f"拼点 {p.die.clash_score}（{labels[results[p.side]]}）"
                for p in live))
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

    def _hit(self, pipe):
        split = self.current_clash_pair and self.current_clash_pair.split
        if (not self._die_live(pipe) or pipe.card.range_deficit
                or not (pipe.die.is_attack or split and pipe.die.is_passive)):
            return
        target = pipe.die.attack_target if pipe.die.attack_redirected else self.resolve_skill_target(pipe.card)
        if target is None or not target.is_alive:
            return
        if not self.current_clash_pair:
            print(f"单方面攻击：{pipe.card.character.combat_name} → {target.combat_name}")
        pipe.push_pack(steps.HIT)
        yield from self._run_to([pipe], "after_dice_hit")

    def _run_to(self, pipes, stops):
        """Run selected sides in initiative order; others keep their exact position."""
        remaining = list(pipes)
        for pipe in remaining:
            pipe.unblock()
        while remaining:
            actions = {}
            for pipe in list(remaining):
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
        if pipe.die is not None and pipe.die.attack_redirected:
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
        # The skip packet's last wait is internal bookkeeping. A skipped die may
        # only trigger its explicit skip effect, not any other dice event.
        if pipe.die and pipe.die.clash_result == "skip" and name != "on_clash_skip":
            return None
        if name in ("logic_dice_clash", "on_dice_clash", steps.RESULT):
            if not all(self._die_live(self.side_pipelines[s]) for s in self.current_clash_pair.dice_dict):
                return None
        event = self._event(pipe)
        if not name.startswith("logic_"):
            if name == "on_skill_use":
                pipe.used = True
            self.game.context.dispatch_pipeline(name, **event)
        elif name == "logic_duel_start" and not self._frame.started:
            self._frame.started = True
            for player in self._ordered_players():
                for char in player.characters:
                    if char.is_alive and not self.game.is_over:
                        char.on_duel_start()
        elif name == "logic_skill_use":
            with self.game.context.binding(**event):
                payment = self.game.context.eval_block([pipe.card, pipe.card.cost, OpCode.PAY_COST])
            pipe.paid = payment is True
            if pipe.paid:
                self.game.used_cards.append(pipe.card)
                print(f"{pipe.card.character.combat_name} 使用「{pipe.card.name}」（牌面 {pipe.card.cost} 费）")
            elif payment is None:
                print(f"「{pipe.card.name}」的支付被取消，跳过该技能。")
            else:
                print(f"{pipe.card.character.combat_name} 未能支付「{pipe.card.name}」的费用，跳过该技能。")
        elif name == "logic_dice_clash":
            with self.game.context.binding(**event):
                pipe.die.roll()
        elif name == "logic_dice_hit" and event["target"] and event["target"].is_alive:
            self.game.context.resolve_hit(**event)
        return name
