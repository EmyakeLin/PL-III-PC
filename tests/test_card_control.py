import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from models.card import Card, CardState
from models.character import Character
from models.duel import DuelSlot
from models.opcode import OpCode
from player.player import Player


def die(score, *entries, **options):
    return dict(type="blunt", level=1, base_value=score - 1, roll_max=1,
                entries=list(entries), **options)


def entry(trigger, *code):
    return dict(trigger=trigger, operation=dict(op="program", code=list(code)))


class CardControlTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        players = [Player(1, "甲"), Player(2, "乙")]
        self.game = Game(players, rng=random.Random(3))
        self.game.first_player = players[0]
        for p in players:
            p.characters.append(Character(dict(id=p.name, name=p.name, rank="BOSS",
                                               max_hp=15, skills=[]), p))
        self.a, self.b = (p.characters[0] for p in players)
        self.game.start_turn()
        self.slot = DuelSlot(self.game)
        self.game.duelspace.append_new_duel(self.slot)
        self.ctx = self.game.context

    def skill(self, owner, name, dice, **options):
        card = Card(owner.player, dict(id=name, name=name, cost=options.pop("cost", 0),
                                       dice=dice, **options), owner)
        owner.skills.append(card)
        return card

    def place(self, *cards):
        for card in cards:
            card.state = CardState.PLACED_FACE_DOWN
            self.slot.add_content(card.player.side, card)

    def battle(self):
        self.game.reveal_cards()
        pipeline = self.game.pipeline
        pipeline.start_duel_combat()
        while pipeline.in_duel_phase:
            pipeline.step_duel_combat()
        self.assertEqual(self.ctx.stack, [])

    def test_double_solo_hits_in_score_order_then_transfers_only_the_unused_dice(self):
        split = entry("before_clash_result", "$opponent_clash_score", 12, "GE",
                      ["$die", "SPLIT_CLASH"], "WHEN")
        steal = entry("on_dice_hit", "$opponent_card", "$card", "TRANSFER_REMAINING_DICE",
                      "$opponent_card", "DESTROY")
        reader = self.skill(self.a, "看破", [die(4, split, steal)])
        gain = entry("on_dice_hit", "$self", "夺来的收益", 1, "STATUS")
        enemy = self.skill(self.b, "被识破", [die(12, "2"), die(8, "3", gain)])
        self.place(reader, enemy)
        self.battle()
        self.assertEqual((self.a.hp, self.b.hp), (13, 12))
        self.assertEqual(self.a.statuses["夺来的收益"], 1)
        self.assertFalse(self.a.won_clash_this_turn or self.b.won_clash_this_turn)
        self.assertTrue(enemy.destroyed)
        self.game.finish_turn()
        self.assertEqual((len(reader.dice), len(enemy.dice)), (1, 2))
        self.assertFalse(enemy.destroyed)

    def test_faster_first_hit_can_destroy_the_other_even_on_a_tie(self):
        split = entry("before_clash_result", "$die", "SPLIT_CLASH")
        destroy = entry("on_dice_hit", "$opponent_card", "DESTROY")
        self.place(self.skill(self.a, "先手", [die(12, split, "1", destroy)]),
                   self.skill(self.b, "后手", [die(12, "7")]))
        self.battle()
        self.assertEqual((self.a.hp, self.b.hp), (15, 14))
        self.assertFalse(self.a.won_clash_this_turn or self.b.won_clash_this_turn)

    def test_close_loss_destroys_both_dice_before_either_result_is_issued(self):
        suppress = entry("before_clash_result", "$prospective_result", "lose", "EQ",
                         "$clash_difference", 3, "LE", "AND",
                         ["$die", "DESTROY", "$opponent_die", "DESTROY"], "WHEN")
        a = self.skill(self.a, "牵制", [die(3, "5")], entries=[suppress])
        b = self.skill(self.b, "目标", [die(6, "5")])
        self.place(a, b)
        self.battle()
        for card in (a, b):
            self.assertTrue(card.instantiated_dice[0].destroyed)
            self.assertIsNone(card.instantiated_dice[0].clash_result)
        self.assertEqual((self.a.hp, self.b.hp), (15, 15))
        self.assertFalse(self.a.won_clash_this_turn or self.b.won_clash_this_turn)

    def test_uniform_reveal_selects_form_only_on_board_then_recovers_printed_dice(self):
        transform = entry("on_card_reveal", "$card", "爆裂一击", "SET_SKILL_FORM",
                          "$self", "开牌次数", 1, "STATUS")
        options = dict(entries=[transform], forms={"爆裂一击": {"name": "爆裂一击", "dice": [die(12, "4")]}})
        card = self.skill(self.a, "全面防守", [die(20)], **options)
        hidden = self.skill(self.a, "另一张", [die(20)], **options)
        self.a.player.cardspace.hand.add_card(hidden)
        self.place(card)
        card.state = CardState.PLACED_FACE_UP  # Already visible from insight.
        self.battle()
        self.game.reveal_cards()
        self.assertEqual((card.name, hidden.name, self.a.statuses["开牌次数"]), ("爆裂一击", "另一张", 1))
        self.assertEqual(self.b.hp, 11)
        self.game.finish_turn()
        self.assertEqual(card.name, "全面防守")
        self.assertEqual(card.dice, [die(20)])

    def test_locked_dice_skip_the_entire_use_then_reopen_in_a_fresh_skill(self):
        gated = die(2, "3", requires_skill_state="second")
        card = self.skill(self.a, "准镜", [gated, die(4, entry("on_dice_hit", "$card", "second", 1, "SET_SKILL_STATE")), gated])
        self.place(card)
        self.battle()
        self.assertIsNone(card.instantiated_dice[0])
        self.assertEqual(self.b.hp, 12)
        self.game.finish_turn()
        self.assertFalse(card.use_state)
        self.assertEqual(card.get_current_die(self.game).position, 2)

    def test_borrowed_skill_pays_as_its_caster_and_returns_to_original_draw_pile(self):
        card = self.skill(self.b, "同名", [die(2, entry("on_dice_hit", "$self", "原牌收益", 1, "STATUS"))],
                          cost=2)
        self.b.player.cardspace.hand.add_card(card)
        self.ctx.eval_block([self.b, self.a, OpCode.TAKE_HAND_CARD])
        self.assertIs(card.character, self.a)
        self.game.place_in_duel(1, card, 0)
        self.battle()
        self.assertEqual(self.a.statuses["原牌收益"], 1)
        self.assertEqual(self.a.player.used_cost + self.a.used_independent_cost, 2)
        self.game.finish_turn()
        self.assertIs(card.character, self.b)
        self.assertIn(card, self.b.player.cardspace.draw.content)
        self.assertNotIn(card, self.a.player.cardspace.draw.content)

    def test_choose_a_slot_to_append_a_stolen_skill_and_pay_its_printed_resource_later(self):
        card = self.skill(self.b, "已预付远程", [die(1, "1")], cost=5, range_level=1,
                          resource_cost={"status": "能源", "amount": 2})
        self.b.player.cardspace.hand.add_card(card)
        first = self.skill(self.a, "常规一", [die(1)])
        self.place(first)
        later = DuelSlot(self.game)
        second = self.skill(self.a, "常规二", [die(1)])
        later.add_content(1, second)
        self.game.duelspace.append_new_duel(later)
        self.a.add_status("能源", 7)
        stolen = self.ctx.eval_block([self.b, self.a, OpCode.TAKE_HAND_CARD])
        self.assertIs(stolen, card)
        self.assertTrue(self.ctx.eval_block([stolen, "能源", OpCode.QUEUE_PREPAID_CARD]))
        choices = self.game.special.options(self.a.player)
        self.assertEqual([a.duel_index for a in choices], [0, 1])
        self.assertEqual(self.a.statuses["能源"], 2)
        self.assertTrue(self.game.special.apply(self.a.player, choices[1]))
        self.assertEqual(later.get_content(1), [second, card])
        self.battle()
        self.assertEqual(self.b.hp, 14)
        self.assertNotIn("能源", self.a.statuses)
        self.assertNotIn("cost_prepaid", card.use_state)
        self.assertEqual(self.a.used_independent_cost + self.a.player.used_cost, 0)
        self.game.finish_turn()
        self.assertIn(card, self.b.player.cardspace.draw.content)

    def test_unaffordable_stolen_card_enters_hand_and_can_be_taken_back(self):
        card = self.skill(self.b, "费用较高", [die(1)], cost=5)
        self.b.player.cardspace.hand.add_card(card)
        self.place(self.skill(self.a, "常规一", [die(1)]))
        self.a.add_status("能源", 3)
        stolen = self.ctx.eval_block([self.b, self.a, OpCode.TAKE_HAND_CARD])
        self.assertIs(stolen, card)
        self.assertFalse(self.ctx.eval_block([stolen, "能源", OpCode.QUEUE_PREPAID_CARD]))
        self.assertIsNone(self.game.special.placement_owner)
        self.assertEqual(self.a.player.cardspace.hand.content, [card])
        self.assertEqual(self.a.statuses["能源"], 3)
        self.ctx.eval_block([self.a, self.b, OpCode.TAKE_HAND_CARD])
        self.assertEqual(self.b.player.cardspace.hand.content, [card])
        self.assertIs(card.printed_owner, card.character)

    def test_borrowers_death_returns_cards_and_printed_owners_death_retires_them(self):
        borrowed = self.skill(self.b, "借来的牌", [die(1)])
        retired = self.skill(self.a, "本方印刷", [die(2)])
        self.b.player.cardspace.hand.add_card(borrowed)
        self.ctx.eval_block([self.b, self.a, OpCode.TAKE_HAND_CARD])
        self.a.player.cardspace.hand.add_card(retired)
        retired.set_controller(self.b)
        self.a.player.cardspace.hand.move_card_to(retired, self.b.player.cardspace.hand)
        self.a.lose_hp(15)
        self.assertEqual(self.b.player.cardspace.draw.content, [borrowed])
        self.assertFalse(borrowed.destroyed)
        self.assertFalse(self.b.player.cardspace.hand.content)
        self.assertIn(retired, self.a.player.cardspace.out_of_combat.content)
        self.assertTrue(retired.destroyed)

    def test_failed_extra_price_does_not_establish_range_advantage(self):
        ranged = self.skill(self.a, "远射", [die(10, "5")], cost=1, range_level=1,
                            resource_cost={"status": "能源", "amount": 2})
        self.a.add_status("能源", 1)
        self.place(ranged, self.skill(self.b, "近攻", [die(4, "1")]))
        self.battle()
        self.assertEqual((self.a.hp, self.b.hp), (14, 15))
        self.assertNotIn("能源", self.a.statuses)
        self.assertEqual(self.a.used_independent_cost + self.a.player.used_cost, 0)
