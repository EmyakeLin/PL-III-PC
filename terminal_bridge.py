"""Hot-seat presentation and input at the application's composition root."""

from models.card import describe_entry, describe_skill_traits
from models.character import Character, CharacterRank
from models.dice import describe_die
from models.roster import RosterDraft


class TerminalBridge:
    def __init__(self, game):
        self.game = game

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
        label = {"NORMAL": "常人", "ELITE": "精英", "BOSS": "Boss", "EMPOWERED_BOSS": "强化 Boss"}[rank.name]
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
            self.game.begin_private_view(player)
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
            self.game.complete_draw(choice, [candidates[index] for index in indices])
