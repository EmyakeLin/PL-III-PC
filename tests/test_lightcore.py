"""Integrity, collapse and independent damage through printed dice and the hooked VM."""
import io
import unittest
from contextlib import redirect_stdout

from entry.builtin_operations import parse_builtin_operation
from game import Game
from loader import load_characters_from_packs
from models.card import Card, CardState, describe_entry
from models.character import Character
from models.duel import DuelSlot
from models.opcode import OpCode
from player.player import Player


class LightcoreTests(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.game = Game([Player(1, "甲"), Player(2, "乙")])
        left, right = self.game.players
        self.game.first_player = left
        self.source = Character(dict(id="source", name="攻击者", rank="NORMAL", max_hp=6, skills=[]), left)
        blank = next(spec for spec in load_characters_from_packs() if spec["id"] == "blank_boss")
        self.target = Character(blank, right)
        left.characters.append(self.source)
        right.characters.append(self.target)
        self.ctx = self.game.context

    def execute(self, amount, opcode):
        with self.ctx.binding(source=self.source, target=self.target):
            return self.ctx.eval_block([self.target, amount, opcode])

    def listen(self, owner, trigger, operation, **fields):
        self.ctx.register_entries(owner, [dict(trigger=trigger, operation=operation, **fields)])

    def test_caps_and_collapse_use_original_max_hp(self):
        self.assertEqual([Character.initial_lightcore_max(n) for n in (1, 3, 4, 6, 9, 15)],
                         [8, 8, 12, 12, 16, 24])
        self.assertEqual((self.target.lightcore_hp, self.target.max_lightcore_hp), (24, 24))
        self.target.max_hp = 22
        self.target.hp = 22
        self.assertEqual(self.execute(100, OpCode.LIGHTCORE_DAMAGE), 100)
        self.assertEqual((self.target.hp, self.target.lightcore_hp, self.target.max_lightcore_hp),
                         (14, 20, 20))

    def test_hit_and_followup_are_separate_segments_in_one_clash(self):
        self.game.start_turn()
        self.target.shield = self.target.reinforced_shield = self.target.concept_shield = 9
        self.target.add_status("致命失衡", 1)
        self.target.add_status("裂血", 6)
        # Cover the printed hit + separate on-hit clause, as played in a normal duel.
        card = Card(self.source.player, dict(id="split", name="分段", cost=0, dice=[dict(
            type="slash", level=1, entries=["7光点伤害", dict(trigger="on_dice_hit", operation=dict(
                op="program", code=["$target", 4, "LIGHTCORE_DAMAGE"]))])]), self.source)
        card.state = CardState.PLACED_FACE_UP
        self.source.skills.append(card)
        slot = DuelSlot(self.game)
        slot.add_content(1, card)
        self.game.duelspace.append_new_duel(slot)
        self.target.max_lightcore_hp, self.target.lightcore_hp = 12, 4
        after = []
        self.listen(self.target, "AFTER LIGHTCORE_DAMAGE", lambda c: after.append(
            (c.event["amount"], c.event["result"], c.event["lightcore_lost"],
             c.event["lightcore_collapsed"], c.event["damage_amount"], self.target.lightcore_hp)))
        self.game.pipeline.start_duel_combat()
        for _ in range(300):
            if not self.game.pipeline.in_duel_phase:
                break
            self.game.pipeline.step_duel_combat()
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertEqual(after, [(7, 7, 4, True, None, 8), (4, 4, 4, False, None, 4)])
        # 1 piercing from bleed at duel start is the only direct damage of the duel.
        self.assertEqual(slot.damage_taken.get(self.target), 2)  # lethal stagger doubles it.
        self.assertNotIn("空白已发动", self.target.statuses)
        self.assertEqual((self.target.hp, self.target.lightcore_hp, self.target.max_lightcore_hp), (7, 4, 8))
        self.assertEqual((self.target.shield, self.target.reinforced_shield, self.target.concept_shield),
                         (7, 7, 9))
        self.assertIn("造成 7 点光点伤害", self.log.getvalue())
        self.assertIn("承受 8 点真实伤害", self.log.getvalue())

    def test_special_damage_ignores_direct_damage_hooks_shields_and_bleed(self):
        self.listen(self.target, "BEFORE DAMAGE", "Cancel")
        self.listen(self.target, "AFTER DAMAGE", "Status: 受到直伤, 1")
        self.target.add_status("致命失衡", 1)
        self.target.add_status("裂血", 6)
        for kind in ("normal", "reinforced", "concept"):
            self.target.add_shield(kind, 2)
        card = Card(self.source.player, dict(id="real", name="真伤", cost=0, dice=[dict(
            type="blunt", level=1, entries=["2真实伤害", "3光点伤害"])]), self.source)
        self.ctx.resolve_hit(card.get_current_die(self.game), self.target)
        self.assertEqual((self.target.hp, self.target.lightcore_hp), (13, 21))
        self.assertEqual((self.target.shield, self.target.reinforced_shield, self.target.concept_shield),
                         (2, 2, 2))
        self.assertEqual(self.target.statuses, {"致命失衡": 1, "裂血": 6})
        self.assertTrue(self.target.bleed_burst)
        self.assertEqual(parse_builtin_operation("5 点光点伤害"), ["target", 5, OpCode.LIGHTCORE_DAMAGE])
        self.assertEqual(parse_builtin_operation("4 真实伤害"), ["target", 4, OpCode.REAL_DAMAGE])

    def test_independent_listeners_can_adjust_or_cancel_only_their_own_channel(self):
        self.listen(self.target, "BEFORE LIGHTCORE_DAMAGE", dict(op="program", code=[2, "ADD"]))
        self.listen(self.target, "BEFORE REAL_DAMAGE", "Cancel")
        self.assertEqual(self.execute(2, OpCode.LIGHTCORE_DAMAGE), 4)
        self.assertIsNone(self.execute(5, OpCode.REAL_DAMAGE))
        self.assertEqual((self.target.hp, self.target.lightcore_hp), (15, 20))

    def test_printed_aliases_resolve_and_render_with_their_own_channels(self):
        for text, expected, label in [
            ("3光点伤害", [3, OpCode.LIGHTCORE_DAMAGE], "3 点光点伤害"),
            ("2点真实伤害", [2, OpCode.REAL_DAMAGE], "2 点真实伤害"),
            ("2点直伤", [2, "normal", "none", OpCode.DAMAGE], "2 点普通伤害"),
            ("2物理直伤", [2, "normal", "none", OpCode.DAMAGE], "2 点普通伤害"),
            ("2 穿甲直伤", [2, "pierce", "none", OpCode.DAMAGE], "2 点穿甲伤害"),
            ("2点超穿甲直伤", [2, "concept", "none", OpCode.DAMAGE], "2 点超穿甲伤害"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(parse_builtin_operation(text), ["target", *expected])
                self.assertEqual(describe_entry(text), label)
                self.assertEqual(parse_builtin_operation(label), ["target", *expected])

    def test_nested_segments_have_private_damage_and_life_loss_measurements(self):
        self.target.lightcore_hp = 1
        self.target.shield = 3
        seen = []
        def observe(ctx):
            seen.append(tuple(ctx.event.get(k) for k in (
                "opcode", "base_amount", "damage_amount", "hp_lost", "lightcore_lost",
                "lightcore_collapsed", "penetration")))
        for name in ("LIGHTCORE_DAMAGE", "REAL_DAMAGE", "RESOLVE_DAMAGE", "DAMAGE", "LOSE_HP"):
            self.listen(self.target, f"AFTER {name}", observe)
        self.listen(self.target, "AFTER LIGHTCORE_DAMAGE", dict(op="program", code=[
            "$self", 1, "pierce", "blunt", "DAMAGE", "$self", 1, "LOSE_HP"]),
            when={"lightcore_collapsed": True})
        self.listen(self.target, "AFTER DAMAGE", dict(op="program", code=[
            "$self", 2, "LIGHTCORE_DAMAGE", "$self", 1, "REAL_DAMAGE"]))
        self.execute(5, OpCode.LIGHTCORE_DAMAGE)
        self.assertEqual(seen, [
            ("REAL_DAMAGE", 8, None, 8, None, False, None),
            ("LIGHTCORE_DAMAGE", 5, None, None, 1, True, None),
            ("RESOLVE_DAMAGE", 1, 1, None, None, False, "pierce"),
            ("DAMAGE", 1, 1, 1, None, False, "pierce"),
            ("LIGHTCORE_DAMAGE", 2, None, None, 2, False, None),
            ("REAL_DAMAGE", 1, None, 1, None, False, None),
            ("LOSE_HP", None, None, 1, None, False, None),
        ])
        self.assertEqual(self.ctx.stack, [])

    def test_pack_reads_full_independent_damage_and_direct_raw_base(self):
        self.target.lightcore_hp = 4
        self.listen(self.target, "BEFORE LIGHTCORE_DAMAGE", dict(op="program", code=[2, "ADD"]))
        self.listen(self.source, "AFTER LIGHTCORE_DAMAGE", dict(op="program", code=[
            "$self", "入射量", "$amount", "STATUS", "$self", "结算量", "$result", "STATUS",
            "$self", "完整度损失", "$lightcore_lost", "STATUS",
        ]), subject="source")
        self.execute(5, OpCode.LIGHTCORE_DAMAGE)
        self.assertEqual(self.source.statuses, {"入射量": 7, "结算量": 7, "完整度损失": 4})
        self.listen(self.target, "BEFORE DAMAGE", "Damage_Add: 2")
        raw = []
        self.listen(self.source, "AFTER RESOLVE_DAMAGE", lambda c: raw.append(
            (c.event["base_amount"], c.event["damage_amount"])), subject="source")
        self.ctx.deal_damage(self.source, self.target, 5)
        self.assertEqual(raw, [(5, 7)])

    def test_terminal_collapse_finishes_reset_and_only_observers_receive_the_terminal_event(self):
        self.listen(self.source, "AFTER LIGHTCORE_DAMAGE", "Shield: 2", subject="source")
        seen = []
        for name in ("REAL_DAMAGE", "LIGHTCORE_DAMAGE"):
            self.listen(None, f"AFTER {name}", lambda c: seen.append(
                (c.event["opcode"], c.event["result"])))
        self.target.hp = self.target.lightcore_hp = 1
        self.execute(7, OpCode.LIGHTCORE_DAMAGE)
        self.assertIs(self.game.winner, self.source.player)
        self.assertEqual((self.target.lightcore_hp, self.target.max_lightcore_hp), (20, 20))
        self.assertEqual(seen, [("REAL_DAMAGE", 8), ("LIGHTCORE_DAMAGE", 7)])
        self.assertEqual(self.source.shield, 0)

    def test_zero_cap_consumes_overflow_and_still_reports_incident_amount(self):
        self.target.max_lightcore_hp = self.target.lightcore_hp = 4
        values = []
        self.listen(self.target, "AFTER LIGHTCORE_DAMAGE", lambda c: values.append(
            (c.event["result"], c.event["lightcore_lost"], c.event["lightcore_collapsed"])))
        self.execute(7, OpCode.LIGHTCORE_DAMAGE)
        self.execute(7, OpCode.LIGHTCORE_DAMAGE)
        self.assertEqual(values, [(7, 4, True), (7, 0, False)])
        self.assertEqual((self.target.hp, self.target.max_lightcore_hp, self.target.lightcore_hp), (7, 0, 0))

    def test_only_real_healing_from_at_least_the_cap_is_lethal(self):
        self.target.max_lightcore_hp = 12
        self.target.lightcore_hp = 1
        self.assertEqual(self.execute(1, OpCode.HEAL), 0)  # full HP
        self.assertTrue(self.target.is_alive)
        self.target.hp = 11
        self.assertEqual(self.execute(2, OpCode.HEAL), 2)
        self.assertEqual(self.target.hp, 13)
        self.assertTrue(self.target.is_alive)
        self.target.add_status("本回合无法死亡", 1)
        self.target.hp = 12
        self.assertEqual(self.execute(0, OpCode.HEAL), 0)
        self.assertEqual(self.execute(1, OpCode.HEAL), 1)
        self.assertEqual((self.target.hp, self.target.is_alive), (0, False))
        self.assertIs(self.game.winner, self.source.player)

    def test_cancelled_heal_can_survive_and_real_damage_respects_existing_immortality(self):
        self.target.add_status("本回合无法死亡", 1)
        self.target.max_lightcore_hp = 12
        self.target.hp = 13
        self.listen(self.target, "BEFORE HEAL", "Cancel")
        self.assertIsNone(self.execute(2, OpCode.HEAL))
        self.assertTrue(self.target.is_alive)
        outcomes = []
        self.listen(self.target, "AFTER REAL_DAMAGE", lambda c: outcomes.append(
            (c.event["amount"], c.event["result"], c.event["hp_lost"])))
        self.assertEqual(self.execute(20, OpCode.REAL_DAMAGE), 20)
        self.assertEqual(outcomes, [(20, 20, 13)])
        self.assertEqual((self.target.hp, self.target.is_alive), (0, True))
