"""Play Sa's printed dice through placement, reveal and the normal combat pipeline."""

import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from player.player import Player


class SaSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = next(c for c in load_characters_from_packs() if c["id"] == "plan_b_sa")

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "萨"), Player(2, "陪练方")
        self.game = Game([self.left, self.right], rng=random.Random(31))
        self.game.first_player = self.left
        self.sa = self.recruit(self.left, self.pack)
        self.target = self.dummy("前锋")
        self.cards = {c.name: c for c in self.sa.skills}
        self.game.start_turn()

    @staticmethod
    def recruit(player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def dummy(self, name):
        return self.recruit(self.right, dict(id=name, name=name, max_hp=30, rank="NORMAL", skills=[]))

    def oppose(self, bases, *, slot=0, actor=None):
        actor = actor or self.target
        spec = dict(id="test", name="陪练牌", cost=0, dice=[
            dict(type="slash", level=1, base_value=base, entries=[]) for base in bases])
        card = Card(self.right, spec, actor)
        actor.skills.append(card)
        self.assertTrue(self.game.place_in_duel(2, card, slot))

    def fight(self, name):
        card = self.cards[name]
        self.assertTrue(self.game.place_in_duel(1, card, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(1200):
            self.game.next_step()
            if self.game.is_over or not self.game.pipeline.in_duel_phase:
                return card
        self.fail(self.log.getvalue()[-1500:])

    def queued(self, target, name):
        return sum(count for _, actor, status, count, _ in self.game.next_turn_statuses
                   if actor is target and status == name)

    def test_s_entry_draws_fifth_card_before_plan_b_and_mends_fissure(self):
        self.left.draw_card(4)
        self.sa.hp = 8
        self.sa.add_status("崩析", 4)
        self.sa.add_status("虚弱", 3)
        initial_cost, initial_duels = self.left.available_cost, self.sa.max_duels
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual(len(self.left.cardspace.hand.content), 5)
        self.assertEqual((self.sa.hp, self.sa.max_duels, self.left.available_cost),
                         (10, initial_duels + 1, initial_cost + 3))
        self.assertEqual((self.sa.statuses["虚弱"], self.sa.statuses["弥合"]), (1, 1))

    def test_shatter_body_loses_stacks_reflects_and_draws(self):
        self.sa.add_status("崩析", 1)
        self.oppose([50, -50, -50])
        card = self.fight("崩毁肉体")
        self.assertEqual([d.clash_result for d in card.instantiated_dice], ["lose", "win", "win"])
        self.assertEqual((self.sa.statuses["崩析"], len(self.left.cardspace.hand.content)), (1, 1))
        # One after-use piercing damage, one reflected physical damage, two printed physical damage.
        self.assertEqual(self.target.hp, 26)

    def test_lock_will_snapshots_dice_level_before_gaining_the_next_stack(self):
        self.sa.add_status("崩析", 5)
        self.sa.hp = 9
        self.oppose([-50, -50])
        card = self.fight("意志锁死")
        self.assertEqual((self.sa.statuses["崩析"], card.level_bonus, self.sa.hp), (6, 1, 10))
        self.assertEqual(self.target.hp, 30)
        self.assertEqual(self.target.statuses.get("崩析"), 2)
        self.assertEqual(self.queued(self.target, "骰子等级降低"), 1)

    def test_trace_rift_applies_stacks_then_propagates_on_later_positive_dice(self):
        self.oppose([-50, -50, -50])
        card = self.fight("循隙灭除")
        self.assertEqual((card.level_bonus, self.sa.statuses["崩析"]), (0, 1))
        self.assertEqual(self.target.statuses["崩析"], 4)
        self.assertEqual(self.queued(self.target, "崩析"), 1)
        self.assertEqual((len(self.left.cardspace.hand.content), self.target.hp), (1, 27))

    def test_crush_mind_rewards_the_winner_and_deals_effect_piercing(self):
        self.sa.add_status("崩析", 4)
        self.oppose([-50, 50, -50])
        card = self.fight("彻灭心神")
        self.assertEqual(self.sa.statuses["骰子等级降低"], 1)
        self.assertEqual(self.queued(self.target, "强壮"), 2)
        self.assertTrue(card.instantiated_dice[-1].did_deal_damage)
        self.assertFalse(card.instantiated_dice[-1].has_damage_part)
        self.assertEqual(self.target.hp, 27)

    def test_flash_rift_clashes_here_but_damages_and_marks_the_next_target(self):
        next_target = self.dummy("后卫")
        self.oppose([-50, -50, -50])
        self.oppose([], actor=next_target, slot=1)
        card = self.fight("闪进解离")
        self.assertEqual(card.instantiated_dice[-1].clash_result, "win")
        self.assertEqual(self.target.hp, 29)
        self.assertEqual(next_target.hp, 29)
        self.assertEqual(self.queued(self.target, "崩裂"), 0)
        self.assertEqual(self.queued(next_target, "崩裂"), 1)

    def test_flash_rift_without_a_next_target_pursues_the_current_opponent(self):
        segments = []
        self.game.context.register_entries(self.sa, [dict(
            trigger="AFTER DAMAGE", subject="source", operation=lambda ctx: segments.append(
                (ctx.event["damage_die"], ctx.event["target"], ctx.event["damage_amount"], ctx.event["penetration"])))])
        self.oppose([-50, -50, -50])
        card = self.fight("闪进解离")
        last = card.instantiated_dice[-1]
        self.assertEqual([s[1:] for s in segments if s[0] is last], [(self.target, 1, "pierce")])
        self.assertEqual(self.queued(self.target, "崩裂"), 0)
