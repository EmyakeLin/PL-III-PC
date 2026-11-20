"""Regression scenarios through the real match entry point and combat models."""
import io
import os
import random
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from game import Game
from loader import load_characters_from_packs
from main import play_game
from models.character import Character
from models.dice import Dice
from player.player import Player


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.pool = load_characters_from_packs()
        self.game = Game([Player(1, "甲"), Player(2, "乙")], rng=random.Random(18))

    def roster(self, size):
        for side, player in enumerate(self.game.players):
            choices = self.pool[side * size:(side + 1) * size]
            for data in choices:
                char = Character(data, player)
                player.characters.append(char)
                char.init_cards()
                char.setup_deck()
            player.cardspace.draw.shuffle(self.game.rng)

    def run_match(self):
        # Decide through the same terminal prompts as human players. Use only the
        # first legal card; both sides still use their real decks, prices and dice.
        decisions = 0

        def answer(prompt):
            nonlocal decisions
            decisions += 1
            self.assertLess(decisions, 1500, "match did not reach an outcome")
            if "输入手牌编号" in prompt:
                player = self.game.placing
                return next((str(i) for i, card in enumerate(player.cardspace.hand.content, 1)
                             if card.character.is_alive and card.character.used_duels < card.character.max_duels), "")
            if "输入 y 扣置" in prompt:
                return "y"
            if "输入弃置编号" in prompt:
                player = self.game._private_player
                keep = self.game.gamerule.DRAW_COUNT + int(self.game.turn_count == 0)
                count = sum(c.is_alive for c in player.characters)
                n = min(len(player.cardspace.draw.content), keep + count - 1) - keep
                return " ".join(str(i) for i in range(1, n + 1))
            return ""

        limit = 20000
        original_step = self.game.next_step
        def advance():
            nonlocal limit
            limit -= 1
            self.assertGreater(limit, 0, "combat scheduler is stuck")
            return original_step()
        with patch.object(self.game, "next_step", advance), patch("builtins.input", answer), redirect_stdout(io.StringIO()) as output:
            play_game(self.game)
        self.assertTrue(self.game.is_over)
        self.assertIsNotNone(self.game.winner)
        self.assertIn("交锋", output.getvalue())
        for player in self.game.players:
            for char in player.characters:
                if not char.is_alive:
                    self.assertTrue(all(card in player.cardspace.out_of_combat.content for card in char.skills))
        return self.game.winner

    def test_original_two_fighters_finish(self):
        self.roster(1)
        self.run_match()

    def test_cli_from_another_directory_finishes_with_victory(self):
        main = Path(__file__).resolve().parents[1] / "main.py"
        # Take the first character on each side, then commit one card per turn.
        moves = ["1", "", "1", ""] + ["1", "end"] * 100
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(main), "--seed", "37"],
            input="\n".join(moves) + "\n", capture_output=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, cwd=tempfile.gettempdir(), timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("阵亡", lines[-2])
        self.assertEqual(lines[-1], "对局结束，玩家一 获胜。")

    def test_complete_three_on_three_with_real_card_pack(self):
        self.roster(3)
        self.run_match()

    def test_crimson_reserve_follows_the_winning_skill_and_pays_its_cost(self):
        self.roster(1)
        vanguard, duelist = (p.characters[0] for p in self.game.players)
        opener = next(c for c in duelist.skills if c.name == "决意贯穿")
        reserve = next(c for c in duelist.skills if c.name == "尖刺必杀")
        enemy_card = next(c for c in vanguard.skills if c.name == "试探刺击")
        self.game.first_player = duelist.player
        self.game.start_turn()
        self.game.place_in_duel(duelist.player.side, opener, 0)
        self.game.place_in_duel(vanguard.player.side, enemy_card, 0)
        with redirect_stdout(io.StringIO()), patch.object(self.game.rng, "randint", return_value=1):
            self.game.reveal_cards()
            self.game.pipeline.start_duel_combat()
            for _ in range(200):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertIn(reserve, self.game.used_cards)
        self.assertNotIn(reserve, duelist.player.cardspace.out_of_combat.content)
        self.assertEqual(duelist.used_independent_cost + duelist.player.used_cost, 4)
        self.assertEqual(vanguard.hp, vanguard.max_hp - 4)

    def test_damage_tiers_and_fatal_stagger_once_per_round(self):
        self.roster(1)
        actor = self.game.players[0].characters[0]
        actor.add_shield("normal", 3)
        actor.add_shield("reinforced", 2)
        actor.add_shield("concept", 1)
        self.assertEqual(actor.take_damage(3, "pierce"), 3)
        self.assertEqual(actor.hp, actor.max_hp - 1)
        self.assertEqual((actor.shield, actor.reinforced_shield, actor.concept_shield), (0, 0, 1))
        self.assertEqual(actor.take_damage(2, "concept"), 2)
        self.assertEqual(actor.hp, actor.max_hp - 2)
        actor.add_status("致命失衡", 2)
        self.assertEqual(actor.take_damage(1), 2)
        self.assertEqual(actor.take_damage(1), 2)
        self.assertEqual(actor.statuses["致命失衡"], 1)
        actor.begin_dice_round()
        self.assertEqual(actor.take_damage(1), 2)
        self.assertNotIn("致命失衡", actor.statuses)

    def test_burn_bleed_breath_and_stagger(self):
        self.roster(1)
        actor = self.game.players[0].characters[0]
        target = self.game.players[1].characters[0]
        actor.add_status("烧伤", 20)
        actor.on_turn_end()
        self.assertEqual((actor.hp, actor.statuses["烧伤"]), (actor.max_hp - 3, 13))
        actor.add_status("裂血", 10)
        self.assertEqual(actor.statuses["裂血"], 9)
        actor.on_duel_start()
        self.game.context.deal_damage(target, actor, 1, damage_part=True)
        self.assertEqual((actor.hp, actor.statuses["裂血"]), (actor.max_hp - 6, 7))
        actor.add_status("呼吸", 7)
        die = actor.skills[0].get_current_die(self.game)
        self.assertTrue(actor.on_attack_hit(die, target))
        actor.add_status("失衡", 20)
        self.assertTrue(actor.trigger_stagger())
        self.assertEqual((actor.statuses["失衡"],actor.statuses["致命失衡"]), (15, 1))

    def test_burn_and_fatal_stagger_consume_on_positive_damage_even_with_full_shields(self):
        self.roster(1)
        actor = self.game.players[0].characters[0]
        actor.add_status("烧伤", 20)
        actor.add_status("致命失衡", 2)
        actor.add_shield("normal", 6)
        actor.on_turn_end()
        self.assertEqual((actor.hp, actor.shield), (actor.max_hp, 0))
        self.assertEqual((actor.statuses["烧伤"], actor.statuses["致命失衡"]), (13, 1))

        actor.begin_dice_round()
        self.game.context.register_entries(actor, [{"trigger": "BEFORE DAMAGE", "operation": "Armor: 6"}])
        actor.on_turn_end()
        self.assertEqual((actor.statuses["烧伤"], actor.statuses["致命失衡"]), (13, 1))

    def test_pack_levels_formula_and_guard_alias(self):
        known_roster = {"铁壁先锋", "绯红决斗者", "演练斥候", "演练医护", "演练队长", "演练重装机",
                        "莱克", "格罗琳娜", "厄尔克斯", "安诺琳", "岑遥", "闻笙", "空白", "阙鸣", "沈砾"}
        self.assertTrue(known_roster.issubset({character["name"] for character in self.pool}))
        self.assertEqual({c["rank"] for c in self.pool}, {"NORMAL", "ELITE", "BOSS", "EMPOWERED_BOSS"})
        die = Dice(dict(type="guard", level=1, base_value=2, multiplier=3, final_bonus=1))
        self.assertTrue(die.is_passive)
        die.value = 99
        self.assertEqual((die.value, die.get_value()), (4, 19))
        die.value = -8
        self.assertEqual(die.get_value(), 10)
        capped = Dice(dict(type="slash", level=3, roll_max=3), self.game)
        with patch.object(self.game.rng, "randint", return_value=3) as roll:
            self.assertEqual(capped.roll(), 3)
        roll.assert_called_once_with(1, 3)
        capped.value = 8
        self.assertEqual(capped.value, 3)

    def test_bleed_burst_spends_stacks_after_its_damage(self):
        self.roster(1)
        actor = self.game.players[0].characters[0]
        actor.add_status("裂血", 6)
        observed = []
        self.game.context.register_entries(actor, [{
            "trigger": "AFTER DAMAGE", "when": {"damage_cause": "裂血爆发"},
            "operation": lambda ctx: observed.append(actor.statuses["裂血"]),
        }])
        actor.add_shield("reinforced", 1)
        self.game.context.deal_damage(self.game.players[1].characters[0], actor, 0, damage_part=True)
        self.assertEqual(observed, [6])
        self.assertEqual((actor.hp, actor.reinforced_shield), (actor.max_hp, 0))
        self.assertEqual(actor.statuses["裂血"], 4)


if __name__ == "__main__":
    unittest.main()
