import random
import sys
from types import SimpleNamespace

from context.context import Context
from gamerule import GameRule
from loader import base_effects
from models.card import CardState, describe_entry, describe_skill_traits
from models.character import Character, CharacterRank
from models.dice import describe_die
from models.duel import DuelSpace
from models.opcode import OpCode
from models.pre_reveal import PreRevealPhase
from models.special_actions import SpecialActions
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
        self.used_cards = []
        self.used_skill_ids = set()
        self.cards_revealed = False
        self.turn_count = 0
        self.turn_number = 0
        self.turn_ending = False
        self.card_serial = 0
        self._prepared_turn = -1
        self.next_turn_statuses = []
        effects = base_effects()
        self.status_entries = dict(effects.status_entries)
        self.status_rules = dict(effects.status_rules)
        self.ability_rules = dict(effects.ability_rules)
        self._overflow_settled_turn = -1
        self.turn_end_statuses = set(effects.turn_end_statuses)
        self.is_over = False
        self.winner = None
        self._private_player = None
        self.context = Context(game=self)
        self.duelspace = DuelSpace(self)
        self.pre_reveal = PreRevealPhase(self)
        self.pipeline = Pipeline(self, step_list)
        self.special = SpecialActions(self)
        self.special_prompt = None
        self.last_step = None
        self.tmp = SimpleNamespace()

    def select_character(self, characters):
        pool = list(characters)
        if len(pool) < len(self.players) and not any(c.get("mirror_allowed") for c in pool):
            raise ValueError("共享角色池至少需要两名角色，才能为双方各留一名。")
        rosters = []
        for index, player in enumerate(self.players):
            reserve = 0 if any(c.get("mirror_allowed") for c in pool) else len(self.players) - index - 1
            limit = min(self.gamerule.MAX_CHAR_COUNT, len(pool) - reserve)
            roster = []
            while len(roster) < limit:
                print(f"\n{player.name} 选人（已选 {len(roster)}，本次最多 {limit} 人）")
                for number, data in enumerate(pool, 1):
                    print(f"  [{number}] {self.character_summary(data)}")
                answer = input("请输入角色编号，? 编号查看技能；选好后按回车确定 ").strip()
                if answer.startswith("?"):
                    number = answer[1:].strip()
                    if number.isdecimal() and 1 <= int(number) <= len(pool):
                        self.show_character(pool[int(number) - 1])
                    continue
                if not answer and roster:
                    break
                if answer.isdecimal() and 1 <= int(answer) <= len(pool):
                    roster.append(pool.pop(int(answer) - 1))
                else:
                    print("请至少选一名角色，并输入列表中的编号。")
            print(f"{player.name} 出战：" + "、".join(data["name"] for data in roster))
            rosters.append(roster)
            pool.extend(spec for spec in roster if spec.get("mirror_allowed"))

        for player, roster in zip(self.players, rosters):
            for data in roster:
                character = Character(data, player)
                player.characters.append(character)
                character.init_cards()
                character.setup_deck()
            player.cardspace.draw.shuffle(self.rng)

    @staticmethod
    def character_summary(data):
        rank = CharacterRank[data["rank"]]
        label = {"NORMAL": "常人", "ELITE": "精英", "BOSS": "Boss", "EMPOWERED_BOSS": "强化 Boss"}[rank.name]
        title = f"　{data['title']}" if data.get("title") else ""
        integrity = Character.initial_lightcore_max(data["max_hp"])
        return (f"{data['name']}{title}　{label}　生命 {data['max_hp']}　完整度 {integrity}"
                f"　最多 {Character.base_duels(data)} 交锋")

    @staticmethod
    def show_character(data):
        print(Game.character_summary(data))
        if data.get("faction"):
            print(f"所属阵营　{data['faction']}")
        for key, label in (("faction_passives", "阵营被动"), ("passive_skills", "角色被动")):
            for passive in data.get(key, []):
                name = passive.get("name", "") if isinstance(passive, dict) else ""
                entries = passive.get("entries", [passive]) if isinstance(passive, dict) else [passive]
                if not entries and passive.get("description"):
                    entries = [passive["description"]]
                for entry in entries:
                    print("  " + " · ".join(part for part in (label, name, describe_entry(entry)) if part))
        for skill in data["skills"]:
            dice = " → ".join(describe_die(die) for die in skill.get("dice", []))
            entries = "；".join(describe_entry(entry) for entry in skill.get("entries", []))
            zone = "战斗外" if skill.get("out_of_combat") else ""
            print("  " + " · ".join(s for s in (skill["name"], f"{skill['cost']} 费",
                                                  describe_skill_traits(skill), dice, entries, zone) if s))

    def begin_private_view(self, player):
        """同屏轮换时清除上一位玩家的手牌，再邀请下一位玩家接手。"""
        if self._private_player is player:
            return
        self._private_player = player
        if sys.stdin.isatty() and sys.stdout.isatty():
            print("\033[2J\033[3J\033[H", end="", flush=True)
            input(f"请把终端交给 {player.name}，接手后按回车查看自己的牌。")

    def close_private_view(self):
        if self._private_player is not None and sys.stdin.isatty() and sys.stdout.isatty():
            print("\033[2J\033[3J\033[H", end="", flush=True)
        self._private_player = None

    def next_step(self):
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

    def offer_special_actions(self):
        """Blocking decisions inside the CLI's otherwise synchronous placement loops."""
        if self.special_prompt is None or self.is_over:
            return
        self.special_prompt(self)
        while not self.is_over and (self.special.pending_attack is not None or self.special.decision_owner is not None
                                    or self.pipeline.interrupt_space is not None):
            if self.special.pending_attack is None and self.special.decision_owner is None:
                self.next_step()
            if not self.is_over:
                self.special_prompt(self)

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
        self.run_pre_reveal_declarations()

    def run_pre_reveal_declarations(self):
        if self.pre_reveal.actor is not None:
            from pre_reveal_cli import run_declarations
            run_declarations(self)

    def open_turn(self):
        number = self.turn_count + 1
        if self.turn_number != number:
            self.turn_number = number
            self.turn_ending = False
            self.context.turn_entry_uses.clear()
            self.used_skill_ids.clear()

    def prepare_turn(self):
        self.open_turn()
        if self._prepared_turn == self.turn_count:
            return
        self._prepared_turn = self.turn_count
        pending, self.next_turn_statuses = self.next_turn_statuses, []
        for player in self.players:
            player.turn_common_cost_bonus, player.next_turn_common_cost = player.next_turn_common_cost, 0
            player.lost_duels.clear()
            for char in player.characters:
                char.won_clash_this_turn = False
                char.turn_duel_bonus, char.next_turn_duels = char.next_turn_duels, 0
        for source, target, name, amount, authority in pending:
            if target.is_alive and not self.is_over:
                with self.context.binding(source=source, target=target, side=source.player.side, authority=authority):
                    self.context.eval_block([target, name, amount, OpCode.STATUS])

    def record_clash_result(self, character, result):
        if result == "win":
            character.won_clash_this_turn = True
        elif result == "lose":
            character.player.lost_duels.add(self.duel_position())

    def draw_phase(self):
        self.prepare_turn()
        print(f"\n第 {self.turn_count + 1} 回合")
        self.cards_revealed = False
        self._private_player = None
        for player in self.players:
            if self.is_over:
                break
            player.draw_for_turn()

    def start_turn(self):
        self.prepare_turn()
        for player in sorted(self.players, key=lambda p: p is not self.first_player):
            player.reset_on_turn_start()

    def determine_first_player(self):
        self.prepare_turn()
        self.close_private_view()
        left, right = self.players
        while True:
            for player in self.players:
                player.calculate_speed()
                members = "、".join(f"{char.name} {char.speed:g}" for char in player.characters if char.is_alive)
                print(f"{player.name} 速度：{members}；阵营速度 {player.speed:g}。")
            if left.speed != right.speed:
                self.first_player = left if left.speed > right.speed else right
                print(f"{self.first_player.name} 先手。")
                return
            print("速度相同，双方重掷。")

    def switch_place_right(self):
        self.placing = next(
            (p for p in self.players if p is not self.placing and p not in self.ended_player),
            self.placing if self.placing not in self.ended_player else None,
        )

    def run_placement(self):
        self.placing = self.first_player
        capacity = 1
        while self.placing is not None and not self.is_over:
            player = self.placing
            self.placed_this_window = 0
            self.begin_private_view(player)
            for _ in range(capacity):
                self.offer_special_actions()
                if self.is_over:
                    return
                self.begin_private_view(player)
                action = player.place_card(self)
                if action == "ended":
                    self.ended_player.append(player)
                    break
                if action == "passed":
                    break
                if action != "placed":
                    raise ValueError(f"未知置卡动作 {action!r}")
                self.placed_this_window += 1
                if self.is_over:
                    break
            self.switch_place_right()
            capacity = self.gamerule.PLACE_CAPACITY

    def auto_place_in_duel(self, side, content):
        owner = content.character
        if self.pre_reveal.phase != "idle" or owner is None or owner.used_duels >= owner.max_duels:
            return False
        return self.place_in_duel(side, content, self.duelspace.locate_nearest_empty_duel(side))

    def place_in_duel(self, side, content, duel_idx, *, special=False, queued=False):
        # Once regular placement closes, only an executing rule effect may insert a card.
        if self.pre_reveal.phase != "idle" and not special and not queued and not self.context.executions:
            return False
        player = content.player
        owner = content.character
        if player.side != side or duel_idx < 0 or not owner.is_alive:
            return False
        if any(content in slot.content.get(side, ()) for slot in self.board_slots()):
            return False
        zones = player.cardspace
        old_zone = next((zone for zone in (zones.hand, zones.draw, zones.delayed_discard,
                                            zones.out_of_combat) if content in zone.content), None)
        event = dict(side=side, source=owner, card=content)
        self.context.dispatch_pipeline("before_place", **event)
        if not owner.is_alive or content.state == CardState.NEGATED:
            return False
        if old_zone is not None and content not in old_zone.content:
            return False
        space = self.duelspace if special or queued else self.active_duelspace
        if queued and (content not in zones.hand.content or duel_idx >= len(space.space)
                       or not self.pipeline.can_join(space.space[duel_idx])):
            return False
        with self.context.binding(special_placement=content if special else None,
                                  queued_placement=content if queued else None):
            placed = self.context.eval_block([side, duel_idx, content, OpCode.PLACE])
        if not placed or duel_idx >= len(space.space):
            return False
        slot = space.space[duel_idx]
        if content not in slot.content.get(side, ()):
            return False
        event["duel"] = slot
        self.context.dispatch_pipeline("on_place", **event)
        self.context.dispatch_pipeline("after_place", **event)
        return True

    def reveal_cards(self):
        if self.cards_revealed:
            return
        self.cards_revealed = True
        self.close_private_view()
        if not self.duelspace.space:
            print("双方空过。")
            return
        for slot in self.duelspace.space:
            for cards in slot.content.values():
                for card in cards:
                    if card.state == CardState.PLACED_FACE_DOWN:
                        card.state = CardState.PLACED_FACE_UP
        print("双方开牌。")
        for slot in self.duelspace.space:
            for player in sorted(self.players, key=lambda p: p is not self.first_player):
                for card in tuple(slot.get_content(player.side)):
                    if card.character.is_alive and not card.destroyed:
                        self.context.dispatch_pipeline("on_card_reveal", source=card.character, side=player.side,
                                                       card=card, duel=slot)
        for number, slot in enumerate(self.duelspace.space, 1):
            sides = []
            for player in self.players:
                cards = slot.content.get(player.side, ())
                names = "、".join(card.name for card in cards) or "空"
                sides.append(f"{player.name}：{names}")
            print(f"交锋 {number}　" + "　对　".join(sides))

    def resolve_status_batches(self):
        """Freeze all eligible holders before any end-of-turn batch listener runs."""
        if self.is_over or self._overflow_settled_turn == self.turn_count:
            return
        self._overflow_settled_turn = self.turn_count
        ordered = sorted(self.players, key=lambda player: player is not self.first_player)
        characters = [char for player in ordered for char in player.characters if char.is_alive]
        batches = []
        for name, rule in self.status_rules.items():
            batch = rule.get("overflow_batch")
            if batch:
                targets = tuple(char for char in characters
                                if char.status_overflow.get(name, 0) >= batch["threshold"])
                if targets:
                    batches.append((name, batch, targets))
        for name, batch, targets in batches:
            if self.is_over:
                break
            print(f"{batch.get('label', name)}触发，目标为{'、'.join(c.combat_name for c in targets)}。")
            self.context.dispatch_pipeline(batch["event"], source=None, target=None, card=None, die=None,
                                           side=None, targets=targets, status=name)
            for char in targets:
                char.status_overflow.pop(name, None)
                excess = char.statuses.get(name, 0) - batch["reduce_to"]
                if char.is_alive and excess > 0:
                    char.add_status(name, -excess)

    def finish_turn(self):
        if not self.turn_ending:
            self.context.dispatch_pipeline("before_turn_end")
        if self.is_over:
            return
        ordered = sorted(self.players, key=lambda player: player is not self.first_player)
        for player in ordered:
            for character in player.characters:
                if character.is_alive and not self.is_over:
                    character.on_turn_end()
        for player in ordered:
            for character in player.characters:
                character.reset_shields()
                character.used_duels = 0
                character.turn_duel_bonus = 0
                for status in self.turn_end_statuses:
                    character.clear_status(status)
                character.expire_turn_abilities()
                character.check_death()
            player.turn_common_cost_bonus = 0
            self.context.eval_block([player, 0, 0, OpCode.RESET_COST])

        on_board = [card for slot in self.board_slots() for cards in slot.content.values()
                    for card in cards]
        remaining = set(on_board)
        used = set(self.used_cards)
        for card in [*self.used_cards, *on_board]:
            if card in remaining and card.character.is_alive:
                remaining.remove(card)
                if card in used:
                    # Turn-end entries run after recycling; keep this use's caster
                    # and local state even if the physical card is returned to its owner.
                    self.context.withdraw_card_use(card, None, used=True, scopes=("turn",))
                card.return_to_printed_owner()
                card.player.cardspace.draw.add_card(card)
        for player in self.players:
            player.cardspace.delayed_discard.push_to_draw()
        self.used_cards.clear()
        self.duelspace.space.clear()
        self.duelspace.current_duel_index = 0
        self.pre_reveal = PreRevealPhase(self)
        self.special.clear()
        self.ended_player.clear()
        self.cards_revealed = False
        self.turn_count += 1
        print(f"第 {self.turn_count} 回合结束。")
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
        return True
