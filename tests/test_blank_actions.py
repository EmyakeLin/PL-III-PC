import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from battle_ui.match import BattleMatch
from displayer import Displayer
from entry.entry import Entry
from game import Game
from loader import load_characters_from_packs
from models.card import CardState
from models.opcode import OpCode
from player.player import Player


class BlankDecisionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.spec = next(c for c in load_characters_from_packs() if c["id"] == "blank_boss")
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right])
        with patch("builtins.input", side_effect=["1", "1"]):
            self.game.select_character([self.spec])
        self.a, self.b = (p.characters[0] for p in self.game.players)
        self.game.first_player = self.left
        self.game.open_turn()

    def take(self, actor, name):
        card = next(c for c in actor.skills if c.name == name)
        self.game.context.eval_block([card, "hand", OpCode.MOVE_CARD])
        return card

    def ability(self, actor, ability, target=None):
        return next(a for a in self.game.special.options(actor.player)
                    if a.ability_id == ability and a.target_card is target)

    def test_insight_exposes_only_chosen_card_locks_until_end_of_placement(self):
        self.game.placing = self.left
        first, second = (self.take(self.b, name) for name in ("斩·突·闪", "看破"))
        self.game.place_in_duel(2, first, 0)
        self.game.place_in_duel(2, second, 1)
        self.a.add_ability_effect("洞察", 1)
        private = Displayer(self.game, viewer_side=1).special_actions()
        inspections = [o for o in private if o["ability_id"] == "insight"]
        self.assertEqual(len(inspections), 2)
        self.assertTrue(all(o["target_card_id"] is None for o in inspections))
        self.game.special.apply(self.left, self.ability(self.a, "insight", second))
        public = Displayer(self.game).snapshot()["duels"]
        self.assertEqual(public[0]["sides"][1]["cards"], [{"hidden": True}])
        self.assertEqual(public[1]["sides"][1]["cards"][0]["name"], second.name)
        self.assertFalse(self.game.context.eval_block([second, "hand", OpCode.MOVE_CARD]))
        self.game.placing = None
        self.assertTrue(self.game.context.eval_block([second, "hand", OpCode.MOVE_CARD]))
        self.assertNotIn("洞察", self.a.ability_effects)

    def test_draw_then_attack_while_no_eligible_attack_card_was_in_hand(self):
        first, second = (self.take(self.a, name) for name in ("斩·突·闪", "趁机攻势"))
        for card in (first, second):
            self.game.special.apply(self.left, self.ability(self.a, "deduce_discard", card))
        self.assertEqual(self.a.statuses["能源"], 6)
        self.assertEqual(self.a.ability_effects["抽卡资格"], 1)
        self.assertFalse(any(o.ability_id == "deduce_discard" for o in self.game.special.options(self.left)))
        draw = self.left.cardspace.draw.content
        seen = next(c for c in draw if c.name == "看破")
        draw.insert(0, draw.pop(draw.index(seen)))
        phase = self.game.pre_reveal
        phase.start()
        self.assertIs(phase.attacker, self.left)
        self.game.special.apply(self.left, self.ability(self.a, "deduce_draw"))
        self.assertEqual(self.left.cardspace.hand.content, [seen])
        self.assertNotIn("抽卡资格", self.a.ability_effects)
        self.assertEqual(self.a.statuses["能源"], 5)
        self.assertTrue(phase.declare_attack(seen, character=self.b).interceptable)

    def test_deduce_draw_only_spends_when_both_costs_can_be_paid(self):
        self.a.hp = 10
        self.a.add_status("能源", 1)
        self.a.add_ability_effect("抽卡资格", 1)
        ctx = self.game.context
        move = self.ability(self.a, "deduce_draw")
        before_hand = list(self.left.cardspace.hand.content)
        receipts = []
        for opcode in ("SPEND_STATUS", "SPEND_ABILITY_EFFECT"):
            ctx.register_entries(self.a, [dict(trigger=f"AFTER {opcode}",
                operation=lambda current: receipts.append((current.event["opcode"], current.event["result"])))])

        for guard in (
            dict(trigger="BEFORE SPEND_STATUS", when={"status": "能源"},
                 operation={"op": "program", "code": [1, "ADD"]}),
            dict(trigger="BEFORE SPEND_ABILITY_EFFECT", when={"ability": "抽卡资格"}, operation="Cancel"),
        ):
            with self.subTest(blocked=guard["trigger"]):
                listener, = ctx.register_entries(self.a, [guard])
                self.assertFalse(self.game.special.apply(self.left, move))
                self.assertEqual(self.a.ability_effects["抽卡资格"], 1)
                self.assertEqual(self.a.statuses["能源"], 1)
                self.assertEqual(self.left.cardspace.hand.content, before_hand)
                self.assertEqual(receipts, [])
                ctx.entries.remove(listener)

        self.assertTrue(self.game.special.apply(self.left, move))
        self.assertNotIn("抽卡资格", self.a.ability_effects)
        self.assertNotIn("能源", self.a.statuses)
        self.assertEqual(len(self.left.cardspace.hand.content), len(before_hand) + 1)
        self.assertCountEqual(receipts, [("SPEND_STATUS", 1), ("SPEND_ABILITY_EFFECT", 1)])

    def test_forced_shot_only_targets_enemy_occupied_slot_and_cannot_retarget(self):
        target = self.take(self.b, "看破")
        shot = self.take(self.a, "牵制射击")
        self.game.place_in_duel(2, target, 1)
        phase = self.game.pre_reveal
        phase.start()
        self.assertEqual(phase.attack_targets(shot), [(None, 1)])
        with self.assertRaises(ValueError):
            phase.declare_attack(shot, character=self.b)
        slot = phase.declare_attack(shot, duel_index=1)
        self.assertTrue(slot.ready)
        self.assertIs(target.state, CardState.PLACED_FACE_DOWN)
        self.assertTrue(slot.prepare(phase))
        self.assertIs(slot.pulled_card, target)

    def test_controller_chooses_slot_for_normally_priced_insertion(self):
        first, second, extra = (self.take(self.a, name) for name in ("看破", "斩·突·闪", "趁机攻势"))
        self.game.place_in_duel(1, first, 0)
        self.game.place_in_duel(1, second, 1)
        code = ["$self", extra.id, "hand", "FIND_SKILL", 0, "SKILL_USE",
                "$own_regular_duels",
                ["$choice_subject", "$chosen_slot", "slot_tail", "INSERT_AT", "INSERT_SKILL"],
                "CHOOSE_SLOT"]
        self.game.context._invoke(Entry.from_spec(
            self.a, {"trigger": "test_slot", "operation": {"op": "program", "code": code}}))
        self.assertEqual(self.game.next_step(), "wait_queued_placement")
        self.assertFalse(self.game.special.options(self.right))
        choices = self.game.special.options(self.left)
        self.assertEqual([move.duel_index for move in choices], [0, 1])
        self.assertTrue(self.game.special.apply(self.left, choices[1]))
        self.assertEqual(self.game.duelspace.space[1].get_content(1), [second, extra])
        self.assertNotIn("cost_prepaid", extra.use_state)

    def test_look_through_opens_before_regular_duel_and_resumes_from_interrupt(self):
        early = self.take(self.a, "看破")
        for player, actor in ((self.left, self.a), (self.right, self.b)):
            regular = self.take(actor, "斩·突·闪")
            self.game.place_in_duel(player.side, regular, 0)
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        self.assertFalse(any(a.card is early for a in self.game.special.options(self.left)))
        self.game.next_step()
        options = self.game.special.options(self.left)
        move = next(a for a in options if a.card is early and a.character is self.b)
        self.game.special.apply(self.left, move)
        instant = self.game.special.duels[0]
        self.assertEqual(instant.origin, "before_duel")
        self.assertTrue(instant.ready)
        for _ in range(100):
            if self.game.pipeline.interrupt_space is None:
                break
            self.game.next_step()
        self.assertIsNone(self.game.pipeline.interrupt_space)
        self.assertTrue(self.game.pipeline.before_duel_start)
        self.game.next_step()
        self.assertFalse(self.game.pipeline.before_duel_start)

    def test_web_mirror_can_select_second_copy_of_same_printed_card(self):
        table = BattleMatch(["blank_boss", "blank_boss"], seed=11)
        table.game.placing = table.game.players[0]
        table.mode = "placement"
        owner = table.game.placing.characters[0]
        own = owner.skills[0]
        foreign = table.game.players[1].characters[0].skills[0]
        for card in (own, foreign):
            table.game.context.eval_block([card, "hand", OpCode.MOVE_CARD])
        opponent = foreign.character
        with patch.object(table.game.rng, "choice", return_value=foreign):
            self.assertTrue(table.game.context.eval_block([opponent, owner, OpCode.TAKE_HAND_CARD]))
        state = table.snapshot()
        cards = [c for c in state["frame"]["players"][0]["hand"] if c["id"] == own.id]
        self.assertEqual(len({c["action_key"] for c in cards}), 2)
        with self.assertRaises(ValueError):
            table.act("place", state["revision"], card_id=own.id)
        foreign_key = next(c["action_key"] for c in cards if c["instance_id"] == foreign.instance_id)
        table.act("place", state["revision"], card_id=foreign_key)
        self.assertIs(table.game.duelspace.space[0].get_content(1)[0], foreign)
