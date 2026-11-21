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
                    "op": "program", "code": ["$value_ref", 10, "VALUE_FLOOR"],
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
