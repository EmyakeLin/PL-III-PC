import random
import unittest
from unittest.mock import patch

from battle_ui.match import BattleMatch
from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.opcode import OpCode
from player.player import Player


class SPCharacterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = {spec["id"]: spec for spec in load_characters_from_packs()}

    def deploy(self, character, opponent=None):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(17))
        self.game.first_player = self.left
        dummy = dict(id="target", name="陪练", rank="NORMAL", max_hp=30, skills=[])
        self.game.deploy_rosters([[self.roster[character]], [self.roster[opponent] if opponent else dummy]])
        self.actor, self.enemy = self.left.characters[0], self.right.characters[0]
        self.ctx = self.game.context

    def start_turn(self):
        self.game.draw_phase()
        self.game.start_turn()
        self.ctx.dispatch_pipeline("on_turn_start")

    @staticmethod
    def training(actor, dice):
        return Card(actor.player, dict(id="training", name="陪练技", cost=0, dice=dice), actor)

    def finish_combat(self):
        for _ in range(1000):
            if not self.game.pipeline.in_duel_phase:
                return
            self.game.next_step()
        self.fail("交锋未完成")

    def resolve_overwrites(self, count):
        self.ctx.dispatch_pipeline("on_before_reveal_phase_start")
        slots = self.game.pre_reveal.space.space
        self.assertEqual([s.attack_card.id for s in slots], ["liu_overwrite"] * count)
        self.game.start_pre_reveal_declarations()
        for slot in slots:
            slot.ready = True
        self.game.pre_reveal.phase = "ready"
        self.game.pre_reveal.begin_resolution()
        with self.ctx.collect_facts() as facts:
            self.finish_combat()
        self.assertEqual([e["cost"] for k, e in facts if k == "skill_payment"], [0] * count)

    def test_pressure_has_no_cap_and_only_sp_losses_double(self):
        for character, start, loss in (("liu_yin", 18, 3), ("liu_yin_sp_quick", 18, 6),
                                       ("liu_yin_sp_unknown", 18, 6), ("liu_yin_sp_regent", 30, 6)):
            with self.subTest(character=character):
                self.deploy(character)
                self.assertEqual(self.actor.statuses["环境压制"], start)
                self.actor.add_status("环境压制", 23)
                self.assertEqual(self.actor.statuses["环境压制"], start + 23)
                self.actor.add_status("环境压制", -3)
                self.assertEqual(self.actor.statuses["环境压制"], start + 23 - loss)
                self.enemy.add_status("环境压制", 31)
                self.enemy.add_status("环境压制", -3)
                self.assertEqual(self.enemy.statuses["环境压制"], 28)

    def test_initial_insight_reserves_free_opening_overwrites(self):
        for character, initial, count in (("liu_yin_sp_quick", 15, 1), ("liu_yin_sp_unknown", 30, 3)):
            with self.subTest(character=character):
                self.deploy(character)
                self.assertEqual(self.actor.statuses["领域洞悉"], initial)
                self.start_turn()
                if count == 3:
                    self.assertEqual(self.actor.hp, 24)
                    self.assertTrue(self.actor.rule_state["天性解放"])
                    self.assertNotIn("环境压制", self.actor.statuses)
                self.resolve_overwrites(count)
                self.assertEqual(self.actor.statuses["环境同调"], count)
                if count == 3:
                    self.assertEqual(self.actor.statuses["领域洞悉"], 24)
                    self.game.finish_turn()
                    self.ctx.dispatch_pipeline("on_turn_end")
                    self.assertEqual(self.actor.statuses["领域洞悉"], 30)
                    self.actor.add_status("环境压制", 20)
                    self.start_turn()
                    self.assertEqual(self.actor.statuses["环境压制"], 20)
                    self.actor.add_status("领域洞悉", -11)
                    self.ctx.dispatch_pipeline("on_turn_end")
                    self.assertEqual(self.actor.statuses["领域洞悉"], 19)

    def test_regent_gets_rewards_only_after_her_own_overwrite(self):
        self.deploy("liu_yin_sp_regent", "liu_yin")
        self.start_turn()
        rewind = next(c for c in self.actor.skills if c.id == "liu_rewind")
        self.ctx.dispatch_pipeline("on_skill_use", source=self.actor, card=rewind, target=self.enemy)
        self.assertEqual(self.actor.statuses["环境压制"], 36)
        self.actor.add_status("领域洞悉", 10)
        self.enemy.add_status("领域洞悉", 10)
        self.assertNotIn("强壮", self.actor.statuses)
        self.game.finish_turn()
        self.start_turn()
        before = self.actor.statuses["领域洞悉"]
        self.resolve_overwrites(2)
        self.assertEqual(self.actor.statuses["领域洞悉"], before)
        self.assertEqual(self.actor.statuses["强壮"], 2)
        self.assertNotIn("强壮", self.enemy.statuses)
        self.actor.add_status("环境压制", -50)
        before = self.actor.statuses.get("能源", 0)
        self.actor.add_status("环境压制", -3)
        self.assertEqual(self.actor.statuses["能源"], before + 6)

    def test_selection_and_recurring_resources(self):
        forms = (
            ("liu_yin_sp_quick", "liu_yin", 18, 4, 1, 0),
            ("liu_yin_sp_unknown", "liu_yin", 24, 4, 1, 0),
            ("liu_yin_sp_regent", "liu_yin", 18, 5, 2, 3),
            ("lan_qing_sp_unmasked", "lan_qing", 18, 3, 0, 0),
            ("lan_qing_sp_unknown", "lan_qing", 30, 5, 2, 3),
        )
        for character, base, hp, duels, draw, cost in forms:
            with self.subTest(character=character):
                match = BattleMatch([[character], [base]], seed=17)
                catalog = {c["id"]: c for c in match.snapshot()["roster_catalog"]}
                self.assertEqual(catalog[character]["skills"], catalog[base]["skills"])
                self.assertNotEqual(catalog[character]["name"], catalog[base]["name"])
                actual = match.game.players[0].characters[0]
                self.assertEqual((actual.max_hp, actual.max_duels), (hp, duels))
                self.deploy(character)
                self.actor.hp = hp - 7
                for turn in (1, 2):
                    initial = len(self.left.cardspace.hand.content)
                    self.start_turn()
                    self.assertEqual(len(self.left.cardspace.hand.content) - initial,
                                     self.game.gamerule.DRAW_COUNT + (turn == 1) + draw)
                    self.assertEqual(self.left.max_cost, self.game.gamerule.MAX_BASIC_COST + cost)
                    self.assertEqual(self.right.max_cost, self.game.gamerule.MAX_BASIC_COST)
                    self.assertEqual(self.actor.hp, hp - 7 + (3 * turn if character == "lan_qing_sp_unknown" else 0))
                    self.game.finish_turn()
                    self.assertEqual(self.left.max_cost, 0)

    def test_snow_rechecks_life_and_applies_base_bonus_once(self):
        for character, threshold in (("lan_qing_sp_unmasked", 6), ("lan_qing_sp_unknown", 12)):
            with self.subTest(character=character):
                self.deploy(character)
                self.start_turn()
                self.actor.rule_state["永久基础值"] = 1
                dice = [dict(type="slash", level=1, base_value=0, entries=[]) for _ in range(5)]
                own = self.training(self.actor, dice)
                opposing = self.training(self.enemy, [dict(d, base_value=50) for d in dice])
                health = [threshold + 1, threshold + 1, threshold + 1, threshold, threshold - 1]
                self.ctx.register_entries(self.actor, [dict(trigger="before_dice_use", subject="source",
                    operation=lambda ctx: setattr(self.actor, "hp", health[ctx.event["die"].position - 1]))])
                self.assertTrue(self.game.place_in_duel(1, own, 0))
                self.assertTrue(self.game.place_in_duel(2, opposing, 0))
                self.game.reveal_cards()
                self.game.pipeline.start_duel_combat()
                self.finish_combat()
                self.assertEqual([d.destroyed for d in opposing.instantiated_dice], [True, True, False, True, False])
                self.assertEqual([d.clash_result for d in own.instantiated_dice], ["lose"] * 5)
                self.assertEqual([d.base_value for d in own.instantiated_dice], [1, 3, 3, 3, 3])
                self.game.finish_turn()
                self.start_turn()
                die = self.training(self.actor, dice).get_current_die(self.game)
                self.ctx.dispatch_pipeline("before_dice_use", source=self.actor, die=die)
                self.assertEqual(die.base_value, 1)

    def test_stagger_bonus_uses_the_success_receipt_and_its_target(self):
        self.deploy("lan_qing_sp_unknown", "lan_qing")
        for attacker, target, roll, expected in (
                (self.actor, self.enemy, 11, 0), (self.actor, self.enemy, 10, 2),
                (self.enemy, self.actor, 10, 1)):
            target.add_status("失衡", 10 - target.statuses.get("失衡", 0))
            with self.ctx.binding(source=attacker), patch.object(self.game.rng, "randint", return_value=roll):
                self.ctx.stack.append(target)
                self.assertEqual(self.ctx.execute_op(OpCode.STAGGER), roll <= 10)
            self.assertEqual(target.statuses.get("致命失衡", 0), expected)

    def test_final_score_replaces_each_direct_hit_segment_before_armor_and_shields(self):
        for score, maximum, fatal, expected in (
                (11, 30, False, [(2, "normal"), (1, "pierce")]),
                (12, 30, False, [(6, "concept"), (3, "concept")]),
                (13, 17, False, [(4, "concept"), (2, "concept")]),
                (12, 30, True, [(12, "concept"), (6, "concept")])):
            with self.subTest(score=score, maximum=maximum, fatal=fatal):
                self.deploy("lan_qing_sp_unknown")
                self.enemy.max_hp = maximum
                self.enemy.hp = maximum - 5
                self.enemy.shield = self.enemy.reinforced_shield = 20
                self.enemy.concept_shield = 2
                if fatal:
                    self.enemy.add_status("致命失衡", 2)
                die = self.training(self.actor, [dict(type="slash", level=1, entries=["2物理", "1穿甲"])]).get_current_die(self.game)
                die.final_score, die.clash_score = score, 50
                segments = []
                self.ctx.register_entries(self.actor, [dict(trigger="AFTER DAMAGE", subject="source",
                    operation=lambda ctx: segments.append((ctx.event["damage_die"], ctx.event["percentage_damage"])))])
                with self.ctx.collect_facts() as facts:
                    self.assertTrue(self.ctx.resolve_hit(die, self.enemy))
                direct = [e for k, e in facts if k == "direct_damage"]
                self.assertEqual([(e["amount"], e["grade"]) for e in direct], expected)
                self.assertEqual(segments, [(die, score >= 12)] * 2)
                lost = sum(n for n, _ in expected) - 2 if score >= 12 else 0
                self.assertEqual(self.enemy.hp, maximum - 5 - lost)
                if fatal:
                    self.assertEqual(self.enemy.statuses["致命失衡"], 1)

    def test_high_score_outside_a_hit_and_damage_from_another_source(self):
        self.deploy("lan_qing_sp_unknown")
        card = self.training(self.actor, [dict(type="evade", level=1, entries=[{
            "trigger":"on_clash_win", "operation":{"op":"program","code":["$event.target",2,"normal","evade","DAMAGE"]}
        }])])
        die = card.get_current_die(self.game)
        die.final_score = 12
        self.ctx.dispatch_pipeline("on_clash_win", source=self.actor, target=self.enemy, card=card, die=die)
        self.assertEqual(self.enemy.hp, 28)
        hit = self.training(self.actor, [dict(type="slash", level=1, entries=[])]).get_current_die(self.game)
        hit.final_score = 12
        self.ctx.register_entries(self.actor, [dict(trigger="AFTER RESOLVE_HIT", subject="source",
            operation={"op":"program","code":["$event.target",2,"normal","none","DAMAGE"]})])
        self.ctx.resolve_hit(hit, self.enemy)
        self.assertEqual(self.enemy.hp, 26)

    def test_printed_group_hit_reads_each_targets_current_maximum(self):
        self.deploy("lan_qing_sp_unknown")
        other = Character(dict(id="teammate", name="另一名陪练", rank="NORMAL", max_hp=11, skills=[]), self.right)
        self.right.characters.append(other)
        other.max_hp = 17
        other.hp = 9
        card = next(c for c in self.actor.skills if c.id == "lan_dance_3")
        card.set_form("active")
        die = card.get_current_die(self.game)
        die.final_score = 12
        with self.ctx.collect_facts() as facts:
            self.ctx.resolve_hit(die, other)
        self.assertEqual([(e["target"], e["amount"], e["grade"]) for k, e in facts if k == "direct_damage"],
                         [(other.name, 4, "concept"), (self.enemy.name, 6, "concept")])
        self.assertEqual((other.hp, self.enemy.hp), (5, 24))

    def test_infusion_moves_a_real_roll_over_the_percentage_threshold(self):
        for bonus, expected in ((0, (2, "normal")), (1, (6, "concept"))):
            with self.subTest(bonus=bonus):
                self.deploy("lan_qing_sp_unknown")
                self.start_turn()
                self.actor.turn_state["涌流灌注"] = bonus
                card = self.training(self.actor, [dict(type="slash", level=1, base_value=7, entries=["2物理"])])
                self.assertTrue(self.game.place_in_duel(1, card, 0))
                self.game.reveal_cards()
                self.game.pipeline.start_duel_combat()
                with patch.object(self.game.rng, "randint", side_effect=lambda low, high: high), self.ctx.collect_facts() as facts:
                    self.finish_combat()
                self.assertEqual(card.instantiated_dice[0].final_score, 11 + bonus)
                self.assertEqual([(e["amount"], e["grade"]) for k, e in facts if k == "direct_damage"], [expected])

    def test_cancelled_first_gain_keeps_the_regents_replacement_available(self):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        game = Game([self.left, self.right])
        actor = Character(self.roster["liu_yin_sp_regent"], self.left)
        game.context.register_entries(actor, [dict(trigger="BEFORE STATUS", subject="target",
            when=[dict(left="$event.status", op="eq", right="环境压制")],
            turn_limit={"key":"取消首次压制", "count":1}, operation={"op":"cancel"})])
        actor.add_status("环境压制", 9)
        self.assertNotIn("环境压制", actor.statuses)
        actor.add_status("环境压制", 4)
        self.assertEqual(actor.statuses["环境压制"], 30)
        actor.add_status("环境压制", -15)
        actor.add_status("环境压制", 7)
        self.assertEqual(actor.statuses["环境压制"], 7)
