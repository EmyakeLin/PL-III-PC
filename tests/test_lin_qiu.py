"""Play Lin Qiu's printed pack through the regular combat and decision queues."""
import io
import random
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.opcode import OpCode
from player.player import Player
from replay_lightcore import ReplayPlayer, declare_attacks


def replay(seed=50):
    """Reproduce a standard, shuffled-deck battle through the CLI's match driver."""
    from main import play_game

    pool = {c["id"]: c for c in load_characters_from_packs()}
    players = [ReplayPlayer(1, "林秋"), ReplayPlayer(2, "安诺琳＋莱克")]
    game = Game(players, rng=random.Random(seed))
    for player, roster in zip(players, (("nova_lin_qiu",), ("plan_b_annolin", "waa_lake"))):
        for key in roster:
            LinQiuTests.recruit(player, pool[key])
        player.cardspace.draw.shuffle(game.rng)

    def choose(game):
        owner = game.special.decision_owner
        if owner:
            options = game.special.options(owner)
            # Legal options are already in display order. A concealed enemy card
            # is chosen by position; the policy never consults the card's identity.
            game.special.apply(owner, options[0])

    game.special_prompt = choose
    game.run_pre_reveal_declarations = lambda: declare_attacks(game)
    play_game(game)
    print(f"第 {game.turn_number} 回合，" + "，".join(
        f"{c.name} {c.hp}/{c.max_hp}" for player in players for c in player.characters))
    return game


class LinQiuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = next(item for item in load_characters_from_packs() if item["name"] == "林秋")

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "林"), Player(2, "对手")
        self.game = Game([self.left, self.right], rng=random.Random(32))
        self.game.first_player = self.left
        self.lin = self.recruit(self.left, self.pack)
        self.enemy = self.recruit(self.right, dict(id="opponent", name="陪练", max_hp=100,
                                                   rank="NORMAL", skills=[]))
        self.game.start_turn()
        self.cards = {card.name: card for card in self.lin.skills}

    @staticmethod
    def recruit(player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def place(self, name, slot=0):
        card = self.cards[name]
        self.assertTrue(self.game.place_in_duel(1, card, slot))
        return card

    def oppose(self, count=1, base=-50, slot=0):
        spec = dict(id=f"dummy{slot}", name="陪练技能", cost=0,
                    dice=[dict(type="slash", level=1, base_value=base, entries=["0物理"]) for _ in range(count)])
        card = Card(self.right, spec, self.enemy)
        self.enemy.skills.append(card)
        self.assertTrue(self.game.place_in_duel(2, card, slot))
        return card

    def open_tunnel(self, amount=20):
        self.lin.add_status("隧道", amount)
        self.lin.add_status("隧道开启", 1)

    def fight(self, choice=None):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=lambda low, high: high):
            for _ in range(2500):
                owner = self.game.special.decision_owner
                if owner:
                    options = self.game.special.options(owner)
                    move = choice(options) if choice else next(
                        (option for option in options if option.kind == "decline_card"), options[0])
                    self.assertTrue(self.game.special.apply(owner, move))
                self.game.next_step()
                if self.game.is_over or not self.game.pipeline.in_duel_phase:
                    return
        self.fail(self.log.getvalue()[-2200:])

    def test_full_hand_opens_at_eight_and_sustains_only_its_own_strength(self):
        self.assertEqual((self.lin.max_hp, self.lin.lightcore_hp, self.lin.max_duels), (15, 24, 3))
        self.assertEqual([c.cost for c in self.lin.skills], [1, 1, 2, 3, 3, 4, 4])
        self.left.draw_card(7)
        self.lin.add_status("隧道", 6)
        self.lin.add_status("强壮", 1)
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.lin.statuses["隧道"], self.lin.statuses["强壮"]), (8, 3))
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual(self.lin.statuses["隧道"], 9)
        self.lin.add_status("隧道", -8)
        self.assertEqual(self.lin.statuses["隧道开启"], 1)
        self.lin.add_status("隧道", -1)
        self.assertNotIn("隧道开启", self.lin.statuses)
        self.assertEqual(self.lin.statuses["强壮"], 1)

    def test_printed_skip_consumes_both_dice_without_a_clash(self):
        card = self.place("机动申请")
        other = self.oppose()
        self.fight()
        self.assertEqual(card.instantiated_dice[0].clash_result, "skip")
        self.assertEqual(other.instantiated_dice[0].clash_result, "skip")
        self.assertNotIn("羽流·林秋", self.lin.statuses)
        self.assertEqual((self.lin.statuses["隧道"], self.enemy.statuses["星结"]), (4, 1))

    def test_two_lock_targets_one_supply_and_reset_including_supplement_overflow(self):
        ally = self.recruit(self.left, dict(id="ally", name="队友", rank="NORMAL", max_hp=6, skills=[]))
        self.lin.hp, ally.hp = 10, 3
        self.open_tunnel(9)
        for actor in (self.enemy, ally):
            actor.add_status("星结", 11)
            actor.add_status("星结", 4)
            actor.add_status("星结", 4)
        self.game.context.dispatch_pipeline("before_turn_end")
        self.assertEqual((self.lin.hp, ally.hp, self.lin.statuses["隧道"]), (11, 4, 11))
        for target in (self.enemy, ally):
            self.assertEqual(target.statuses["星结"], 6)
            self.assertEqual(target.status_overflow.get("星结", 0), 0)

    def test_boundary_protection_only_covers_itself_and_higher_authority_wins(self):
        self.open_tunnel()
        boundary = self.place("分界")
        other = self.place("拔剑相向", 1)
        with self.game.context.binding(source=self.enemy):
            self.game.context.eval_block([boundary, OpCode.DESTROY])
            self.game.context.eval_block([other, OpCode.DESTROY])
        self.assertTrue(other.destroyed)
        self.assertFalse(boundary.destroyed)
        with self.game.context.binding(source=self.enemy, authority=1):
            self.game.context.eval_block([boundary, OpCode.DESTROY])
        self.assertTrue(boundary.destroyed)

    def test_repeated_counterflow_four_hits_two_clashes_and_only_repeat_deals_extra(self):
        self.open_tunnel()
        self.lin.add_status("羽流·林秋", 12)
        self.enemy.add_status("星结", 12)
        card = self.place("铭刻逆流")
        self.oppose(3)
        self.fight()
        head, tail, repeat = card.instantiated_dice
        self.assertEqual([die.landed_hits for die in (head, tail, repeat)], [2, 2, 2])
        self.assertFalse(tail.is_repeat)
        self.assertTrue(repeat.is_repeat)
        self.assertEqual(repeat.final_score, tail.final_score + 4)
        self.assertEqual(self.enemy.hp, 90)  # four 0+1 printed hits and two 3 piercing follow-ups
        self.assertEqual(self.log.getvalue().count("追加命中 陪练"), 3)
        self.assertEqual(self.lin.statuses["本回合羽流判定成功"], 3)
        self.game.context.dispatch_pipeline("before_turn_end")
        self.assertNotIn("羽流·林秋", self.lin.statuses)

    def test_resident_defeat_is_damage_only_and_keeps_target_skill(self):
        self.lin.add_status("隧道", 2)
        self.enemy.add_status("星结", 8)
        card = self.place("分界")
        enemy_card = self.oppose(base=60)
        self.fight()
        die = card.instantiated_dice[0]
        self.assertEqual((die.clash_result, die.landed_hits, die.base_value), ("lose", 1, 1))
        self.assertEqual((die.value, die.final_score), (20, 42))
        self.assertEqual((self.enemy.hp, self.enemy.statuses["星结"], enemy_card.destroyed), (98, 8, False))
        self.assertIn("命中 陪练，仅结算伤害部分", self.log.getvalue())

    def test_solo_does_not_roll_feather_and_each_die_has_its_own_first_hit(self):
        self.open_tunnel()
        self.lin.add_status("羽流·林秋", 12)
        self.enemy.add_status("星结", 12)
        card = self.place("羽流剑术")
        self.oppose(1)
        self.fight()
        self.assertEqual([die.landed_hits for die in card.instantiated_dice], [2, 1, 1])
        # First slash 2+1, second slash 3, last slash 2+1 conditional piercing.
        self.assertEqual((self.enemy.hp, self.right.next_turn_common_cost), (91, -1))

    def test_surprise_spends_last_tunnel_to_skip_the_entire_losing_round(self):
        self.open_tunnel(1)
        self.place("出其不意")
        enemy = self.oppose(2, base=60)
        self.fight()
        self.assertEqual([die.clash_result for die in enemy.instantiated_dice], ["skip", "win"])
        self.assertNotIn("隧道开启", self.lin.statuses)

    def test_void_cut_costs_once_per_use_and_uses_current_stars_each_hit(self):
        self.open_tunnel()
        self.lin.add_status("羽流·林秋", 12)
        self.enemy.add_status("星结", 12)
        card = self.place("空断")
        self.oppose(2, base=-2)
        self.fight()
        self.assertEqual([die.landed_hits for die in card.instantiated_dice], [2, 2])
        self.assertEqual(card.use_state["spent_statuses"]["隧道"], 8)  # 2 fee, 2 on use, 4 blades
        self.assertEqual((self.enemy.next_turn_duels, self.enemy.statuses["星结"]), (-4, 8))
        self.assertEqual(self.enemy.hp, 90)
        self.assertEqual(sum(n for _, t, name, n, _ in self.game.next_turn_statuses
                             if t is self.enemy and name == "限制"), 4)

    def test_paying_last_tunnel_reverses_void_cut_range_advantage(self):
        self.open_tunnel(2)
        card = self.place("空断")
        self.oppose(2).data["range_level"] = 2
        self.fight()
        self.assertNotIn("隧道开启", self.lin.statuses)
        self.assertEqual(card.use_state["spent_statuses"]["隧道"], 2)
        self.assertTrue(all(die.clash_result == "win" and not die.landed_hits for die in card.instantiated_dice))
        self.assertEqual(self.enemy.hp, 100)

    def test_pay_last_tunnel_loses_range_immunity_before_boundary_uses_its_die(self):
        self.open_tunnel(2)
        card = self.place("分界")
        self.oppose().data["range_level"] = 3
        self.fight()
        self.assertEqual(card.use_state["spent_statuses"]["隧道"], 2)
        self.assertEqual(card.instantiated_dice[0].type, "blank")
        self.assertEqual(self.enemy.hp, 100)

    def test_same_die_opens_one_choice_and_inserts_boundary_with_discount(self):
        self.open_tunnel()
        self.lin.add_status("羽流·林秋", 12)
        self.left.draw_card(7)
        surprise = self.place("出其不意")
        self.oppose(3)
        later = self.oppose(slot=1)
        choices = []

        def choose(options):
            if any(option.kind == "decline_card" for option in options):
                choices.append("insert")
                return next(option for option in options if option.target_card is self.cards["分界"])
            choices.append("destroy")
            return next(option for option in options if option.target_card is later)

        self.fight(choose)
        self.assertEqual(surprise.instantiated_dice[-1].landed_hits, 2)
        self.assertEqual(choices, ["insert", "destroy"])
        self.assertTrue(later.destroyed)
        self.assertEqual(self.left.available_cost + self.lin.available_cost, 1)
        self.assertEqual(self.cards["分界"].use_state["spent_statuses"]["隧道"], 3)

    def test_double_hit_destroys_two_waiting_dice_before_any_new_pair(self):
        self.lin.add_status("羽流·林秋", 12)
        self.left.draw_card(7)
        self.place("出其不意")
        enemy = self.oppose(6)

        def choose(options):
            return next(option for option in options if option.target_card is self.cards["拔剑相向"])

        self.fight(choose)
        fourth, fifth, sixth = enemy.instantiated_dice[3:]
        self.assertTrue(fourth.destroyed and fifth.destroyed)
        self.assertIsNone(fourth.clash_result)
        self.assertIsNone(fifth.clash_result)
        self.assertEqual(sixth.clash_result, "lose")
        self.assertNotIn("空白轮", self.log.getvalue())
        self.assertEqual(self.cards["拔剑相向"].instantiated_dice[0].landed_hits, 2)

    def test_standard_shuffled_match_reaches_victory(self):
        game = replay()
        self.assertTrue(game.is_over)
        self.assertEqual((game.winner.name, game.turn_number), ("林秋", 7))
        self.assertEqual([actor.hp for player in game.players for actor in player.characters], [8, 0, 0])
        self.assertIn("「分界」本次费用减免 2，实付 2 费", self.log.getvalue())
        self.assertIn("「空断」追加命中", self.log.getvalue())


if __name__ == "__main__":
    if sys.argv[1:2] == ["--replay"]:
        replay(*map(int, sys.argv[2:]))
    else:
        unittest.main()
