"""Regression coverage for the local battle adapter, independent of the browser."""

import io
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from http import HTTPStatus

from battle_ui.__main__ import BattleSession


class BattleSessionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.session = BattleSession(seed=37)

    def test_two_commands_against_one_revision_only_place_one_card(self):
        opening = self.session.state()
        card_id = opening["legal_cards"][0]
        command = {"action": "place", "revision": opening["revision"], "card_id": card_id}
        with ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(self.session.command, [command, command]))
        self.assertCountEqual([status for status, _ in replies], [HTTPStatus.OK, HTTPStatus.CONFLICT])
        self.assertEqual(replies[0][1], replies[1][1])
        changed = self.session.state()
        self.assertEqual(changed["mode"], "handoff")
        self.assertTrue(all(player["hand"] is None for player in changed["frame"]["players"]))
        slots = changed["frame"]["duels"]
        self.assertEqual(sum(len(side["cards"]) for slot in slots for side in slot["sides"]), 1)

    def test_new_match_hides_hands_and_rejects_old_match_commands(self):
        opening = self.session.state()
        roster = [choice["id"] for choice in opening["choices"][:2]]
        status, replaced = self.session.command({"action": "new", "revision": opening["revision"], "roster": roster})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(replaced["mode"], "handoff")
        self.assertTrue(all(p["hand"] is None for p in replaced["frame"]["players"]))
        self.assertNotEqual(opening["revision"], replaced["revision"])
        status, recovered = self.session.command({"action": "end", "revision": opening["revision"]})
        self.assertEqual((status, recovered), (HTTPStatus.CONFLICT, replaced))
        with self.assertRaises(ValueError):
            self.session.command({"action": "new", "revision": replaced["revision"], "roster": [roster[0]] * 2})
        self.assertEqual(self.session.state(), replaced)

    def test_default_duel_shows_public_clash_scores_and_reaches_victory(self):
        state = self.session.state()
        saw_comparison = False
        for _ in range(300):
            mode, frame = state["mode"], state["frame"]
            if mode != "placement":
                self.assertTrue(all(p["hand"] is None for p in frame["players"]))
            if mode == "finished":
                break
            if mode == "combat":
                dice = [side["die"] for side in frame["combat"]["sides"]]
                if all(die and die["clash_score"] is not None for die in dice):
                    left, right = dice
                    expected = ("draw", "draw")
                    if left["clash_score"] > right["clash_score"]:
                        expected = ("win", "lose")
                    elif left["clash_score"] < right["clash_score"]:
                        expected = ("lose", "win")
                    self.assertEqual((left["result"], right["result"]), expected)
                    saw_comparison = True
            command = {"revision": state["revision"]}
            if mode == "placement":
                command.update(action="place", card_id=state["legal_cards"][0])
            else:
                command["action"] = "ready" if mode == "handoff" else "next"
            status, state = self.session.command(command)
            self.assertEqual(status, HTTPStatus.OK)
        else:
            self.fail("交锋未在 300 次公开结算或置卡选择内结束")
        self.assertTrue(saw_comparison)
        self.assertTrue(frame["is_over"])
        self.assertIn(frame["winner_side"], (1, 2))
