"""New character choices through the independent seats and their public journal."""
import io
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from itertools import count

from battle_mcp.decision_view import decision_view
from battle_mcp.room import Room, move_id
from displayer import hand_key
from entry.entry import Entry
from models.card import Card
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

    def test_human_can_pause_live_play_without_a_declaration_and_only_owner_can_resume(self):
        self.create(("ember_wen_sheng", "plan_b_annolin"), 37)
        # Deliver each scheduled room beat deterministically. The HTTP regression
        # exercises the same callback on the real timer.
        self.enterContext(patch("battle_mcp.room.threading.Timer"))
        self.command(1, "ready", human=True)
        self.command(2, "ready")
        view = self.command(1, "pause")
        self.assertEqual(view["paused_by"], 1)
        self.assertEqual(view["declarations"], [])
        self.assertIsNone(self.room._beat_timer)
        with self.assertRaises(ValueError):
            self.command(2, "resume")
        self.assertFalse(self.room.observe(2)["options"])
        self.command(1, "resume")
        stale_revision = self.room.observe(1)["revision"]
        for _ in range(160):
            if self.room.engine._mode() == "combat":
                break
            required = self.room.engine.required_sides()
            if required:
                side = required[0]
                moves = self.room.observe(side)["options"]
                move = next((m for m in moves if m["kind"] == "place" and m["card_id"] == "wen_sheng_call"),
                            None) or next(m for m in moves if m["kind"] in ("end", "end_attack"))
                self.command(side, "act", option_id=move["id"])
            else:
                self.assertIsNotNone(self.room._beat_timer)
                with patch("battle_mcp.room.threading.current_thread", return_value=self.room._beat_timer):
                    self.room._advance_beat()
        else:
            self.fail("未进入交锋")
        view = self.room.pause(1, stale_revision, "pause-in-combat")
        self.assertEqual(view["frame"]["mode"], "combat")
        attack = next(move for move in view["options"] if move["kind"] == "special_attack")
        self.command(1, "act", option_id=attack["id"])
        self.assertIsNone(self.room.paused_by)
        self.assertIsNotNone(self.game.pipeline.interrupt_space)

    def test_turn_start_effect_requests_a_concealed_board_target_before_placement(self):
        self.create(("nova_lin_qiu", "waa_lake"), 4)
        lin, lake = (p.characters[0] for p in self.game.players)
        first, second = lake.skills[:2]
        for card in (first, second):
            self.assertTrue(self.game.place_in_duel(2, card, 0))
        self.game.context.register_entries(lin, [{"trigger": "on_turn_start",
            "choice_prompt": "指定一张已置卡牌。", "operation": {"op": "program", "code": [
                "$board_skills", {"literal": {"then": {"op": "program", "code": ["$chosen_card", "DESTROY"]}}},
                "CHOOSE_CARD",
            ]}}])
        self.start()
        view = self.room.observe(1)
        self.assertEqual(self.game.last_step, "on_turn_start")
        self.assertEqual(view["frame"]["effect_choice"]["description"], "指定一张已置卡牌。")
        self.assertEqual([move["effect_target"]["position"] for move in view["options"]], [1, 2])
        self.assertFalse(self.room.observe(2)["options"])
        self.assertNotIn(first.id, str(view["options"]))
        self.command(1, "act", option_id=view["options"][1]["id"])
        self.assertTrue(second.destroyed)
        self.assertFalse(first.destroyed)
        self.assertEqual(self.room.engine._mode(), "placement")

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
        prompt = view["frame"]["effect_choice"]
        self.assertEqual((prompt["source_name"], prompt["source_card_id"], prompt["die_position"],
                          prompt["selection"], prompt["optional"]), ("出其不意", "lin_qiu_surprise", 3, "hand", True))
        self.assertIn("通常费用减2", prompt["description"])
        compact = decision_view(view)
        self.assertEqual(compact["frame"]["effect_choice"], prompt)
        self.assertNotIn("effect_choice", self.room.observe(2)["frame"])
        self.assertNotIn("effect_choice", self.room.observe(None)["frame"])
        moves = {option.get("target_card_id"): option for option in view["options"]}
        blade = moves["lin_qiu_draw_blade"]
        self.assertEqual(blade["use_preview"], {"base_cost": 1, "discount": 2, "cost": 0, "resource_cost": None})
        cut = moves["lin_qiu_void_cut"]
        self.assertEqual(cut["use_preview"], {"base_cost": 4, "cost": 2, "discount": 2,
                                               "resource_cost": {"status": "隧道", "amount": 2, "available": 1}})
        self.assertEqual(cut["effect_target"]["card"]["name"], "空断")
        self.assertEqual((cut["effect_target"]["zone"], cut["effect_target"]["side"]), ("hand", 1))
        old_fields = {k: v for k, v in cut.items() if k not in ("id", "effect_target", "use_preview")}
        self.assertEqual(cut["id"], move_id(1, old_fields))
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
        self.assertEqual([move["effect_target"] for move in choices],
                         [{"zone": "board", "kind": "regular", "side": 2, "number": 1, "position": number}
                          for number in (1, 2)])
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
        request = self.room.observe(1)
        self.assertEqual(request["frame"]["effect_choice"]["selection"], "slot")
        self.assertEqual([m["effect_target"] for m in request["options"]],
                         [{"zone": "board", "kind": "regular", "side": 1, "number": number} for number in (1, 2)])
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
        self.assertEqual([m["effect_target"] for m in options],
                         [{"zone": "board", "side": 2, "kind": "regular", "number": 1, "position": n}
                          for n in (1, 2)])
        for c in (first, second):
            self.assertNotIn(c.id, str(options))
            self.assertNotIn(c.name, str(options))
        self.room.engine.apply(1, options[1])
        slot = self.room.observe(None)["frame"]["duels"][0]["sides"][1]["cards"]
        self.assertEqual(slot[0], {"hidden": True})
        self.assertEqual(slot[1]["name"], second.name)

    def test_replacement_distinguishes_same_named_face_down_targets(self):
        self.create(("ember_wen_sheng", "plan_b_annolin"), 1125)
        self.start()
        actor = self.game.players[0].characters[0]
        original = next(c for c in actor.skills if c.id == "wen_sheng_duet")
        incoming = next(c for c in actor.skills if c.id == "wen_sheng_understudy")
        duplicate = Card(actor.player, original.printed_data, actor)
        actor.skills.append(duplicate)
        for target in (original, duplicate):
            self.assertTrue(self.game.place_in_duel(1, target, 0))
        options = [m for m in self.room.engine.options(1)
                   if m.get("card_id") == incoming.id and m["kind"] == "special_replace"]
        self.assertEqual([m["effect_target"]["position"] for m in options], [1, 2])
        self.assertEqual([m["effect_target"]["card"]["instance_id"] for m in options],
                         [original.instance_id, duplicate.instance_id])
        self.assertNotEqual(move_id(1, options[0]), move_id(1, options[1]))
        self.assertIn("常规交锋 1 · 第 2 张", options[1]["label"])
        self.assertEqual(self.room.observe(None)["frame"]["duels"][0]["sides"][0]["cards"], [{"hidden": True}] * 2)
        self.room.engine.apply(1, options[1])
        self.assertEqual(self.game.duelspace.space[0].get_content(1), [original, incoming])
