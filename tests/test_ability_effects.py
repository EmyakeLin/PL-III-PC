import io
import unittest
from contextlib import redirect_stdout

from displayer import Displayer
from game import Game
from loader import load_characters_from_packs
from models.card import Card, CardState
from models.character import Character
from models.opcode import OpCode
from models.special_actions import SpecialAction
from player.player import Player


class AbilityEffectsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right])
        self.game.first_player = self.left
        self.ctx = self.game.context
        self.spec = dict(id="actor", name="队员", rank="NORMAL", max_hp=9, skills=[])
        self.actor = Character(self.spec, self.left)
        self.left.characters.append(self.actor)
        self.enemy = Character(dict(self.spec, id="opponent", name="对手"), self.right)
        self.right.characters.append(self.enemy)
        self.game.start_turn()

    def test_separate_opcodes_events_and_postfix_counts(self):
        actor = self.actor
        seen = []
        def record(ctx):
            seen.append((ctx.event["opcode"], ctx.event["status"], ctx.event.get("ability")))

        self.ctx.register_entries(actor, [
            dict(trigger=f"AFTER {opcode}", operation=record)
            for opcode in ("STATUS", "ABILITY_EFFECT", "SPEND_STATUS", "SPEND_ABILITY_EFFECT")])
        actor.add_status("充能", 4)
        actor.add_status("置卡机会", 8)
        actor.add_ability_effect("充能", 8)
        actor.add_ability_effect("置卡机会", 2)
        self.assertIsNone(self.ctx.eval_block([actor, actor, "置卡机会", 1, OpCode.QUEUE_STATUS]))
        self.assertFalse(self.game.next_turn_statuses)
        self.assertIsNone(self.ctx.eval_block([actor, "置卡机会", "all", OpCode.SPEND_STATUS]))
        self.assertFalse(actor.spend_ability_effect("充能"))
        self.assertEqual(seen, [("STATUS", "充能", None), ("ABILITY_EFFECT", None, "置卡机会")])

        self.ctx.register_entries(actor, [dict(trigger="on_check_abilities", operation=dict(op="program", code=[
            "$self", "normal", "$self", "置卡机会", "STATUS_COUNT", "SHIELD",
            "$self", "normal", "$self", "充能", "ABILITY_COUNT", "SHIELD",
            "$self", "normal", "$self", "置卡机会", "ABILITY_COUNT", "SHIELD",
            "$self", "置卡机会", 1, "SPEND_ABILITY_EFFECT_IN_FULL",
            ["$self", "充能", 1, "SPEND_STATUS", "POP"], "WHEN",
        ]))])
        self.ctx.dispatch_pipeline("on_check_abilities", source=actor)
        self.assertEqual(actor.shield, 2)
        self.assertEqual(actor.statuses, {"充能": 3})
        self.assertEqual(actor.ability_effects, {"置卡机会": 1})
        self.assertEqual(seen[-2:], [("SPEND_ABILITY_EFFECT", None, "置卡机会"), ("SPEND_STATUS", "充能", None)])

    def test_ability_cost_interception_preserves_card_and_quota(self):
        owner = self.actor
        owner.add_ability_effect("置卡机会", 1)
        card = Card(self.left, dict(id="place", name="补位", cost=1, dice=[]), owner)
        self.left.cardspace.hand.add_card(card)
        move = SpecialAction("place", card, duel_index=0)
        guard, = self.ctx.register_entries(owner, [
            dict(trigger="BEFORE SPEND_ABILITY_EFFECT", when={"ability": "置卡机会"}, operation="Cancel")])
        self.assertFalse(self.game.special.apply(self.left, move))
        self.assertEqual(owner.used_duels, 0)
        self.assertIn(card, self.left.cardspace.hand.content)
        self.assertEqual(owner.ability_effects, {"置卡机会": 1})
        self.ctx.entries.remove(guard)
        self.assertTrue(self.game.special.apply(self.left, move))
        self.assertEqual(owner.used_duels, 1)
        self.assertFalse(owner.ability_effects)

    def test_turn_end_expires_only_declared_temporary_abilities(self):
        self.game.ability_rules["长期许可"] = {}
        self.actor.add_ability_effect("长期许可", 2)
        self.actor.add_ability_effect("换卡机会", 3)
        self.actor.add_status("充能", 2)
        events = []
        self.ctx.register_entries(self.actor, [dict(trigger="on_ability_expired",
            operation=lambda ctx: events.append((ctx.event["ability"], ctx.event["amount"], ctx.event["target"])))])
        self.game.finish_turn()
        self.assertEqual(events, [("换卡机会", 3, self.actor)])
        self.assertEqual(self.actor.ability_effects, {"长期许可": 2})
        self.assertEqual(self.actor.statuses, {"充能": 2})

    def test_granted_insight_inherits_action_and_view_on_another_character(self):
        blank = next(spec for spec in load_characters_from_packs() if spec["id"] == "blank_boss")
        self.right.characters.append(Character(blank, self.right))
        self.game.placing = self.left
        card = Card(self.right, dict(id="secret", name="扣牌", cost=1, dice=[]), self.enemy)
        self.right.cardspace.hand.add_card(card)
        self.game.place_in_duel(2, card, 0)
        self.actor.add_ability_effect("洞察", 1)
        view = Displayer(self.game, viewer_side=1)
        character = view.snapshot()["players"][0]["characters"][0]
        self.assertNotIn("洞察", character["statuses"])
        self.assertEqual(character["ability_effects"], {"洞察": 1})
        self.assertIn("洞察", view.catalog()["ability_effects"])
        self.assertNotIn("洞察", view.catalog()["statuses"])
        option, = (a for a in self.game.special.options(self.left) if a.ability_id == "insight")
        self.assertTrue(self.game.special.apply(self.left, option))
        self.assertIs(card.state, CardState.PLACED_FACE_UP)
        self.assertTrue(self.game.special.is_locked(card))
        self.assertFalse(self.actor.ability_effects)

    def test_character_without_game_loads_both_basic_effect_packs(self):
        solo = Character(self.spec, Player(1, "单测"))
        self.assertEqual(solo.add_ability_effect("置卡机会", 2), 2)
        self.assertIsNone(solo.add_status("置卡机会", 1))
        solo.add_status("充能", 3)
        self.assertFalse(solo.spend_ability_effect("置卡机会", 3))
        self.assertTrue(solo.spend_ability_effect("置卡机会", 1))
        solo.expire_turn_abilities()
        self.assertFalse(solo.ability_effects)
        self.assertEqual(solo.statuses, {"充能": 3})
