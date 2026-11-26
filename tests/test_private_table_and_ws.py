"""Integration tests for unified Room, RoomRuleset, GameRule overrides, 6-char room codes, and RFC 6455 WebSocket."""

import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit

from models.card import Card
from battle_mcp.room import Room
from battle_mcp.transport import ArenaServer
from battle_mcp.ws import SimpleWebSocketClient
from tests.test_mcp_transport import WireClient


class PrivateTableAndWebSocketTests(WireClient, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ArenaServer(port=0, seed=42)
        cls.worker = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(2)

    def _ws(self, path, token=None):
        client = SimpleWebSocketClient("127.0.0.1", self.server.server_port, path)
        try:
            client.send_json({"type": "auth", "token": token})
            welcome = client.recv_json()
            self.assertEqual(welcome["type"], "welcome", welcome)
            return client, welcome
        except Exception:
            client.close()
            raise

    def test_room_code_join_claims_seat2_then_falls_back_to_spectator_and_pushes_via_websocket(self):
        status, created = self.request("/api/rooms", {"mode": "regular", "variant": "online"})
        self.assertEqual(status, 201, created)
        code = created["code"]
        self.assertEqual(len(code), 6)
        room_id = created["id"]
        host_token = parse_qs(urlsplit(created["play_url"]).fragment)["token"][0]

        # 1st joiner gets Seat 2
        s_join1, join1 = self.request("/api/rooms/join", {"code": code.lower()})
        self.assertEqual(s_join1, 200)
        self.assertEqual((join1["role"], join1["side"]), ("player", 2))
        guest_token = parse_qs(urlsplit(join1["play_url"]).fragment)["token"][0]

        # 2nd joiner with same code becomes read-only Spectator
        s_join2, join2 = self.request("/api/rooms/join", {"code": code})
        self.assertEqual(s_join2, 200)
        self.assertEqual((join2["role"], join2["side"]), ("spectator", None))

        ws_path = f"/rooms/{room_id}/ws"
        ws1, w1 = self._ws(ws_path, host_token)
        ws2, w2 = self._ws(ws_path, guest_token)
        ws_spec, w_spec = self._ws(ws_path, None)
        self.addCleanup(ws1.close)
        self.addCleanup(ws2.close)
        self.addCleanup(ws_spec.close)

        self.assertEqual(w1["side"], 1)
        self.assertEqual(w2["side"], 2)
        self.assertIsNone(w_spec["side"])
        self.assertEqual(w1["state"]["ruleset"]["pick_mode"], "blind")

        # Spectator cannot issue commands
        ws_spec.send_json({"type": "cmd", "cmd": "ready", "revision": 0, "request_id": "spec-1"})
        err_msg = ws_spec.recv_json()
        self.assertEqual(err_msg["type"], "error")
        self.assertEqual(err_msg["status"], 403)

        # Host sets 3-character Cang Feng squad (power = 3 + 2 + 2 = 7); Guest in Blind mode sees count & power, NOT IDs!
        ws1.send_json({
            "type": "cmd",
            "cmd": "update_team",
            "team": ["cang_feng_he_lian", "cang_feng_ji_lan", "cang_feng_ji_xia"],
            "revision": w1["state"]["revision"],
            "request_id": "h-team-1",
        })

        def recv_until(ws, pred, limit=8):
            for _ in range(limit):
                m = ws.recv_json()
                if pred(m):
                    return m
            self.fail("Condition not met on WebSocket stream")

        guest_push = recv_until(ws2, lambda m: m["type"] == "state" and m["state"]["lobby_state"]["pick_meta"]["1"]["count"] == 3)
        p1_meta = guest_push["state"]["lobby_state"]["pick_meta"]["1"]
        self.assertEqual(p1_meta, {"count": 3, "power": 7, "masked": True, "ready": False})
        self.assertEqual(guest_push["state"]["lobby_state"]["picks"]["1"], [])

    def test_power_scale_snake_draft_unready_concede_and_reopen_lobby_loop(self):
        room = Room(selectable=True, seed=11, room_code="TEST88")
        # Power cap = 5: Boss(3) + Elite(2) = 5 OK; Boss(3) + Boss(3) = 6 rejected
        room.update_rules(1, {"power_cap": 5, "pick_mode": "draft", "duplicate_policy": "strict_unique"}, 0, "r1")
        room.update_team(1, [], 0, "clear1")
        room.update_team(2, [], 0, "clear2")

        # Host passes first pick to Seat 2!
        room.pass_first_pick(1, 0, "pass-first")
        self.assertEqual(room.canvas_state(1)["lobby_state"]["draft_turn_side"], 2)

        # Seat 1 trying to pick out of turn in snake draft is rejected
        with self.assertRaisesRegex(ValueError, "轮到席位 2"):
            room.update_team(1, ["plan_b_annolin"], 0, "bad-turn")

        # Snake order with Seat 2 first: P2(1) -> P1(2) -> P2(2) ...
        # P2 picks Extreme character (power 5) and immediately locks (`ready`), handing remaining picks to P1!
        room.update_team(2, ["lan_qing_sp_unknown"], 0, "p2-pick-1")
        room.ready(2, 0, "p2-lock", human=True, canvas=True)
        self.assertFalse(room.started)

        # P2 unready -> allowed before match starts!
        room.unready(2, 0, "p2-unlock")
        self.assertNotIn(2, room.seated)
        room.ready(2, 0, "p2-relock", human=True, canvas=True)

        # P1 picks Boss(3) in step 1, then tries over-cap second pick Boss(3)+Boss(3)=6 > 5 -> rejected, then picks Elite(2) = 5!
        room.update_team(1, ["cang_feng_he_lian"], 0, "p1-pick-1")
        with self.assertRaisesRegex(ValueError, "超出本房间上限"):
            room.update_team(1, ["cang_feng_he_lian", "lan_qing"], 0, "p1-overcap")

        room.update_team(1, ["cang_feng_he_lian", "cang_feng_ji_lan"], 0, "p1-pick-2")
        room.ready(1, 0, "p1-lock", human=True, canvas=True)
        self.assertTrue(room.started)
        self.assertEqual([len(p.characters) for p in room.engine.game.players], [2, 1])

        # Mid-match Concede settles victory cleanly
        room.concede(2, 0, "p2-concede")
        self.assertTrue(room.engine.game_over)
        self.assertEqual(room.canvas_state(1)["frame"]["winner_side"], 1)

        # Same-room Reopen Lobby returns both players to selection table with teams preserved!
        room.reopen_lobby(2, 0, "reopen-1")
        self.assertFalse(room.started)
        self.assertEqual(room.canvas_state(1)["lobby_state"]["picks"][1], ["cang_feng_he_lian", "cang_feng_ji_lan"])

    def test_custom_gamerule_and_hp_scale_overrides_apply_without_mutating_packs(self):
        custom = {
            "draw_count": 4,
            "max_basic_cost": 9,
            "char_independent_cost": 2,
            "place_capacity": 3,
            "hp_scale_pct": 150,
            "duplicate_policy": "free_duplicates",
        }
        room = Room(
            [["plan_b_heris", "plan_b_heris"], ["plan_b_heck"]],
            seed=19,
            bot=True,
            ruleset=custom,
            start_immediately=True,
        )
        p1, p2 = room.engine.game.players
        # Heris printed max_hp is 6 -> 150% = 9; two duplicate Heris copies in P1's squad!
        self.assertEqual([c.max_hp for c in p1.characters], [9, 9])
        # Heck printed max_hp is 12 -> 150% = 18
        self.assertEqual(p2.characters[0].max_hp, 18)

        # Advance past Turn 1 draw_select for 2-character P1: Turn 1 keep = draw_count(4) + 1 = 5!
        snap = room.canvas_state(1)
        self.assertEqual(snap["frame"]["draw_select"]["keep"], 5)
        discard_n = snap["frame"]["draw_select"]["discard_count"]
        cand_ids = [c["action_key"] for c in snap["frame"]["draw_select"]["candidates"][:discard_n]]
        room.draw_bottom(1, cand_ids, snap["revision"], "db-1")

        snap = room.canvas_state(1)
        p1_frame = next(p for p in snap["frame"]["players"] if p["side"] == 1)
        self.assertEqual(len(p1_frame["hand"]), 5)
        self.assertEqual(p1_frame["cost"]["refill"], 9)
        self.assertEqual(p1_frame["cost"]["available"], 10)  # 9 base refill + 1 from Plan-B faction passive!
        self.assertEqual([c["cost"]["available"] for c in p1_frame["characters"]], [2, 2])
        self.assertEqual(room.engine.game.gamerule.PLACE_CAPACITY, 3)

        # Verify global pack data was NOT mutated
        fresh = Room(["plan_b_heris", "plan_b_heck"], seed=19, start_immediately=True)
        self.assertEqual(fresh.engine.game.players[0].characters[0].max_hp, 6)

    def test_disconnect_60s_freezes_clock_and_120s_unlocks_optional_claim_without_forced_kill(self):
        room = Room(["plan_b_annolin", "plan_b_heck"], seed=23)
        room.disconnect_warn_s = 0.06
        room.disconnect_claim_s = 0.14
        room.on_ws_connect(1)
        room.on_ws_connect(2)
        room.ready(1, 0, "r1", human=True, canvas=True)
        room.ready(2, 0, "r2", human=True, canvas=True)
        self.assertTrue(room.started)

        # Seat 2 disconnects
        room.on_ws_disconnect(2)
        time.sleep(0.08)
        st_warn = room.canvas_state(1)
        self.assertTrue(st_warn["disconnect_frozen"])
        self.assertFalse(st_warn["can_claim_disconnect_win"])
        self.assertFalse(room.engine.game_over)

        # Seat 2 stays offline past claim threshold -> game is STILL alive until Seat 1 chooses to claim!
        time.sleep(0.09)
        st_claim = room.canvas_state(1)
        self.assertFalse(room.engine.game_over, "Must never forcibly kill a friend's game at 120s!")
        self.assertTrue(st_claim["can_claim_disconnect_win"])

        room.claim_disconnect_win(1, st_claim["revision"], "claim-1")
        self.assertTrue(room.engine.game_over)
        self.assertEqual(room.canvas_state(1)["frame"]["winner_side"], 1)

    def test_solo_bot_executes_mid_duel_cut_in_place_when_slot_is_empty(self):
        room = Room(["cang_feng_ji_lan", "plan_b_heck"], seed=31, bot=True, start_immediately=True)
        human, bot = room.engine.game.players
        for slot in room.engine.game.duelspace.space:
            slot.content[1] = []
            slot.content[2] = []
        for ch in human.characters + bot.characters:
            ch.used_duels = 0

        # Human places a 3-die card in Duel 1; Bot starts Duel 1 empty-slotted holding an anytime `place` card!
        human_triple = Card(human, {
            "id": "human_triple",
            "name": "三连压制",
            "cost": 0,
            "dice": [{"type": "slash", "level": 2, "entries": []} for _ in range(3)],
        }, human.characters[0])
        human.characters[0].skills.append(human_triple)
        human.cardspace.hand.add_card(human_triple)
        room.engine.game.auto_place_in_duel(1, human_triple)

        bot.cardspace.hand.content.clear()
        bot_cutin = Card(bot, {
            "id": "bot_smart_cutin",
            "name": "机动迎击",
            "cost": 1,
            "anytime_play": ["place"],
            "dice": [{"type": "slash", "level": 4, "entries": []}],
        }, bot.characters[0])
        bot.characters[0].skills.append(bot_cutin)

        # Step through placement (give bot_cutin to Bot right after placement ends so Bot enters combat with empty slot!)
        for idx in range(20):
            snap = room.canvas_state(1)
            opts = snap["options"]
            end_move = next((m for m in opts if m["kind"] in ("end", "end_attack", "let_through")), None)
            if end_move:
                room.act(1, end_move["id"], snap["revision"], f"step-{idx}")
            elif snap["can_advance"]:
                if snap["frame"]["mode"] == "reveal" and bot_cutin not in bot.cardspace.hand.content:
                    bot.cardspace.hand.add_card(bot_cutin)
                room.next_beat(1, snap["revision"], f"next-{idx}")
            else:
                break

        # Advance into combat beats -> Bot should automatically play `bot_smart_cutin` via `special_place` into Duel 1!
        bot_cut_in_seen = False
        for idx in range(20):
            snap = room.canvas_state(1)
            duel1 = next((d for d in snap["frame"]["duels"] if d["number"] == 1), None)
            if duel1:
                b_cards = next(s for s in duel1["sides"] if s["side"] == 2)["cards"]
                if any(c.get("id") == "bot_smart_cutin" for c in b_cards):
                    bot_cut_in_seen = True
                    break
            if snap["can_advance"]:
                room.next_beat(1, snap["revision"], f"cnext-{idx}")
            else:
                break

        self.assertTrue(bot_cut_in_seen, "Solo AI Bot should cut into active Duel 1 with anytime place card!")


if __name__ == "__main__":
    unittest.main()
