"""Hot-seat presentation and input at the application's composition root."""

import sys
from contextlib import contextmanager
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from player.target_order import TargetOrder

from terminal_events import format_fact

from pre_reveal_cli import run_declarations
from models.card import describe_entry, describe_skill_traits
from models.character import Character, CharacterRank
from models.dice import describe_die
from models.roster import RosterDraft


class TerminalBridge:
    def __init__(self, game, *, special_prompt=None):
        self.game = game
        self.special_prompt = special_prompt
        self._private_player = None
        self._facts = None
        self._executor = None

    @contextmanager
    def session(self):
        with ThreadPoolExecutor(max_workers=1) as executor, self.game.context.collect_facts() as facts:
            self._executor, self._facts = executor, facts
            try:
                yield
            finally:
                self.flush()
                self._executor = self._facts = None

    def execute(self, command, *args, **kwargs):
        """Drive a synchronous kernel command, answering target reservations on the terminal thread."""
        if self._executor is None:
            return command(*args, **kwargs)
        orders = {}
        previous = {player: player.target_order for player in self.game.players}

        def reserve(player):
            order = TargetOrder()
            orders[player] = order
            player.target_order = order

        for player in self.game.players:
            reserve(player)
        try:
            task = self._executor.submit(command, *args, **kwargs)
            while True:
                offers = {order.offered: (player, order) for player, order in orders.items()}
                ready, _ = wait([task, *offers], return_when=FIRST_COMPLETED)
                if task in ready:
                    return task.result()
                for offer in ready:
                    player, order = offers[offer]
                    try:
                        target = self.choose_target(player, offer.result())
                        reserve(player)
                        order.submit(target)
                    except BaseException:
                        order.cancel()
                        raise
        finally:
            for player, order in orders.items():
                order.cancel()
                player.target_order = previous[player]

    def choose_target(self, player, choice):
        self.flush()
        print(f"{player.name} 选择单方面攻击的目标：")
        for number, character in enumerate(choice.candidates, 1):
            print(f"  [{number}] {character.combat_summary()}")
        while True:
            answer = input(f"输入编号，回车选 {choice.default.name}，set 编号可更改默认目标 ").strip()
            if not answer:
                return choice.default
            persistent = answer.lower().startswith("set ")
            number = answer[4:].strip() if persistent else answer
            if number.isdecimal() and 1 <= int(number) <= len(choice.candidates):
                target = choice.candidates[int(number) - 1]
                if persistent:
                    player.set_default_target(target)
                    print(f"{player.name} 的默认目标已设为 {target.name}。")
                return target
            print("请输入存活目标的编号。")

    def flush(self):
        while self._facts:
            message = format_fact(*self._facts.popleft())
            if message:
                print(message)

    def select_character(self, characters):
        draft = RosterDraft(characters, len(self.game.players), self.game.gamerule.MAX_CHAR_COUNT)
        for player in self.game.players:
            pool = draft.pool.copy()
            limit = draft.limit
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
            draft.submit(roster)

        self.game.deploy_rosters(draft.teams)

    @staticmethod
    def character_summary(data):
        rank = CharacterRank[data["rank"]]
        label = {"NORMAL": "常人", "ELITE": "精英", "BOSS": "Boss", "EMPOWERED_BOSS": "强化 Boss",
                 "EXTREME": "极端战力"}[rank.name]
        title = f"　{data['title']}" if data.get("title") else ""
        integrity = Character.initial_lightcore_max(data["max_hp"])
        return (f"{data['name']}{title}　{label}　生命 {data['max_hp']}　完整度 {integrity}"
                f"　最多 {Character.base_duels(data)} 交锋")

    @staticmethod
    def show_character(data):
        print(TerminalBridge.character_summary(data))
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
        for printed in data["skills"]:
            TerminalBridge.show_skill(printed)
            for form in printed.get("forms", {}).values():
                TerminalBridge.show_skill({**printed, **form})

    @staticmethod
    def show_skill(skill):
        dice = " → ".join(describe_die(die) for die in skill.get("dice", []))
        entries = "；".join(describe_entry(entry) for entry in skill.get("entries", []))
        zone = "战斗外" if skill.get("out_of_combat") else ""
        print("  " + " · ".join(s for s in (skill["name"], f"{skill['cost']} 费",
                                              describe_skill_traits(skill), dice, entries, zone) if s))

    def settle_draws(self):
        while self.game.pending_draw is not None:
            choice = self.game.pending_draw
            player = choice.player
            candidates, discard_count = choice.candidates, choice.discard_count
            self.begin_private_view(player)
            print(f"{player.name} 从 {len(candidates)} 张候选牌中选 {discard_count} 张置于牌堆底。")
            for number, card in enumerate(candidates, 1):
                print(f"  [{number}] {card.character.name} · {card.describe()}")
            while True:
                raw = input("输入弃置编号，多个编号以空格或逗号隔开 ").strip()
                values = raw.replace("，", " ").replace(",", " ").split()
                if len(values) == discard_count and all(value.isdecimal() for value in values):
                    indices = [int(value) - 1 for value in values]
                    if len(set(indices)) == discard_count and all(0 <= i < len(candidates) for i in indices):
                        break
                print(f"请选择 {discard_count} 个不同的有效编号。")
            self.execute(self.game.complete_draw, choice, [candidates[index] for index in indices])

    def begin_private_view(self, player):
        """同屏轮换时清除上一位玩家的手牌，再邀请下一位玩家接手。"""
        self.flush()
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

    def offer_special_actions(self):
        """Blocking decisions inside the CLI's otherwise synchronous placement loops."""
        game = self.game
        if self.special_prompt is None or game.is_over:
            return
        self.special_prompt(self)
        self.flush()
        while not game.is_over and (game.special.pending_attack is not None or game.special.decision_owner is not None
                                    or game.pipeline.interrupt_space is not None):
            if game.special.pending_attack is None and game.special.decision_owner is None:
                self.advance()
            if not game.is_over:
                self.special_prompt(self)

    def advance(self):
        game = self.game
        action = self.execute(game.next_step)
        self.flush()
        if action == "logic_draw_cards":
            self.settle_draws()
            self.close_private_view()
        elif action == "logic_start_placement":
            while game.placing is not None and not game.is_over:
                player = game.placing
                self.begin_private_view(player)
                self.offer_special_actions()
                if game.is_over:
                    break
                self.begin_private_view(player)
                self.place_card(player)
            self.close_private_view()
        elif action == "logic_before_reveal_declarations":
            self.declare_attacks()
        return action

    def declare_attacks(self):
        if self.game.pre_reveal.actor is not None:
            run_declarations(self)

    def place_card(self, player):
        game = self.game
        hand = player.cardspace.hand.content
        if not game.legal_placements():
            print(f"{player.name} 没有可置入的牌，结束本轮置卡。")
            return self.execute(game.submit_placement, player, after="end")
        slot_number = game.duelspace.locate_nearest_empty_duel(player.side) + 1
        print(f"\n{player.name} 置卡 · 交锋 {slot_number}　通用费 {player.available_cost}")
        opposing = next(p for p in game.players if p is not player)
        for seat in (player, opposing):
            status = "；".join(f"{c.combat_summary()}，交锋 {c.used_duels}/{c.max_duels}"
                              for c in seat.characters if c.is_alive)
            print(f"{seat.name}（牌堆 {len(seat.cardspace.draw.content)}，手牌 {len(seat.cardspace.hand.content)}）：{status}")
        for number, slot in enumerate(game.duelspace.space, 1):
            own = "、".join(card.name for card in slot.content.get(player.side, ())) or "空"
            opposing_cards = slot.content.get(opposing.side, ())
            opposing_count = len(opposing_cards)
            hidden = f"扣置 {opposing_count} 张" if opposing_count else "空"
            public = [c.name for c in opposing_cards if c.state.name == "PLACED_FACE_UP"]
            if public:
                hidden = "、".join(public + ["扣置牌"] * (opposing_count - len(public)))
            print(f"交锋 {number}　己方 {own}　对方 {hidden}")
        for number, card in enumerate(hand, 1):
            char = card.character
            print(f"  [{number}] {char.name} · {card.describe()}　个人费 {char.available_cost}")
        while True:
            extra = "，pass 暂交置卡权" if game.placed_this_window else ""
            answer = input(f"输入手牌编号，回车结束本轮置卡{extra} ").strip().lower()
            if answer == "pass" and game.placed_this_window:
                return self.execute(game.submit_placement, player, after="pass")
            if answer in ("", "end"):
                if not input("再按回车确认结束本轮置卡，输入其他内容取消 ").strip():
                    print(f"{player.name} 结束本轮置卡。")
                    return self.execute(game.submit_placement, player, after="end")
                continue
            if not answer.isdecimal() or not 1 <= int(answer) <= len(hand):
                print("请输入有效的手牌编号。")
                continue
            card = hand[int(answer) - 1]
            if card not in game.legal_placements():
                print("这张手牌当前无法扣置，请选其他牌。")
                continue
            confirm = input("输入 y 扣置、pass 扣置并交权、end 扣置并结束本轮，回车取消 ").strip().lower()
            if confirm not in ("y", "yes", "pass", "end"):
                continue
            after = confirm if confirm in ("pass", "end") else "continue"
            if not self.execute(game.submit_placement, player, card, after=after):
                print("此次置卡未生效。")
                return
            print(f"{player.name} 已在第 {slot_number} 交锋扣置一张牌。")
            return
