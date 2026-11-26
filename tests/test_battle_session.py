"""Regression coverage for BattleMatch state machine and hotseat Room concurrency."""

import io
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from http import HTTPStatus
from unittest.mock import patch

from battle_mcp.room import Room, RoomConflict
from battle_ui.match import BattleMatch, StaleActionError


class _LocalMatchDriver:
    """Thread-safe test harness driving `BattleMatch` directly."""

    def __init__(self, seed=37):
        self._lock = threading.Lock()
        self._seed = seed
        self._offset = 0
        self.match = BattleMatch(seed=seed)
        self._fold_empty_timings()

    def _fold_empty_timings(self):
        while self.match.mode == "timing" and not self.match.snapshot()["special_available"]:
            self.match._advance()

    def state(self):
        with self._lock:
            snap = {**self.match.table_assets(), **self.match.snapshot()}
            snap["revision"] += self._offset
            return snap

    def command(self, body):
        action = body.get("action")
        rev = body.get("revision")
        with self._lock:
            cur_rev = self.match.revision + self._offset
            if type(rev) is not int or rev != cur_rev:
                snap = {**self.match.table_assets(), **self.match.snapshot()}
                snap["revision"] += self._offset
                return HTTPStatus.CONFLICT, snap
            if action == "new":
                next_match = BattleMatch(
                    body.get("roster"),
                    seed=self._seed,
                    initial_handoff=True,
                )
                self._offset = cur_rev + 1
                self.match = next_match
                self._fold_empty_timings()
                snap = {**self.match.table_assets(), **self.match.snapshot()}
                snap["revision"] += self._offset
                return HTTPStatus.OK, snap
            try:
                self.match.act(
                    action,
                    self.match.revision,
                    card_id=body.get("card_id"),
                    card_ids=body.get("card_ids"),
                    target=body.get("target"),
                    side=body.get("side"),
                    duel_number=body.get("duel_number"),
                    option=body.get("option"),
                    character_id=body.get("character_id"),
                )
                self._fold_empty_timings()
            except StaleActionError:
                snap = {**self.match.table_assets(), **self.match.snapshot()}
                snap["revision"] += self._offset
                return HTTPStatus.CONFLICT, snap
            snap = {**self.match.table_assets(), **self.match.snapshot()}
            snap["revision"] += self._offset
            return HTTPStatus.OK, snap


class BattleMatchAndHotseatTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.session = _LocalMatchDriver(seed=37)

    def test_hotseat_room_rejects_duplicate_concurrent_revision_commands(self):
        room = Room(["plan_b_annolin", "lan_qing"], seed=37, hotseat=True, start_immediately=True)
        self.addCleanup(room.close)
        s0 = room.canvas_state(None, hotseat=True)
        self.assertIsNotNone(s0["hotseat_handoff_side"])
        room.hotseat_ready(s0["hotseat_handoff_side"], s0["revision"], "r1")
        s1 = room.canvas_state(None, hotseat=True)
        place_opt = next(m for m in s1["options"] if m["kind"] == "place")

        def attempt(req_id):
            try:
                room.act(None, place_opt["id"], s1["revision"], req_id, hotseat=True)
                return HTTPStatus.OK
            except RoomConflict:
                return HTTPStatus.CONFLICT

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(attempt, ["p-a", "p-b"]))
        self.assertCountEqual(statuses, [HTTPStatus.OK, HTTPStatus.CONFLICT])

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
        roster = ["plan_b_heck", "plan_b_annolin"]
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

        play("new", roster=["plan_b_heck", "plan_b_annolin"])
        self.session.match._pre_reveal_claimed = {1: True, 2: True}
        for player in self.session.match.game.players:
            for card in player.characters[0].skills:
                card.data["pre_reveal"] = True
                card.data["cost"] = 1
        ready()
        first = state["active_side"]
        second = 3 - first
        p_first = state["frame"]["players"][first - 1]["hand"]
        place_1, atk_1, atk_2 = p_first[0]["id"], p_first[1]["id"], p_first[2]["id"]
        play("place", card_id=place_1)
        ready()
        p_second = state["frame"]["players"][second - 1]["hand"]
        reserved, interceptor = p_second[0]["id"], p_second[1]["id"]
        play("place", card_id=reserved)
        play("end")
        ready()
        play("end")
        ready()
        if state["active_side"] != first:
            play("switch_side")
            ready()
        self.assertEqual(state["mode"], "pre_attack")
        before = self.session.state()
        with self.assertRaises(ValueError):
            play("attack", card_id=atk_1, target={"kind": "duel", "number": 0})
        self.assertEqual(before, self.session.state())
        play("attack", card_id=atk_1, target={"kind": "duel", "number": 1})
        ready()
        self.assertFalse(state["frame"]["pre_reveal"]["duels"][0]["ready"])
        play("intercept", card_id=interceptor)
        ready()
        board = state["frame"]
        self.assertEqual(board["duels"][0]["sides"][second - 1]["cards"], [{"hidden": True}])
        early = board["pre_reveal"]["duels"][0]
        self.assertTrue(early["ready"])
        self.assertEqual(early["target"]["kind"], "intercept")
        self.assertIsNone(early["pulled_card_id"])
        play("attack", card_id=atk_2, target={"kind": "duel", "number": 1})
        ready()
        play("let_through")
        ready()
        play("end_attack")
        if state["mode"] in ("handoff", "pre_attack", "intercept"):
            if state["mode"] == "handoff":
                ready()
            if state["can_end_attack"]:
                play("end_attack")
        saw_pull = False
        while state["mode"] in ("combat", "timing"):
            board = state["frame"]
            if state["mode"] == "combat":
                self.assertFalse(board["cards_revealed"])
                self.assertTrue(all(p["hand"] is None for p in board["players"]))
                self.assertEqual(board["combat"]["kind"], "pre_reveal")
                if board["combat"]["duel_number"] == 2:
                    self.assertEqual(board["duels"][0]["sides"][second - 1]["cards"], [])
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

        play("new", roster=["plan_b_heck", "plan_b_annolin"])
        self.session.match._pre_reveal_claimed = {1: True, 2: True}
        # Model two attack-capable hands; the defender has exactly two cards,
        # so after counterattacking and intercepting once it must decide with an empty hand.
        for player in self.session.match.game.players:
            for card in player.characters[0].skills:
                card.data["pre_reveal"] = True
                card.data["cost"] = 1
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
