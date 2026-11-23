"""Paper automa rulings, checked against physical cards and the live game pipeline."""
import random
import http.client
import threading
import unittest
from unittest.mock import patch

from battle_mcp.challenges import CHALLENGES
from battle_mcp.room import Room
from battle_mcp.bot import choose_draw_bottom, choose_move
from battle_mcp.declarations import ORDINARY
from battle_mcp.transport import ArenaServer
from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.opcode import OpCode
from player.player import Player
from tests.test_mcp_transport import WireClient


class CarrierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = next(c for c in load_characters_from_packs(extra_packs=CHALLENGES["carrier"].packs)
                        if c["id"] == "structured_carrier")

    def setUp(self):
        self.human, self.machine = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.human, self.machine], rng=random.Random(12))
        self.ctx = self.game.context
        enemies = [dict(id=name, name=name, rank="NORMAL", max_hp=hp, skills=[])
                   for name, hp in (("甲一", 18), ("甲二", 12))]
        self.game.deploy_rosters([enemies, [self.pack]])
        self.boss, = self.machine.characters
        self.one, self.two = self.human.characters
        self.game.first_player = self.human
        self.game.start_turn()
        self.cards = {c.id.removeprefix("carrier_"): c for c in self.boss.skills}

    def place(self, card, index=0):
        self.assertTrue(self.game.place_in_duel(card.player.side, card, index))

    def dummy_card(self, *, dice=1, ranged=0, bonus=0, damage=1):
        return Card(self.human, dict(id="sample", name="陪练", cost=0, range_level=ranged, dice=[
            dict(type="slash", level=1, base_value=bonus, entries=[f"{damage}物理"]) for _ in range(dice)]), self.one)

    def fight(self):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=lambda low, high: high):
            for _ in range(2500):
                if self.game.is_over or not self.game.pipeline.in_duel_phase:
                    return
                self.game.next_step()
                if self.game.special.decision_owner:
                    self.assertIs(self.game.special.decision_owner, self.human)
                    options = self.game.special.options(self.human)
                    self.game.special.apply(self.human, options[0])
        self.fail("交锋未结束")

    def test_template_rolls_slots_targets_and_wait(self):
        for rolls, regular, early, high in (
            ([1], "nnnnn", 0, False), ([2], "dnnn", 0, False), ([3], "dnd", 2, False),
            ([4, 1], "nnnnn", 0, False), ([4, 2], "dnnn", 0, False),
            ([4, 3], "dnd", 2, False), ([4, 4], "ddd", 3, True)):
            with self.subTest(rolls=rolls):
                self.setUp()
                zones = self.machine.cardspace
                self.assertEqual((len(zones.draw.content), len(zones.decisive.content)), (10, 5))
                decks = {"n": zones.draw.content.copy(), "d": zones.decisive.content.copy()}
                expected = [decks[k].pop(0) for k in regular]
                with patch.object(self.game.rng, "randint", side_effect=rolls) as rng:
                    self.ctx.dispatch_pipeline("after_turn_start")
                    if rolls[0] == 4:
                        self.assertEqual(self.game.duelspace.space, [])
                    self.ctx.dispatch_pipeline("before_reveal")
                    self.ctx.dispatch_pipeline("on_before_reveal_phase_start")
                    self.assertEqual(rng.call_count, len(rolls))
                self.assertEqual([s.get_content(2)[0] for s in self.game.duelspace.space], expected)
                attacks = self.game.pre_reveal.space.space
                self.assertEqual([s.attack_card for s in attacks], decks["n"][:early])
                self.assertEqual([s.target_character for s in attacks], [self.one if high else self.two] * early)
                self.assertEqual(zones.hand.content, [])

    def test_modified_four_rerolls_only_once_and_returns_to_each_deck(self):
        self.boss.add_status("模板修正", 2)
        self.game.draw_phase()
        self.assertEqual(len(self.machine.cardspace.draw.content), 10)
        with patch.object(self.game.rng, "randint", side_effect=[2, 4]):
            self.ctx.dispatch_pipeline("after_turn_start")
            self.ctx.dispatch_pipeline("before_reveal")
        self.assertEqual(self.boss.statuses["模板数"], 6)
        selected = [slot.get_content(2)[0] for slot in self.game.duelspace.space]
        self.machine.max_cost = self.boss.independent_cost = 0
        for card in selected:
            self.assertTrue(self.machine.pay_skill_cost(card))
            self.assertEqual(card.cost, 3)
        self.game.finish_turn()
        self.assertEqual(self.machine.cardspace.decisive.content[-3:], selected)
        self.assertNotIn("模板数", self.boss.statuses)
        self.assertEqual(self.machine.cardspace.hand.content, [])

    def test_frozen_hp_and_first_real_hit_during_each_window(self):
        self.boss.hp = 12
        self.assertEqual(self.ctx.eval_block([self.boss, 4, OpCode.HEAL]), None)
        self.boss.take_damage(5)
        self.ctx.eval_block([self.boss, 4, OpCode.LOSE_HP])
        self.assertEqual(self.boss.hp, 12)
        self.boss.add_shield("normal", 5)
        self.ctx.eval_block([self.boss, 7, OpCode.REAL_DAMAGE])
        self.assertEqual((self.boss.hp, self.boss.shield, self.boss.statuses["纳米休止"]), (9, 5, 1))
        self.ctx.eval_block([self.boss, 2, OpCode.REAL_DAMAGE])
        self.assertEqual(self.boss.hp, 7)
        self.game.turn_count += 1
        self.game.open_turn()
        self.assertIn("纳米休止", self.boss.statuses)
        self.game.turn_count += 1
        self.game.open_turn()
        self.assertNotIn("纳米休止", self.boss.statuses)
        self.boss.add_status("载体容器", 2)
        self.ctx.eval_block([self.boss, 2, OpCode.REAL_DAMAGE])
        self.assertEqual(self.boss.hp, 5)
        self.assertNotIn("纳米休止", self.boss.statuses)

    def test_pressure_thresholds_and_sustained_strength(self):
        die = self.cards["heart"].get_current_die(self.game)
        self.one.add_status("威压", 6)
        self.assertEqual(die.resolve_level(), 5)
        self.two.add_status("威压", 1)
        self.assertEqual(die.resolve_level(), 6)
        for total in (11, 12, 17, 18, 23, 24):
            self.one.add_status("威压", min(12, total) - self.one.statuses["威压"])
            self.two.add_status("威压", max(0, total - 12) - self.two.statuses.get("威压", 0))
            expected = 0 if total == 11 else 2 + (total - 12) // 6
            self.assertEqual(self.boss.statuses.get("强壮", 0), expected)
        self.boss.clear_status("强壮")
        self.assertEqual(self.boss.statuses["强壮"], 4)
        self.one.add_status("威压", 20)
        self.assertEqual(self.one.statuses["威压"], 12)
        self.ctx.eval_block([self.two, self.two.hp, OpCode.REAL_DAMAGE])
        self.assertEqual(self.boss.statuses["强壮"], 2)

    def test_launch_precedes_overflow_rest_and_cools_six(self):
        self.boss.add_status("堆芯熔毁", 16)
        self.assertEqual(self.boss.status_overflow["堆芯熔毁"], 7)
        self.boss.add_status("载体容器", 2)
        self.assertEqual(self.boss.status_overflow["堆芯熔毁"], 5)
        self.boss.add_status("堆芯熔毁", 3)
        self.assertNotIn("纳米休止", self.boss.statuses)
        self.ctx.dispatch_pipeline("before_turn_end")
        self.assertNotIn("容器发射", self.boss.statuses)
        self.assertNotIn("载体容器", self.boss.statuses)
        self.assertNotIn("堆芯熔毁", self.boss.status_overflow)
        self.assertEqual(self.boss.statuses["纳米休止"], 1)

    def test_core_reward_self_damage_rounding_and_immunity(self):
        for stacks in (4, 5, 7, 8, 9):
            for protected in (False, True):
                with self.subTest(stacks=stacks, protected=protected):
                    self.setUp()
                    self.boss.add_status("堆芯熔毁", stacks)
                    if protected:
                        self.boss.add_status("熔毁免伤", 1)
                    self.game.finish_turn()
                    self.assertEqual(self.boss.hp, 18 if protected else 18 - stacks // 3)
                    self.assertEqual(self.boss.statuses["堆芯熔毁"], stacks - (stacks + 2) // 3)
                    self.assertEqual(self.boss.statuses.get("载体容器", 0), int(stacks >= 8))
                    self.game.prepare_turn()
                    self.assertEqual(self.boss.statuses.get("伤害提升", 0), int(stacks >= 5))

    def test_meltdown_only_gained_for_a_hit_over_one(self):
        for amount in (0, 1, 2, 7):
            die = self.dummy_card(damage=amount).get_current_die(self.game)
            self.ctx.resolve_hit(die, self.boss)
        self.assertEqual(self.boss.hp, 18)
        self.assertEqual(self.boss.statuses["堆芯熔毁"], 4)

    def test_percentage_health_shields_and_fractional_death(self):
        self.boss.add_status("载体容器", 2)
        die = self.cards["puncture"].get_current_die(self.game)
        self.one.hp = 9
        self.one.add_shield("normal", 4)
        with self.ctx.collect_facts() as facts:
            self.ctx.resolve_hit(die, self.one)
        segments = [v for k, v in facts if k == "direct_damage"]
        self.assertEqual([(v["amount"], v["grade"], v["lost"]) for v in segments], [(3.6, "concept", 3.6)])
        self.assertEqual(self.one.hp, 5)
        self.assertAlmostEqual(self.one.shield, 0.4)
        self.one.max_hp = 24
        self.ctx.resolve_hit(die, self.one)
        self.assertEqual(self.one.hp, 0)
        self.assertFalse(self.one.is_alive)

    def test_capture_requires_a_physical_skill(self):
        sample = self.dummy_card()
        temporary = Card(self.human, sample.data, self.one, temporary=True)
        self.place(temporary)
        self.assertFalse(self.ctx.eval_block([self.boss, temporary, "draw", True, OpCode.TAKE_BOARD_CARD]))
        self.assertIn(temporary, self.game.duelspace.space[0].get_content(1))
        self.assertNotIn(temporary, self.machine.cardspace.draw.content)

    def test_capture_takes_the_physical_card_and_recycles_to_new_owner(self):
        card = self.dummy_card(dice=4)
        self.place(self.cards["replica"])
        self.place(card)
        self.fight()
        self.assertIs(card.printed_owner, self.one)
        self.assertIs(card.character, self.boss)
        self.assertIs(self.machine.cardspace.draw.content[-1], card)
        self.assertNotIn(card, self.game.duelspace.space[0].get_content(1))
        self.game.finish_turn()
        card.data["requires_status"] = {"无法满足": 2}
        card.data["resource_cost"] = {"status": "能源", "amount": 4}
        self.place(card)
        self.assertTrue(self.machine.pay_skill_cost(card))
        self.game.finish_turn()
        self.assertIs(self.machine.cardspace.draw.content[-1], card)
        self.ctx.eval_block([self.one, self.one.hp, OpCode.REAL_DAMAGE])
        self.assertFalse(self.one.is_alive)
        self.assertTrue(self.boss.is_alive)
        self.assertFalse(card.destroyed)
        self.assertIs(self.machine.cardspace.draw.content[-1], card)

    def test_end_of_turn_container_opens_a_window_for_the_following_turn(self):
        self.boss.add_status("载体容器", 1)
        self.boss.add_status("堆芯熔毁", 8)
        self.game.finish_turn()
        self.assertEqual(self.boss.statuses["载体容器"], 2)
        self.assertIn("容器发射", self.boss.statuses)
        self.game.prepare_turn()
        hp = self.boss.hp
        self.ctx.eval_block([self.boss, 1, OpCode.REAL_DAMAGE])
        self.assertEqual(self.boss.hp, hp - 1)
        self.assertNotIn("纳米休止", self.boss.statuses)
        self.game.finish_turn()
        self.assertNotIn("容器发射", self.boss.statuses)
        self.assertNotIn("载体容器", self.boss.statuses)

    def test_percentage_absorbed_by_concept_shield_and_heal_keeps_fraction(self):
        self.boss.add_status("载体容器", 2)
        self.one.hp = 9
        self.one.add_shield("concept", 4)
        die = self.cards["puncture"].get_current_die(self.game)
        self.ctx.resolve_hit(die, self.one)
        self.assertEqual((self.one.hp, self.one.concept_shield), (9, 0.4))
        self.ctx.resolve_hit(die, self.one)
        self.assertEqual(self.one.hp, 5)  # 5.8 after the remaining shield absorbs 0.4.
        self.ctx.eval_block([self.one, 1, OpCode.HEAL])
        self.assertEqual(self.one.hp, 6)
        self.ctx.resolve_hit(die, self.one)
        self.assertEqual(self.one.hp, 3)  # 6.8 - 3.6 = 3.2.

    def test_parry_activates_only_when_opposed_and_deals_damage_once(self):
        for opposed in (False, True):
            with self.subTest(opposed=opposed):
                self.setUp()
                self.place(self.cards["parry"])
                if opposed:
                    self.place(self.dummy_card(dice=3))
                with self.ctx.collect_facts() as facts:
                    self.fight()
                parts = [e["amount"] for k, e in facts if k == "direct_damage"]
                self.assertEqual(parts, [1] if opposed else [])
                self.assertEqual(self.one.statuses.get("威压", 0), 3 if opposed else 0)

    def test_monster_counts_after_use_pressure_and_stops_at_printed_fifth_die(self):
        for stacks, uses in [(0, 2), (1, 2), (2, 3), (5, 4), (6, 5), (12, 5)]:
            with self.subTest(stacks=stacks):
                self.setUp()
                self.one.add_status("威压", stacks)
                self.machine.set_default_target(self.one)
                self.place(self.cards["monster"])
                with self.ctx.collect_facts() as facts:
                    self.fight()
                hits = [e for k, e in facts if k == "hit"]
                self.assertEqual(len(hits), uses)
                self.assertTrue(all(h["target"] == self.one.name for h in hits))

    def test_passive_attack_die_can_clash_against_a_block(self):
        guard = self.dummy_card()
        guard.dice[0]["type"] = "block"
        self.place(guard)
        parry = self.cards["parry"]
        self.place(parry)
        self.fight()
        self.assertEqual(parry.instantiated_dice[0].clash_result, "win")
        self.assertEqual(self.one.hp, 17)

    def test_nightmare_deals_from_correct_pile_and_returns_exceptions_to_hand(self):
        for name in ("barrier", "replica", "shackles"):
            with self.subTest(name=name):
                self.setUp()
                zones = self.machine.cardspace
                drawn = self.cards[name]
                zones.draw.content.remove(drawn)
                zones.draw.content.insert(0, drawn)
                self.place(self.cards["nightmare"])
                substitute = self.cards["crystal"]
                zones.decisive.content.remove(substitute)
                zones.decisive.content.insert(0, substitute)
                self.fight()
                is_exception = name in ("barrier", "replica")
                self.assertEqual(zones.hand.content, [drawn] if is_exception else [])
                self.assertEqual(self.game.duelspace.space[1].get_content(2),
                                 [substitute if is_exception else drawn])
                self.game.finish_turn()
                self.game.prepare_turn()
                self.assertEqual(self.boss.statuses["模板修正"], 1)

    def test_brand_checks_pressure_before_its_own_on_use_and_delays_limits(self):
        for initial in (5, 6):
            with self.subTest(initial=initial):
                self.setUp()
                self.machine.set_default_target(self.one)
                self.one.add_status("威压", initial)
                card = self.cards["brand"]
                self.place(card)
                self.fight()
                self.assertEqual(card.final_bonus, 3 if initial == 5 else 0)
                self.assertEqual(self.one.statuses["威压"], min(initial + 6, 12))
                self.assertNotIn("限制", self.one.statuses)
                self.game.finish_turn()
                self.game.prepare_turn()
                self.assertEqual(self.one.statuses["限制"], 2)
                self.assertNotIn("限制", self.two.statuses)

    def test_oppression_hits_each_enemy_and_schedules_weakness_once_per_character(self):
        self.place(self.dummy_card(dice=3))
        self.place(self.cards["oppression"])
        self.fight()
        self.assertEqual((self.one.hp, self.two.hp), (16, 10))
        self.assertEqual([enemy.statuses["威压"] for enemy in (self.one, self.two)], [3, 3])
        self.assertEqual(self.one.statuses["限制"], 2)
        self.assertNotIn("限制", self.two.statuses)
        self.game.finish_turn()
        self.game.prepare_turn()
        self.assertEqual([enemy.statuses["虚弱"] for enemy in (self.one, self.two)], [1, 1])

    def test_heart_second_die_reads_first_clash_result(self):
        for opposed in (False, True):
            with self.subTest(opposed=opposed):
                self.setUp()
                self.machine.set_default_target(self.one)
                card = self.cards["heart"]
                self.place(card)
                if opposed:
                    self.place(self.dummy_card())
                with self.ctx.collect_facts() as facts:
                    self.fight()
                self.assertEqual([v["amount"] for k, v in facts if k == "direct_damage"],
                                 [3, 2] if opposed else [3, 0])
                second = card.instantiated_dice[1]
                self.assertEqual(second.final_score, 14 if opposed else 12)

    def test_repair_heals_when_unfrozen_and_prevents_only_this_turns_meltdown(self):
        self.ctx.eval_block([self.boss, 1, OpCode.REAL_DAMAGE])
        self.boss.hp = 10
        self.boss.add_status("堆芯熔毁", 7)
        self.place(self.dummy_card(dice=3))
        self.place(self.cards["repair"])
        self.fight()
        self.assertEqual((self.boss.hp, self.boss.statuses["堆芯熔毁"]), (13, 5))
        self.game.finish_turn()
        self.assertEqual(self.boss.hp, 13)
        self.assertNotIn("熔毁免伤", self.boss.statuses)
        self.game.prepare_turn()
        self.assertEqual(self.boss.statuses["模板修正"], 1)

    def test_crystal_survives_destroy_and_repeats_its_d100(self):
        crystal = self.cards["crystal"]
        self.assertFalse(self.ctx.eval_block([crystal, OpCode.DESTROY]))
        other = Card(self.machine, dict(id=crystal.id, name="样本", cost=0, dice=[]), self.boss)
        self.assertTrue(self.ctx.eval_block([other, OpCode.DESTROY]))
        attack = self.dummy_card(dice=2)
        self.place(attack)
        self.place(crystal)
        self.fight()
        used = [d for d in crystal.instantiated_dice if d and d.landed_hits]
        self.assertEqual([(d.roll_max, d.final_score) for d in used], [(100, 130), (100, 130)])
        self.assertFalse(crystal.destroyed)

    def test_executioner_adds_a_separate_damage_part_only_at_six_pressure(self):
        for initial in (3, 4):
            with self.subTest(initial=initial):
                self.setUp()
                self.machine.set_default_target(self.one)
                self.one.add_status("威压", initial)
                self.place(self.cards["executioner"])
                with self.ctx.collect_facts() as facts:
                    self.fight()
                self.assertEqual([e["amount"] for k, e in facts if k == "direct_damage"],
                                 [2, 2, 1] if initial == 4 else [2, 2])
                self.assertEqual(self.one.statuses.get("虚弱", 0), 2 if initial == 4 else 0)

    def test_cataclysm_forces_launch_without_containers_and_rewards_a_kill(self):
        self.one.hp = 3
        self.machine.set_default_target(self.one)
        self.place(self.cards["cataclysm"])
        self.fight()
        self.assertFalse(self.one.is_alive)
        self.assertEqual(self.two.statuses["威压"], 6)
        self.assertIn("容器发射", self.boss.statuses)
        self.assertNotIn("载体容器", self.boss.statuses)

    def test_barrier_destroys_opposing_card_and_victim_discards_if_over_two(self):
        for n in (2, 3):
            with self.subTest(n=n):
                self.setUp()
                hand = self.human.cardspace.hand
                spare = self.dummy_card()
                hand.add_card(spare)
                attack = self.dummy_card(dice=n)
                self.place(attack)
                self.place(self.cards["barrier"])
                self.fight()
                self.assertTrue(attack.destroyed)
                self.assertFalse(spare.destroyed)
                self.assertEqual(spare in hand.content, n == 2)
                self.assertEqual(spare in self.human.cardspace.delayed_discard.content, n == 3)

    def test_counter_uses_two_physical_top_cards_on_ranged_openings(self):
        for i, ranged in enumerate((0, 1, 2, 1)):
            self.place(self.dummy_card(ranged=ranged), i)
        top = self.machine.cardspace.draw.content[:2]
        self.fight()
        slots = self.game.duelspace.space
        self.assertEqual([s.get_content(2) for s in slots[:4]], [[], [top[0]], [top[1]], []])
        self.assertEqual([c.effective_range for c in top], [c.data.get("range_level", 0)+1 for c in top])
        self.assertEqual(self.boss.rule_state["反制次数"], 2)

    def test_room_locks_challenge_on_ready_and_restart(self):
        room = Room(challenge=CHALLENGES["carrier"], seed=7)
        self.addCleanup(room.close)
        with self.assertRaises(ValueError):
            room.ready(1, 0, "other", human=True, canvas=True, roster=[["plan_b_annolin"], ["lan_qing"]])
        room.ready(1, 0, "start", human=True, canvas=True)
        view = room.canvas_state(1)
        self.assertEqual(view["challenge"], "结构化载体")
        with self.assertRaises(ValueError):
            room.rematch(1, view["revision"], "swap", roster=[["structured_carrier"], ["structured_carrier"]])
        room.rematch(1, view["revision"], "again")
        self.assertEqual(room.canvas_state(1)["match_number"], 2)


class ChallengeWireTests(WireClient, unittest.TestCase):
    def test_invitation_plays_and_restarts_both_challenges(self):
        for challenge, preset in CHALLENGES.items():
            with self.subTest(challenge=challenge):
                room = Room(challenge=preset, seed=4)
                with ArenaServer(room, port=0) as self.server:
                    thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
                    thread.start()
                    try:
                        self.assertEqual(set(self.server.tokens), {1})
                        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
                        try:
                            client.request("GET", "/canvas/")
                            response = client.getresponse()
                            self.assertEqual(response.status, 200)
                            self.assertIn(b'pixi-canvas', response.read())
                        finally:
                            client.close()
                        self.play(preset, squad=["plan_b_annolin", "plan_b_heris"])
                    finally:
                        self.server.shutdown()
                        thread.join(2)

    def play(self, preset, squad):
        def post(path, **body):
            code, state = self.request("/api/" + path, body, side=1)
            self.assertEqual(code, 200, state)
            return state

        lobby = post("canvas/state")
        self.assertEqual(lobby["challenge"], preset.name)
        post("canvas/ready", revision=lobby["revision"], request_id="start", roster=[squad, [preset.character_id]])
        for n in range(500):
            view = post("canvas/state")
            frame = view["frame"]
            self.assertIsNone(frame["players"][1]["hand"])
            args = dict(revision=view["revision"], request_id=str(n))
            if frame["is_over"]:
                break
            if draw := frame.get("draw_select"):
                post("canvas/draw_bottom", card_ids=choose_draw_bottom(draw), **args)
            elif moves := [m for m in view["options"] if m["kind"] in ORDINARY]:
                post("act", option_id=choose_move(frame, moves)["id"], **args)
            else:
                self.assertTrue(view["can_advance"])
                post("canvas/next", **args)
        else:
            self.fail("挑战未进入终局")
        public = self.request("/api/canvas/state", {})[1]
        self.assertTrue(public["frame"]["is_over"])
        self.assertEqual(public["frame"]["winner_side"], frame["winner_side"])
        self.assertTrue(all(p["hand"] is None for p in public["frame"]["players"]))
        post("canvas/rematch", revision=view["revision"], request_id="rematch")
        again = post("canvas/state")
        self.assertEqual(again["match_number"], 2)
        self.assertEqual(again["challenge"], preset.name)
