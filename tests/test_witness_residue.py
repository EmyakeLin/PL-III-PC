"""Printed rulings for the Light Creature Union challenge, exercised on live cards."""
import random
import unittest
from unittest.mock import patch

from battle_ui.table_bridge import TableBridge
from bots.witness_residue import choose_move
from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.opcode import OpCode
from player.player import Player
from terminal_events import format_fact


class ResidueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = {c["id"]: c for c in load_characters_from_packs()}

    def setUp(self):
        self.deploy()

    def deploy(self, extra_enemies=()):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(24))
        self.ctx = self.game.context
        dummy = dict(id="dummy", name="陪练", rank="NORMAL", max_hp=90, skills=[])
        self.game.deploy_rosters([[self.pool["witness_residue"]], [dummy, *extra_enemies]])
        self.actor, self.enemy = self.left.characters[0], self.right.characters[0]
        self.game.first_player = self.left
        self.game.draw_phase()
        self.game.start_turn()
        self.ctx.dispatch_pipeline("on_turn_start")
        self.cards = {c.name: c for c in self.actor.skills}

    def test_printing_and_start_resources(self):
        self.assertEqual(self.actor.name, "“目击残差”")
        self.assertEqual((self.actor.rank.name, self.actor.hp, self.actor.lightcore_hp), ("EXTREME", 30, 44))
        self.assertEqual((self.actor.max_duels, self.left.available_cost + self.actor.available_cost,
                          self.actor.statuses["能源"]), (5, 9, 6))
        self.assertEqual(len(self.cards), 15)
        self.assertEqual({c.cost for c in self.cards.values()}, {1, 2, 3})
        self.assertEqual(len(self.left.cardspace.hand.content), 4)

    def test_team_draw_keeps_four_and_preserves_bot_instances_and_choices(self):
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right], rng=random.Random(17))
        game.deploy_rosters([[self.pool["witness_residue"], self.pool["lan_qing"]], [self.pool["liu_yin"]]])
        game.draw_phase()
        choice = game.pending_draw
        self.assertEqual((len(choice.candidates), choice.keep, choice.discard_count), (5, 4, 1))
        game.complete_draw(choice, [choice.candidates[1]])
        self.assertEqual(left.cardspace.hand.content, [choice.candidates[i] for i in (0, 2, 3, 4)])
        self.assertIs(left.cardspace.draw.content[-1], choice.candidates[1])
        self.assertEqual(len(right.cardspace.hand.content), 3)

    def test_lightcore_recovery_is_public_and_only_reports_actual_points(self):
        bridge = TableBridge(self.ctx)
        self.actor.hp, self.actor.lightcore_hp = 25, 43
        with self.ctx.collect_facts() as facts:
            self.ctx.eval_block([self.actor, 3, OpCode.HEAL])
            self.ctx.eval_block([self.actor, 3, OpCode.HEAL])
        event, = [e for e in bridge.events if e["kind"] == "lightcore_healed"]
        self.assertEqual((event["target_id"], event["amount"], event["lightcore_after"]), (self.actor.id, 1, 44))
        line, = [format_fact(k, v) for k, v in facts if k == "lightcore_healed"]
        self.assertIn("“目击残差” 回复 1 点光点生命", line)

    def test_double_damage_uses_shield_input_and_heal_uses_actual_recovery(self):
        self.enemy.add_shield("normal", 6)
        before = self.enemy.lightcore_hp
        self.ctx.deal_damage(self.actor, self.enemy, 3, "normal", "blunt")
        self.assertEqual((self.enemy.hp, self.enemy.shield, self.enemy.lightcore_hp), (90, 3, before - 6))
        self.ctx.deal_damage(self.actor, self.enemy, 0, "normal", "blunt")
        self.assertEqual(self.enemy.lightcore_hp, before - 6)
        self.actor.hp = 28
        self.actor.lightcore_hp = 20
        self.ctx.eval_block([self.actor, 5, OpCode.HEAL])
        self.ctx.eval_block([self.actor, 5, OpCode.HEAL])
        self.assertEqual((self.actor.hp, self.actor.lightcore_hp), (30, 22))
        self.actor.hp, self.actor.lightcore_hp = 23, 43
        self.ctx.eval_block([self.actor, 3, OpCode.HEAL])
        self.assertEqual(self.actor.lightcore_hp, 44)

    def test_energy_thresholds_and_future_supply(self):
        self.actor.hp = 8
        self.actor.lightcore_hp = 15
        self.actor.add_status("能源", 40)
        for amount, expected in [(5, (8, 5, 0)), (2, (11, 1, 1)), (23, (23, 0, 4)), (6, (26, 0, 4))]:
            self.ctx.eval_block([self.actor, "能源", amount, OpCode.SPEND_STATUS])
            self.assertEqual((self.actor.hp, self.actor.rule_state["耗能余数"],
                              self.actor.rule_state.get("供能加成", 0)), expected)
        self.assertEqual(self.actor.lightcore_hp, 33)
        self.game.finish_turn()
        before = self.actor.statuses["能源"]
        hand = len(self.left.cardspace.hand.content)
        self.game.draw_phase()
        self.game.start_turn()
        self.ctx.dispatch_pipeline("on_turn_start")
        self.assertEqual((self.actor.statuses["能源"] - before, len(self.left.cardspace.hand.content) - hand), (7, 4))

    def fight(self, names, opponents=None, *, choose=True, opposing_range=0):
        selected = []
        for i, name in enumerate(names):
            self.assertTrue(self.game.place_in_duel(1, self.cards[name], i))
        for i, dice in enumerate(opponents or []):
            card = Card(self.right, dict(id=f"reply{i}", name="陪练技", cost=0, dice=dice,
                                         range_level=opposing_range), self.enemy)
            self.assertTrue(self.game.place_in_duel(2, card, i))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=lambda low, high: high):
            for _ in range(2500):
                if not self.game.pipeline.in_duel_phase or self.game.is_over:
                    return selected
                self.game.next_step()
                if player := self.game.special.decision_owner:
                    options = self.game.special.options(player)
                    wanted = "choose_option" if choose else "decline_option"
                    pick = next(o for o in options if o.kind == wanted)
                    selected.append(pick.option_id)
                    self.game.special.apply(player, pick)
        self.fail("交锋未结束")

    def test_paid_heavy_then_two_fresh_imprints(self):
        self.actor.add_status("能源", 2)
        with self.ctx.collect_facts() as facts:
            choices = self.fight(["倾身", "全形"])
        self.assertEqual(choices, ["lean", "unfold"])
        self.assertEqual([v["amount"] for k,v in facts if k == "status_spent" and v["name"] == "能源"], [4, 4])
        self.assertEqual([v["amount"] for k,v in facts if k == "direct_damage"], [2, 5, 3, 3, 3])
        self.assertEqual(self.actor.rule_state["余形"]["type"], "slash")
        self.assertIn("全形", self.actor.rule_state["余形说明"])

    def test_short_payment_or_declined_choice_keeps_the_baseline_card(self):
        for balance, choose, expected in ((1, True, []), (6, False, [None, None])):
            with self.subTest(balance=balance):
                self.setUp()
                self.actor.add_status("能源", balance - self.actor.statuses["能源"])
                with self.ctx.collect_facts() as facts:
                    choices = self.fight(["倾身", "折返"], choose=choose)
                self.assertEqual(choices, expected)
                self.assertEqual([v["amount"] for k,v in facts if k == "direct_damage"], [2, 3, 2])
                self.assertEqual(self.actor.statuses["能源"], balance)

    def test_sever_copy_destroys_only_current_opposing_card(self):
        weak = dict(type="slash",level=1,entries=["1物理"])
        with self.ctx.collect_facts() as facts:
            self.fight(["断节","全形"], [[weak], [weak]*4])
        destroyed = [v for k,v in facts if k == "die_destroyed"]
        self.assertEqual([(v["card_id"], v["position"]) for v in destroyed], [("reply1", 2), ("reply1", 4)])

    def test_sever_can_read_a_range_protected_card_but_cannot_destroy_its_die(self):
        weak = dict(type="slash", level=1, entries=["1物理"])
        for reach, positions in ((0, [3]), (1, [])):
            with self.subTest(reach=reach):
                self.deploy()
                with self.ctx.collect_facts() as facts:
                    self.fight(["断节"], [[weak] * 3], opposing_range=reach)
                self.assertEqual([v["position"] for k, v in facts if k == "die_destroyed"], positions)

    def test_prepend_preserves_previously_selected_dice_and_their_state(self):
        card = self.cards["并行"]
        first, second = card.planned_dice(self.game)
        second.destroyed = True
        face = self.cards["收束"].dice[0]
        card.prepend_printed_die(face, 2)
        left, right, tail = list(card.planned_dice(self.game))
        self.assertIs(tail, first)
        self.assertIs(card.instantiated_dice[-1], second)
        self.assertEqual((left.position, right.position, first.position, second.position), (1, 2, 3, 4))
        self.assertIsNot(left.data, right.data)
        self.assertEqual((left.is_printed_on_card, right.is_printed_on_card, tail.is_printed_on_card),
                         (False, False, True))

    def test_challenge_policy_builds_a_paid_sequence_and_declines_unsafe_healing(self):
        def skill(name, cost):
            return {"id": "residue_" + name, "cost": cost}
        cards = [skill("whole", 3), skill("core", 3)]
        actor = dict(max_hp=30, hp=23, max_lightcore_hp=24, cost={"available": 1},
                     duels={"max": 5, "used": 0}, statuses={"能源": 6})
        own = dict(side=2, characters=[actor], hand=cards, cost={"available": 8})
        frame = dict(viewer_side=2, players=[own, dict(side=1, characters=[{"alive": True}])], duels=[])
        moves = [dict(kind="place", card_id=c["id"]) for c in cards]
        self.assertEqual(choose_move(frame, moves)["card_id"], "residue_core")
        choices = [dict(kind="special_choose_option", option_id="restore"), dict(kind="special_decline_option")]
        self.assertIs(choose_move(frame, choices), choices[0])
        actor["hp"] = 24
        self.assertIs(choose_move(frame, choices), choices[1])

    def test_printed_guard_copy_enables_only_the_two_slashes(self):
        self.actor.hp = 10
        weak = dict(type="slash", level=1, entries=["1物理"])
        self.fight(["收束", "并行"], [[weak], [weak]*3])
        card = self.cards["并行"]
        self.assertEqual([d.type for d in card.instantiated_dice], ["block", "slash", "slash"])
        self.assertEqual([d.is_printed_on_card for d in card.instantiated_dice], [False, True, True])
        self.assertEqual([d.final_bonus for d in card.instantiated_dice], [0, 4, 4])
        self.assertEqual(self.actor.hp, 18)
        card.reset_for_draw()
        self.assertEqual([d["type"] for d in card.dice], ["slash", "slash"])

    def test_only_actually_rolled_faces_replace_the_public_imprint(self):
        # The last block has no opponent and never rolls. The first slash remains.
        self.fight(["横生", "折返"])
        self.assertEqual([d["type"] for d in self.cards["折返"].dice], ["slash", "pierce"])
        self.assertEqual(self.actor.rule_state["余形"]["type"], "pierce")
        self.game.finish_turn()
        self.assertIn("折返", self.actor.rule_state["余形说明"])

    def test_lurking_form_can_keep_or_release_previous_print(self):
        weak = dict(type="slash", level=1, entries=[])
        for choose, expected in ((True, "pierce"), (False, "evade")):
            with self.subTest(choose=choose):
                self.setUp()
                self.fight(["透界", "潜相"], [[weak], [weak]], choose=choose)
                self.assertEqual(self.actor.rule_state["余形"]["type"], expected)

    def test_native_lightcore_collapse_has_die_credit_and_restores_energy_or_hp(self):
        self.enemy.lightcore_hp = 5
        self.actor.hp = 12
        self.fight(["透界"])
        self.assertEqual((self.actor.statuses["能源"], self.actor.hp), (9, 12))
        self.setUp()
        self.enemy.lightcore_hp = 7
        self.actor.hp = 12
        self.fight(["贯核"])
        self.assertEqual((self.actor.statuses["能源"], self.actor.hp), (6, 16))

    def test_probe_reads_post_damage_integrity_and_regroup_heals_twice(self):
        self.enemy.lightcore_hp = self.enemy.max_lightcore_hp // 2 + 4
        self.fight(["探隙"])
        self.assertEqual(self.actor.statuses["能源"], 8)
        self.setUp()
        self.actor.hp, self.actor.lightcore_hp = 10, 10
        self.ctx.eval_block([self.actor, "能源", 3, OpCode.SPEND_STATUS])
        self.fight(["归拢"])
        self.assertEqual((self.actor.hp, self.actor.lightcore_hp), (18, 18))

    def test_wide_strike_settles_each_recipient_and_shed_grants_placement(self):
        self.deploy([dict(id="extra", name="陪练二", rank="NORMAL", max_hp=30, skills=[])])
        other = self.right.characters[1]
        self.enemy.add_shield("normal", 2)
        with self.ctx.collect_facts() as facts:
            self.fight(["蜕形", "横亘"])
        self.assertEqual([(v["character_id"], v["amount"]) for k,v in facts if k == "lightcore_damage"],
                         [(self.enemy.id, 4), (other.id, 4)])
        self.assertEqual((self.enemy.hp, other.hp), (90, 28))
        self.assertEqual(self.cards["横亘"].instantiated_dice[-1].final_bonus, 8)
        self.assertEqual(self.actor.ability_effects["置卡机会"], 1)
        self.assertTrue(any(k == "cards_drawn" and v["count"] == 1 for k,v in facts))
