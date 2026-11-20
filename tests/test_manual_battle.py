"""Play through the same exported text and pasted reply available to a human operator."""

import io
import json
import threading
import unittest
from contextlib import contextmanager, redirect_stdout

from battle_mcp.room import Room
from battle_mcp.transport import ArenaServer
from tests.test_mcp_transport import WireClient


class ManualBattleTests(WireClient, unittest.TestCase):
    @contextmanager
    def table(self, left="ember_wen_sheng", seed=1125):
        room = Room((left, "plan_b_annolin"), seed)
        with redirect_stdout(io.StringIO()), ArenaServer(room, port=0) as self.server:
            worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
            worker.start()
            self.serial = 0
            try:
                yield
            finally:
                self.server.shutdown()
                worker.join(2)

    def desk(self, command, data, *, seat=None, expected=200):
        # An operator may relay both conversations. A seat invitation can relay only that seat.
        headers = {} if seat else {"Authorization": "Bearer " + self.server.desk_token}
        status, result = self.request("/api/desk/" + command, data, side=seat, **headers)
        self.assertEqual(status, expected, result)
        return result

    def export(self, side, kind="turn", *, seat=None):
        result = self.desk("export", {"side": side, "kind": kind}, seat=seat)
        position = json.loads(result["text"].rsplit("\n", 1)[-1])
        self.assertEqual(position["reply_to"], result["reply_to"])
        self.assertEqual(position["side"], side)
        return position, result["text"]

    def paste(self, position, *, seat=None, expected=200, **action):
        payload = json.dumps({"reply_to": position["reply_to"], **action}, ensure_ascii=False)
        answer = f"我的决定如下。\n\n```json\n{payload}\n```"
        return self.desk("submit", {"side": position["side"], "reply": answer}, seat=seat, expected=expected)

    def pick(self, side, kind, **required):
        position, _ = self.export(side)
        move = next(m for m in position["options"] if m["kind"] == kind
                    and all(m.get(k) == v for k, v in required.items()))
        return self.paste(position, choice=move["choice"])

    def ordinary(self, side, command, **args):
        status, view = self.request("/api/observe", {}, side=side)
        self.assertEqual(status, 200)
        self.serial += 1
        status, result = self.request("/api/" + command,
                                      {"revision": view["revision"], "request_id": str(self.serial), **args}, side=side)
        self.assertEqual(status, 200, result)
        return result

    def play_to_victory(self, human_side):
        for side in (1, 2):
            if side == human_side:
                self.ordinary(side, "ready")
            else:
                seat = side if human_side else None
                initial, lesson = self.export(side, "intro", seat=seat)
                self.assertIn("闻笙", lesson)
                self.assertIn("安诺琳", lesson)
                self.assertIn("拼点", lesson)
                result = self.paste(initial, seat=seat, ready=True)
                self.assertFalse(result["duplicate"])
                self.assertTrue(self.paste(initial, seat=seat, ready=True)["duplicate"])
        counts = {1: 0, 2: 0}
        for _ in range(120):
            status = self.desk("status", {})
            if status["finished"]:
                self.assertTrue(all(counts.values()))
                return status["winner_side"], counts
            for entry in status["seats"]:
                if not entry["has_decision"]:
                    continue
                side = entry["side"]
                if side == human_side:
                    _, view = self.request("/api/observe", {}, side=side)
                    self.ordinary(side, "act", option_id=view["options"][0]["id"])
                else:
                    seat = side if human_side else None
                    position, _ = self.export(side, seat=seat)
                    self.paste(position, choice=position["options"][0]["choice"], seat=seat)
                counts[side] += 1
                break
            else:
                self.fail("双方均已准备，战场仍未结束，却没有下一项决定。")
        self.fail("在 120 次决定内没有打到终局。")

    def test_paste_against_browser_and_paste_against_paste(self):
        with self.table():
            mixed = self.play_to_victory(human_side=1)
        with self.table():
            relayed = self.play_to_victory(human_side=None)
        self.assertEqual(mixed, relayed)
        self.assertIn(mixed[0], (1, 2))

    def test_fixed_seat_and_reserved_roll_before_replacement(self):
        with self.table():
            self.assertEqual(self.request("/api/desk/status", {})[0], 403)
            self.desk("export", {"side": 2, "kind": "turn"}, seat=1, expected=403)
            only_own = self.desk("status", {}, seat=2)
            self.assertEqual([s["side"] for s in only_own["seats"]], [2])
            initial, _ = self.export(1, "intro", seat=1)
            plan = {"event": "scores_ready", "mode": "reserve",
                    "when": {"turn": 1, "duel_kind": "regular", "duel_number": 1, "die_number": 1},
                    "match": {"kind": "special_replace", "card_id": "wen_sheng_understudy"}}
            self.paste(initial, seat=1, prepare=plan)
            self.paste(self.export(1, seat=1)[0], seat=1, ready=True)
            self.ordinary(2, "ready")
            self.pick(1, "place", card_id="wen_sheng_duet")
            enemy, _ = self.export(2, seat=2)
            self.assertFalse(enemy["frame"]["players"][0].get("hand"))
            self.assertEqual(enemy["frame"]["duels"][0]["sides"][0]["cards"], [{"hidden": True}])
            self.assertFalse(enemy.get("declarations"))
            self.pick(2, "place", card_id="annolin_drifting_sword")
            self.pick(2, "end")
            self.pick(1, "end")
            decision, _ = self.export(1, seat=1)
            self.assertEqual(decision["event"]["kind"], "scores_ready")
            self.assertEqual(len(decision["event"]["scores"]), 2)
            swap = next(m for m in decision["options"] if m["kind"] == "special_replace"
                        and m["target_card_id"] == "wen_sheng_duet")
            self.paste(decision, seat=2, choice=swap["choice"], expected=403)
            self.paste(decision, seat=1, choice=swap["choice"])
            self.assertTrue(self.paste(decision, seat=1, choice=swap["choice"])["duplicate"])
            _, public = self.request("/api/observe", {"cursor": 0})
            blanks = [e for e in public["events"] if "空白轮" in e["text"]]
            self.assertEqual(len(blanks), 1)

    def test_stale_defence_reply_leaves_both_numbers_open(self):
        with self.table("mistport_cen_yao", 37):
            for side in (1, 2):
                self.paste(self.export(side, "intro")[0], ready=True)
            self.pick(1, "place", card_id="cen_yao_fold_rule")
            self.pick(2, "place")
            self.pick(2, "end")
            self.pick(1, "end")
            self.pick(1, "attack", card_id="cen_yao_sounding", duel_number=1)
            self.assertEqual({s["side"] for s in self.desk("status", {})["seats"] if s["has_decision"]}, {1, 2})
            old, _ = self.export(2)
            first = next(m for m in old["options"] if m["kind"] == "let_through" and m["response_number"] == 1)
            self.pick(1, "attack", card_id="cen_yao_transit", duel_number=1)
            self.paste(old, choice=first["choice"], expected=409)
            fresh, _ = self.export(2)
            self.assertEqual([d["ready"] for d in fresh["frame"]["pre_reveal"]["duels"]], [False, False])
            self.pick(2, "intercept", response_number=2)
            again, _ = self.export(2)
            self.assertEqual([d["ready"] for d in again["frame"]["pre_reveal"]["duels"]], [False, True])
