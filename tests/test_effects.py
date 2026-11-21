import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from models.card import Card, CardState
from models.character import Character
from models.duel import DuelSlot
from models.opcode import OpCode
from player.player import Player


class EffectRules(unittest.TestCase):
    def setUp(self):
        self.game = Game([Player(1, "甲"), Player(2, "乙")], rng=random.Random(5))
        self.ctx = self.game.context
        self.people = []
        for p in self.game.players:
            char = Character(dict(id=p.name, name=p.name, rank="ELITE", max_hp=20,
                                  skills=[], passive_skills=[]), p)
            self.people.append(char)
            p.characters = [char]
        self.atk, self.defender = self.people
        self.game.first_player = self.defender.player

    def card(self, owner, entries=(), parts=(), name="招式"):
        return Card(owner.player, dict(name=name, id=name, cost=1, entries=list(entries),
                                       dice=[dict(type="blunt", level=1, entries=list(parts))]), owner)

    def listen(self, owner, trigger, operation, **options):
        self.ctx.register_entries(owner, [dict(trigger=trigger, operation=operation, **options)])

    def test_damage_uses_actual_source_grade_and_after_damage_reaction(self):
        card = self.card(self.defender, parts=["1 穿甲", "2 超穿甲"])
        die = card.get_current_die(self.game)
        self.atk.add_shield("normal", 4)
        self.atk.add_shield("concept", 1)
        self.listen(self.atk, "AFTER DAMAGE", "Heal: 1")
        self.ctx.resolve_hit(die, self.atk)
        self.assertEqual(self.defender.hp, 20)
        self.assertEqual(self.atk.hp, 20)
        self.assertEqual((self.atk.shield, self.atk.concept_shield), (1, 0))

    def test_damage_reports_modified_amount_separately_from_hp_loss(self):
        before, after = [], []

        def before_apply(ctx):
            event = ctx.event
            target = event["target"]
            before.append((event["source"], target, event["amount"], event["penetration"],
                           target.hp, target.shield, target.is_alive))

        def after_damage(ctx):
            event = ctx.event
            after.append((event["amount"], event["result"], event["hp_lost"]))

        self.listen(self.atk, "BEFORE DAMAGE", "Damage_Add: 2", subject="source")
        self.listen(self.defender, "BEFORE RESOLVE_DAMAGE", before_apply, subject="target",
                    when={"amount_at_least": 7})
        self.listen(self.atk, "AFTER DAMAGE", after_damage, subject="source",
                    when={"result_at_least": 7})
        for hp, shield, expected_loss in ((12, 7, 0), (12, 2, 5), (4, 2, 4)):
            with self.subTest(hp=hp, shield=shield):
                self.defender.hp = hp
                self.defender.shield = shield
                with redirect_stdout(io.StringIO()) as output:
                    damage = self.ctx.deal_damage(self.atk, self.defender, 5)
                self.assertIn("甲 对 乙 造成 7 点伤害", output.getvalue())
                self.assertEqual(damage, 7)
                self.assertEqual(before, [(self.atk, self.defender, 7, "normal", hp, shield, True)])
                self.assertEqual(after, [(7, 7, expected_loss)])
                self.assertEqual((self.defender.hp, self.defender.shield), (hp - expected_loss, 0))
                before.clear()
                after.clear()

    def test_pack_can_read_damage_and_explicit_hp_loss(self):
        self.listen(self.atk, "AFTER DAMAGE", {"op": "program", "code": [
            "$self", "累计伤害", "$damage_amount", "STATUS",
            "$self", "累计扣血", "$hp_lost", "STATUS",
        ]}, subject="source")
        self.listen(self.defender, "AFTER DAMAGE", "Status: 掉血次数, 1",
                    when={"hp_lost_at_least": 1})
        self.defender.shield = 6
        self.ctx.deal_damage(self.atk, self.defender, 4)
        self.ctx.deal_damage(self.atk, self.defender, 4)
        self.assertEqual(self.atk.statuses, {"累计伤害": 8, "累计扣血": 2})
        self.assertEqual(self.defender.statuses, {"掉血次数": 1})

    def test_damage_readers_see_the_updated_operand_before_hp_changes(self):
        self.listen(self.defender, "BEFORE RESOLVE_DAMAGE", {"op": "program", "code": [2, "ADD"]})
        self.listen(self.defender, "BEFORE RESOLVE_DAMAGE", {"op": "program", "code": [
            "$self", "判定时伤害", "$damage_amount", "STATUS",
        ]}, when={"damage_amount_at_least": 7})
        before_shields = []
        self.listen(self.defender, "AFTER RESOLVE_DAMAGE", lambda ctx: before_shields.append(
            (ctx.event["result"], self.defender.hp, self.defender.shield)))
        self.defender.shield = 7
        self.assertEqual(self.ctx.deal_damage(self.atk, self.defender, 5), 7)
        self.assertEqual(self.defender.statuses, {"判定时伤害": 7})
        self.assertEqual(before_shields, [(7, 20, 7)])
        self.assertEqual((self.defender.hp, self.defender.shield), (20, 0))

    def test_bleed_damage_is_reported_separately_from_the_hit_that_triggered_it(self):
        self.defender.shield = 4
        self.defender.add_status("裂血", 6)
        parts = []
        self.listen(self.atk, "AFTER DAMAGE", lambda ctx: parts.append(
            (ctx.event["penetration"], ctx.event["result"], ctx.event["hp_lost"])), subject="any")
        damage = self.ctx.deal_damage(self.atk, self.defender, 3, damage_part=True)
        self.assertEqual(damage, 3)
        self.assertCountEqual(parts, [("normal", 3, 0), ("pierce", 1, 1)])
        self.assertEqual((self.defender.hp, self.defender.shield), (19, 0))

    def test_zero_and_cancelled_damage_do_not_meet_a_damage_threshold(self):
        results = []
        self.listen(self.defender, "BEFORE DAMAGE", "Armor: 4")
        self.listen(self.defender, "AFTER DAMAGE", lambda ctx: results.append(ctx.event["result"]))
        self.listen(self.defender, "AFTER DAMAGE", "Status: 受伤次数, 1",
                    when={"result_at_least": 1})
        self.defender.shield = 3
        self.assertEqual(self.ctx.deal_damage(self.atk, self.defender, 4), 0)
        self.assertEqual(results, [0])
        self.listen(self.defender, "BEFORE RESOLVE_DAMAGE", "Cancel")
        self.assertEqual(self.ctx.deal_damage(self.atk, self.defender, 8), 0)
        self.assertEqual(results, [0])
        self.assertEqual((self.defender.hp, self.defender.shield), (20, 3))
        self.assertNotIn("受伤次数", self.defender.statuses)

    def test_direct_life_loss_ignores_shields_and_death_interrupts_own_program(self):
        self.atk.add_shield("normal", 6)
        self.atk.add_status("致命失衡", 1)
        self.listen(self.atk, "AFTER DAMAGE", "Heal: 2")
        self.atk.hp = 5
        self.listen(self.atk, "sacrifice", {"op": "program", "code": [
            "$self", 4, "LOSE_HP", "$target", "标记", 1, "STATUS",
        ]})
        for expected_hp in (1, 0):
            self.ctx.dispatch_pipeline("sacrifice", source=self.atk, target=self.defender)
            self.assertEqual(self.atk.hp, expected_hp)
            self.assertEqual(self.atk.shield, 6)
            self.assertEqual(self.atk.statuses.get("致命失衡"), 1)
            self.assertEqual(self.defender.statuses.get("标记"), 1)
            self.assertEqual(self.ctx.stack, [])
        self.assertFalse(self.atk.is_alive)

    def test_before_hit_damage_and_grade_aware_armor(self):
        card = self.card(self.atk, parts=[
            {"trigger": "before_dice_hit", "operation": "Damage_Add: 1"},
            "2 穿甲", "1 超穿甲"])
        die = card.get_current_die(self.game)
        self.defender.add_status("致命失衡", 1)
        self.listen(self.defender, "BEFORE DAMAGE", "Armor: 2, 穿甲")
        self.ctx.dispatch_pipeline("before_dice_hit", die=die, card=card, side=1,
                                   source=self.atk, target=self.defender)
        self.ctx.resolve_hit(die, self.defender)
        # First part: 2*2+1-2. Second part: 1+1 (higher grade than armor).
        self.assertEqual(self.defender.hp, 15)

    def test_equal_authority_resists_status_higher_authority_breaks_through(self):
        self.listen(self.defender, "BEFORE STATUS", "Cancel", when={"status": "烧伤"})
        self.listen(self.atk, "on_turn_start", "Status: 烧伤, 4")
        self.listen(self.atk, "on_dice_hit", "Status: 烧伤, 3", authority="较高话语权")
        self.ctx.dispatch_pipeline("on_turn_start", source=self.atk, target=self.defender)
        self.assertNotIn("烧伤", self.defender.statuses)
        self.ctx.dispatch_pipeline("on_dice_hit", source=self.atk, target=self.defender)
        self.assertEqual(self.defender.statuses["烧伤"], 3)
        self.assertEqual(self.ctx.stack, [])

    def test_fixed_and_multiplicative_reductions_respect_grade(self):
        self.listen(self.defender, "BEFORE DAMAGE", ["Damage_Multiply: 0.5, 穿甲", "Damage_Add: -1"])
        for grade in ("normal", "pierce", "concept"):
            self.ctx.deal_damage(self.atk, self.defender, 4, grade)
        self.assertEqual(self.defender.hp, 13)  # 1 normal, 2 piercing, 4 super-piercing.

    def test_source_order_precedes_authority_and_preserves_print_order(self):
        seen = []
        for char, message, power in ((self.atk, "迟", 2), (self.defender, "先1", 0),
                                     (self.defender, "先2", 2)):
            self.listen(char, "on_turn_start", lambda _, name=message: seen.append(name),
                        authority=power)
        self.ctx.dispatch_pipeline("on_turn_start")
        self.assertEqual(seen, ["先1", "先2", "迟"])

    def test_duration_next_card_and_period(self):
        effects = [dict(trigger="on_skill_use", operation="Shield: 2", scope="next_skill")]
        a, b = self.card(self.atk, effects), self.card(self.atk)
        self.listen(self.atk, "beat", "Shield: 1", period={"from":"opening", "until":"closing"})
        for name in ("beat", "opening", "beat", "closing", "beat"):
            self.ctx.dispatch_pipeline(name)
        self.assertEqual(self.atk.shield, 1)
        for card in (a, b, b):
            for stage in ("before_skill_use", "on_skill_use", "after_skill_use"):
                self.ctx.dispatch_pipeline(stage, source=self.atk, side=1, card=card)
        self.assertEqual(self.atk.shield, 3)

    def test_resource_gate_consumes_energy_only_once(self):
        self.listen(self.atk, "on_dice_hit", [
            {"op": "status", "name": "能源", "amount": -2, "target": "self"},
            "Damage: 3, pierce"
        ], when={"owner_status_at_least": {"能源": 2}})
        self.atk.add_status("能源", 3)
        for _ in range(2):
            self.ctx.dispatch_pipeline("on_dice_hit", source=self.atk, target=self.defender)
        self.assertEqual(self.atk.statuses, {"能源": 1})
        self.assertEqual(self.defender.hp,17)

    def test_destroy_single_invocation_keeps_the_listener(self):
        self.listen(self.atk, "on_turn_start", "Shield: 2")
        self.listen(self.defender, "BEFORE ENTRY", "Destroy: execution", subject="any",
                    when={"entry_trigger": "on_turn_start"})
        self.ctx.dispatch_pipeline("on_turn_start", source=self.atk)
        self.assertEqual(self.atk.shield, 0)
        self.ctx.unregister_entries(self.defender)
        self.ctx.dispatch_pipeline("on_turn_start", source=self.atk)
        self.assertEqual(self.atk.shield, 2)

    def test_destroy_opponent_die_and_skill(self):
        card = self.card(self.defender)
        die = card.get_current_die(self.game)
        self.listen(self.atk, "on_dice_use", ["Destroy: opponent_die", "Destroy: opponent_card"])
        self.ctx.dispatch_pipeline("on_dice_use", source=self.atk, opponent_die=die, opponent_card=card)
        self.assertTrue(die.destroyed)
        self.assertEqual(card.state, CardState.NEGATED)

    def test_protected_card_resists_equal_but_not_higher_destruction(self):
        card = self.card(self.defender, [
            {"trigger": "BEFORE DESTROY", "operation": "Cancel", "authority": 1}])
        self.listen(self.atk, "attack1", "Destroy: opponent_card", authority=1)
        self.listen(self.atk, "attack2", "Destroy: opponent_card", authority=2)
        self.ctx.dispatch_pipeline("attack1", source=self.atk, opponent_card=card)
        self.assertFalse(card.destroyed)
        self.ctx.dispatch_pipeline("attack2", source=self.atk, opponent_card=card)
        self.assertTrue(card.destroyed)

    def test_explicit_hit_opcode_can_be_intercepted(self):
        card = self.card(self.atk, parts=["2"])
        die = card.get_current_die(self.game)
        self.listen(self.defender, "BEFORE RESOLVE_HIT", "Cancel", subject="target")
        self.ctx.resolve_hit(die, self.defender)
        self.assertEqual(self.defender.hp, 20)
        self.assertEqual(self.ctx.stack, [])

    def test_destroy_pending_damage_part_prevents_only_this_execution(self):
        card = self.card(self.atk, parts=["2"])
        die = card.get_current_die(self.game)
        self.listen(self.defender, "BEFORE DAMAGE", "Destroy: execution")
        self.ctx.resolve_hit(die, self.defender)
        self.assertEqual(self.defender.hp,20)
        self.ctx.unregister_entries(self.defender)
        self.ctx.resolve_hit(die, self.defender)
        self.assertEqual(self.defender.hp,18)

    def test_roll_modification_is_clamped_and_bound_to_its_die(self):
        card = self.card(self.atk, parts=[dict(trigger="AFTER ROLL", operation="Roll_Add: 100")])
        die = card.get_current_die(self.game)
        die.roll()
        self.assertEqual(die.value, 4)
        self.listen(self.atk, "before_dice_clash", "Roll_Set: -100")
        other = self.card(self.atk).get_current_die(self.game)
        self.ctx.dispatch_pipeline("before_dice_clash", source=self.atk, die=other)
        other.roll()
        self.assertEqual(other.value, 1)

    def test_reserve_card_enters_current_slot_at_most_once(self):
        reserve = self.card(self.atk, name="援护")
        self.atk.player.cardspace.out_of_combat.add_card(reserve)
        slot = DuelSlot(self.game)
        self.game.duelspace.append_new_duel(slot)
        self.game.cards_revealed = True
        self.listen(self.atk, "on_dice_hit", {"op": "place_skill", "card_id": "援护"})
        for _ in range(2):
            self.ctx.dispatch_pipeline("on_dice_hit", source=self.atk, duel=slot)
        self.assertEqual(slot.content[1], [reserve])
        self.assertFalse(self.atk.player.cardspace.out_of_combat.content)
        self.assertEqual(reserve.state, CardState.PLACED_FACE_UP)

    def test_discard_order_and_stack_quote(self):
        a, b = self.card(self.atk), self.card(self.atk)
        self.atk.player.cardspace.hand.content[:] = [a, b]
        self.listen(self.atk, "on_turn_start", "Discard: 2")
        self.ctx.dispatch_pipeline("on_turn_start")
        self.assertEqual(self.atk.player.cardspace.delayed_discard.content, [a,b])
        self.ctx.eval_block([[2,3,OpCode.MUL], OpCode.EVAL, 1, OpCode.SUB])
        self.assertEqual(self.ctx.pop(), 5)
