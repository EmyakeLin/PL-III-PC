"""流阴及其引入的拼点规则，经真实卡面、词条和执行器结算。"""
import io
import random
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch

from battle_ui.table_bridge import TableBridge
from displayer import Displayer, _visible_card
from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.duel import ClashPair
from models.opcode import OpCode
from player.player import Player
from terminal_bridge import TerminalBridge


class LiuYinTests(unittest.TestCase):
    def setUp(self):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(17))
        self.game.first_player = self.left
        self.actor, self.enemy = [self.recruit(p, dict(id=p.name, name=p.name, rank="NORMAL",
                                                       max_hp=18, skills=[])) for p in self.game.players]

    def recruit(self, player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def die(self, actor):
        card = Card(actor.player, dict(name="取值测试", id="roll", cost=0,
                                       dice=[dict(type="slash", level=3, final_bonus=4)]), actor)
        return card.get_current_die(self.game)

    def test_choices_sample_the_modified_value_twice_and_roll_once(self):
        die = self.die(self.actor)
        paths = []
        ctx = self.game.context
        ctx.register_entries(self.actor, [
            dict(trigger="BEFORE RESOLVE_ROLL_VALUE", operation={"op":"program","code":[-1,"MUL",9,"ADD"]}),
            *[dict(trigger="AFTER " + name, operation=lambda vm, name=name: paths.append(name))
              for name in ("RESOLVE_ROLL_VALUE", "ROLL")]
        ])
        for ability, expected in (("优势次数", 6), ("劣势次数", 2)):
            self.actor.add_ability_effect(ability, 2)
            paths.clear()
            with patch.object(self.game.rng, "randint", side_effect=[3, 7]):
                self.assertEqual(die.roll(clash=True), expected + 4)
            self.assertEqual(die.value, expected)
            self.assertEqual(paths, ["RESOLVE_ROLL_VALUE", "RESOLVE_ROLL_VALUE", "ROLL"])
            self.assertEqual(self.actor.ability_effects[ability], 1)
            with patch.object(self.game.rng, "randint", return_value=5) as rng:
                die.roll()
                self.actor.roll_speed()
                self.assertEqual(rng.call_count, 2)
            self.assertEqual(self.actor.ability_effects[ability], 1)
            self.actor.spend_ability_effect(ability)

    def test_opposing_uses_cancel_on_grant(self):
        for first, second in (("优势次数", "劣势次数"), ("劣势次数", "优势次数")):
            for amount in (1, 2, 5):
                self.actor.ability_effects.clear()
                self.actor.add_ability_effect(first, 2)
                self.actor.add_ability_effect(second, amount)
                expected = {first: 1} if amount == 1 else {second: 3} if amount == 5 else {}
                self.assertEqual(self.actor.ability_effects, expected)

    def test_cancelled_grant_preserves_opposite_uses(self):
        self.actor.add_ability_effect("优势次数", 2)
        self.game.context.register_entries(self.actor, [dict(trigger="BEFORE ABILITY_EFFECT",
            subject="target", when=[dict(left="$event.ability",op="eq",right="劣势次数")],
            operation={"op":"cancel"})])
        self.actor.add_ability_effect("劣势次数", 1)
        self.assertEqual(self.actor.ability_effects, {"优势次数":2})

    def deploy(self, character_id="liu_yin"):
        data = next(c for c in load_characters_from_packs() if c["id"] == character_id)
        self.liu = self.recruit(self.left, data)
        self.cards = {card.id: card for card in self.liu.skills}
        self.game.start_turn()
        self.ctx = self.game.context

    def fight(self, card, opposing=None, *, balance=100):
        self.left.max_cost = self.right.max_cost = balance
        self.assertTrue(self.game.place_in_duel(self.left.side, card, 0))
        if opposing:
            self.assertTrue(self.game.place_in_duel(self.right.side, opposing, 0))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with self.game.context.collect_facts() as facts:
            for _ in range(2000):
                if not self.game.pipeline.in_duel_phase or self.game.is_over:
                    return facts
                self.game.next_step()
        self.fail("交锋未完成")

    def test_three_stacks_convert_only_eligible_physical_segments(self):
        self.deploy()
        self.liu.add_status("环境同调", 3)
        self.assertEqual((self.liu.hp, self.liu.lightcore_hp, self.liu.max_duels), (18, 28, 4))
        self.assertEqual(self.liu.statuses["环境压制"], 18)
        self.assertEqual(len([c for c in self.liu.skills if not c.out_of_combat]), 11)
        facts = self.fight(self.cards["liu_execution"])
        self.assertEqual([e["amount"] for kind, e in facts if kind == "lightcore_damage"], [4, 4, 7])
        self.assertFalse(any(kind == "direct_damage" for kind, _ in facts))
        with self.ctx.collect_facts() as facts:
            self.ctx.deal_damage(self.liu, self.enemy, 2)
        self.assertEqual([k for k, _ in facts if k in ("direct_damage", "lightcore_damage")],
                         ["direct_damage", "lightcore_damage"])

    def test_overwrite_crossed_thresholds_choose_enemy_and_pay_zero(self):
        self.deploy()
        other = self.recruit(self.right, dict(id="enemy2", name="第二名敌人", rank="NORMAL", max_hp=18, skills=[]))
        self.liu.add_status("领域洞悉", 21)
        self.liu.add_status("领域洞悉", -13)
        self.liu.add_status("领域洞悉", 2)
        self.game.finish_turn()
        self.game.start_turn()
        choice = Mock()
        choice.resolve.return_value = other
        self.left.target_order = choice
        self.ctx.dispatch_pipeline("on_before_reveal_phase_start")
        slots = self.game.pre_reveal.space.space
        self.assertEqual(len(slots), 2)
        self.assertEqual(choice.resolve.call_args.args[0], [self.enemy, other])
        self.assertEqual([slot.target_character for slot in slots], [other, self.enemy])
        self.assertIsNot(slots[0].attack_card, slots[1].attack_card)
        self.assertTrue(all(slot.attack_card.temporary and slot.attack_card.cost == 3 for slot in slots))
        self.left.max_cost = self.liu.independent_cost = 0
        self.game.start_pre_reveal_declarations()
        for slot in slots:
            slot.ready = True
        self.game.pre_reveal.phase = "ready"
        self.game.pre_reveal.begin_resolution()
        with self.ctx.collect_facts() as facts:
            for _ in range(500):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
            else:
                self.fail("开牌前交锋未结算")
        self.assertEqual([e["cost"] for k, e in facts if k == "skill_payment"], [0, 0])
        self.assertEqual(self.liu.statuses["环境同调"], 2)

    def test_reversal_swaps_the_conditions_and_preserves_draws_and_scores(self):
        self.deploy()
        first = self.cards["liu_invisible"].get_current_die(self.game)
        other = self.die(self.enemy)
        other.final_bonus = 0
        pair = ClashPair({1:first, 2:other})
        for a, b, result in ((3, 7, "win"), (7, 3, "lose"), (3, 3, "draw")):
            first.value, other.value = a, b
            self.assertEqual(pair.clash_check()[1], result)
            self.assertEqual((first.clash_score, other.clash_score), (a, b))
        first.make_blank()
        first.value, other.value = 3, 7
        self.assertNotIn("拼点逆转", first.score_traits())
        self.assertEqual(pair.clash_check(), {1: "lose", 2: "win"})

    def test_reversal_is_printed_once_on_the_invisible_slash(self):
        self.deploy()
        card = self.cards["liu_invisible"]
        catalog = Displayer(self.game).catalog()
        liu = next(c for c in catalog["players"][0]["characters"] if c["id"] == self.liu.id)
        printed = next(skill for skill in liu["skills"] if skill["id"] == card.id)
        for face in (printed, _visible_card(card)):
            self.assertNotIn("拼点逆转", face["range_traits"])
            self.assertEqual(face["dice"][0]["range_traits"].count("拼点逆转"), 1)
        self.assertEqual(card.describe().count("拼点逆转"), 1)
        self.assertTrue(all("拼点逆转" not in die["range_traits"]
                            for die in _visible_card(self.cards["liu_blade"])["dice"]))

    def test_catalog_terminal_and_both_armor_faces_read_structured_data(self):
        self.deploy()
        catalog = Displayer(self.game).catalog()
        actor = next(c for c in catalog["players"][0]["characters"] if c["id"] == self.liu.id)
        self.assertNotIn("printed_text", actor)
        with redirect_stdout(io.StringIO()) as out:
            TerminalBridge.show_character(self.liu.data)
        self.assertIn("流阴", out.getvalue())
        self.assertIn("光生会", out.getvalue())
        raw_passives = [
            spec for spec in (*self.liu.data.get("faction_passives", ()), *self.liu.data.get("passive_skills", ()))
            if not (isinstance(spec, dict) and spec.get("hidden"))
        ]
        projected_passives = actor["faction_passives"] + actor["passives"]
        self.assertEqual(len(projected_passives), len(raw_passives))
        for raw, projected in zip(raw_passives, projected_passives):
            self.assertEqual(projected["name"], raw.get("name"))
            expected_lines = [line for line in raw["description"].splitlines() if line.strip()]
            self.assertEqual(projected["display_lines"], expected_lines)
        for name in ("领域洞悉", "环境同调", "环境压制"):
            self.assertTrue(catalog["statuses"][name])
        self.assertEqual(len(actor["skills"]), len(self.liu.data["skills"]))
        for spec in actor["skills"]:
            self.assertNotIn("printed_text", spec)
            card = self.cards[spec["id"]]
            for form in [None, *card.data.get("forms", {})]:
                card.set_form(form)
                face = _visible_card(card)
                raw_entries = (card.data["forms"][form].get("entries", card.data.get("entries", ()))
                               if form else card.data.get("entries", ()))
                expected_visible = [e["description"] for e in raw_entries
                                    if isinstance(e, dict) and not e.get("hidden") and e.get("description")]
                with self.subTest(card=card.name, form=form):
                    self.assertEqual(face["name"], card.name)
                    self.assertEqual(face["cost"], card.cost)
                    self.assertEqual(face["entries"], expected_visible)
                    for die in face["dice"]:
                        self.assertNotIn("printed_line", die)
                        self.assertIn("damage_parts", die)
        rewind = _visible_card(self.cards["liu_rewind"])
        self.assertEqual(rewind["dice"][0]["damage_parts"][0]["amount"], 1)
        self.assertEqual(rewind["dice"][0]["damage_parts"][0]["grade"], "normal")

    def test_invisible_hit_follows_low_score_and_ties_produce_no_hit(self):
        for against, result, hits in ((7, "win", ["无形杀"]), (1, "lose", ["对手斩击"]), (3, "draw", [])):
            with self.subTest(against=against):
                self.setUp()
                self.deploy()
                card = self.cards["liu_invisible"]
                opponent = Card(self.right, dict(id="slash", name="对手斩击", cost=0, dice=[
                    dict(type="slash", level=3, final_bonus=against - 3)]), self.enemy)
                with patch.object(self.game.rng, "randint", return_value=3):
                    facts = self.fight(card, opponent)
                sides, = [event["sides"] for kind, event in facts if kind == "clash_scored"]
                scores = {side[0]: side[2:5] for side in sides}
                self.assertEqual(scores[self.liu.combat_name], (3, 3, result))
                self.assertEqual(scores[self.enemy.combat_name][:2], (against, against))
                self.assertEqual([event["card"] for kind, event in facts if kind == "hit"], hits)

    def test_percentage_uses_max_hp_concept_shield_and_separate_light_segment(self):
        self.deploy()
        self.enemy.max_hp = 17
        self.enemy.hp = 12
        self.enemy.concept_shield = 4
        self.liu.add_status("环境同调", 3)
        self.liu.add_status("战甲", 1)
        facts = self.fight(self.cards["liu_armor"])
        self.assertEqual([(e["amount"], e["grade"], e["lost"]) for k,e in facts if k=="direct_damage"],
                         [(6, "concept", 2)])
        self.assertEqual([e["amount"] for k,e in facts if k=="lightcore_damage"], [6])

    def test_instant_death_compares_authority_for_each_attempt(self):
        self.deploy()
        self.ctx.register_entries(self.enemy, [dict(trigger="BEFORE CHECK_DEATH", subject="target",
            authority="较高话语权", operation={"op":"cancel"})])
        with self.ctx.binding(authority=0):
            for _ in range(3):
                self.assertFalse(self.ctx.eval_block([self.enemy, OpCode.INSTANT_DEATH]))
        self.assertTrue(self.enemy.is_alive)
        with self.ctx.binding(authority=2):
            self.assertTrue(self.ctx.eval_block([self.enemy, OpCode.INSTANT_DEATH]))
        self.assertFalse(self.enemy.is_alive)

    def emit_use(self, card, target=None):
        self.ctx.dispatch_pipeline("on_skill_use", side=self.left.side, source=self.liu,
                                   card=card, target=target or self.enemy)

    def test_rewind_pressure_changes_on_use_hit_loss_and_after_use(self):
        for target_score, die_delta in ((1, -1), (7, 3), (3, 0)):
            for energy in (0, 1):
                with self.subTest(target_score=target_score, energy=energy):
                    self.setUp()
                    self.deploy()
                    self.liu.add_status("环境压制", -13)
                    if energy:
                        self.liu.add_status("能源", energy)
                    opponent = Card(self.right, dict(id="other", name="对手斩击", cost=0, dice=[
                        dict(type="slash", level=3, final_bonus=target_score - 3)]), self.enemy)
                    with patch.object(self.game.rng, "randint", return_value=3):
                        facts = self.fight(self.cards["liu_rewind"], opponent)
                    changes = [e for k, e in facts if k == "status_balance" and e["status"] == "环境压制"]
                    self.assertEqual(changes[0]["before"], 5)
                    expected = [6]
                    if die_delta:
                        expected.append(die_delta)
                    expected.append(-2)
                    if energy:
                        expected.append(-1)
                    expected.append(-1)  # 行至阴处的首张技能
                    self.assertEqual([e["after"] - e["before"] for e in changes], expected)

    def test_rewind_merges_actual_stacks_and_restores_life_without_heal(self):
        for initial_drop in (0, -13):  # 分别测试满压制 18 与低压制 5 起手
            with self.subTest(initial_drop=initial_drop):
                self.setUp()
                self.deploy()
                if initial_drop:
                    self.liu.add_status("环境压制", initial_drop)
                before_pressure = self.liu.statuses["环境压制"]
                self.liu.hp = 12
                self.liu.add_status("强壮", 2)
                self.liu.add_status("虚弱", 2)
                self.emit_use(self.cards["liu_rewind"])
                self.liu.hp = 8
                self.liu.add_status("强壮", 1)
                self.liu.add_status("虚弱", -1)
                self.liu.add_status("束缚", 2)
                # 减到原本压制层数或更低但尚未归零时，不应触发回退
                current = self.liu.statuses["环境压制"]
                self.liu.add_status("环境压制", -(current - max(1, before_pressure - 1)))
                self.assertEqual(self.liu.hp, 8)
                self.assertTrue(self.liu.rule_state.get("逆流溯源待生效"))
                # 环境压制减少至 0 时触发回退
                with self.ctx.collect_facts() as facts:
                    self.liu.add_status("环境压制", -self.liu.statuses["环境压制"])
                self.assertEqual(self.liu.hp, 12)
                self.assertEqual(self.liu.statuses["强壮"], 3)
                self.assertEqual(self.liu.statuses["虚弱"], 1)
                self.assertNotIn("束缚", self.liu.statuses)
                self.assertNotIn("环境压制", self.liu.statuses)
                self.assertEqual(self.liu.statuses["领域洞悉"], 12)
                self.assertFalse(self.liu.rule_state.get("逆流溯源待生效"))
                self.assertFalse(any(k in ("healed", "lightcore_damage") for k, _ in facts))
                self.assertFalse(any(effect.terms.event == "on_status_changed" for effect in self.ctx.scheduled_effects))

    def test_rewind_recast_before_trigger_overwrites_saved_snapshot_and_keeps_single_schedule(self):
        self.deploy()
        self.liu.hp = 15
        self.liu.add_status("强壮", 3)
        self.liu.add_status("虚弱", 1)
        self.emit_use(self.cards["liu_rewind"])
        # 生效前状态变化，再次打出逆流溯源，应直接覆盖旧存档且只保留 1 个监听
        self.liu.hp = 10
        self.liu.add_status("强壮", -2)
        self.liu.add_status("虚弱", 1)
        self.emit_use(self.cards["liu_rewind"])
        scheduled = [e for e in self.ctx.scheduled_effects if e.terms.event == "on_status_changed"]
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(self.liu.rule_state["逆流溯源生命"], 10)
        # 再次受损与叠负面后，清空环境压制，按第二次存档回退
        self.liu.hp = 6
        self.liu.add_status("虚弱", 2)
        with self.ctx.collect_facts() as facts:
            self.liu.add_status("环境压制", -self.liu.statuses["环境压制"])
        self.assertEqual(self.liu.hp, 10)
        self.assertEqual(self.liu.statuses["强壮"], 1)
        self.assertEqual(self.liu.statuses["虚弱"], 2)
        self.assertFalse(any(k in ("healed", "lightcore_damage") for k, _ in facts))
        self.assertFalse(any(e.terms.event == "on_status_changed" for e in self.ctx.scheduled_effects))

    def test_rewind_does_not_trigger_after_death(self):
        self.deploy()
        self.liu.hp = 12
        self.emit_use(self.cards["liu_rewind"])
        self.liu.hp = 0
        self.liu.check_death()
        self.assertFalse(self.liu.is_alive)
        self.liu.add_status("环境压制", -self.liu.statuses["环境压制"])
        self.assertEqual(self.liu.hp, 0)
        self.assertFalse(self.liu.is_alive)

    def test_rewind_marker_displays_saved_snapshot_excludes_pressure_and_self_and_clears_on_trigger(self):
        self.deploy()
        self.assertNotIn("溯源标记", self.liu.statuses)
        self.assertNotIn("溯源标记", self.game.status_entries)

        def projected_liu():
            snap = Displayer(self.game).snapshot()
            return next(c for p in snap["players"] for c in p["characters"] if c["id"] == self.liu.id)

        self.assertNotIn("溯源标记", projected_liu()["status_details"])
        # 第一次打出：有其他状态时展示生命与其他状态，过滤环境压制与溯源标记自身
        self.liu.hp = 15
        self.liu.add_status("强壮", 2)
        self.liu.add_status("虚弱", 1)
        self.emit_use(self.cards["liu_rewind"])
        self.assertEqual(self.liu.statuses.get("溯源标记"), 1)
        details = projected_liu()["status_details"]["溯源标记"]
        self.assertEqual(details[0], "已记录生命：15")
        self.assertIn("强壮 2", details[1])
        self.assertIn("虚弱 1", details[1])
        self.assertNotIn("环境压制", details[1])
        self.assertNotIn("溯源标记", details[1])
        # 生效前清空其他状态后重打：标记仍为 1，详情刷新且过滤自身与环境压制后显示“无”
        self.liu.hp = 10
        self.liu.clear_status("强壮")
        self.liu.clear_status("虚弱")
        self.emit_use(self.cards["liu_rewind"])
        self.assertEqual(self.liu.statuses.get("溯源标记"), 1)
        self.assertEqual(projected_liu()["status_details"]["溯源标记"], ["已记录生命：10", "已记录状态：无"])
        # 环境压制归零触发回退后，溯源标记清除且不再出现在 status_details
        self.liu.add_status("环境压制", -self.liu.statuses["环境压制"])
        self.assertNotIn("溯源标记", self.liu.statuses)
        self.assertNotIn("溯源标记", projected_liu()["statuses"])
        self.assertNotIn("溯源标记", projected_liu()["status_details"])

    def test_adaptation_uses_actual_safe_payment_then_heals_separately(self):
        self.deploy()
        self.liu.add_status("领域洞悉", 10)
        self.liu.hp = 3
        card = self.cards["liu_adapt"]
        self.emit_use(card)
        self.assertEqual((self.liu.hp, self.liu.statuses["领域洞悉"]), (1, 12))
        self.ctx.dispatch_pipeline("after_skill_use", side=self.left.side, source=self.liu,
                                   card=card, target=self.enemy)
        self.assertEqual((self.liu.hp, self.enemy.lightcore_hp), (2, 27))

    def test_rewind_restores_spike_activation_but_leaves_infusion_at_its_current_value(self):
        self.deploy()
        self.liu.add_status("环境压制", -13)
        pack = next(c for c in load_characters_from_packs() if c["id"] == "lan_qing")
        card = Card(self.left, next(s for s in pack["skills"] if s["id"] == "lan_turn"), self.liu)
        self.emit_use(card)
        self.emit_use(self.cards["liu_rewind"])
        rewind = next(e for e in self.ctx.scheduled_effects if e.terms.event == "on_status_changed")
        self.assertEqual(self.liu.rule_state["逆流溯源状态"]["电叉·极锐刺·活化"], 1)
        self.assertNotIn("涌流灌注", self.liu.rule_state["逆流溯源状态"])
        self.emit_use(card)
        self.ctx.eval_block([self.liu, "电叉·极锐刺·活化", 1, OpCode.SPEND_STATUS])
        self.liu.add_status("环境压制", -6)
        self.assertIn(rewind, self.ctx.scheduled_effects)
        self.assertNotIn("电叉·极锐刺·活化", self.liu.statuses)
        self.liu.add_status("环境压制", -self.liu.statuses["环境压制"])
        self.assertNotIn(rewind, self.ctx.scheduled_effects)
        self.assertEqual(self.liu.statuses["电叉·极锐刺·活化"], 1)
        self.assertEqual(self.liu.turn_state["涌流灌注"], 4)

    def test_zero_release_subsequent_reduction_and_armor_actual_gain(self):
        self.deploy()
        self.liu.add_status("战甲", 1)
        self.liu.add_status("领域洞悉", 29)
        self.liu.add_status("环境压制", -18)
        self.assertEqual((self.liu.statuses["领域洞悉"], self.liu.statuses["能源"]), (30, 30))
        # 环境压制为 0 时，处于天性解放状态，减少环境压制改为获得能源
        self.assertTrue(self.liu.rule_state.get("天性解放"))
        self.liu.add_status("环境压制", -2)
        self.assertEqual((self.liu.statuses.get("环境压制", 0), self.liu.statuses["能源"]), (0, 32))
        # 环境压制再次 > 0 时，解除天性解放状态：减压制正常扣压制而不获能源，拼点开始/失败也不打光点
        self.liu.add_status("环境压制", 4)
        self.assertFalse(self.liu.rule_state.get("天性解放"))
        self.liu.add_status("环境压制", -2)
        self.assertEqual((self.liu.statuses["环境压制"], self.liu.statuses["能源"]), (2, 32))
        before_lc = self.enemy.lightcore_hp
        self.ctx.dispatch_pipeline("before_dice_clash", side=self.left.side, source=self.liu, target=self.enemy)
        self.ctx.dispatch_pipeline("on_clash_lose", side=self.left.side, source=self.liu, target=self.enemy)
        self.assertEqual(self.enemy.lightcore_hp, before_lc)
        # 压制重新归零后，重新进入天性解放，但不重复发放行至阴处的 12 层领域洞悉
        self.liu.add_status("领域洞悉", -10)
        self.liu.add_status("环境压制", -2)
        self.assertEqual(self.liu.statuses.get("环境压制", 0), 0)
        self.assertTrue(self.liu.rule_state.get("天性解放"))
        self.assertEqual(self.liu.statuses["领域洞悉"], 20)
        self.liu.add_status("环境压制", -3)
        self.assertEqual(self.liu.statuses["能源"], 35)
        self.ctx.dispatch_pipeline("before_dice_clash", side=self.left.side, source=self.liu, target=self.enemy)
        self.ctx.dispatch_pipeline("on_clash_lose", side=self.left.side, source=self.liu, target=self.enemy)
        self.assertEqual(self.enemy.lightcore_hp, before_lc - 2)

    def test_rewind_works_again_after_release_once_pressure_returns_to_zero(self):
        self.deploy()
        # 先清空环境压制进入天性解放
        self.liu.add_status("环境压制", -18)
        self.assertTrue(self.liu.rule_state.get("天性解放"))
        # 解放后打出逆流溯源：加 6 压制并挂溯源标记，天性解放状态随之解除
        self.liu.hp = 14
        self.emit_use(self.cards["liu_rewind"])
        self.assertEqual(self.liu.statuses["环境压制"], 6)
        self.assertEqual(self.liu.statuses["溯源标记"], 1)
        self.assertFalse(self.liu.rule_state.get("天性解放"))
        self.liu.hp = 9
        # 压制 > 0 时可以正常扣减环境压制直至归零，触发回退、清除溯源标记并重新进入天性解放
        self.liu.add_status("环境压制", -6)
        self.assertEqual(self.liu.hp, 14)
        self.assertNotIn("环境压制", self.liu.statuses)
        self.assertNotIn("溯源标记", self.liu.statuses)
        self.assertTrue(self.liu.rule_state.get("天性解放"))
        self.assertEqual(self.liu.statuses["领域洞悉"], 12)
        # 归零后天性解放重新生效，后续减压制转为能源
        self.liu.add_status("环境压制", -2)
        self.assertEqual(self.liu.statuses.get("能源", 0), 2)

    def test_extreme_range_triggers_retaliation_but_protected_skill_stays_live(self):
        self.deploy()
        other = Card(self.right, dict(id="range", name="远程", cost=0, range_level=3, dice=[]), self.enemy)
        protected = self.cards["liu_overwrite"]
        protected.set_range_opponent(other)
        self.assertEqual(protected.range_deficit, 2)
        self.ctx.eval_block([protected, OpCode.DESTROY])
        self.assertFalse(protected.destroyed)
        self.assertIsNone(self.ctx.eval_block([protected, OpCode.NEGATE_SKILL]))
        self.assertFalse(other.destroyed)
        self.cards["liu_blade"].set_range_opponent(other)
        self.assertTrue(other.destroyed)
        self.assertEqual(self.enemy.ability_effects["劣势次数"], 1)
        self.assertEqual(self.liu.statuses["环境压制"], 14)

    def test_self_destruction_retaliates_once(self):
        self.deploy()
        other = self.die(self.enemy).card
        other.dice[0]["base_value"] = -50
        self.liu.hp = 15
        self.fight(self.cards["liu_hope"], other)
        self.assertEqual((self.liu.hp, self.enemy.ability_effects.get("劣势次数")), (16, 1))
        self.assertTrue(other.destroyed)

    def test_each_collapse_heal_including_a_nested_collapse(self):
        self.deploy()
        self.liu.add_status("环境同调", 3)
        self.liu.hp = 10
        self.actor.lightcore_hp = self.enemy.lightcore_hp = 1
        with self.ctx.collect_facts() as facts, self.ctx.binding(source=self.liu):
            self.ctx.eval_block([self.enemy, 1, OpCode.LIGHTCORE_DAMAGE])
        self.assertEqual([e["amount"] for k,e in facts if k=="healed"], [3, 3])
        self.assertEqual(self.liu.hp, 16)
        self.assertEqual(self.liu.lightcore_hp, 22)

    def test_returned_finisher_ends_only_this_duel(self):
        self.deploy()
        card = self.cards["liu_annihilate"]
        self.liu.add_status("环境同调", 3)
        other = Card(self.right, dict(id="break", name="毁牌", cost=0, dice=[dict(
            type="slash", level=1, base_value=120, entries=["1物理",dict(
                trigger="on_dice_hit", operation={"op":"program","code":["$event.opponent_card","DESTROY"]})])]), self.enemy)
        following = Card(self.right, dict(id="next",name="下一场",cost=0,dice=[
            dict(type="slash",level=1,entries=["1光点"])]), self.enemy)
        self.assertTrue(self.game.place_in_duel(self.right.side, other, 0))
        self.assertTrue(self.game.place_in_duel(self.right.side, following, 1))
        skipped = Card(self.right, dict(id="unused",name="本场待用",cost=0,dice=[
            dict(type="slash",level=1,entries=["1光点"])]), self.enemy)
        self.game.duelspace.space[0].add_content(self.right.side, skipped)
        facts = self.fight(card)
        self.assertIn(card, self.left.cardspace.hand.content)
        self.assertFalse(card.destroyed)
        self.assertEqual([e["card"] for k,e in facts if k=="skill_used"].count("下一场"), 1)
        self.assertFalse(any(k == "skill_used" and e["card"] == "本场待用" for k,e in facts))

    def test_finisher_uses_pre_collapse_hp_and_carries_only_the_excess(self):
        self.deploy()
        self.enemy.lightcore_hp = 1
        self.liu.add_status("能源", 5)
        self.liu.add_status("骰子等级降低", 4)
        card = self.cards["liu_annihilate"]
        die = card.get_current_die(self.game)
        die.resolve_level()
        self.assertEqual(die.roll_max, 100)
        attempts = []
        self.ctx.register_entries(self.enemy, [
            dict(trigger="BEFORE CHECK_DEATH", subject="target", operation=lambda ctx: (
                attempts.append(ctx.event["lethal"]), ctx.cancel_op(0)))])
        bridge = TableBridge(self.ctx)
        facts = self.fight(card)
        self.assertEqual(attempts, [])
        self.assertTrue(self.enemy.is_alive)
        self.assertEqual((self.enemy.hp, self.enemy.lightcore_hp, self.enemy.max_lightcore_hp), (9,17,20))
        self.assertEqual([e["amount"] for k, e in facts if k == "lightcore_damage"], [4])
        self.assertEqual([e["lost"] for k, e in facts if k == "lightcore_overflow"], [3])
        self.assertEqual([(e["kind"], e.get("lightcore_after")) for e in bridge.events
                          if e["kind"].startswith("lightcore_")],
                         [("lightcore_damage", 0), ("lightcore_collapse", None), ("lightcore_restored", 24),
                          ("lightcore_max_changed", 20), ("lightcore_overflow", 17)])
        self.assertNotIn("能源", self.liu.statuses)

    def test_finisher_two_collapses_then_three_death_checks_even_after_full_revives(self):
        for revives, survives in ((3, False), (4, True)):
            with self.subTest(revives=revives):
                self.setUp()
                self.deploy()
                target = self.enemy
                target.lightcore_hp = 1
                self.liu.add_status("能源", 22)  # 21 光点，刚好打空 1/28 和恢复后的 20/20。
                target.add_status("复活次数", revives)
                checks = []
                self.ctx.register_entries(target, [
                    dict(trigger="BEFORE CHECK_DEATH", subject="target",
                         operation=lambda ctx: checks.append((ctx.event["lethal"], target.hp))),
                    dict(trigger="BEFORE CHECK_DEATH", subject="target",
                         when=[{"left":{"field":"$self.statuses","key":"复活次数","default":0},"op":"gt","right":0}],
                         operation={"op":"program","code":[
                             "$self", "复活次数", 1, "SPEND_STATUS", "$self", "$self.max_hp", "SET_HP", {"op":"cancel"}]}),
                ])
                facts = self.fight(self.cards["liu_annihilate"])
                self.assertEqual(checks, [(False, 0), (True, 18), (True, 18), (True, 18)])
                self.assertEqual((target.is_alive, target.hp), (survives, 18 if survives else 0))
                self.assertEqual([e["amount"] for k, e in facts if k == "real_damage"], [9, 9])
                self.assertEqual([e["amount"] for k, e in facts if k == "lightcore_damage"], [21])
                self.assertEqual([e["amount"] for k, e in facts if k == "status_spent" and e["name"] == "复活次数"],
                                 [1] * revives)
                self.assertEqual(len([1 for k, e in facts if k == "hit"]), 1)

    def test_finisher_threshold_uses_the_current_max_and_rounds_half_up(self):
        for max_hp, hp, expected in ((17, 9, 3), (17, 9.5, 0), (17, 10, 0), (19, 10, 3)):
            with self.subTest(max_hp=max_hp, hp=hp):
                self.setUp()
                self.deploy()
                self.enemy.max_hp = max_hp
                self.enemy.hp = hp
                self.enemy.lightcore_hp = 1
                self.liu.add_status("能源", 2)
                attempts = []
                def protect(ctx):
                    if ctx.event["lethal"]:
                        attempts.append(self.enemy.hp)
                    self.enemy.hp = 17
                    ctx.cancel_op(0)
                self.ctx.register_entries(self.enemy, [dict(trigger="BEFORE CHECK_DEATH", subject="target", operation=protect)])
                facts = self.fight(self.cards["liu_annihilate"])
                self.assertEqual(len(attempts), expected)
                self.assertFalse(any(k == "lightcore_overflow" for k, _ in facts))

    def test_all_liu_forms_apply_lightcore_modifiers_and_pay_for_one_hit(self):
        for character_id in ("liu_yin", "liu_yin_sp_quick", "liu_yin_sp_unknown", "liu_yin_sp_regent"):
            with self.subTest(character_id=character_id):
                self.setUp()
                self.deploy(character_id)
                self.liu.add_status("能源", 19)
                self.enemy.lightcore_hp = 1
                receipts = []
                def observe(ctx):
                    e = ctx.event
                    receipts.append((e["damage_die"], e["amount"], e["result"], e["lightcore_lost"]))
                self.ctx.register_entries(self.enemy, [
                    dict(trigger="BEFORE LIGHTCORE_DAMAGE", operation={"op":"program","code":[2,"ADD"]}),
                    dict(trigger="AFTER LIGHTCORE_DAMAGE", operation=observe),
                ])
                card = self.cards["liu_annihilate"]
                die = card.get_current_die(self.game)
                facts = self.fight(card)
                self.assertEqual(receipts, [(die, 20, 20, 20)])
                self.assertEqual(self.enemy.lightcore_hp, 1)
                self.assertEqual([e["amount"] for k, e in facts if k == "status_spent" and e["name"] == "能源"], [19])

    def test_passive_damage_during_the_finisher_does_not_inherit_its_die(self):
        self.deploy()
        self.enemy.lightcore_hp = 1
        self.liu.add_status("能源", 5)
        self.ctx.register_entries(self.liu, [dict(trigger="BEFORE LIGHTCORE_DAMAGE", subject="source",
            operation={"op":"program","code":["$event.target", 40, "LIGHTCORE_DAMAGE"]})])
        facts = self.fight(self.cards["liu_annihilate"])
        self.assertEqual([e["amount"] for k, e in facts if k == "lightcore_damage"], [40, 4])
        self.assertFalse(any(k in ("lightcore_overflow", "lightcore_max_changed") for k, _ in facts))
        self.assertEqual((self.enemy.hp, self.enemy.lightcore_hp, self.enemy.max_lightcore_hp), (9, 20, 24))

    def test_finisher_stops_when_there_is_no_next_lightcore_bar(self):
        self.deploy()
        self.enemy.lightcore_hp = 1
        self.enemy.max_lightcore_hp = 8
        self.liu.add_status("能源", 100)
        facts = self.fight(self.cards["liu_annihilate"])
        self.assertEqual((self.enemy.hp, self.enemy.max_lightcore_hp, self.enemy.lightcore_hp), (9, 0, 0))
        self.assertEqual([e["amount"] for k, e in facts if k == "lightcore_damage"], [99])
        self.assertFalse(any(k == "lightcore_overflow" for k, _ in facts))

    def test_prison_blanks_eight_in_first_actual_duel_only(self):
        self.deploy()
        self.ctx.dispatch_pipeline("after_skill_use", side=self.left.side, source=self.liu,
                                   card=self.cards["liu_prison"], target=self.enemy)
        self.game.finish_turn()
        self.game.start_turn()
        cards = [Card(self.right, dict(id=str(i), name=str(i), cost=0, dice=[
            dict(type="slash", level=4, final_bonus=9, entries=["1光点"]) for _ in range(n)]), self.enemy)
                 for i,n in enumerate((2,1))]
        for i,card in enumerate(cards):
            self.assertTrue(self.game.place_in_duel(self.right.side, card, i))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", side_effect=[8,9,8]):
            for _ in range(1000):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
        self.assertEqual([(die.type, die.value) for c in cards for die in c.instantiated_dice],
                         [("blank",8), ("slash",9), ("slash",8)])

    def test_invisible_pays_each_repeat_and_uses_snapshot_at_twelve(self):
        for energy, count, remaining in ((11,1,11),(12,3,0),(19,4,1)):
            with self.subTest(energy=energy):
                self.setUp()
                self.deploy()
                self.liu.add_status("能源", energy)
                facts = self.fight(self.cards["liu_invisible"])
                self.assertEqual(len([e for k,e in facts if k == "hit"]), count)
                self.assertEqual(self.liu.statuses.get("能源",0), remaining)

    def test_sustained_threshold_and_budget_refill(self):
        self.deploy()
        self.liu.add_status("强壮", 2)
        self.liu.add_status("环境同调", 3)
        self.left.turn_common_cost_bonus = -self.game.gamerule.MAX_BASIC_COST
        self.left.reset_on_turn_start()
        self.assertEqual(self.left.max_cost, 4)
        self.assertEqual((self.liu.statuses["迅捷"], self.liu.statuses["强壮"]), (1,3))
        self.liu.add_status("环境同调", -2)
        self.assertNotIn("迅捷", self.liu.statuses)
        self.assertEqual(self.liu.statuses["强壮"], 2)

    def test_failed_payment_preserves_first_discount(self):
        self.deploy()
        self.left.max_cost = self.liu.independent_cost = 0
        self.assertFalse(self.ctx.pay_skill_cost(self.cards["liu_execution"])["paid"])
        self.assertTrue(self.ctx.pay_skill_cost(self.cards["liu_blade"])["paid"])
        self.assertFalse(self.ctx.pay_skill_cost(self.cards["liu_shadow"])["paid"])

    def test_skill_range_matching_preserves_the_other_dice_only_range(self):
        self.deploy()
        card = self.cards["liu_execution"]
        opposing = self.die(self.enemy).card
        self.assertEqual(card.paired_ranges(opposing, 0, 2), (0, 2))
        opposing.data["range_level"] = 2
        self.assertEqual(card.paired_ranges(opposing), (2, 2))
        self.assertEqual(self.cards["liu_hope"].paired_ranges(opposing), (0, 1))

    def test_rewind_restores_insight_without_an_energy_gain(self):
        self.deploy()
        self.liu.add_status("领域洞悉", 15)
        self.liu.add_status("战甲", 1)
        self.liu.add_status("环境压制", -10)
        self.emit_use(self.cards["liu_rewind"])
        self.liu.add_status("领域洞悉", -2)
        # 仅减少 6 层尚未归零时不触发回退
        self.liu.add_status("环境压制", -6)
        self.assertEqual(self.liu.statuses["领域洞悉"], 13)
        self.assertNotIn("能源", self.liu.statuses)
        # 归零时先回退领域洞悉 13->15（不触发战甲获能），再由行至阴处获得 12 洞悉（触发战甲获 12 能源）
        self.liu.add_status("环境压制", -self.liu.statuses["环境压制"])
        self.assertEqual(self.liu.statuses["领域洞悉"], 27)
        self.assertEqual(self.liu.statuses["能源"], 12)

    def test_dismember_upgrades_only_later_dice_and_requires_all_three_hits(self):
        for remote, miss, expected in ((0,False,[5,4,4,4]),(1,False,[5,3,3,2]),(0,True,[5,3,3])):
            with self.subTest(remote=remote, miss=miss):
                self.setUp()
                self.deploy()
                self.liu.add_status("环境同调", 1)
                card = self.cards["liu_dismember"]
                enemy = Card(self.right, dict(id="guard",name="对阵",cost=0,range_level=remote,dice=[
                    dict(type="block",level=1,base_value=(100 if miss and i==0 else -100))
                    for i in range(4)]), self.enemy)
                self.fight(card, enemy)
                used = [d for d in card.instantiated_dice if d is not None]
                self.assertEqual([d.level.value for d in used],expected)

    def test_heart_and_shadow_use_exact_thresholds(self):
        for hand, gain in ((4,0),(5,1),(8,1),(9,2)):
            with self.subTest(hand=hand):
                self.setUp()
                self.deploy()
                pile = self.left.cardspace.draw
                for _ in range(hand):
                    pile.move_card_to(0, self.left.cardspace.hand)
                self.ctx.dispatch_pipeline("on_turn_start")
                self.assertEqual(self.liu.statuses.get("领域洞悉",0),gain)
        self.enemy.lightcore_hp = 15
        self.emit_use(self.cards["liu_shadow"])
        self.assertNotIn("骰子等级提升", self.liu.statuses)
        self.enemy.lightcore_hp = 14
        self.emit_use(self.cards["liu_shadow"])
        self.assertEqual(self.liu.statuses["骰子等级提升"],1)
