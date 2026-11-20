"""闻笙对安诺琳。用 python -m tests.test_special_elite --replay 复盘这场标准对局。"""

import io
import random
import sys
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.character import Character
from pipeline.pipeline_errors import PipelineFinished
from player.player import Player


class ReplayPlayer(Player):
    def place_card(self, game):
        character = self.characters[0]
        if self.side == 1:
            priorities = ("对手戏",) if game.turn_number == 1 else ("谢幕枪", "救场", "点名上场", "对手戏")
        else:
            priorities = ("漂泊剑法", "剑携涡流", "翠流迸发", "流风习习", "飘流翠风")
        remaining = character.available_cost + self.available_cost
        remaining -= sum(card.cost for slot in game.duelspace.space for card in slot.get_content(self.side))
        card = next((c for name in priorities for c in self.cardspace.hand.content
                     if c.name == name and c.cost <= remaining), None)
        if card is None or character.used_duels >= character.max_duels:
            print(f"〔决策〕{character.name}结束常规置卡。")
            return "ended"
        if not game.auto_place_in_duel(self.side, card):
            raise AssertionError("常规置卡未成功")
        print(f"〔决策〕{character.name}扣置「{card.name}」（赛后公开）。")
        return "placed"


def theatre_match(left, right, seed, *, shuffle=True):
    game = Game([left, right], rng=random.Random(seed))
    pool = {c["name"]: c for c in load_characters_from_packs()}
    for player, name in ((left, "闻笙"), (right, "安诺琳")):
        character = Character(pool[name], player)
        player.characters.append(character)
        character.init_cards()
        character.setup_deck()
        if shuffle:
            player.cardspace.draw.shuffle(game.rng)
    return game


def replay():
    seed = 1125
    left, right = ReplayPlayer(1, "余烬剧团"), ReplayPlayer(2, "PlanB")
    game = theatre_match(left, right, seed)
    print(f"闻笙 对 安诺琳　标准单人队伍　随机种子 {seed}")
    print("复盘命令　python -m tests.test_special_elite --replay")
    lead, rival = left.characters[0], right.characters[0]
    decisions = set()

    def choose(label, player, kind, card_name=None, target_name=None):
        if label in decisions:
            return
        for action in game.special.options(player):
            if action.kind != kind or (card_name and action.card.name != card_name):
                continue
            if target_name and (action.target_card is None or action.target_card.name != target_name):
                continue
            if kind == "attack" and action.character is not rival:
                continue
            description = label + (f"「{action.card.name}」" if action.card else "")
            if action.target_card:
                description += f"替下「{action.target_card.name}」"
            print(f"〔决策〕{player.characters[0].name}选择{description}。")
            actor = action.card.character
            previous_duels = actor.used_duels
            if not game.special.apply(player, action):
                raise AssertionError(f"所选操作未生效：{description}")
            if kind == "place":
                print(f"〔交锋额度〕{actor.name}已用常规交锋 {previous_duels}/{actor.max_duels}"
                      f" → {actor.used_duels}/{actor.max_duels}。")
            if kind == "attack":
                if game.special.pending_attacks or game.pipeline.interrupt_space is None:
                    raise AssertionError("场内「飞场」应直接开始即时交锋。")
                print("〔战场〕「飞场」未开启迎击窗口。")
            decisions.add(label)
            return

    def decline_turn_attacks():
        while game.pre_reveal.attacker is not None:
            game.pre_reveal.end_attack()
    game.run_pre_reveal_declarations = decline_turn_attacks
    for _ in range(18000):
        if game.is_over:
            print(f"〔终局〕第 {game.turn_number} 回合，{game.winner.characters[0].name}获胜。"
                  f"闻笙 {lead.hp}/{lead.max_hp}，安诺琳 {rival.hp}/{rival.max_hp}。")
            return game, decisions
        interrupt = game.pipeline.interrupt_space
        try:
            node = game.next_step()
        except PipelineFinished:
            game.pipeline.current_step_index = -1
            game.pipeline.is_finished = False
            continue
        if game.is_over:
            continue
        if interrupt is not None and game.pipeline.interrupt_space is None and game.pipeline.in_duel_phase:
            print(f"〔战场〕即时交锋结束，恢复常规交锋 {game.duelspace.current_duel_index + 1}。")
        if isinstance(node, tuple):
            for player, event in zip(game.players, node):
                if event == "logic_skill_use":
                    actor = player.characters[0]
                    print(f"〔费用〕{actor.name}尚余个人费 {actor.available_cost}，通用费 {player.available_cost}。")
        if game.turn_number == 1 and game.cards_revealed:
            if "before_skill_choice" in node:
                choose("换卡机会", left, "replace", "点名上场", "对手戏")
            if lead.statuses.get("置卡机会", 0):
                choose("置卡机会", left, "place", "谢幕枪")
            if "on_dice_clash" in node:
                choose("拼点判定前救场", left, "replace", "救场", "点名上场")
        elif game.turn_number >= 2 and game.cards_revealed and "on_skill_use" in node:
            choose("即时主动进攻", left, "attack", "飞场")
    raise AssertionError("对局未能在规定步数内结束")


