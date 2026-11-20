import io
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from threading import Thread

from battle_mcp.room import Room, RoomConflict


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.serial = 0

    def create(self, left="ember_wen_sheng", seed=1125):
        self.room = Room((left, "plan_b_annolin"), seed)
        self.addCleanup(self.room.close)

    def command(self, side, name, **args):
        self.serial += 1
        return getattr(self.room, name)(side, revision=self.room.observe(side)["revision"],
                                        request_id=str(self.serial), **args)

    def prepare(self, side, event, mode="reserve", match=None, **when):
        return self.command(side, "prepare", declaration=dict(event=event, mode=mode, when=when, match=match or {}))

    def start(self):
        self.command(1, "ready")
        self.command(2, "ready")

    def act(self, side, kind, **match):
        options = self.room.observe(side)["options"]
        move = next(m for m in options if m["kind"] == kind and all(m.get(k) == v for k,v in match.items()))
        return self.command(side, "act", option_id=move["id"])

    def arrange(self, left_skill, right_skill):
        self.act(1, "place", card_id=left_skill)
        self.act(2, "place", card_id=right_skill)
        self.act(2, "end")
        self.act(1, "end")

    def test_pregame_reading_quotes_the_rulebook_and_public_printed_cards(self):
        self.create()
        full = self.room.rules("full")
        book = (Path(__file__).resolve().parents[1] / full["source"]).read_text(encoding="utf-8")
        self.assertEqual(full["text"], book)
        self.assertIn(f'**{full["version"]}**', book)
        brief = self.room.rules("briefing")
        self.assertEqual(brief["version"], full["version"])
        self.assertEqual(brief["catalog"], self.room.rules("catalog")["catalog"])
        self.assertEqual([p["characters"][0]["name"] for p in brief["catalog"]["players"]], ["闻笙", "安诺琳"])
        self.assertIn("无法消耗充能", brief["catalog"]["statuses"]["能源封印"][0])
        self.assertIn("换卡机会", brief["catalog"]["players"][0]["characters"][0]["passives"][0]["entries"][0])
        ids = {s["id"] for s in brief["sections"]}
        self.assertTrue({"1.1", "1.6", "2.1", "2.4", "2.5", "3.3", "4.6", "6.1", "7.3"} <= ids)
        for article in brief["sections"]:
            chapter = self.room.rules(article["id"])
            self.assertEqual(article["title"], chapter["title"])
            for paragraph in article["text"].split("\n\n"):
                self.assertIn(paragraph, chapter["text"])
        self.assertTrue(ids <= {s["id"] for s in self.room.rules()["topics"]})
        self.assertEqual(self.room.observe(1)["revision"], 0)
        self.start()
        self.act(1, "place", card_id="wen_sheng_duet")
        self.assertEqual(self.room.rules("briefing"), brief)
        self.assertNotIn("catalog", self.room.observe(2))

    def test_only_prior_declarations_authorize_optional_moves(self):
        self.create()
        self.prepare(1, "scores_ready", match={"kind":"special_replace", "card_id":"wen_sheng_understudy"},
                     turn=1, duel_kind="regular", duel_number=1, die_number=1)
        self.assertEqual(self.room.observe(2)["revision"], 0)
        self.assertEqual(self.room.observe(None)["declarations"], [])
        self.command(1, "ready")
        self.assertEqual(self.room.observe(1)["frame"]["turn"], 0)
        self.assertFalse(self.room.observe(1)["options"])
        self.command(2, "ready")
        self.assertTrue(self.room.observe(1)["options"])
        self.assertFalse(any(m["kind"].startswith("special_") for m in self.room.observe(1)["options"]))
        self.arrange("wen_sheng_duet", "annolin_drifting_sword")
        v = self.room.observe(1)
        self.assertEqual(v["event"]["kind"], "scores_ready")
        self.assertEqual(len(v["event"]["scores"]), 2)
        self.assertTrue(v["options"])
        self.assertEqual({m["kind"] for m in v["options"]}, {"special_replace", "decline"})
        self.assertFalse(self.room.observe(2)["options"])
        self.prepare(2, "scores_ready")
        self.assertFalse(self.room.observe(2)["options"])  # no late registration for this roll
        with self.assertRaises(ValueError):
            self.command(2, "act", option_id=v["options"][0]["id"])
        with self.assertRaises(PermissionError):
            self.room.act(None, "decline", 0, "test")
        self.act(1, "special_replace", target_card_id="wen_sheng_duet")
        events = self.room.observe(None, 0)["events"]
        self.assertTrue(any("空白轮" in e["text"] for e in events))

    def test_execute_at_second_seats_new_placement_window(self):
        self.create()
        self.prepare(2, "placement", "execute", {"kind":"place", "card_id":"annolin_drifting_sword"})
        self.start()
        self.act(1, "place", card_id="wen_sheng_duet")
        frame = self.room.observe(2)["frame"]
        self.assertEqual(frame["duels"][0]["sides"][1]["cards"][0]["id"], "annolin_drifting_sword")
        self.assertEqual(self.room.observe(1)["frame"]["duels"][0]["sides"][1]["cards"], [{"hidden":True}])
        self.assertEqual(self.room.observe(2)["declarations"], [])

    def test_parallel_attack_response_timer_and_wait_do_not_pass(self):
        self.create("mistport_cen_yao", 37)
        self.prepare(1, "timer", pending_number=1, after_ms=50)
        self.start()
        self.arrange("cen_yao_fold_rule", self.room.observe(2)["frame"]["players"][1]["hand"][0]["id"])
        self.act(1, "attack", card_id="cen_yao_sounding", duel_number=1)
        view = self.act(1, "attack", card_id="cen_yao_transit", duel_number=1)
        self.act(2, "intercept", response_number=2)
        deadline = time.monotonic() + 2
        while not any(m["kind"] == "decline" for m in view["options"]):
            self.assertLess(time.monotonic(), deadline)
            update = self.room.wait(1, view["cursor"], .1)
            view = self.room.observe(1) if update.get("timeout") else update
        self.assertEqual([d["ready"] for d in view["frame"]["pre_reveal"]["duels"]], [False, True])
        self.act(1, "decline")
        self.act(1, "end_attack")
        last = self.room.observe(2)
        self.assertTrue(self.room.wait(2, last["cursor"], 0)["timeout"])
        self.assertTrue(any(m["kind"] == "let_through" and m["response_number"] == 1 for m in last["options"]))
        self.act(2, "let_through", response_number=1)

    def test_duplicate_request_is_idempotent_and_stale_action_cannot_commit(self):
        self.create()
        self.start()
        view = self.room.observe(1)
        choice = next(m for m in view["options"] if m["kind"] == "place")
        args = (1, choice["id"], view["revision"], "one move")
        errors = []
        def submit():
            try:
                self.room.act(*args)
            except Exception as exc:
                errors.append(exc)
        workers = [Thread(target=submit) for _ in range(2)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.room.observe(1)["frame"]["duels"]), 1)
        with self.assertRaises(RoomConflict):
            self.room.act(1, choice["id"], view["revision"], "another")
        with self.assertRaises(RoomConflict):
            self.room.act(1, "decline", view["revision"], "one move")

    def test_registered_timer_expires_when_target_is_answered(self):
        self.create("mistport_cen_yao", 37)
        self.prepare(1, "timer", pending_number=1, after_ms=60000)
        self.start()
        self.arrange("cen_yao_fold_rule", self.room.observe(2)["frame"]["players"][1]["hand"][0]["id"])
        self.act(1, "attack", card_id="cen_yao_sounding", duel_number=1)
        before = self.room.observe(1)
        self.act(2, "let_through", response_number=1)
        frame = self.room.wait(1, before["cursor"], 0)
        self.assertFalse(frame["declarations"])
        self.assertTrue(any(e["kind"] == "expired" for e in frame["events"]))
        self.assertFalse(any(e["kind"] == "expired" for e in self.room.observe(None, 0)["events"]))

    def test_new_response_number_can_fire_an_earlier_exact_intercept_order(self):
        self.create("mistport_cen_yao", 37)
        self.prepare(2, "pre_reveal", "execute", {"kind":"let_through", "response_number":2})
        self.start()
        self.arrange("cen_yao_fold_rule", self.room.observe(2)["frame"]["players"][1]["hand"][0]["id"])
        self.act(1, "attack", card_id="cen_yao_sounding", duel_number=1)
        self.act(1, "attack", card_id="cen_yao_transit", duel_number=1)
        view = self.room.observe(2)
        self.assertEqual([d["ready"] for d in view["frame"]["pre_reveal"]["duels"]], [False, True])
        self.assertEqual(view["declarations"], [])

    def test_score_guard_reads_settled_scores_and_runs_without_new_choice(self):
        self.create()
        self.prepare(1, "scores_ready", "execute", {"kind":"special_replace", "card_id":"wen_sheng_understudy",
                     "target_card_id":"wen_sheng_duet"}, score="lt", duel_number=1, die_number=1)
        self.start()
        self.arrange("wen_sheng_duet", "annolin_drifting_sword")
        journal = self.room.observe(None, 0)["events"]
        swaps = [i for i, e in enumerate(journal) if "替换技能" in e["text"]]
        self.assertEqual(len(swaps), 1)
        self.assertEqual(journal[swaps[0]-1]["kind"], "scores_ready")
        self.assertTrue(any("空白轮" in e["text"] for e in journal[swaps[0]:]))
