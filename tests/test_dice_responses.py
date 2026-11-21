import io
import unittest
from contextlib import redirect_stdout

from game import Game
from models.card import Card
from models.character import Character
from player.player import Player


def die(base, damage=1, **spec):
    return dict(type="slash", level=1, base_value=base, roll_max=1, entries=[str(damage)], **spec)


class DiceResponseTests(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.a, self.b = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.a, self.b])
        self.game.first_player = self.a
        for player in self.game.players:
            player.characters.append(Character(dict(id=player.name, name=player.name, rank="BOSS",
                                                    max_hp=30, skills=[]), player))
        self.actor, self.enemy = self.a.characters[0], self.b.characters[0]
        self.game.start_turn()

    def card(self, actor, name, dice, **spec):
        card = Card(actor.player, dict(id=name, name=name, cost=0, dice=dice, **spec), actor)
        actor.skills.append(card)
        return card

    def place(self, card, slot):
        self.assertTrue(self.game.place_in_duel(card.player.side, card, slot))

    def fight(self):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(2000):
            self.game.next_step()
            if not self.game.pipeline.in_duel_phase:
                break
        self.assertFalse(self.game.pipeline.in_duel_phase, self.log.getvalue()[-1400:])
        self.assertEqual(self.game.context.stack, [])

    def reserve_card(self, count):
        card = self.card(self.actor, "储备", [die(10)], entries=[dict(trigger="on_skill_use", operation={
            "op": "program", "code": ["$card", 1, count, "RESERVE_DIE", "$self", "使用次数", 1, "STATUS"]})])
        self.place(card, 0)
        return card

    def test_excess_dice_are_contested_until_stock_runs_out(self):
        attack = self.reserve_card(2)
        foe = self.card(self.enemy, "四骰", [die(0, 3) for _ in range(4)])
        self.place(foe, 0)
        self.fight()
        self.assertEqual([d.clash_result for d in foe.instantiated_dice], ["lose", "lose", "lose", None])
        self.assertEqual((self.actor.hp, self.enemy.hp), (27, 27))
        self.assertEqual(self.actor.statuses["使用次数"], 1)
        self.assertFalse(self.actor.reserved_dice)
        self.assertEqual(self.game.used_cards.count(attack), 1)

    def test_reserve_follows_target_and_expires_with_the_turn(self):
        self.reserve_card(3)
        ally = Character(dict(id="ally", name="同伴", max_hp=20, rank="NORMAL", skills=[]), self.a)
        self.a.characters.append(ally)
        self.b.choose_one_sided_target = lambda player: ally
        self.place(self.card(self.enemy, "另选目标", [die(0, 2)]), 1)
        self.fight()
        self.assertEqual(ally.hp, 18)
        self.assertEqual(self.actor.reserved_dice[0].remaining, 3)
        self.game.finish_turn()
        self.assertFalse(self.actor.reserved_dice)

    def test_redirected_attack_meets_the_actual_targets_response(self):
        self.reserve_card(1)
        redirected = die(0, 3)
        redirected["entries"].append(dict(trigger="before_dice_pair", operation=dict(
            op="program", code=["$die", "$next_duel_target", "ROUTE_DIE_ATTACK"])))
        foe = self.card(self.enemy, "转火", [redirected])
        ally = Character(dict(id="ally", name="同伴", max_hp=20, rank="NORMAL", skills=[]), self.a)
        self.a.characters.append(ally)
        self.place(self.card(ally, "原对位", [dict(type="evade", level=1)]), 1)
        self.place(foe, 1)
        self.place(self.card(self.actor, "次交锋", []), 2)
        self.fight()
        self.assertEqual(foe.instantiated_dice[0].clash_result, "lose")
        self.assertEqual((self.actor.hp, ally.hp), (30, 20))
        self.assertFalse(self.actor.reserved_dice)

    def test_reserved_melee_can_win_under_level_two_without_hitting(self):
        self.reserve_card(1)
        shot = self.card(self.enemy, "强化远程", [die(0, 3)], range_level=2)
        self.place(shot, 1)
        self.fight()
        self.assertEqual(shot.instantiated_dice[0].clash_result, "lose")
        self.assertEqual((self.actor.hp, self.enemy.hp), (30, 29))
        self.assertFalse(self.actor.reserved_dice)

    def test_one_cartridge_removes_two_positions_before_pairing_with_the_finisher(self):
        cost = dict(status="弹药", amount=1)
        salvo = self.card(self.actor, "射击", [die(9, resource_cost=cost) for _ in range(3)] + [die(8)])
        enemy = self.card(self.enemy, "三骰", [die(0, 3) for _ in range(3)])
        self.actor.add_status("弹药", 1)
        pairs = []
        self.game.context.register_entries(self.actor, [
            dict(trigger="on_dice_clash", operation=lambda ctx: pairs.append(
                (ctx.event["die"].position, ctx.event["opponent_die"].position)))])
        self.place(salvo, 0)
        self.place(enemy, 0)
        self.fight()
        self.assertEqual(pairs, [(1, 1), (4, 2)])
        self.assertEqual([d.landed_hits if d else None for d in salvo.instantiated_dice], [1, None, None, 1])
        self.assertEqual([d.clash_result for d in enemy.instantiated_dice], ["lose", "lose", None])
        self.assertEqual((self.actor.hp, self.enemy.hp), (27, 28))
        self.assertNotIn("弹药", self.actor.statuses)

    def test_ineligible_opponent_keeps_eligible_dies_first_payment(self):
        cost = dict(status="弹药", amount=1)
        self.actor.add_status("弹药", 2)
        self.place(self.card(self.actor, "有弹", [die(9, resource_cost=cost)]), 0)
        self.place(self.card(self.enemy, "跳过一位", [die(9, resource_cost=cost), die(0)]), 0)
        self.fight()
        self.assertEqual(self.actor.statuses["弹药"], 1)
        self.assertEqual(self.enemy.hp, 29)

    def test_printed_skip_does_not_spend_for_a_die_that_never_fires(self):
        cost = dict(status="弹药", amount=1)
        self.actor.add_status("弹药", 1)
        salvo = self.card(self.actor, "两发", [die(9, resource_cost=cost), die(9, resource_cost=cost)])
        self.place(salvo, 0)
        self.place(self.card(self.enemy, "本轮跳过", [dict(type="skip"), die(0)]), 0)
        self.fight()
        self.assertEqual([d.clash_result for d in salvo.instantiated_dice], ["skip", "win"])
        self.assertNotIn("弹药", self.actor.statuses)

    def test_unfunded_dice_cannot_listen_to_the_resource_payment_attempt(self):
        unfunded = die(9, resource_cost=dict(status="弹药", amount=1))
        unfunded["entries"].append(dict(trigger="BEFORE SPEND_STATUS", scope="global", subject="any",
                                         operation=lambda ctx: self.fail("未能使用的骰子提前激活了词条")))
        card = self.card(self.actor, "缺费骰", [unfunded, die(0)])
        self.place(card, 0)
        self.fight()
        self.assertIsNone(card.instantiated_dice[0])
        self.assertEqual(self.enemy.hp, 29)

    def test_solo_defense_and_an_empty_round_cannot_spend_a_response(self):
        self.reserve_card(1)
        self.place(self.card(self.enemy, "无人对位的闪避", [dict(type="evade", level=1)]), 1)
        vanishing = die(0)
        vanishing["entries"].append(dict(trigger="on_dice_use", operation={
            "op": "program", "code": ["$die", "DESTROY"]}))
        self.place(self.card(self.actor, "消失骰", [vanishing]), 2)
        guard = self.card(self.enemy, "取得空白轮胜利的招架", [dict(type="block", level=1)])
        self.place(guard, 2)
        self.fight()
        self.assertEqual(guard.instantiated_dice[0].clash_result, "win")
        self.assertEqual(self.actor.reserved_dice[0].remaining, 1)

    def test_die_destroyed_by_first_payment_does_not_pay_or_give_an_empty_win(self):
        fee = {"status": "弹药", "amount": 1}
        self.game.first_player = self.b
        self.actor.add_status("弹药", 1)
        self.enemy.add_status("弹药", 1)
        self.game.context.register_entries(self.enemy, [dict(
            trigger="AFTER SPEND_STATUS", when={"status": "弹药", "result_at_least": 1},
            operation={"op": "program", "code": ["$opponent_die", "DESTROY"]})])
        first = self.card(self.enemy, "付款时摧毁对位", [die(8, resource_cost=fee)])
        second = self.card(self.actor, "付费骰与后备骰", [die(20, resource_cost=fee), die(3)])
        self.place(first, 0)
        self.place(second, 0)
        self.fight()
        removed, replacement = second.instantiated_dice
        self.assertTrue(removed.destroyed)
        self.assertIsNone(removed.clash_result)
        self.assertEqual(self.actor.statuses["弹药"], 1)
        self.assertEqual((first.instantiated_dice[0].clash_result, replacement.clash_result), ("win", "lose"))
        self.assertNotIn("空白轮", self.log.getvalue())

    def test_old_extreme_range_yields_to_response_then_resumes_on_next_solo(self):
        self.reserve_card(1)
        strong = self.card(self.actor, "极限远程", [die(0)], range_level=3)
        observed = []
        dice = [die(20), die(20), die(20)]
        for spec in dice:
            spec["entries"].append(dict(trigger="before_dice_pair", operation=lambda ctx:
                                        observed.append(ctx.event["die"].position)))
        excess = self.card(self.enemy, "余骰", dice)
        self.place(strong, 1)
        self.place(excess, 1)
        self.fight()
        self.assertEqual([d.type for d in excess.instantiated_dice], ["blank", "slash", "blank"])
        self.assertEqual([d.landed_hits for d in excess.instantiated_dice], [0, 1, 0])
        self.assertEqual(observed, [2])
        self.assertEqual(self.actor.hp, 29)

    def test_previous_extreme_range_cannot_waive_an_unblanked_shots_ammo_cost(self):
        self.reserve_card(1)
        self.place(self.card(self.actor, "极限远程", [die(0)], range_level=3), 1)
        cost = dict(status="弹药", amount=1)
        foe = self.card(self.enemy, "无弹余骰", [die(20), die(20, resource_cost=cost), die(20)])
        self.place(foe, 1)
        self.fight()
        self.assertIsNone(foe.instantiated_dice[1])
        self.assertEqual(foe.instantiated_dice[2].clash_result, "win")
        self.assertEqual(self.actor.hp, 29)