class UnderstudyTests(unittest.TestCase):
    def test_call_grants_optional_placement_and_unused_opportunities_expire(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = theatre_match(left, right, 27, shuffle=False)
        game.first_player = left
        actor = left.characters[0]
        with redirect_stdout(io.StringIO()):
            game.start_turn()
            game.context.dispatch_pipeline("on_turn_start")
            self.assertEqual([c.name for c in left.cardspace.hand.content], ["点名上场"])
            self.assertEqual(actor.statuses.get("换卡机会"), 1)
            left.draw_card(1)
            game.auto_place_in_duel(1, left.cardspace.hand.content[0])
            game.reveal_cards()
            game.pipeline.start_duel_combat()
            for _ in range(200):
                if not game.pipeline.in_duel_phase:
                    break
                game.next_step()
            self.assertFalse(game.pipeline.in_duel_phase)
            self.assertEqual(actor.statuses.get("置卡机会"), 1)
            self.assertEqual([c.name for c in left.cardspace.hand.content], ["飞场"])
            game.finish_turn()
        self.assertNotIn("置卡机会", actor.statuses)
        self.assertNotIn("换卡机会", actor.statuses)

    def test_entrance_can_take_an_open_slot_without_placement_opportunity(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = theatre_match(left, right, 27, shuffle=False)
        game.first_player = left
        with redirect_stdout(io.StringIO()):
            game.start_turn()
            left.draw_card(2)
            right.draw_card(1)
            game.auto_place_in_duel(right.side, right.cardspace.hand.content[0])
            placements = [a for a in game.special.options(left) if a.kind == "place"]
            self.assertEqual([(a.card.name, a.duel_index) for a in placements], [("飞场", 0)])
            self.assertTrue(game.special.apply(left, placements[0]))
        first_slot = game.duelspace.space[0]
        self.assertEqual([c.name for c in first_slot.get_content(1)], ["飞场"])
        self.assertEqual([c.name for c in first_slot.get_content(2)], ["漂泊剑法"])
        self.assertEqual(left.characters[0].used_duels, 1)

    def test_printed_match_runs_from_normal_decks_to_victory(self):
        with redirect_stdout(io.StringIO()) as output:
            game, decisions = replay()
        self.assertEqual(decisions, {"换卡机会", "置卡机会", "拼点判定前救场", "即时主动进攻"})
        record = output.getvalue()
        self.assertIn("闻笙已用常规交锋 1/2 → 2/2", record)
        blank = record.index("空白轮")
        returned = record.index("「点名上场」回手")
        new_use = record.index("使用「救场」")
        self.assertLess(returned, blank)
        self.assertLess(blank, new_use)
        self.assertIn("闻笙尚余个人费 0，通用费 3", record[new_use:record.index("闻笙 的普通护盾")])
        instant_start = record.index("结算即时交锋 1")
        resumed = record.index("即时交锋结束，恢复常规交锋 1", instant_start)
        self.assertIn("闻笙 使用「飞场」", record[instant_start:resumed])
        self.assertIn("单方面攻击：闻笙 → 安诺琳", record[instant_start:resumed])
        self.assertIn("拼点 ", record[resumed:record.index("\n交锋 2", resumed)])
        self.assertTrue(game.is_over)
        self.assertIsNotNone(game.winner)


if __name__ == "__main__":
    if sys.argv[1:] == ["--replay"]:
        replay()
    else:
        unittest.main()
