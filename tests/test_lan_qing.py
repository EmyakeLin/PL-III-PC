"""Exercise Lan Qing's printed rules through real placements, choices and dice rounds."""
import random
import unittest
from unittest.mock import patch

from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from player.player import Player


class LanQingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = next(c for c in load_characters_from_packs() if c["id"] == "lan_qing")

    def setUp(self):
        self.start_game()

    def start_game(self):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(27))
        self.game.first_player = self.left
        self.actor = self.recruit(self.left, self.pack)
        self.enemy = self.dummy(self.right, "甲敌")
        self.cards = {card.id: card for card in self.actor.skills}
        self.game.start_turn()
        self.left.max_cost = self.right.max_cost = 100

    @staticmethod
    def recruit(player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def dummy(self, player, name):
        return self.recruit(player, dict(id=name, name=name, rank="NORMAL", max_hp=80, skills=[]))

    def training(self, actor, *bases):
        return Card(actor.player, dict(id="training", name="陪练", cost=0, dice=[
            dict(type="slash", level=1, base_value=base, entries=["1物理"]) for base in bases]), actor)

    def place(self, card, slot=0):
        self.assertTrue(self.game.place_in_duel(card.player.side, card, slot))
        return card

    def fight(self):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=lambda low, high: high):
            for _ in range(5000):
                if self.game.is_over or not self.game.pipeline.in_duel_phase:
                    return
                self.game.next_step()
        self.fail("交锋未结算完毕")

    def test_solo_attack_rolls_once_and_resolves_final_score_without_clashing(self):
        card = self.training(self.actor, 5)
        card.dice[0]["multiplier"] = 2
        die = card.get_current_die(self.game)
        self.actor.add_status("强壮", 3)
        self.place(card)
        from entry.entry import Entry
        path = []
        for op in ("ROLL", "RESOLVE_FINAL_SCORE", "RESOLVE_CLASH_SCORE", "RESOLVE_HIT"):
            self.game.context.entries.append(Entry.from_spec(self.actor, dict(
                trigger="AFTER " + op, subject="source", operation=lambda ctx, op=op: path.append(op))))
        self.fight()
        self.assertEqual(path, ["ROLL", "RESOLVE_FINAL_SCORE", "RESOLVE_HIT"])
        self.assertEqual((die.value, die.final_score, die.clash_score, die.clash_result), (4, 21, None, None))

    def test_splitting_a_scored_pair_into_solo_attacks_keeps_the_original_rolls(self):
        actor_card = self.place(self.training(self.actor, 20))
        other_card = self.place(self.training(self.enemy, 0))
        self.game.context.register_entries(self.actor, [dict(trigger="before_clash_result", subject="source",
            operation={"op":"program", "code":["$event.die", "SPLIT_CLASH"]})])
        rolled = []
        self.game.context.register_entries(None, [dict(trigger="AFTER ROLL",
            operation=lambda ctx: rolled.append(ctx.event["die"]))])
        self.fight()
        dice = (actor_card.instantiated_dice[0], other_card.instantiated_dice[0])
        self.assertCountEqual(rolled, dice)
        self.assertEqual([(d.final_score, d.clash_result, d.landed_hits) for d in dice],
                         [(24, None, 1), (4, None, 1)])

    def test_paralysis_samples_only_combat_rolls_before_clamping_or_final_bonuses(self):
        die = self.training(self.actor, 5).get_current_die(self.game)
        self.actor.add_status("麻痹", 2)
        with patch.object(self.game.rng, "randint", side_effect=[3, 4, 4, 1, 4, 2]) as rng:
            self.actor.roll_speed()
            self.assertEqual(self.actor.statuses["麻痹"], 2)
            self.assertEqual((die.roll(), die.value), (6, 1))
            self.assertEqual(self.actor.statuses["麻痹"], 1)
            self.assertEqual((die.roll(), die.value), (8, 3))
            self.assertNotIn("麻痹", self.actor.statuses)
            self.assertEqual(die.roll(), 7)
            self.assertEqual(rng.call_count, 6)

    def test_each_target_gets_its_own_hit_and_stagger_receipt(self):
        other = self.dummy(self.right, "乙敌")
        self.enemy.add_status("失衡", 20)
        for enemy in (self.enemy, other):
            enemy.add_status("电击", 1)
        card = self.place(self.cards["lan_end"])
        with self.game.context.collect_facts() as facts:
            self.fight()
        hits = [data["target"] for kind, data in facts if kind == "hit"]
        self.assertEqual(hits, [self.enemy.combat_name] * 3 + [other.combat_name])
        self.assertEqual(card.instantiated_dice[2].landed_hits, 2)
        self.assertEqual([a.statuses["麻痹"] for a in (self.enemy, other)], [4, 4])
        self.assertEqual([a.statuses["电流"] for a in (self.enemy, other)], [5, 3])
        # First hit succeeds at 20, removes five, then grants its printed three.
        checks = [data["before"] for kind, data in facts if kind == "status_check" and data["check"] == "stagger"]
        self.assertEqual(checks, [20, 19, 1])

    def test_fatal_stagger_uses_the_current_segment_before_shields(self):
        ctx = self.game.context
        for base, bonus, stacks, expected, grade in (
                (1, 0, 2, 1, "normal"), (2, 0, 1, 4, "pierce"), (1, 1, 1, 3, "pierce")):
            with self.subTest(base=base, bonus=bonus):
                self.enemy.clear_status("致命失衡")
                self.enemy.add_status("致命失衡", 2)
                self.enemy.begin_dice_round()
                self.enemy.shield = 15
                with ctx.collect_facts() as facts, ctx.binding(hit_modifiers=[("damage_add", bonus, "normal")]):
                    actual = ctx.deal_damage(self.actor, self.enemy, base, damage_part=True)
                self.assertEqual((actual, self.enemy.statuses["致命失衡"]), (expected, stacks))
                segment = next(data for kind, data in facts if kind == "direct_damage")
                self.assertEqual((segment["grade"], segment["lost"]), (grade, 0 if grade == "normal" else expected))

    def test_end_snapshots_enemy_stagger_at_use_and_caps_only_its_clash_score(self):
        for stacks, fatal, expected in ((3, 1, 0), (4, 1, 1), (20, 20, 8)):
            with self.subTest(stacks=stacks, fatal=fatal):
                self.start_game()
                other = self.dummy(self.right, "失衡持有者")
                self.enemy.add_status("失衡", stacks)
                other.add_status("致命失衡", fatal)
                card = self.place(self.cards["lan_end"])
                self.place(self.training(self.enemy, -50, -50, -50))
                self.fight()
                self.assertEqual(card.use_state["拼点加值"], expected)
                self.assertEqual([d.clash_score - d.final_score for d in card.instantiated_dice], [expected] * 3)

    def test_current_overflow_requires_distinct_choices_before_recycling(self):
        cards = [self.training(self.enemy, n) for n in (1, 2, 3)]
        for card in cards:
            self.right.cardspace.hand.add_card(card)
        self.enemy.add_status("电流", 17)
        self.enemy.shield = 5
        self.game.finish_turn()
        self.assertEqual((self.enemy.hp, self.enemy.shield), (77, 2))
        self.assertEqual(self.game.turn_count, 0)
        for card in (cards[2], cards[0]):
            self.assertIs(self.game.special.decision_owner, self.right)
            action = next(a for a in self.game.special.options(self.right) if a.target_card is card)
            self.assertTrue(self.game.special.apply(self.right, action))
        self.assertEqual(self.right.cardspace.delayed_discard.content, [cards[2], cards[0]])
        self.game.finish_turn()
        self.assertEqual(self.right.cardspace.hand.content, [cards[1]])
        self.assertNotIn("电流", self.enemy.statuses)

    def test_destroyed_opponent_does_not_turn_the_promised_loss_into_a_win(self):
        card = self.place(self.cards["lan_open"])
        enemy = self.place(self.training(self.enemy, 60, 60))
        self.fight()
        first, second = card.instantiated_dice
        self.assertEqual((first.clash_result, second.clash_result), ("lose", "lose"))
        self.assertTrue(enemy.instantiated_dice[0].destroyed)
        self.assertIsNone(enemy.instantiated_dice[0].clash_result)
        self.assertEqual(enemy.instantiated_dice[1].clash_result, "win")
        self.assertEqual((first.base_value, second.base_value), (0, 2))
        self.assertEqual(self.enemy.statuses.get("电击"), 2)

    def test_single_survivor_uses_the_declared_result_or_ordinary_win(self):
        for result in (None, "lose", "draw", "win", "invalid"):
            with self.subTest(result=result):
                self.start_game()
                code = ["$event.opponent_die", "DESTROY"]
                if result is not None:
                    code += ["$event.die", result, "SET_UNOPPOSED_RESULT"]
                self.game.context.register_entries(self.enemy, [dict(
                    trigger="before_clash_result", subject="source", operation={"op":"program", "code":code})])
                first = self.place(self.training(self.actor, 50))
                second = self.place(self.training(self.enemy, 0))
                if result == "invalid":
                    with self.assertRaisesRegex(ValueError, "拼点结果"):
                        self.fight()
                    continue
                self.fight()
                self.assertTrue(first.instantiated_dice[0].destroyed)
                self.assertEqual(second.instantiated_dice[0].clash_result, result or "win")

    def test_hand_history_and_duel_floor_follow_the_actor(self):
        mate = self.dummy(self.left, "友")
        for actor, count in ((self.actor, 3), (mate, 1)):
            for index in range(count):
                card = self.training(actor, 0)
                self.left.cardspace.hand.add_card(card)
                self.place(card, index)
        self.place(self.training(self.actor, 0), 3)
        self.assertEqual(dict(self.game.turn_history.hand_plays), {self.actor: 3, mate: 1})
        self.game.turn_history.clear()
        self.actor.hp = 10
        cost = self.left.available_cost
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.actor.hp, self.left.available_cost), (11, cost + 1))
        self.game.turn_history.clear()
        self.game.context.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.actor.hp, self.left.available_cost), (11, cost + 1))
        for delta, expected in ((0, 3), (-1, 2), (-20, 2), (7, 10)):
            self.actor.turn_duel_bonus = delta
            self.assertEqual(self.actor.max_duels, expected)

    def test_shared_charge_is_spent_by_one_copy_and_the_current_form_finishes(self):
        key = "电叉·回环舞·活化"
        self.actor.add_status(key, 1)
        self.actor.add_status(key, 1)
        first, second = self.cards["lan_dance_3"], self.cards["lan_dance_2"]
        self.assertEqual((self.actor.statuses[key], first.effective_range), (1, 1))
        self.place(first)
        self.place(second, 1)
        self.fight()
        self.assertNotIn(key, self.actor.statuses)
        self.assertEqual([d.type for d in first.instantiated_dice], ["slash", "slash", "slash"])
        self.assertIn(second, self.left.cardspace.hand.content)

    def test_ultimate_counts_names_and_excludes_itself_in_the_other_branch(self):
        names = ["电叉·回环舞·活化", "电叉·极锐刺·活化", "深秋·风卷残叶·活化"]
        own = "残雪·幽蓝流光·活化"
        for prior, charged in ((1, False), (2, False), (0, True), (3, True)):
            with self.subTest(prior=prior, charged=charged):
                self.start_game()
                for name in names[:prior]:
                    self.actor.add_status(name, 1)
                if charged:
                    self.actor.add_status(own, 1)
                card = self.place(self.cards["lan_light"])
                self.fight()
                activated_itself = prior >= 2 and not charged
                self.assertEqual(card.dice[0]["type"], "evade" if charged or activated_itself else "pierce")
                self.assertNotIn(own, self.actor.statuses)
                self.assertEqual([self.actor.statuses.get(k, 0) for k in names], [0 if activated_itself else 1] * 3)

    def test_moved_tail_resumes_its_original_use_in_an_empty_friendly_slot(self):
        self.actor.add_status("电叉·极锐刺·活化", 1)
        skill = self.place(self.cards["lan_spike_2"])
        self.place(self.training(self.enemy, -50))
        other = self.dummy(self.right, "末场目标")
        self.place(self.training(other), 1)
        self.left.set_default_target(other)
        with self.game.context.collect_facts() as facts:
            self.fight()
        self.assertEqual(self.game.turn_history.skill_uses[self.actor, skill.id], 1)
        self.assertEqual([d["target"] for k, d in facts if k == "hit"], [self.enemy.combat_name, other.combat_name])
        slots = self.game.duelspace.space
        self.assertIn(skill, slots[0].get_content(1))
        self.assertNotIn(skill, slots[1].get_content(1))
        self.assertIs(skill.instantiated_dice[1].card, skill)
        self.assertEqual(self.actor.used_duels, 1)
        self.game.turn_number += 1
        self.game.context.dispatch_pipeline("on_turn_prepared")
        self.assertEqual(other.statuses["电击"], 2)

    def test_destroying_the_physical_card_in_its_old_slot_cancels_the_moved_die(self):
        self.actor.add_status("电叉·极锐刺·活化", 1)
        skill = self.place(self.cards["lan_spike_2"])
        self.place(self.training(self.enemy, -50))
        middle = self.place(self.training(self.enemy, 10), 1)
        self.place(self.training(self.enemy), 2)
        observed = []
        def destroy_original(ctx):
            from models.opcode import OpCode
            first, _, last = self.game.duelspace.space
            next_die = self.game.pipeline.next_planned_die(self.actor)
            observed.append((next_die.card, next_die.position, tuple(last.get_content(1))))
            for physical in first.get_content(1):
                ctx.eval_block([physical, OpCode.DESTROY])
        self.game.context.register_entries(middle, [dict(trigger="on_skill_use", operation=destroy_original)])
        with self.game.context.collect_facts() as facts:
            self.fight()
        self.assertEqual(observed, [(skill, 2, ())])
        self.assertTrue(skill.destroyed)
        self.assertEqual([data["card"] for kind, data in facts if kind == "hit"].count(skill.name), 1)
        self.assertIsNone(skill.instantiated_dice[1].final_score)

    def test_blank_copy_uses_first_adjacent_face_and_hits_current_victim(self):
        for first in (True, False):
            with self.subTest(first=first):
                self.start_game()
                current, adjacent = (0, 1) if first else (1, 0)
                other = self.dummy(self.right, "相邻敌人")
                self.left.set_default_target(other)
                sample = self.place(self.training(other, -40, -40), adjacent)
                ignored = self.place(self.training(other, 70, 70), adjacent)
                victim_card = self.place(self.training(self.enemy, 95, 95), current)
                leaf = self.place(self.cards["lan_leaf_4"], current)
                with self.game.context.collect_facts() as facts:
                    self.fight()
                self.assertTrue(victim_card.destroyed)
                self.assertEqual([die.clash_result for die in leaf.instantiated_dice], ["win", "win", None])
                self.assertEqual([d["target"] for k, d in facts if k == "hit" and d["card"] == leaf.name],
                                 [self.enemy.combat_name] * 2)
                self.assertFalse(sample.destroyed or ignored.destroyed)

    def test_blank_face_preserves_printed_numbers_and_omits_skill_and_die_effects(self):
        from entry.entry import Entry
        spec = {"id":"sample", "name":"样本", "cost":4, "range_level":2, "entries":["DRAW 3"],
                "dice":[{"type":"skip"}, {"type":"blunt", "level":4, "roll_max":10, "base_value":3,
                          "multiplier":2, "entries":["9物理"], "resource_cost":{"status":"电流", "amount":2}}]}
        rule = Entry.from_spec(self.actor, {"trigger":"on_skill_use", "operation":{"op":"program",
            "code":["$self", "副本", {"literal":spec}, "BLANK_SKILL_FACE", "SET_CHARACTER_STATE"]}})
        self.game.context._invoke(rule)
        result = self.actor.rule_state["副本"]
        self.assertEqual(result["dice"], [
            {"type":"skip"}, {"type":"blank", "level":4, "roll_max":10, "base_value":3, "multiplier":2}])
        self.assertEqual(result["cost"], 0)
        self.assertNotIn("entries", result)
        self.assertNotIn("range_level", result)
        self.assertEqual(spec["dice"][1]["entries"], ["9物理"])

    def test_destroyed_next_position_is_empty_or_collapses_as_printed(self):
        for active in (False, True):
            with self.subTest(active=active):
                self.start_game()
                if active:
                    self.actor.add_status("深秋·风卷残叶·活化", 1)
                leaf = self.place(self.cards["lan_leaf_3"])
                opponent = self.place(self.training(self.enemy, -20, -20, -20))
                with self.game.context.collect_facts() as facts:
                    self.fight()
                self.assertTrue(opponent.instantiated_dice[1].destroyed)
                self.assertEqual(opponent.instantiated_dice[1].keep_position, active)
                self.assertEqual(opponent.instantiated_dice[2].clash_result, "lose")
                scored = [d for k, d in facts if k == "clash_scored"]
                self.assertEqual(scored[1]["sides"][0][1], "blunt" if active else "slash")

    def test_last_snow_continues_past_one_cancelled_secondary_hit(self):
        shielded = self.dummy(self.right, "拦截")
        last = self.dummy(self.right, "后列")
        self.left.set_default_target(self.enemy)
        self.game.context.register_entries(shielded, [dict(
            trigger="BEFORE RESOLVE_HIT", subject="target", operation={"op": "cancel"})])
        self.place(self.cards["lan_end"])
        self.fight()
        self.assertEqual([actor.statuses.get("麻痹", 0) for actor in (self.enemy, shielded, last)], [3, 0, 3])

    def test_ultimate_duplicate_target_and_lethal_primary(self):
        for same, lethal in ((True, False), (False, False), (False, True)):
            with self.subTest(same=same, lethal=lethal):
                self.start_game()
                other = self.dummy(self.right, "次要目标")
                if lethal:
                    self.enemy.hp = 1
                card = self.place(self.cards["lan_light"])
                self.place(self.training(self.enemy, -40, -40))
                self.place(self.training(self.enemy if same else other, -40), 1)
                with self.game.context.collect_facts() as facts:
                    self.fight()
                hits = [d["target"] for k, d in facts if k == "hit" and d["card"] == card.name]
                self.assertEqual(hits[:1 if same else 2],
                                 [self.enemy.combat_name] if same else [self.enemy.combat_name, other.combat_name])
                self.assertEqual(card.instantiated_dice[0].landed_hits, 1 if same else 2)
                self.assertEqual(self.actor.rule_state["永久基础值"], 1 if same or lethal else 2)

    def test_no_adjacent_card_still_attacks_the_character_whose_skill_was_destroyed(self):
        other = self.dummy(self.right, "错误的默认目标")
        self.left.set_default_target(other)
        self.place(self.training(self.enemy, 60))
        leaf = self.place(self.cards["lan_leaf_4"])
        with self.game.context.collect_facts() as facts:
            self.fight()
        self.assertEqual([d["target"] for k, d in facts if k == "hit" and d["card"] == leaf.name],
                         [self.enemy.combat_name] * 2)

    def test_all_printed_faces_are_loadable_and_keep_their_printed_die_order(self):
        faces = {
            "open": ("evade blunt", ""), "dance_2": ("slash slash", "block blunt slash"),
            "dance_3": ("slash evade evade", "slash slash slash"), "turn": ("pierce pierce", ""),
            "spike_2": ("pierce blunt", "pierce slash"), "spike_3": ("pierce block blunt", "pierce"),
            "close": ("block evade block evade", ""), "leaf_3": ("evade slash evade", "evade slash blunt"),
            "leaf_4": ("evade slash blunt", "evade pierce slash blunt"),
            "light": ("pierce blunt", "evade slash pierce"), "end": ("slash slash slash", "")}
        self.assertEqual(set(self.cards), {"lan_" + key for key in faces})
        for ident, forms in faces.items():
            for active, types in enumerate(forms):
                if not types:
                    continue
                with self.subTest(ident=ident, active=active):
                    self.start_game()
                    card = self.cards["lan_" + ident]
                    if active:
                        self.actor.add_status(card.printed_data["form_when"]["status"], 1)
                    self.place(card)
                    self.place(self.training(self.enemy, *([-50] * 4)))
                    self.fight()
                    face = self.game.duelspace.space[0].used_skill_faces[1][0]
                    self.assertEqual([d["type"] for d in face["dice"]], types.split())
                    self.assertEqual(self.game.turn_history.skill_uses[self.actor, card.id], 1)
                    self.assertEqual(self.game.context.stack, [])

    def test_growth_uses_card_family_caps_and_survives_recycling(self):
        self.actor.rule_state.update({"极锐刺基础": 3, "风卷残叶骰级": 2})
        self.place(self.cards["lan_turn"])
        self.place(self.training(self.enemy, -50, -50))
        self.place(self.cards["lan_close"], 1)
        self.place(self.training(self.enemy, -50, -50, -50, -50), 1)
        self.fight()
        self.assertEqual(self.actor.rule_state, {"极锐刺基础": 4, "风卷残叶骰级": 3})
        self.game.finish_turn()
        self.game.start_turn()
        self.left.max_cost = 100
        self.place(self.cards["lan_turn"])
        self.place(self.cards["lan_spike_3"], 1)
        self.place(self.cards["lan_close"], 2)
        self.place(self.training(self.enemy, -50, -50, -50, -50), 2)
        leaf = self.place(self.cards["lan_leaf_4"], 3)
        levels = []
        self.game.context.register_entries(self.actor, [dict(trigger="AFTER RESOLVE_DIE_LEVEL",
            when=[{"left":"$event.card.id", "op":"eq", "right":leaf.id}],
            operation=lambda ctx: levels.append(ctx.event["result"]))])
        self.fight()
        self.assertEqual(self.actor.rule_state, {"极锐刺基础": 4, "风卷残叶骰级": 3})
        self.assertEqual(self.cards["lan_spike_3"].instantiated_dice[0].base_value, 4)
        self.assertIn(6, levels)
        self.assertIn(leaf, self.left.cardspace.hand.content)
