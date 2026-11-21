import io
import unittest
from contextlib import redirect_stdout
from itertools import count

from battle_mcp.decision_view import decision_view
from battle_mcp.room import Room


class MirrorRoomCardsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.room = Room(("blank_boss", "blank_boss"), seed=8)
        self.addCleanup(self.room.close)
        self.serial = count()
        for side in (1, 2):
            self.room.ready(side, self.room.observe(side)["revision"], str(next(self.serial)))

        # In this shuffle, seat 2 steals seat 1's Pin with an unopposed Read.
        self.play(2, "end")
        self.play(1, "end")
        self.play(2, "attack", card_id="blank_read", character_id="blank_boss")
        self.play(1, "let_through")
        self.play(2, "end_attack")
        self.play(1, "end_attack")
        self.play(1, "place", card_id="blank_sequence")
        view = self.room.observe(2)
        pins = [c for c in view["frame"]["players"][1]["hand"] if c["id"] == "blank_pin"]
        self.assertEqual(len(pins), 2)
        self.own, self.stolen = sorted(pins, key=lambda c: c["borrowed"])
        self.assertEqual((self.own["borrowed"], self.stolen["borrowed"]), (False, True))
        self.assertNotEqual(self.own["action_key"], self.stolen["action_key"])

    def play(self, side, kind, **fields):
        view = self.room.observe(side)
        move = next(m for m in view["options"] if m["kind"] == kind
                    and all(m.get(key) == value for key, value in fields.items()))
        return self.room.act(side, move["id"], view["revision"], str(next(self.serial)))

    def open_pre_reveal(self):
        self.play(2, "place", card_id="blank_guard")
        self.play(2, "place", card_id="blank_bloom")
        self.play(1, "end")
        self.play(2, "end")
        self.play(1, "attack", card_id="blank_read", character_id="blank_boss")
        self.play(1, "end_attack")

    def test_reconnected_seat_places_the_selected_physical_card_face_down(self):
        view = self.room.observe(2)
        keys = {c["action_key"] for c in (self.own, self.stolen)}
        places = [m for m in view["options"] if m.get("card_id") in keys and m["kind"] == "place"]
        self.assertEqual(len({m["id"] for m in places}), 2)
        self.assertEqual(self.room.observe(2, view["cursor"])["options"], view["options"])
        compact = decision_view(view)["frame"]["players"]
        self.assertNotIn("hand", compact[0])
        self.assertEqual({c["action_key"] for c in compact[1]["hand"] if c["id"] == "blank_pin"}, keys)
        placed = self.play(2, "place", card_id=self.stolen["action_key"])
        slot = placed["frame"]["duels"][0]["sides"][1]["cards"]
        self.assertEqual(slot[0]["instance_id"], self.stolen["instance_id"])
        remaining = [c for c in placed["frame"]["players"][1]["hand"] if c["id"] == "blank_pin"]
        self.assertEqual([(c["instance_id"], c["action_key"]) for c in remaining],
                         [(self.own["instance_id"], "blank_pin")])
        for side in (1, None):
            frame = self.room.observe(side)["frame"]
            self.assertIsNone(frame["players"][1]["hand"])
            self.assertEqual(frame["duels"][0]["sides"][1]["cards"], [{"hidden": True}])

    def test_each_pin_can_only_target_the_occupied_enemy_slot(self):
        self.open_pre_reveal()
        keys = {self.own["action_key"], self.stolen["action_key"]}
        frame = self.room.observe(2)
        self.assertEqual(len(frame["frame"]["duels"]), 2)
        shots = [m for m in frame["options"] if m["kind"] == "attack" and m.get("card_id") in keys]
        self.assertCountEqual([(m["card_id"], m.get("duel_number"), m.get("character_id")) for m in shots],
                              [(key, 1, None) for key in keys])
        committed = self.play(2, "attack", card_id=self.stolen["action_key"], duel_number=1)
        slot = committed["frame"]["pre_reveal"]["duels"][1]
        self.assertTrue(slot["ready"])
        self.assertFalse(slot["interceptable"])
        self.assertEqual(slot["target"], {"kind": "duel", "number": 1})
        self.assertEqual(slot["sides"][1]["cards"][0]["instance_id"], self.stolen["instance_id"])
        self.assertEqual(self.room.observe(None)["event"]["card_id"], "blank_pin")

    def test_interception_uses_the_selected_copy(self):
        self.open_pre_reveal()
        wanted = {self.own["action_key"], self.stolen["action_key"]}
        replies = [m for m in self.room.observe(2)["options"] if m["kind"] == "intercept"
                   and m["response_number"] == 1 and m["card_id"] in wanted]
        self.assertEqual({m["card_id"] for m in replies}, wanted)
        committed = self.play(2, "intercept", card_id=self.stolen["action_key"], response_number=1)
        slot = committed["frame"]["pre_reveal"]["duels"][0]
        self.assertEqual(slot["sides"][1]["cards"][0]["instance_id"], self.stolen["instance_id"])
        self.assertEqual(self.room.observe(None)["event"]["card_id"], "blank_pin")
