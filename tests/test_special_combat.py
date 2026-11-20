import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from loader import load_characters_from_packs
from models.card import Card, CardState
from models.character import Character
from models.duel import DuelSlot
from models.special_actions import SpecialAction
from player.player import Player


def die(kind="slash", damage=0, base=0, entries=()):
    return dict(type=kind, level=1, base_value=base, entries=([str(damage)] if damage else []) + list(entries))


class SpecialCombatTests(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(12))
        self.pipeline = self.game.pipeline
        self.game.first_player = self.left
        annolin = next(c for c in load_characters_from_packs() if c["name"] == "安诺琳")
        self.actor = Character(annolin, self.left)
        self.foe = Character(dict(id="guard", name="守卫", rank="ELITE", max_hp=30, skills=[]), self.right)
        self.left.characters.append(self.actor)
        self.right.characters.append(self.foe)
        self.actor.init_cards()
        self.game.start_turn()
        self.game.cards_revealed = True

    def skill(self, actor, name, dice, cost=0, **traits):
        card = Card(actor.player, dict(id=name, name=name, dice=dice, cost=cost, **traits), actor)
        actor.skills.append(card)
        return card

    def in_hand(self, card):
        card.player.cardspace.hand.add_card(card)
        return card

    def start(self, *cards):
        self.slot = DuelSlot(self.game)
        for card in cards:
            card.state = CardState.PLACED_FACE_UP
            self.slot.add_content(card.player.side, card)
        self.game.duelspace.append_new_duel(self.slot)
        self.pipeline.start_duel_combat()

    def until(self, node, side=1):
        while self.pipeline.in_duel_phase:
            result = self.game.next_step()
            if result[side - 1] == node:
                return
        self.fail(f"未抵达 {node}")

    def finish(self):
        for _ in range(900):
            if not self.pipeline.in_duel_phase:
                return
            self.game.next_step()
        self.fail("交锋未结束")

    def replace(self, new, old):
        self.assertTrue(self.game.special.apply(new.player, SpecialAction("replace", new, target_card=old)))

    def interrupt(self, card, target):
        self.assertTrue(self.game.special.apply(card.player, SpecialAction("attack", card, character=target)))
        self.assertIsNone(self.game.special.pending_attack)
        self.assertIsNotNone(self.pipeline.interrupt_space)

    def test_swap_after_hit_keeps_payment_and_damage_and_uses_fresh_skill_in_full(self):
        use = [dict(trigger="on_skill_use", operation="Shield: 1")]
        old = self.skill(self.actor, "旧", [die(damage=2), die(damage=10)], 2,
                         entries=use + [dict(trigger="after_skill_use", operation="Shield: 8")])
        new = self.in_hand(self.skill(self.actor, "新", [die(damage=3), die(damage=4)],
                                      3, anytime_replace=True, entries=use))
        self.start(old)
        self.until("on_dice_hit")
        self.replace(new, old)
        self.finish()
        self.assertEqual((self.foe.hp, self.actor.shield), (21, 2))
        self.assertEqual((self.actor.available_cost, self.left.available_cost), (0, 1))
        self.assertEqual(self.left.cardspace.hand.content, [old])
        self.assertEqual(self.slot.get_content(1), [new])
        self.assertEqual(new.current_dice_index, 2)
        self.assertFalse(self.pipeline.can_replace(self.slot, new))

    def test_lost_evade_has_no_result_but_its_activated_duel_effect_survives(self):
        old = next(c for c in self.actor.skills if c.name == "流风习习")
        self.actor.hp = 5
        incoming = self.in_hand(self.skill(self.actor, "接替", [die(damage=2)], anytime_replace=True))
        foe = self.skill(self.foe, "劈", [die(damage=1)])
        self.start(old, foe)
        self.until("on_dice_clash")
        evade = self.pipeline.current_clash_pair.dice_dict[1]
        self.replace(incoming, old)
        self.until("on_clash_win", side=2)
        self.assertEqual(self.pipeline.current_clash_results, {2: "win"})
        self.assertIsNone(evade.clash_result)
        self.assertFalse(self.actor.won_clash_this_turn)
        self.assertFalse(self.left.lost_duels)
        self.finish()
        # One vortex from actual damage during this duel. No evade heal or charge.
        self.assertEqual((self.actor.hp, self.actor.statuses.get("涡流")), (4, 1))
        self.assertFalse(any(owner is self.actor for owner, key in self.game.context.turn_entry_uses))
        self.assertFalse(self.game.context._lasting_entries)

    def test_unaffordable_replacement_leaves_paid_cost_and_prior_effects_in_place(self):
        gain = [dict(trigger="on_skill_use", operation="Shield: 1")]
        old = self.skill(self.actor, "已用", [die(damage=2)], 2, entries=gain)
        expensive = self.in_hand(self.skill(self.actor, "五费", [die(damage=5)], 5,
                                            anytime_replace=True, entries=gain))
        self.start(old)
        self.until("on_skill_use")
        self.replace(expensive, old)
        self.finish()
        self.assertEqual((self.actor.shield, self.actor.available_cost, self.left.available_cost), (1, 0, 4))
        self.assertEqual(self.foe.hp, 30)
        self.assertEqual(self.left.cardspace.hand.content, [old])
        self.assertEqual(self.slot.get_content(1), [expensive])

    def test_blank_round_still_obeys_range_win_branch_suppression(self):
        ranged = self.skill(self.actor, "远射", [die(damage=2)], range_level=2)
        incoming = self.in_hand(self.skill(self.actor, "空技能", [], anytime_replace=True))
        defense = self.skill(self.foe, "招架", [die("block", entries=[
            dict(trigger="on_clash_win", operation="Shield: 3")])])
        self.start(ranged, defense)
        self.until("on_dice_clash")
        survivor = self.pipeline.current_clash_pair.dice_dict[2]
        self.replace(incoming, ranged)
        self.finish()
        self.assertEqual(survivor.clash_result, "win")
        self.assertTrue(survivor.win_branch_skipped)
        self.assertTrue(self.foe.won_clash_this_turn)
        self.assertEqual(self.foe.shield, 0)

    def test_same_physical_card_exchanged_twice_still_starts_a_fresh_use(self):
        old = self.skill(self.actor, "再来", [die(damage=2)], 2, anytime_replace=True,
                         entries=[dict(trigger="on_skill_use", operation="Shield: 1")])
        substitute = self.in_hand(self.skill(self.actor, "调换", [die(damage=10)], 3, anytime_replace=True))
        defense = self.skill(self.foe, "招架", [die("block", entries=[dict(trigger="on_clash_win",
                                                                     operation="Shield: 1")])])
        self.start(old, defense)
        self.until("on_dice_clash")
        old_die = self.pipeline.current_clash_pair.dice_dict[1]
        self.replace(substitute, old)
        self.replace(old, substitute)
        self.finish()
        self.assertIsNone(old_die.clash_result)
        self.assertIsNot(old.instantiated_dice[0], old_die)
        self.assertEqual((self.foe.hp, self.foe.shield), (29, 0))
        self.assertEqual((self.actor.shield, self.left.available_cost), (2, 2))
        self.assertTrue(self.foe.won_clash_this_turn)
        self.assertEqual(self.left.cardspace.hand.content, [substitute])

    def test_two_nested_attacks_restore_the_exact_clash_and_its_scoped_listeners(self):
        old = self.skill(self.actor, "本场", [die(damage=2, base=9)], 1)
        foe = self.skill(self.foe, "架", [die("block")])
        prior = self.in_hand(self.skill(self.actor, "先前单独声明", [], anytime_play=["attack"]))
        first = self.in_hand(self.skill(self.actor, "插入甲", [die(damage=1)], anytime_play=["attack"]))
        second = self.in_hand(self.skill(self.foe, "插入乙", [die(damage=1)], anytime_play=["attack"]))
        self.start(old, foe)
        self.until("on_dice_clash")
        regular = self.game.duel_position()
        original_pair = self.pipeline.current_clash_pair
        self.interrupt(prior, self.foe)
        self.assertEqual(self.game.duel_position()[1], 0)
        while self.pipeline.interrupt_space is not None:
            self.game.next_step()
        self.assertEqual(self.game.duel_position(), regular)
        self.interrupt(first, self.foe)
        self.until("on_dice_use")
        outer_space = self.pipeline.interrupt_space
        group, index = self.game.duel_position()
        self.assertEqual(index, 1)
        outer_die = self.game.context.active_dice[1]
        self.interrupt(second, self.actor)
        self.assertIsNot(self.pipeline.interrupt_space, outer_space)
        self.assertEqual(self.game.duel_position(), (group, 2))
        while self.pipeline.interrupt_space is not outer_space:
            self.game.next_step()
        self.assertEqual(self.game.duel_position(), (group, 1))
        self.assertIs(self.game.context.active_dice[1], outer_die)
        while self.pipeline.interrupt_space is not None:
            self.game.next_step()
        self.assertEqual(self.game.duel_position(), regular)
        self.assertIs(self.pipeline.current_clash_pair, original_pair)
        self.assertIs(self.game.context.active_dice[1], original_pair.dice_dict[1])
        self.assertEqual((self.actor.hp, self.foe.hp), (8, 29))
        self.finish()
        self.assertEqual((self.actor.hp, self.foe.hp), (8, 27))
        self.assertEqual(original_pair.dice_dict[1].clash_result, "win")
        self.assertCountEqual(self.game.used_cards, [old, foe, prior, first, second])
        self.assertEqual([line for line in self.log.getvalue().splitlines() if line.startswith("结算即时交锋")],
                         ["结算即时交锋 1", "结算即时交锋 2", "结算即时交锋 3"])

    def test_nested_dice_round_limit_is_independent_and_restored_after_interrupt(self):
        self.actor.max_hp = self.actor.hp = 30
        original = self.skill(self.actor, "对位", [die(base=9)])
        defense = self.skill(self.foe, "对位守备", [die("block")])
        attack = self.in_hand(self.skill(self.foe, "单击", [die(damage=1)], anytime_play=["attack"]))
        self.start(original, defense)
        self.until("on_dice_clash")
        self.actor.add_status("致命失衡", 4)
        self.game.context.deal_damage(self.foe, self.actor, 1)
        self.assertEqual(self.actor.statuses["致命失衡"], 3)
        self.actor.add_status("裂血", 3)
        self.interrupt(attack, self.actor)
        while self.pipeline.interrupt_space is not None:
            self.game.next_step()
        # Child duel-start bleed and its die each consumed one layer.
        self.assertEqual(self.actor.statuses["致命失衡"], 1)
        self.game.context.deal_damage(self.foe, self.actor, 1)
        self.assertEqual((self.actor.hp, self.actor.statuses["致命失衡"]), (22, 1))
        self.finish()
