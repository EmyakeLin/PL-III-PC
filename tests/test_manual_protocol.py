import io
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout

from battle_mcp.manual import ManualDesk, _letter
from battle_mcp.room import Room, RoomConflict


class ManualProtocolTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.room = Room(("ember_wen_sheng", "plan_b_annolin"), seed=1125)
        self.addCleanup(self.room.close)
        self.desk = ManualDesk(self.room)

    @staticmethod
    def state(packet):
        return json.loads(packet["text"].rsplit("\n", 1)[1])

    def send(self, side, packet, **command):
        return self.desk.import_reply(side, json.dumps(dict(command, reply_to=packet["reply_to"])))

    def start(self):
        for side in (1, 2):
            packet = self.desk.export(side)
            self.send(side, packet, ready=True)

    def test_briefing_and_fresh_exports_share_the_same_unspent_ticket(self):
        packet = self.desk.export(1, briefing=True)
        brief = self.room.rules("briefing")
        self.assertIn(brief["version"], packet["text"])
        self.assertIn(brief["catalog"]["players"][0]["characters"][0]["skills"][0]["id"], packet["text"])
        current = self.desk.export(1)
        self.assertEqual(current["reply_to"], packet["reply_to"])
        self.assertIn(f'"reply_to":"{packet["reply_to"]}","ready":true', current["text"])
        self.assertNotIn(brief["version"], current["text"])
        self.assertEqual(_letter(26), "Z")
        self.assertEqual(_letter(27), "AA")
        self.assertEqual(_letter(52), "AZ")
        self.assertEqual(_letter(53), "BA")
        next_step = self.send(1, packet, rules="1.6")
        query = self.state(next_step)
        self.assertNotEqual(query["reply_to"], packet["reply_to"])
        self.assertIn("预留决定", next_step["text"])
        self.assertEqual(self.desk.export(1)["reply_to"], query["reply_to"])
        self.send(1, query, ready=True)
        retry = self.send(1, packet, rules="1.6")
        self.assertTrue(retry["duplicate"])
        self.assertEqual(retry["text"], next_step["text"])

    def test_only_authorized_seat_sees_choices_and_own_hidden_cards(self):
        self.start()
        initial = self.desk.export(1)
        v = self.state(initial)
        self.assertTrue(v["options"])
        move = next(m for m in v["options"] if m["kind"] == "place")
        self.assertNotIn("id", move)
        self.assertIn(move["card_id"], {c["id"] for c in v["frame"]["players"][0]["hand"]})
        self.assertNotIn("hand", v["frame"]["players"][1])
        with self.assertRaises(RoomConflict):
            self.send(2, initial, choice=move["choice"])
        self.send(1, initial, choice=move["choice"])
        opponent = self.state(self.desk.export(2))
        self.assertEqual(opponent["frame"]["duels"][0]["sides"][0]["cards"], [{"hidden": True}])
        self.assertNotIn(move["card_id"], self.desk.export(2)["text"])
        with self.assertRaises(PermissionError):
            self.desk.export(None)
        with self.assertRaises(PermissionError):
            self.desk.import_reply(None, "{}")
        self.assertEqual(self.desk.status(())["seats"], [])
        single = self.desk.status((2,))["seats"]
        self.assertEqual(len(single), 1)
        self.assertEqual(set(single[0]), {"side", "ready", "name", "has_decision", "revision"})
        self.assertNotIn(initial["reply_to"], json.dumps(self.desk.status((1, 2))))

    def test_concurrent_paste_fenced_and_raw_applies_once(self):
        self.start()
        packet = self.desk.export(1)
        choice = next(m["choice"] for m in self.state(packet)["options"] if m["kind"] == "place")
        raw = json.dumps({"reply_to": packet["reply_to"], "choice": choice})
        fenced = "我选这张牌。\r\n```json\r\n" + raw + "\r\n```\r\n完成。"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda text: self.desk.import_reply(1, text), [fenced, raw]))
        self.assertEqual(sorted(r["duplicate"] for r in results), [False, True])
        self.assertEqual(results[0]["revision"], results[1]["revision"])
        self.assertEqual(len(self.room.observe(1)["frame"]["duels"]), 1)
        with self.assertRaises(RoomConflict):
            self.send(1, packet, wait=True)

    def test_stale_cross_room_and_malformed_replies_preserve_state(self):
        a, b = self.desk.export(1), self.desk.export(2)
        self.send(1, a, ready=True)
        self.desk.export(2)
        with self.assertRaises(RoomConflict):
            self.send(2, b, ready=True)
        b = self.desk.export(2)
        raw = json.dumps({"reply_to": b["reply_to"], "ready": True})
        with self.assertRaises(RoomConflict):
            ManualDesk(self.room).import_reply(2, raw)
        bad = ["```python\nprint('hi')\n```", raw + "\n" + raw,
               "```json\n" + raw + "\n```\n```json\n" + raw + "\n```",
               raw.replace('"ready"', '"extra":0,"ready"'), raw.replace('"ready"', '"ready":false,"ready"'),
               raw.replace("true", "1"), raw.replace('"ready"', '"side":2,"ready"'), "x" * 65537,
               "```json\n" + raw, "答案\n```\n" + raw + "\n```\n" + raw]
        for text in bad:
            with self.subTest(text=text[:50]), self.assertRaises(ValueError):
                self.desk.import_reply(2, text)
        self.assertEqual(self.room.observe(2)["revision"], b["revision"])
        self.assertFalse(self.room.observe(2)["started"])
        self.send(2, b, ready=True)

    def test_private_plans_cancellation_and_wait_use_room_rules(self):
        b = self.desk.export(2)
        a = self.desk.export(1)
        self.send(1, a, prepare={"event":"roll", "mode":"reserve"})
        self.assertEqual(self.desk.export(2)["reply_to"], b["reply_to"])
        self.assertFalse(self.state(self.desk.export(2)).get("declarations"))
        a = self.desk.export(1)
        key = self.state(a)["declarations"][0]["id"]
        self.send(1, a, prepare={"cancel":key})
        self.start()
        packet = self.desk.export(1)
        state = self.state(packet)
        self.send(1, packet, wait=True)
        after = self.state(self.desk.export(1, cursor=packet["cursor"]))
        self.assertNotEqual(after["reply_to"], state["reply_to"])
        self.assertEqual(after["options"], state["options"])
        self.assertEqual(after["revision"], state["revision"])
        self.assertEqual(after["events"], [])
