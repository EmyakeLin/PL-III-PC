"""Exercise Qi Zheng's printed pack through the regular duel and interruption queues."""

import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from main import play_game
from models.card import Card
from models.character import Character, CharacterRank
from player.player import Player
from replay_lightcore import ReplayPlayer, declare_attacks


def recruit(player, spec):
    actor = Character(spec, player)
    player.characters.append(actor)
    actor.init_cards()
    actor.setup_deck()
    return actor


class QiZhengTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = {spec["id"]: spec for spec in load_characters_from_packs()}

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(31))
        self.game.first_player = self.left
        self.boss = recruit(self.left, self.roster["iron_qi_zheng"])
        self.enemy = recruit(self.right, dict(id="dummy", name="陪练", rank="NORMAL", max_hp=100, skills=[]))
        self.cards = {card.name: card for card in self.boss.skills}
        self.game.start_turn()

    def fight(self, name, opposing_bases=()):
        card = self.cards[name]
        self.assertTrue(self.game.place_in_duel(1, card, 0))
        if opposing_bases:
            dice = [dict(type="slash", level=3, base_value=base, entries=[]) for base in opposing_bases]
            reply = Card(self.right, dict(id="reply", name="迎击", cost=0, dice=dice), self.enemy)
            self.assertTrue(self.game.place_in_duel(2, reply, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1000):
            self.game.next_step()
            if self.game.is_over or not self.game.pipeline.in_duel_phase:
                return card
        self.fail(self.log.getvalue()[-1800:])

    def test_printed_roster_and_turn_income(self):
        self.assertEqual((self.boss.rank, self.boss.hp, self.boss.max_duels, len(self.cards)),
                         (CharacterRank.EMPOWERED_BOSS, 18, 4, 11))
        self.assertTrue(self.cards["抽刀"].can_open_pre_reveal)
        self.assertEqual(self.cards["压阵射击"].effective_range, 2)
        common = self.left.available_cost
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.left.available_cost, len(self.left.cardspace.hand.content)), (common + 1, 1))
        self.assertEqual(self.boss.reinforced_shield, 0)

    def test_unopposed_hook_applies_five_bleed_without_a_first_clash_win(self):
        card = self.fight("勾带")
        self.assertEqual((self.enemy.hp, self.enemy.statuses["裂血"]), (97, 5))
        self.assertEqual((card.level_bonus, card.final_bonus), (1, 2))
        self.assertEqual([die.landed_hits for die in card.instantiated_dice], [1, 1])

    def test_two_lost_dice_only_land_the_first_damage_part(self):
        card = self.fight("勾带", [50, 50])
        self.assertEqual([die.clash_result for die in card.instantiated_dice], ["lose", "lose"])
        self.assertEqual([die.landed_hits for die in card.instantiated_dice], [1, 0])
        self.assertEqual((self.enemy.hp, self.enemy.statuses["裂血"]), (99, 3))
        self.assertEqual(len(self.left.cardspace.hand.content), 0)

    def test_late_first_win_starts_burst_after_the_last_hit(self):
        card = self.fight("勾带", [50, -50])
        self.assertEqual([die.clash_result for die in card.instantiated_dice], ["lose", "win"])
        self.assertEqual((self.enemy.hp, self.enemy.statuses["裂血"]), (98, 6))
        self.assertEqual(len(self.left.cardspace.hand.content), 1)

    def test_two_wins_call_one_free_copy_then_resume_the_parent_hit(self):
        seen = []
        self.game.context.register_entries(self.boss, [
            dict(trigger="on_skill_use", operation=lambda ctx: seen.append(ctx.event["card"]))])
        hook = self.fight("勾带", [-50, -50])
        self.assertEqual((self.enemy.hp, self.enemy.statuses["裂血"]), (92, 6))
        self.assertEqual([card.id for card in seen], [hook.id, self.cards["过身"].id])
        self.assertTrue(seen[1].temporary)
        self.assertIn(self.cards["过身"], self.left.cardspace.draw.content)
        self.assertEqual(self.boss.used_independent_cost + self.left.used_cost, hook.cost)
        self.assertEqual([die.landed_hits for die in hook.instantiated_dice], [1, 1])
        self.assertEqual((hook.level_bonus, hook.final_bonus), (1, 2))
        self.assertEqual((seen[1].level_bonus, seen[1].final_bonus), (2, 4))

        # The first hook has several qualifying hits but only one pursuit. Both
        # once-per-turn passives must become available again on the next turn.
        self.game.finish_turn()
        self.game.start_turn()
        self.enemy.clear_status("裂血")
        self.fight("勾带", [-50, -50])
        self.assertEqual((self.enemy.hp, self.enemy.statuses["裂血"]), (84, 6))
        self.assertEqual([card.temporary for card in seen], [False, True, False, True])
        self.assertIsNot(seen[1], seen[3])

    def test_finisher_cannot_unlock_repeats_in_the_middle_of_its_first_hit(self):
        self.enemy.add_status("裂血", 3)
        card = self.fight("刀过无声", [-50, -50])
        self.assertEqual((card.level_bonus, card.final_bonus), (1, 2))
        self.assertEqual([die.is_repeat for die in card.instantiated_dice], [False, False])
        self.assertIn("以「过身」进攻 陪练", self.log.getvalue())

    def test_finisher_repeats_twice_if_six_bleed_is_present_on_use(self):
        self.enemy.add_status("裂血", 6)
        card = self.fight("刀过无声")
        self.assertEqual((card.level_bonus, card.final_bonus), (2, 4))
        self.assertEqual([die.is_repeat for die in card.instantiated_dice], [False, True, True, False])
        self.assertEqual([die.landed_hits for die in card.instantiated_dice], [1, 1, 1, 1])
        self.assertEqual(self.enemy.hp, 80)  # 18 from hits/bursts and 2 from duel openings.

    def test_standard_shuffled_match_calls_pursuit_against_sa(self):
        left, right = ReplayPlayer(1, "祁铮"), ReplayPlayer(2, "萨")
        match = Game([left, right], rng=random.Random(13))
        for player, key in ((left, "iron_qi_zheng"), (right, "plan_b_sa")):
            recruit(player, self.roster[key])
            player.cardspace.draw.shuffle(match.rng)
        match.run_pre_reveal_declarations = lambda: declare_attacks(match)
        play_game(match)
        self.assertTrue(match.is_over)
        self.assertIs(match.winner, left)
        self.assertIn("以「过身」进攻 萨", self.log.getvalue())


if __name__ == "__main__":
    unittest.main()
