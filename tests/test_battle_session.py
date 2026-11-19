"""Regression coverage for the local battle adapter, independent of the browser."""

import io
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from http import HTTPStatus
from unittest.mock import patch

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

    def test_pre_reveal_decisions_keep_ordinary_cards_hidden_until_each_pull(self):
        state = self.session.state()

        def play(action, **fields):
            nonlocal state
            status, state = self.session.command(dict(action=action, revision=state["revision"], **fields))
            self.assertEqual(status, HTTPStatus.OK)
            if state["mode"] == "handoff":
                self.assertFalse(state["legal_cards"])
                self.assertTrue(all(p["hand"] is None for p in state["frame"]["players"]))

        def ready():
            if state["mode"] == "handoff":
                play("ready")

        play("new", roster=["mistport_cen_yao", "plan_b_annolin"])
        ready()
        play("place", card_id="cen_yao_fold_rule")
        ready()
        annolin_hand = state["frame"]["players"][1]["hand"]
        reserved, interceptor = annolin_hand[0]["id"], annolin_hand[1]["id"]
        play("place", card_id=reserved)
        play("end")
        ready()
        play("end")
        ready()
        self.assertEqual(state["mode"], "pre_attack")
        before = self.session.state()
        with self.assertRaises(ValueError):
            play("attack", card_id="cen_yao_sounding", target={"kind": "duel", "number": 0})
        self.assertEqual(before, self.session.state())
        play("attack", card_id="cen_yao_sounding", target={"kind": "duel", "number": 1})
        ready()
        self.assertFalse(state["frame"]["pre_reveal"]["duels"][0]["ready"])
        play("intercept", card_id=interceptor)
        ready()
        board = state["frame"]
        self.assertEqual(board["duels"][0]["sides"][1]["cards"], [{"hidden": True}])
        early = board["pre_reveal"]["duels"][0]
        self.assertTrue(early["ready"])
        self.assertEqual(early["target"]["kind"], "intercept")
        self.assertIsNone(early["pulled_card_id"])
        play("attack", card_id="cen_yao_transit", target={"kind": "duel", "number": 1})
        ready()
        play("let_through")
        ready()
        play("end_attack")
        saw_pull = False
        while state["mode"] == "combat":
            board = state["frame"]
            self.assertFalse(board["cards_revealed"])
            self.assertTrue(all(p["hand"] is None for p in board["players"]))
            self.assertEqual(board["combat"]["kind"], "pre_reveal")
            if board["combat"]["duel_number"] == 2:
                self.assertEqual(board["duels"][0]["sides"][1]["cards"], [])
                self.assertEqual(board["pre_reveal"]["duels"][1]["pulled_card_id"], reserved)
                saw_pull = True
            play("next")
        self.assertTrue(saw_pull)
        self.assertEqual(state["mode"], "reveal")

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

    def test_either_seat_can_act_while_numbered_responses_stay_open(self):
        state = self.session.state()

        def play(action, **fields):
            nonlocal state
            status, state = self.session.command(dict(action=action, revision=state["revision"], **fields))
            self.assertEqual(status, HTTPStatus.OK)
            if state["mode"] == "handoff":
                self.assertTrue(all(p["hand"] is None for p in state["frame"]["players"]))
                for key in ("legal_cards", "legal_attack_cards", "legal_intercept_cards", "pending_responses"):
                    self.assertEqual(state[key], [])

        def take_seat(side):
            if state["mode"] != "handoff" and state["active_side"] != side:
                play("switch_side")
            if state["mode"] == "handoff":
                play("ready", side=side)
            self.assertEqual(state["active_side"], side)

        play("new", roster=["mistport_cen_yao", "plan_b_annolin"])
        # Model two attack-capable hands; the defender has exactly two cards,
        # so after counterattacking and intercepting once it must decide with an empty hand.
        for player in self.session.match.game.players:
            for card in player.characters[0].skills:
                card.data["pre_reveal"] = True
        first = state["active_side"]
        second = 3 - first
        defender = next(p for p in self.session.match.game.players if p.side == second)
        while len(defender.cardspace.hand.content) > 2:
            defender.cardspace.hand.move_card_to(0, defender.cardspace.draw)
        take_seat(first)
        play("end")
        take_seat(second)
        play("end")
        take_seat(first)

        targets = {p["side"]: {"kind": "character", "id": p["characters"][0]["id"]}
                   for p in state["frame"]["players"]}
        clock = self.enterContext(patch("battle_ui.match.time.time_ns", return_value=1_000_000_000))
        play("attack", card_id=state["legal_attack_cards"][0], target=targets[second])
        first_clock = {"number": 1, "declared_at_ms": 1000, "answered_at_ms": None}
        self.assertEqual(state["response_times"], [first_clock])
        self.assertEqual(state["mode"], "handoff")
        self.assertCountEqual(state["eligible_sides"], [first, second])
        take_seat(second)
        self.assertEqual(state["pending_responses"], [1])
        self.assertFalse(state["can_end_attack"])
        self.assertEqual(state["legal_attack_cards"], [])
        clock.return_value = 9_500_000_000
        play("switch_side")
        take_seat(first)
        self.assertEqual(state["response_times"], [first_clock])
        play("attack", card_id=state["legal_attack_cards"][0], target=targets[second])
        take_seat(first)
        play("end_attack")

        take_seat(second)
        self.assertEqual(state["pending_responses"], [1, 2])
        self.assertTrue(state["legal_attack_cards"])
        self.assertTrue(state["legal_intercept_cards"])
        before = state
        with self.assertRaises(ValueError):
            play("let_through")  # A specific number is required with two open duels.
        self.assertEqual(before, self.session.state())
        play("attack", card_id=state["legal_attack_cards"][0], target=targets[first])
        take_seat(second)
        clock.return_value = 18_250_000_000
        play("intercept", card_id=state["legal_intercept_cards"][0], duel_number=2)
        take_seat(second)
        self.assertEqual(state["response_times"][:2], [
            first_clock, {"number": 2, "declared_at_ms": 9500, "answered_at_ms": 18250},
        ])
        self.assertEqual([s["ready"] for s in state["frame"]["pre_reveal"]["duels"]], [False, True, False])
        self.assertEqual(state["pending_responses"], [1])
        self.assertIn(second, state["eligible_sides"])
        self.assertEqual(state["legal_intercept_cards"], [])
        self.assertTrue(state["can_end_attack"])
        before = state
        with self.assertRaises(ValueError):
            play("intercept", card_id="not_in_hand", duel_number=1)
        self.assertEqual(self.session.state(), before)
        play("switch_side")
        take_seat(second)
        self.assertEqual(state["response_times"][0], first_clock)
        play("end_attack")
        take_seat(first)
        play("let_through", duel_number=3)
        take_seat(second)
        self.assertEqual(state["pending_responses"], [1])
        self.assertFalse(state["can_end_attack"])
        self.assertFalse(state["frame"]["cards_revealed"])
        self.assertEqual(state["legal_intercept_cards"], [])
        self.assertIsNone(state["response_times"][0]["answered_at_ms"])
        with self.assertRaises(ValueError):
            play("let_through", duel_number=2)
        play("let_through", duel_number=1)
        self.assertIn(state["mode"], ("combat", "finished"))
