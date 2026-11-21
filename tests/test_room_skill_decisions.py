"""New character choices through the independent seats and their public journal."""
import io
import unittest
from contextlib import redirect_stdout
from itertools import count

from battle_mcp.room import Room
from displayer import hand_key
from entry.entry import Entry
from models.opcode import OpCode


class RoomSkillDecisionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.requests = count()

    def create(self, roster, seed):
        self.room = Room(roster, seed=seed)
        self.addCleanup(self.room.close)
        self.game = self.room.engine.game

    def command(self, side, operation, **fields):
        view = self.room.observe(side)
        return getattr(self.room, operation)(side, revision=view["revision"],
                                             request_id=str(next(self.requests)), **fields)

    def start(self):
        for side in (1, 2):
            self.command(side, "ready")

    def act(self, side, kind, **fields):
        moves = self.room.observe(side)["options"]
        move = next(m for m in moves if m["kind"] == kind and all(m.get(k) == v for k, v in fields.items()))
        return self.command(side, "act", option_id=move["id"])

    def reach_surprise_hit(self, seed):
        self.create(("nova_lin_qiu", "waa_lake"), seed)
        self.start()
        for _ in range(12):
            if self.room.observe(None)["frame"]["mode"] == "skill_choice":
                return
            for side in (1, 2):
                moves = self.room.observe(side)["options"]
                chosen = next((m for m in moves if m["kind"] == "place" and m["card_id"] == "lin_qiu_surprise"),
                              None) or next((m for m in moves if m["kind"] in ("end", "end_attack")), None)
                if chosen:
                    self.command(side, "act", option_id=chosen["id"])
                    break
            else:
                self.fail("没有到达林秋的插牌时点")
        self.fail("林秋的末骰没有触发选牌")

    def test_surprise_hit_prompts_only_lin_and_resumes_with_the_chosen_skill(self):
        self.reach_surprise_hit(8)
        view = self.room.observe(1)
        self.assertEqual(self.room.engine.required_sides(), [1])
        self.assertEqual(self.room.observe(1, view["cursor"])["options"], view["options"])
        self.assertFalse(self.room.observe(None)["options"])
        self.assertFalse(self.room.observe(2)["options"])
        with self.assertRaises(ValueError):
            self.command(2, "act", option_id=view["options"][0]["id"])
        journal = self.room.observe(None)["cursor"]
        self.act(1, "special_choose_card", target_card_id="lin_qiu_draw_blade")
        events = self.room.observe(None, journal)["events"]
        self.assertIn("玩家一依词条选择技能。", [e["text"] for e in events if e["kind"] == "action"])
        self.assertTrue(any("使用 拔剑相向" in e["text"] for e in events))
        self.assertIsNone(self.game.special.decision_owner)

    def test_declining_surprise_is_available_without_a_prior_declaration(self):
        self.reach_surprise_hit(4)
        self.act(1, "special_decline_card")
        self.assertEqual(self.room.observe(None)["frame"]["turn"], 2)
        self.assertIsNone(self.game.special.decision_owner)

    def test_seat_distinguishes_two_enemy_face_down_cards_in_the_same_slot(self):
        self.create(("nova_lin_qiu", "waa_lake"), 4)
        self.start()
        lin, lake = (p.characters[0] for p in self.game.players)
        first, second = lake.skills[:2]
        for card in (first, second):
            self.assertTrue(self.game.place_in_duel(2, card, 0))
        entry = Entry.from_spec(lin, {"trigger": "test_target", "operation": {"op": "program", "code": [
            "$target_board_skills", {"literal": {"then": {"op": "program", "code": ["$chosen_card", "DESTROY"]}}},
            "CHOOSE_CARD",
        ]}})
        with self.game.context.binding(source=lin, target=lake):
            self.game.context._invoke(entry)
        choices = self.room.observe(1)["options"]
        self.assertEqual([m["kind"] for m in choices], ["special_choose_card"] * 2)
        self.assertNotEqual(choices[0]["id"], choices[1]["id"])
        for card in (first, second):
            self.assertNotIn(card.name, str(choices))
            self.assertNotIn(card.id, str(choices))
        self.assertFalse(self.room.observe(2)["options"])
        self.command(1, "act", option_id=choices[1]["id"])
        self.assertTrue(second.destroyed)
        self.assertFalse(first.destroyed)

    def test_effect_choosing_a_slot_pauses_the_original_placement_seat(self):
        self.create(("blank_boss", "waa_lake"), 4)
        self.start()
        caster = self.game.players[0].characters[0]
        first, second, extra = caster.skills[:3]
        for index, card in enumerate((first, second)):
            self.assertTrue(self.game.place_in_duel(1, card, index))
        if extra not in caster.player.cardspace.hand.content:
            caster.player.cardspace.draw.move_card_to(extra, caster.player.cardspace.hand)
        rule = Entry.from_spec(caster, {"trigger": "test_slot", "operation": {"op": "program", "code": [
            "$self", extra.id, "hand", "FIND_SKILL", 0, "SKILL_USE", "$own_regular_duels",
            ["$choice_subject", "$chosen_slot", "slot_tail", "INSERT_AT", "INSERT_SKILL"], "CHOOSE_SLOT",
        ]}})
        self.game.context._invoke(rule)
        self.assertEqual([m["duel_number"] for m in self.room.observe(1)["options"]], [1, 2])
        self.assertFalse(self.room.observe(2)["options"])
        self.act(1, "special_choose_slot", duel_number=2)
        self.assertEqual(self.game.duelspace.space[1].get_content(1), [second, extra])
        self.assertIsNone(self.game.special.placement_owner)

    def test_declaration_can_reserve_discards_and_sends_only_ability_name_to_opponent(self):
        self.create(("blank_boss", "waa_lake"), 4)
        self.command(1, "prepare", declaration={"mode": "reserve", "event": "placement",
                     "match": {"kind": "special_ability", "ability_id": "deduce_discard"}})
        self.start()
        if self.game.placing.side == 2:
            self.act(2, "end")
        moves = [m for m in self.room.observe(1)["options"] if m.get("ability_id") == "deduce_discard"]
        self.assertGreater(len(moves), 1)
        self.assertFalse(self.room.observe(2)["options"])
        self.command(1, "act", option_id=moves[1]["id"])
        actor = self.game.players[0].characters[0]
        self.assertEqual(actor.player.cardspace.delayed_discard.content[-1].id, moves[1]["target_card_id"])
        event = next(e for e in reversed(self.room.observe(None, 0)["events"]) if e["kind"] == "action")
        self.assertEqual(event["text"], "玩家一使用智脑·弃牌。")

    def test_mirror_discards_keep_the_other_seats_reserved_choices_on_the_same_window(self):
        self.create(("blank_boss", "blank_boss"), 8)
        for side in (1, 2):
            self.command(side, "prepare", declaration={"mode": "reserve", "event": "timing",
                         "match": {"kind": "special_ability", "ability_id": "deduce_discard"}})
        self.start()
        second = self.room.observe(2)["options"]
        reserved = next(m for m in second if m.get("ability_id") == "deduce_discard")
        self.act(1, "special_ability", ability_id="deduce_discard")
        self.assertIn(reserved, self.room.observe(2)["options"])
        self.command(2, "act", option_id=reserved["id"])
        self.assertEqual([len(p.cardspace.delayed_discard.content) for p in self.game.players], [1, 1])

    def test_discard_ability_can_pick_the_stolen_copy_even_with_an_identical_hand_card(self):
        self.create(("blank_boss", "blank_boss"), 2)
        self.start()
        player = self.game.placing
        other = next(p for p in self.game.players if p is not player)
        stolen = self.game.context.eval_block([other.characters[0], player.characters[0], OpCode.TAKE_HAND_CARD])
        original = next(c for c in player.cardspace.hand.content if c is not stolen and c.id == stolen.id)
        choices = [m for m in self.room.engine.options(player.side) if m.get("ability_id") == "deduce_discard"]
        self.assertIn(hand_key(original), [m["target_card_id"] for m in choices])
        move = next(m for m in choices if m["target_card_id"] == hand_key(stolen))
        self.assertIn("取自对手", move["label"])
        event = self.room.engine.apply(player.side, move)
        self.assertIn(original, player.cardspace.hand.content)
        self.assertIn(stolen, player.cardspace.delayed_discard.content)
        self.assertNotIn(stolen.name, event["text"])

    def test_insight_distinguishes_several_hidden_targets_in_one_slot(self):
        self.create(("blank_boss", "waa_lake"), 4)
        self.start()
        actor, target = (p.characters[0] for p in self.game.players)
        first, second = target.skills[:2]
        for c in (first, second):
            self.assertTrue(self.game.place_in_duel(2, c, 0))
        actor.add_ability_effect("洞察", 1)
        options = [m for m in self.room.engine.options(1) if m.get("ability_id") == "insight"]
        self.assertEqual(len(options), 2)
        self.assertNotEqual(options[0]["choice_key"], options[1]["choice_key"])
        for c in (first, second):
            self.assertNotIn(c.id, str(options))
            self.assertNotIn(c.name, str(options))
        self.room.engine.apply(1, options[1])
        slot = self.room.observe(None)["frame"]["duels"][0]["sides"][1]["cards"]
        self.assertEqual(slot[0], {"hidden": True})
        self.assertEqual(slot[1]["name"], second.name)
