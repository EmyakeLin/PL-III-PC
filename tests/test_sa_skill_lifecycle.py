import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from player.player import Player


def rule(trigger, code, **options):
    return dict(trigger=trigger, operation=dict(op="program", code=code), **options)


class SkillLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        left, right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([left, right], rng=random.Random(7))
        self.game.first_player = left
        self.a, self.b = [Character(dict(id=p.name, name=p.name, max_hp=20, rank="BOSS", skills=[]), p)
                          for p in self.game.players]
        left.characters.append(self.a)
        right.characters.append(self.b)
        self.game.start_turn()

    def card(self, owner, skill_id, entries=(), cost=0):
        card = Card(owner.player, dict(id=skill_id, name=skill_id, cost=cost, entries=entries, dice=[]), owner)
        owner.skills.append(card)
        return card

    def place(self, card, index=0):
        self.assertTrue(self.game.place_in_duel(card.player.side, card, index))

    def fight(self):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        for _ in range(600):
            if not self.game.pipeline.in_duel_phase:
                return
            self.game.next_step()
        self.fail("交锋未结束")

    def test_end_turn_recovers_exact_card_to_bottom_and_remembers_actual_caster(self):
        combo = self.card(self.a, "配合")
        stolen = self.card(self.b, "借用")
        stolen.set_controller(self.a)
        unpaid = self.card(self.a, "付不起", cost=100)
        observer = self.card(self.a, "回收", [rule("on_turn_end", [
            "$self", "配合", "USED_SKILL_THIS_TURN", "$self", "借用", "USED_SKILL_THIS_TURN", "AND",
            "$self", "付不起", "USED_SKILL_THIS_TURN", "NOT", "AND",
            ["$self", "绝技", "out_of_combat", "FIND_SKILL", "draw", "MOVE_CARD"], "WHEN",
        ], scope="turn")])
        ultimate = self.card(self.a, "绝技", [rule("after_skill_use", ["$card", "out_of_combat", "MOVE_CARD"])])
        other_copy = self.card(self.b, "绝技")
        self.b.player.cardspace.out_of_combat.add_card(other_copy)
        for card in (ultimate, unpaid, stolen, combo, observer):
            self.place(card)
        self.fight()
        self.assertEqual(self.a.player.cardspace.out_of_combat.content, [ultimate])
        self.assertNotIn((self.b, stolen.id), self.game.used_skill_ids)
        self.assertNotIn((self.a, unpaid.id), self.game.used_skill_ids)
        self.game.finish_turn()
        self.assertIs(stolen.character, self.b)
        self.game.context.dispatch_pipeline("on_turn_end")
        self.assertEqual(self.a.player.cardspace.draw.content, [combo, observer, unpaid, ultimate])
        self.assertEqual(self.b.player.cardspace.out_of_combat.content, [other_copy])
        self.game.context.dispatch_pipeline("on_turn_end")
        self.assertEqual(self.a.player.cardspace.draw.content.count(ultimate), 1)
        self.game.start_turn()
        self.assertFalse(self.game.used_skill_ids)

    def test_turn_end_of_borrowed_skill_remembers_the_user_after_recycling(self):
        borrowed = self.card(self.b, "借用", [
            rule("on_skill_use", ["$card", "次数", 2, "SET_SKILL_STATE"]),
            rule("on_turn_end", ["$self", "受益", "$owner", "次数", "SKILL_STATE", "STATUS"], scope="turn"),
        ])
        borrowed.set_controller(self.a)
        self.place(borrowed)
        self.fight()
        self.game.finish_turn()
        self.assertIs(borrowed.character, self.b)
        self.game.context.dispatch_pipeline("on_turn_end")
        self.assertEqual(self.a.statuses.get("受益"), 2)
        self.assertNotIn("受益", self.b.statuses)

    def test_next_duel_selector_destroys_only_opposing_cards_in_adjacent_slot(self):
        destroy_next = self.card(self.a, "截断", [rule("on_skill_use", [
            "$next_duel_enemy_skills", ["$target", "DESTROY"], "FOR_EACH_TARGET",
        ])])
        same_side = self.card(self.a, "友方")
        first, second, last = [self.card(self.b, str(i)) for i in range(3)]
        self.place(destroy_next)
        self.place(same_side, 1)
        self.place(first, 1)
        self.place(second, 1)
        self.place(last, 2)
        self.fight()
        self.assertTrue(first.destroyed and second.destroyed)
        self.assertFalse(same_side.destroyed or last.destroyed)
        self.assertEqual(self.game.used_cards, [destroy_next, same_side, last])

    def test_missing_next_enemy_skill_does_not_search_later_slots(self):
        first = self.card(self.a, "首交锋")
        waiting = self.card(self.b, "第三交锋")
        self.place(first, 0)
        self.place(waiting, 2)
        self.assertEqual(self.game.duelspace.next_duel_enemy_skills(1), [])
        self.assertIsNone(self.game.duelspace.next_duel_target(1))

    def test_removed_skill_keeps_duel_effect_through_following_ally_skill_only(self):
        exile = self.card(self.a, "离场", [
            rule("on_skill_use", ["$card", "已锁定", 1, "SET_SKILL_STATE"]),
            rule("BEFORE STATUS", [
                "$owner", "已锁定", "SKILL_STATE", [{"op": "cancel"}], "WHEN",
            ], scope="duel", subject="target", when={"status": "标记"}),
            rule("after_skill_use", ["$card", "out_of_combat", "MOVE_CARD"]),
        ])
        for index, card in enumerate((exile, self.card(self.a, "同一场"), self.card(self.a, "下一场"))):
            if index:
                self.game.context.register_entries(card, [rule("on_skill_use", ["$self", "标记", 1, "STATUS"])])
            self.place(card, int(index == 2))
        self.fight()
        self.assertEqual(self.a.statuses.get("标记"), 1)
        self.assertEqual(self.a.player.cardspace.out_of_combat.content, [exile])

    def recruit_sa(self):
        player = self.a.player
        spec = next(c for c in load_characters_from_packs() if c["id"] == "plan_b_sa")
        self.a = Character(spec, player)
        player.characters[:] = [self.a]
        self.a.init_cards()
        self.a.setup_deck()
        self.b.hp = self.b.max_hp = 100
        player.max_cost = 30
        return {card.name: card for card in self.a.skills}

    def use_yellow_wind(self, stacks):
        cards = self.recruit_sa()
        self.a.add_status("崩析", stacks)
        wind = cards["黄风漫天"]
        self.place(wind)
        opponent = Card(self.b.player, dict(id="rival", name="对位", cost=0, dice=[
            dict(type="slash", level=1, base_value=-30, entries=[]) for _ in range(5)]), self.b)
        self.place(opponent)
        levels = []
        self.game.context.register_entries(self.a, [dict(trigger="AFTER RESOLVE_DIE_LEVEL", subject="source",
            operation=lambda ctx: levels.append((ctx.event["die"].position, ctx.event["result"])))])
        self.fight()
        self.assertEqual(self.a.player.cardspace.out_of_combat.content, [wind])
        return levels

    def test_high_wind_repeats_the_printed_level_final_die_twice(self):
        levels = self.use_yellow_wind(6)
        self.assertEqual(levels, [(1, 2), (2, 1), (3, 4), (3, 4), (3, 4)])
        self.assertEqual(self.a.statuses["崩析"], 6)

    def test_low_wind_raises_first_dice_and_locks_last_die(self):
        levels = self.use_yellow_wind(5)
        self.assertEqual(levels, [(1, 6), (2, 5), (3, 4)])
        self.assertEqual(self.a.statuses["崩析"], 1)

    def test_printed_combo_recovers_wind_after_regular_recycling(self):
        cards = self.recruit_sa()
        wind = cards["黄风漫天"]
        for index, card in enumerate((wind, cards["分崩离析"], cards["闪进解离"])):
            self.place(card, index)
        self.fight()
        zones = self.a.player.cardspace
        self.assertEqual(zones.out_of_combat.content, [wind])
        self.game.context.dispatch_pipeline("before_turn_end")
        self.game.finish_turn()
        self.game.context.dispatch_pipeline("on_turn_end")
        self.assertFalse(zones.out_of_combat.content)
        self.assertIs(zones.draw.content[-1], wind)
        self.assertEqual(zones.draw.content.count(wind), 1)
