import io
import json
import random
import unittest
from contextlib import redirect_stdout

from displayer import Displayer
from game import Game
from loader import load_characters_from_packs
from models.card import CardState
from models.character import Character
from models.opcode import OpCode
from player.player import Player


class DisplayerTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))

    def make_game(self):
        game = Game([Player(1, "甲"), Player(2, "乙")], rng=random.Random(27))
        for player in game.players:
            skills = []
            for suffix in ("置入", "手中", "牌库"):
                name = player.name + suffix
                skills.append({
                    "id": name, "name": name, "cost": 1,
                    "dice": [{"type": "slash", "level": 1, "base_value": 1, "entries": ["1物理"]}],
                })
            actor = Character(dict(id=player.name, name=player.name, rank="NORMAL",
                                   max_hp=6, skills=skills), player)
            player.characters.append(actor)
            actor.init_cards()
            actor.setup_deck()
        return game

    def prepare_board(self, game):
        game.first_player = game.players[0]
        game.start_turn()
        for player in game.players:
            player.draw_card(2)
            self.assertTrue(game.auto_place_in_duel(player.side, player.cardspace.hand.content[0]))

    def test_reserved_dice_publish_the_captured_face_and_remaining_opportunities(self):
        game = self.make_game()
        actor = game.players[0].characters[0]
        card = actor.skills[0]
        card.dice.append({"type": "evade", "level": 2})
        game.context.eval_block([actor, card, 2, OpCode.CAPTURE_SKILL_DIE, 3,
                                 "before_one_sided_attack", 4, "use", 1, OpCode.GRANT_DIE_RESPONSE])
        card.name = "换面后"
        actor.reserved_dice[0].spend("use")
        for seat in (None, 1, 2):
            view = Displayer(game, viewer_side=seat).snapshot()
            self.assertEqual(view["players"][0]["characters"][0]["reserved_dice"],
                             [{"skill": "甲置入", "position": 2, "remaining": 2}])

    def test_unstarted_match_is_safe_to_read(self):
        game = Game([Player(1, "A"), Player(2, "B")])
        view = Displayer(game).snapshot()
        self.assertIsNone(view["node"])
        self.assertIsNone(view["combat"])
        self.assertIsNone(view["winner_side"])
        self.assertFalse(view["is_over"])
        self.assertEqual(view["duels"], [])
        self.assertEqual(view, json.loads(json.dumps(view, allow_nan=False)))
        with self.assertRaises(ValueError):
            Displayer(game, viewer_side=42).snapshot()

    def test_hand_and_slot_visibility_before_and_after_reveal(self):
        game = self.make_game()
        self.prepare_board(game)
        for viewer in (None, 1, 2):
            view = Displayer(game, viewer_side=viewer).snapshot()
            encoded = json.dumps(view, ensure_ascii=False)
            for player, team, slot in zip(game.players, view["players"], view["duels"][0]["sides"]):
                self.assertEqual((team["side"], slot["side"]), (player.side, player.side))
                self.assertEqual((team["draw_count"], team["hand_count"]), (1, 1))
                self.assertNotIn(player.name + "牌库", encoded)
                if player.side == viewer:
                    self.assertEqual([card["id"] for card in team["hand"]], [player.name + "手中"])
                    self.assertEqual(slot["cards"][0]["id"], player.name + "置入")
                else:
                    self.assertIsNone(team["hand"])
                    self.assertEqual(slot["cards"], [{"hidden": True}])
                    self.assertNotIn(player.name + "手中", encoded)
                    self.assertNotIn(player.name + "置入", encoded)

        # A negated face-down card still belongs to the private placement.
        game.players[1].characters[0].skills[0].state = CardState.NEGATED
        self.assertEqual(Displayer(game, viewer_side=1).snapshot()["duels"][0]["sides"][1]["cards"],
                         [{"hidden": True}])
        game.reveal_cards()
        view = Displayer(game).snapshot()
        for team, slot in zip(view["players"], view["duels"][0]["sides"]):
            self.assertIsNone(team["hand"])
            self.assertEqual(slot["cards"][0]["id"], team["name"] + "置入")
            self.assertEqual(slot["cards"][0]["character_id"], team["characters"][0]["id"])

    def test_lightcore_and_its_reduced_maximum_are_public(self):
        game = self.make_game()
        target = game.players[0].characters[0]
        old = Displayer(game).snapshot()["players"][0]["characters"][0]
        self.assertEqual((old["lightcore_hp"], old["max_lightcore_hp"]), (12, 12))
        game.context.eval_block([target, 14, OpCode.LIGHTCORE_DAMAGE])
        game.context.eval_block([target, 2, OpCode.LIGHTCORE_DAMAGE])
        for viewer in (None, 1, 2):
            now = Displayer(game, viewer_side=viewer).snapshot()["players"][0]["characters"][0]
            self.assertEqual((now["hp"], now["lightcore_hp"], now["max_lightcore_hp"]), (3, 6, 8))
        self.assertEqual(old["max_lightcore_hp"], 12)

    def test_delayed_discard_and_out_of_combat_lists_are_private(self):
        game = self.make_game()
        for player in game.players:
            zones = player.cardspace
            zones.draw.move_card_to(0, zones.delayed_discard)
            zones.draw.move_card_to(0, zones.out_of_combat)
        for viewer in (None, 1, 2):
            view = Displayer(game, viewer_side=viewer).snapshot()
            for team in view["players"]:
                for zone, suffix in (("delayed_discard", "置入"), ("out_of_combat", "手中")):
                    self.assertEqual(team[zone + "_count"], 1)
                    if team["side"] == viewer:
                        self.assertEqual([c["id"] for c in team[zone]], [team["name"] + suffix])
                    else:
                        self.assertIsNone(team[zone])
                        self.assertNotIn(team["name"] + suffix, json.dumps(view, ensure_ascii=False))

    def test_public_catalog_uses_printed_rules_independently_of_live_zones(self):
        game = Game([Player(1, "甲"), Player(2, "乙")])
        player = game.players[0]
        data = next(c for c in load_characters_from_packs() if c["name"] == "安诺琳")
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        public = Displayer(game)
        catalog = public.catalog()
        self.assertEqual(catalog, json.loads(json.dumps(catalog, allow_nan=False)))
        self.assertEqual(catalog, Displayer(game, viewer_side=1).catalog())
        printed = catalog["players"][0]["characters"][0]
        self.assertEqual([skill["cost"] for skill in printed["skills"]], [1, 2, 2, 3, 5])
        self.assertIn("翠流漂泊", [p["name"] for p in printed["passives"]])
        self.assertTrue(any("拼点" in line for line in catalog["statuses"]["涡流"]))
        first_die = printed["skills"][0]["dice"][0]
        self.assertEqual((first_die["type"], first_die["roll_max"]), ("slash", 6))
        self.assertTrue(any("命中" in entry for entry in first_die["entries"]))
        self.assertNotIn("state", printed["skills"][0])
        player.draw_card(2)
        self.assertTrue(game.auto_place_in_duel(player.side, actor.skills[0]))
        self.assertEqual(public.catalog(), catalog)
        first_die["entries"].clear()
        catalog["statuses"]["涡流"].clear()
        self.assertTrue(public.catalog()["players"][0]["characters"][0]["skills"][0]["dice"][0]["entries"])
        self.assertTrue(public.catalog()["statuses"]["涡流"])

    def test_reordering_a_private_deck_cannot_leak_through_other_fields(self):
        original, reordered = self.make_game(), self.make_game()
        pile = reordered.players[1].cardspace.draw
        pile.move_card_to(0, pile)
        # Even the owner cannot see which draw pile order the game is using.
        self.assertEqual(Displayer(original, viewer_side=2).snapshot(),
                         Displayer(reordered, viewer_side=2).snapshot())
        for game in (original, reordered):
            self.prepare_board(game)
        # The rotation changed all three of this player's hidden cards: one on
        # the board, one in hand, and one still in the draw pile.
        for viewer in (None, 1):
            self.assertEqual(Displayer(original, viewer_side=viewer).snapshot(),
                             Displayer(reordered, viewer_side=viewer).snapshot())
        self.assertNotEqual(Displayer(original, viewer_side=2).snapshot(),
                            Displayer(reordered, viewer_side=2).snapshot())

    def test_mutating_visible_data_does_not_change_game_or_next_snapshot(self):
        game = self.make_game()
        self.prepare_board(game)
        player = game.players[0]
        actor = player.characters[0]
        actor.add_status("强壮", 2)
        board_card = actor.skills[0]
        display = Displayer(game, viewer_side=player.side)
        before = display.snapshot()
        editable = display.snapshot()
        team = editable["players"][0]
        team["characters"][0]["statuses"]["强壮"] = 50
        team["characters"][0]["shields"].clear()
        team["hand"][0]["dice"].clear()
        editable["duels"][0]["sides"][0]["cards"][0]["dice"][0]["type"] = "blank"
        self.assertEqual(actor.statuses["强壮"], 2)
        self.assertEqual(board_card.dice[0]["type"], "slash")
        self.assertEqual(len(player.cardspace.hand.content[0].dice), 1)
        self.assertEqual(display.snapshot(), before)
        self.assertIsNone(board_card.instantiated_dice)

    def test_observing_each_step_preserves_rng_events_and_battle_result(self):
        def fight(observe):
            game = self.make_game()
            self.prepare_board(game)
            actor = game.players[0].characters[0]
            actor.add_status("强壮", 1)
            game.context.register_entries(actor, [{
                "trigger": "BEFORE RESOLVE_CLASH_SCORE", "operation": {
                    "op": "program", "code": ["$event.value_ref", 10, "VALUE_FLOOR"],
                },
            }])
            game.players[1].characters[0].hp = 1
            game.reveal_cards()
            game.pipeline.start_duel_combat()
            display = Displayer(game) if observe else None
            events, dice = [], []
            for _ in range(200):
                if display:
                    rng_before = game.rng.getstate()
                    entries_before = tuple(game.context.entries)
                    view = display.snapshot()
                    self.assertEqual(view, display.snapshot())
                    self.assertEqual(view, json.loads(json.dumps(view, allow_nan=False)))
                    self.assertEqual(game.rng.getstate(), rng_before)
                    self.assertEqual(tuple(game.context.entries), entries_before)
                    if view["combat"]:
                        side = next(s for s in view["combat"]["sides"] if s["side"] == actor.player.side)
                        if side["die"] is not None:
                            dice.append(side["die"])
                if not game.pipeline.in_duel_phase:
                    break
                events.append(game.next_step())
            else:
                self.fail("对局未完成")
            if display:
                self.assertTrue(view["is_over"])
                self.assertEqual(view["winner_side"], actor.player.side)
                self.assertIsNone(view["combat"])
                self.assertTrue(any(d["rolled_value"] is None and d["final_score"] is None
                                    and d["clash_score"] is None for d in dice))
                rolled = next(d for d in dice if d["rolled_value"] is not None and d["clash_score"] is None)
                self.assertIsNone(rolled["final_score"])
                won = next(d for d in dice if d["result"] == "win")
                self.assertEqual((won["position"], won["base_value"], won["clash_score"]), (1, 1, 10))
                self.assertEqual(won["final_score"], 1 + won["rolled_value"] + 1)
            self.assertTrue(game.is_over)
            return events, game.winner.side, [p.characters[0].hp for p in game.players], game.rng.getstate()

        self.assertEqual(fight(observe=True), fight(observe=False))

    def test_all_packs_project_structured_damage_parts_and_well_formed_triggers(self):
        from pathlib import Path
        from displayer import _passives, _printed_skill, format_damage_part

        def assert_well_formed_brackets(text, ctx):
            pos = 0
            while True:
                open_idx = text.find("【", pos)
                if open_idx == -1:
                    break
                close_idx = text.find("】", open_idx + 1)
                self.assertNotEqual(close_idx, -1, f"unclosed 【 in {ctx}: {text}")
                self.assertTrue(text[open_idx + 1:close_idx].strip(), f"empty 【】 in {ctx}: {text}")
                pos = close_idx + 1

        extra = [Path(__file__).resolve().parents[1] / "_packs" / "challenges" / "structured_carrier.json"]
        chars = load_characters_from_packs(extra_packs=extra)
        self.assertTrue(chars)
        for char in chars:
            self.assertNotIn("printed_text", char)
            for passive in _passives(char.get("faction_passives", ())) + _passives(char.get("passive_skills", ())):
                for line in passive["display_lines"]:
                    assert_well_formed_brackets(line, f"{char['id']} passive")
            for raw_skill in char["skills"]:
                skill = _printed_skill(raw_skill, include_forms=True)
                self.assertNotIn("printed_text", skill)
                for form in [skill, *skill["forms"]]:
                    self.assertIsInstance(form["name"], str)
                    self.assertIsInstance(form["cost"], int)
                    for entry in form["entries"]:
                        assert_well_formed_brackets(entry, f"{char['id']}.{form['id']}")
                    for die in form["dice"]:
                        self.assertNotIn("printed_line", die)
                        self.assertIn("damage_parts", die)
                        ranks = []
                        for part in die["damage_parts"]:
                            self.assertIn(part["grade"], ("normal", "pierce", "concept", "lightcore", "real"))
                            self.assertIsInstance(part["amount"], (int, str))
                            expected = format_damage_part(part["amount"], part["grade"], aoe=part.get("aoe", False))
                            self.assertEqual(part["text"], expected)
                            self.assertNotIn("label", part)
                            ranks.append(0 if part["grade"] == "normal" and not part.get("aoe")
                                         else 1 if part["grade"] == "normal" else 2)
                        self.assertEqual(ranks, sorted(ranks), die["damage_parts"])
                        for entry in die["entries"]:
                            assert_well_formed_brackets(entry, f"{char['id']}.{form['id']} die")

    def test_concise_damage_formatting_orders_normal_first_and_supports_aoe_and_expressions(self):
        from displayer import _printed_die
        mixed = _printed_die({
            "type": "slash", "level": 3,
            "entries": [
                "1真实",
                "2穿甲",
                "1物理",
                {"damage_part": {"amount": 1, "grade": "normal", "aoe": True}, "description": "群体 1"},
                {"damage_part": {"amount": 1, "grade": "pierce", "aoe": True}, "description": "群体 1 穿甲"},
                {"damage_part": {"amount": "(能源值-1)", "grade": "lightcore"}, "description": "【命中时】附带效果"},
            ],
        })
        self.assertEqual(
            [p["text"] for p in mixed["damage_parts"]],
            ["1", "群体 1", "1 真实", "2 穿甲", "群体 1 穿甲", "(能源值-1) 光点"],
        )
        self.assertEqual(mixed["entries"], ["【命中时】附带效果"])

    def test_hidden_internal_entries_are_excluded_while_visible_plain_and_triggered_lines_survive(self):
        from displayer import _passives, _printed_skill
        skill = _printed_skill({
            "id": "pair_test", "name": "对比技能", "cost": 1,
            "entries": [
                {"description": "本技能不会被摧毁", "hidden": False},
                {"description": "内部登记钩子", "hidden": True},
                {"description": "【使用时】获得1能源"},
            ],
            "dice": [{
                "type": "slash", "level": 3,
                "entries": [
                    "1物理",
                    {"description": "内部跟踪", "hidden": True},
                    {"description": "【命中时】抽1卡"},
                ],
            }],
        })
        self.assertEqual(skill["entries"], ["本技能不会被摧毁", "【使用时】获得1能源"])
        self.assertEqual(skill["dice"][0]["entries"], ["【命中时】抽1卡"])
        passives = _passives([{
            "name": "多行被动",
            "description": "第一行原文\n【回合开始】第二行触发",
            "entries": [{"description": "低层钩子1"}, {"description": "低层钩子2"}],
        }])
        self.assertEqual(passives[0]["display_lines"], ["第一行原文", "【回合开始】第二行触发"])

    def test_dual_form_skills_project_both_forms_and_track_active_form_across_live_and_roster_views(self):
        from battle_ui.match import BattleMatch

        chars = load_characters_from_packs()
        liu_spec = next(c for c in chars if c["name"] == "流阴")
        lan_spec = next(c for c in chars if c["name"] == "澜清")

        match = BattleMatch(roster=[[liu_spec["id"]], [lan_spec["id"]]], seed=19, initial_handoff=False)
        roster_by_id = {c["id"]: c for c in match.table_assets()["roster_catalog"]}
        roster_armor = next(s for s in roster_by_id[liu_spec["id"]]["skills"] if s["id"] == "liu_armor")
        self.assertEqual([f["name"] for f in roster_armor["dual_forms"]], ["战甲塑造", "肃清引信"])
        self.assertEqual([f["form_label"] for f in roster_armor["dual_forms"]], ["常态", "战甲≥1"])

        roster_dance = next(s for s in roster_by_id[lan_spec["id"]]["skills"] if s["id"] == "lan_dance_2")
        self.assertEqual([f["form_label"] for f in roster_dance["dual_forms"]], ["常态", "活化态"])
        self.assertEqual(len(roster_dance["dual_forms"][0]["dice"]), 2)
        self.assertEqual(len(roster_dance["dual_forms"][1]["dice"]), 3)

        # Verify live _visible_card preserves BOTH forms before and after status transformation!
        game = Game([Player(1, "甲"), Player(2, "乙")])
        liu = Character(liu_spec, game.players[0])
        lan = Character(lan_spec, game.players[1])
        game.players[0].characters.append(liu)
        game.players[1].characters.append(lan)
        liu.init_cards()
        lan.init_cards()
        armor_card = next(c for c in liu.skills if c.id == "liu_armor")
        dance_card = next(c for c in lan.skills if c.id == "lan_dance_2")
        game.players[0].cardspace.hand.add_card(armor_card)
        game.players[1].cardspace.hand.add_card(dance_card)

        v1_before = Displayer(game, viewer_side=1).snapshot()["players"][0]["hand"][0]
        self.assertEqual((v1_before["name"], v1_before["active_form"], v1_before["active_form_label"]),
                         ("战甲塑造", None, "常态"))
        self.assertEqual([(f["name"], f["is_active_form"]) for f in v1_before["dual_forms"]],
                         [("战甲塑造", True), ("肃清引信", False)])

        liu.add_status("战甲", 1)
        v1_after = Displayer(game, viewer_side=1).snapshot()["players"][0]["hand"][0]
        self.assertEqual((v1_after["name"], v1_after["active_form"], v1_after["active_form_label"]),
                         ("肃清引信", "armored", "战甲≥1"))
        self.assertEqual([(f["name"], f["is_active_form"]) for f in v1_after["dual_forms"]],
                         [("战甲塑造", False), ("肃清引信", True)])

        lan.add_status("电叉·回环舞·活化", 1)
        v2_after = Displayer(game, viewer_side=2).snapshot()["players"][1]["hand"][0]
        self.assertEqual((v2_after["active_form"], v2_after["active_form_label"]), ("active", "活化态"))
        self.assertEqual([f["is_active_form"] for f in v2_after["dual_forms"]], [False, True])
        self.assertEqual([len(f["dice"]) for f in v2_after["dual_forms"]], [2, 3])
