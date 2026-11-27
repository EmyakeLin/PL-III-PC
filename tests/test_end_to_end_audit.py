"""Real non-mocked integration tests covering HTTP/WS transport, perspective fog of war,
kernel-to-Chronicle accounting, formula consistency, and presentation FX projection.
"""

import http.client
import io
import json
import random
import threading
import unittest
from contextlib import redirect_stdout
from urllib.parse import parse_qs, urlsplit

from battle_mcp.hosting import Lobby
from battle_mcp.transport import ArenaServer
from battle_ui.chronicle import BattleChronicle, format_die_formula
from battle_ui.match import BattleMatch
from displayer import Displayer
from game import Game
from loader import load_characters_from_packs
from models.character import Character
from models.dice import Dice, DiceLevel
from models.opcode import OpCode
from models.special_actions import SpecialAction
from pipeline.pipeline import Pipeline, SidePipeline
from player.player import Player


def _http_get(port, path, *, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("GET", path, headers=headers)
        res = conn.getresponse()
        return res.status, res.getheader("Content-Type", ""), res.read()
    finally:
        conn.close()


def _http_post(port, path, body, *, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("POST", path, json.dumps(body), headers)
        res = conn.getresponse()
        raw = res.read()
        return res.status, json.loads(raw) if raw else None
    finally:
        conn.close()


class EndToEndBackendAuditTests(unittest.TestCase):
    def test_http_assets_lineup_fx_and_battle_record_viewer_perspective(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        server = ArenaServer(None, port=0, seed=13)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            st, ctype, raw = _http_get(server.server_port, "/fx_assets/star_knot_ring.svg")
            self.assertEqual(st, 200)
            self.assertIn(b"<svg", raw)

            st_bad, _, _ = _http_get(server.server_port, "/fx_assets/../secret.svg")
            self.assertEqual(st_bad, 404)

            st_lu, _, raw_lu = _http_get(server.server_port, "/api/lineup?mode=regular&variant=solo")
            self.assertEqual(st_lu, 200)
            lu = json.loads(raw_lu)
            self.assertIn("character_fx", lu)
            self.assertIn("nova_lin_qiu", lu["character_fx"])
            self.assertIn("cang_feng_he_lian", lu["character_fx"])
            self.assertIn("character_colors", lu)

            st_cr, room = _http_post(server.server_port, "/api/rooms", {
                "mode": "regular",
                "variant": "online",
                "roster": [["nova_lin_qiu"], ["plan_b_annolin"]],
            })
            self.assertEqual(st_cr, 201)
            rid = room["id"]
            tok1 = parse_qs(urlsplit(room["play_url"]).fragment)["token"][0]
            tok2 = parse_qs(urlsplit(room["guest_url"]).fragment)["token"][0]

            # Both seats ready in online room to enter draw/placement
            _, st1 = _http_post(server.server_port, f"/rooms/{rid}/api/canvas/state", {}, token=tok1)
            _, st2 = _http_post(server.server_port, f"/rooms/{rid}/api/canvas/state", {}, token=tok2)
            _http_post(server.server_port, f"/rooms/{rid}/api/canvas/ready",
                       {"revision": st1["revision"], "request_id": "r1"}, token=tok1)
            _, st2 = _http_post(server.server_port, f"/rooms/{rid}/api/canvas/state", {}, token=tok2)
            _http_post(server.server_port, f"/rooms/{rid}/api/canvas/ready",
                       {"revision": st2["revision"], "request_id": "r2"}, token=tok2)

            # Finish any draw_select & advance until a placement window opens for seat 1 or 2
            req_n = 0
            placed_info = None
            for _ in range(60):
                acted = False
                for s_tok, seat in ((tok1, 1), (tok2, 2)):
                    st_s, cur = _http_post(server.server_port, f"/rooms/{rid}/api/canvas/state", {}, token=s_tok)
                    self.assertEqual(st_s, 200, cur)
                    ds = cur.get("frame", {}).get("draw_select")
                    if ds:
                        cands = [c["action_key"] for c in ds["candidates"][:ds["discard_count"]]]
                        req_n += 1
                        st_d, d_resp = _http_post(server.server_port, f"/rooms/{rid}/api/canvas/draw_bottom",
                                                  {"revision": cur["revision"], "request_id": f"d{req_n}", "card_ids": cands},
                                                  token=s_tok)
                        self.assertEqual(st_d, 200, d_resp)
                        acted = True
                        continue
                    place_opt = next((o for o in cur.get("options", ()) if o["kind"] == "place"), None)
                    if place_opt and cur.get("frame", {}).get("mode") == "placement":
                        req_n += 1
                        card_obj = next(
                            c for c in cur["frame"]["players"][seat - 1]["hand"]
                            if (c.get("action_key") or c["id"]) == place_opt["card_id"]
                        )
                        st_p, p_resp = _http_post(server.server_port, f"/rooms/{rid}/api/canvas/cmd", {
                            "cmd": "act",
                            "option_id": place_opt["id"],
                            "revision": cur["revision"],
                            "request_id": f"p{req_n}",
                        }, token=s_tok)
                        self.assertEqual(st_p, 200, p_resp)
                        placed_info = (seat, card_obj["name"])
                        break
                if placed_info:
                    break
                if not acted:
                    _, cur_any = _http_post(server.server_port, f"/rooms/{rid}/api/canvas/state", {}, token=tok1)
                    if cur_any.get("can_advance_beat") or cur_any.get("can_advance"):
                        req_n += 1
                        _http_post(server.server_port, f"/rooms/{rid}/api/canvas/next",
                                   {"revision": cur_any["revision"], "request_id": f"n{req_n}"}, token=tok1)

            self.assertIsNotNone(placed_info, "Failed to reach a placement window")
            owner_seat, card_name = placed_info
            owner_tok = tok1 if owner_seat == 1 else tok2
            other_tok = tok2 if owner_seat == 1 else tok1

            st_own, _, raw_own = _http_get(server.server_port, f"/rooms/{rid}/api/battle_record", token=owner_tok)
            self.assertEqual(st_own, 200)
            rec_own = json.loads(raw_own)
            self.assertIn(f"扣置「{card_name}」", rec_own["markdown"])
            self.assertFalse(rec_own["chronicle"]["unlocked_all"])

            st_opp, _, raw_opp = _http_get(server.server_port, f"/rooms/{rid}/api/battle_record", token=other_tok)
            self.assertEqual(st_opp, 200)
            rec_opp = json.loads(raw_opp)
            self.assertNotIn(f"扣置「{card_name}」", rec_opp["markdown"])
            self.assertIn("扣置了 1 张技能", rec_opp["markdown"])

            st_pub, _, raw_pub = _http_get(server.server_port, f"/rooms/{rid}/api/battle_record")
            self.assertEqual(st_pub, 200)
            rec_pub = json.loads(raw_pub)
            self.assertNotIn(f"扣置「{card_name}」", rec_pub["markdown"])
        finally:
            server.shutdown()
            server.server_close()

    def test_turn_end_recycle_format_no_dict_and_no_stray_dollar_in_markdown(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(3))
        game.deploy_rosters([[pool["plan_b_annolin"]], [pool["plan_b_heck"]]])
        chronicle = BattleChronicle(game)
        game.start_turn()
        game.context.record("duel_started", series="regular", number=1)
        game.context.record("hp_lost", target=p2.characters[0].combat_name, lost=4,
                            hp=p2.characters[0].hp - 4, maximum=p2.characters[0].max_hp)
        game.finish_turn()

        md = chronicle.to_markdown(viewer_side=1, unlock_all=True)
        self.assertNotIn("{'side':", md)
        self.assertRegex(md, r"第 \d+ 回合结束（P1 回收 \d+ 张、P2 回收 \d+ 张）。")
        self.assertNotIn("$", md)

    def test_direct_damage_with_after_apply_damage_trigger_single_counts_and_keeps_shields(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(5))
        game.deploy_rosters([[pool["plan_b_annolin"]], [pool["plan_b_heck"]]])
        chronicle = BattleChronicle(game)
        game.start_turn()
        atk = p1.characters[0]
        dfd = p2.characters[0]
        dfd.add_shield("normal", 3)
        dfd.add_shield("reinforced", 2)
        chronicle.flush()

        # Simulate an `AFTER APPLY_DAMAGE` entry (e.g. `偏转力场` status gain) firing BEFORE `direct_damage` record!
        game.context.register_entries(dfd, [{
            "trigger": "AFTER APPLY_DAMAGE",
            "operation": {"op": "program", "code": ["$self", "守护", 1, "STATUS"]},
        }])
        game.context.record("duel_started", series="regular", number=1)
        with game.context.binding(source=atk, target=dfd, side=1, card=atk.skills[0],
                                  modifiers=[], incoming_modifiers=[], damage_precomputed=True,
                                  damage_die=None):
            game.context.eval_block([dfd, 8, "normal", "effect", OpCode.DAMAGE])

        snap = chronicle.snapshot(viewer_side=1, unlock_all=True)
        t1 = snap["turns"][0]
        self.assertEqual(t1["stats"]["damage_by_side"]["1"], 3)
        duel = next(b for b in t1["blocks"] if b["kind"] == "duel")
        self.assertEqual(duel["summary"]["hp_delta"]["2"], -3)
        damage_items = [it for rnd in duel["rounds"] for it in rnd["items"] if it["category"] == "damage"]
        self.assertEqual(len(damage_items), 1)
        self.assertIn("强化盾抵消2 / 普通盾抵消3", damage_items[0]["formula"])

    def test_hidden_card_replaced_before_reveal_stays_secret_after_cards_revealed(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(7))
        game.deploy_rosters([[pool["nova_lin_qiu"]], [pool["lan_qing"]]])
        chronicle = BattleChronicle(game)
        game.first_player = p1
        game.start_turn()
        game.run_placement()
        p1.draw_card(3)
        card_a, card_b = p1.cardspace.hand.content[0], p1.cardspace.hand.content[1]
        self.assertNotEqual(card_a.id, card_b.id)

        self.assertTrue(game.place_in_duel(1, card_a, 0))
        chronicle.record_action(
            "place",
            side=1,
            actor_id=card_a.character.id,
            actor_name=card_a.character.name,
            card_id=card_a.id,
            card_name=card_a.name,
            cost=card_a.cost,
            duel_number=1,
            face_up=False,
            instance_id=card_a.instance_id,
        )
        card_b.data["anytime_replace"] = True
        act = SpecialAction("replace", card_b, target_card=card_a)
        self.assertTrue(game.special.apply(p1, act))

        # Before reveal: P2 sees neither A nor B
        pre_p2 = chronicle.to_markdown(viewer_side=2)
        self.assertNotIn(card_a.name, pre_p2)
        self.assertNotIn(card_b.name, pre_p2)

        # Reveal: P2 sees B (now on board), MUST NOT see withdrawn A in text or entities!
        game.reveal_cards()
        post_p2 = chronicle.to_markdown(viewer_side=2)
        self.assertIn(card_b.name, post_p2)
        self.assertNotIn(card_a.name, post_p2)
        post_entities = [
            e for b in chronicle.snapshot(viewer_side=2)["turns"][0]["blocks"]
            for r in b["rounds"] for it in r["items"] for e in it["entities"]
        ]
        self.assertFalse(any(e.get("name") == card_a.name for e in post_entities))
        self.assertTrue(any(e.get("name") == card_b.name for e in post_entities))

        # Game over: full unlock exposes A as well
        post_full = chronicle.to_markdown(viewer_side=2, unlock_all=True)
        self.assertIn(card_a.name, post_full)

    def test_standalone_character_facts_no_duplicate_with_opcode_and_missing_facts(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        pool = {c["id"]: c for c in load_characters_from_packs()}
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(9))
        game.deploy_rosters([[pool["plan_b_annolin"]], [pool["plan_b_heck"]]])
        chronicle = BattleChronicle(game)
        game.start_turn()
        actor = p1.characters[0]

        # Opcode operations should produce 1 entry each (not doubled by character.py balance facts)
        game.context.eval_block([actor, 3, OpCode.LOSE_HP])
        game.context.eval_block([actor, 2, OpCode.HEAL])
        game.context.eval_block([actor, "normal", 4, OpCode.SHIELD])
        game.context.eval_block([actor, "烧伤", 3, OpCode.STATUS])
        items_after_opcodes = [it["text"] for b in chronicle.snapshot(1)["turns"][0]["blocks"]
                               for r in b["rounds"] for it in r["items"]]
        self.assertEqual(sum("失去 3 点生命" in t for t in items_after_opcodes), 1)
        self.assertEqual(sum("恢复 2 点生命" in t for t in items_after_opcodes), 1)
        self.assertEqual(sum("普通盾 → 4" in t for t in items_after_opcodes), 1)
        self.assertEqual(sum("烧伤 +3 → 3" in t for t in items_after_opcodes), 1)

        # Direct kernel mutations (outside opcodes) must STILL log once!
        actor.lose_hp(1)
        actor.heal(1)
        actor.add_shield("normal", 2)
        actor.clear_status("烧伤")
        items_after_direct = [it["text"] for b in chronicle.snapshot(1)["turns"][0]["blocks"]
                              for r in b["rounds"] for it in r["items"]]
        self.assertEqual(sum("失去 1 点生命" in t for t in items_after_direct), 1)
        self.assertEqual(sum("恢复 1 点生命" in t for t in items_after_direct), 1)
        self.assertEqual(sum("普通盾 4 → 6" in t for t in items_after_direct), 1)
        self.assertEqual(sum("清空 3 层 烧伤" in t for t in items_after_direct), 1)

        # Missing facts & crash-prone attack_declared(duel_index=None)
        card = actor.skills[0]
        with game.context.binding(source=actor, side=1, card=card):
            p1.common_cost = 5
            actor.independent_cost = 1
            game.context.pay_skill_cost(card)
        game.context.record("attack_declared", series="pre_reveal", number=1, player=p1.name,
                            card=card.name, target=p2.characters[0].name, duel_index=None)
        game.context.record("unopposed_clash_lose", actor=actor.combat_name)
        game.context.record("rear_card_invalidated", side=1, card=card.name, card_id=card.id)
        game.context.record("hand_card_taken", receiver=actor.combat_name, from_side=2)
        game.context.record("card_face_changed", card=card.name, face="up")
        game.context.record("placement_lock", card=card.name, locked=True)
        game.context.record("ability_changed", target=actor.combat_name, name="充能", total=2)
        game.context.record("ability_spent", target=actor.combat_name, name="充能", amount=1, total=1)

        all_txt = "\n".join(
            it["text"] for b in chronicle.snapshot(1, unlock_all=True)["turns"][0]["blocks"]
            for r in b["rounds"] for it in r["items"]
        )
        self.assertIn("费用支付：", all_txt)
        self.assertIn("判定拼点落败", all_txt)
        self.assertIn("后置技能", all_txt)
        self.assertIn("接过一张技能牌", all_txt)
        self.assertIn("翻正", all_txt)
        self.assertIn("锁定位置", all_txt)
        self.assertIn("使用 1 次充能 → 剩余 1 次", all_txt)

    def test_custom_die_formula_with_multiplier_and_resolve_final_score_effect(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        p1, p2 = Player(1, "甲"), Player(2, "乙")
        game = Game([p1, p2], rng=random.Random(17))
        c1_def = {"id": "test_a", "name": "甲", "rank": "NORMAL", "max_hp": 12,
                  "skills": [{"id": "s1", "name": "斩击", "cost": 1, "dice": []}]}
        c2_def = {"id": "test_b", "name": "乙", "rank": "NORMAL", "max_hp": 12,
                  "skills": [{"id": "s2", "name": "格挡", "cost": 1, "dice": []}]}
        game.deploy_rosters([[c1_def], [c2_def]])
        game.start_turn()
        actor = p1.characters[0]
        card = actor.skills[0]
        die = Dice({"type": "slash", "level": int(DiceLevel.D6.value),
                    "base_value": 2, "multiplier": 3, "calc_formula": "b + v * m"}, game=game)
        die.card = card
        die.value = 4  # raw calc = 2 + 4 * 3 = 14
        game.context.register_entries(actor, [{
            "trigger": "BEFORE RESOLVE_FINAL_SCORE",
            "operation": {"op": "program", "code": [2, "ADD"]},
        }])
        final_val = die.resolve_value(OpCode.RESOLVE_FINAL_SCORE, die.calculate_final_score())
        self.assertEqual(final_val, 16)

        pipe = SidePipeline(1, game, lane="front")
        pipe.card = card
        pipe.die = die
        detail = Pipeline._die_roll_detail(pipe, result="win")
        self.assertEqual(detail["final_effect_bonus"], 2)
        expr, _ = format_die_formula(detail)
        self.assertIn("公式[b + v * m]", expr)
        self.assertIn("效果修正+2", expr)
        self.assertIn("= 最终16", expr)

    def test_hp_scale_lightcore_initial_max_and_special_fx_payload(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        match = BattleMatch(
            ["nova_lin_qiu", "lan_qing"],
            seed=21,
            ruleset={
                "power_cap": None, "max_chars": None, "duplicate_policy": "team_unique",
                "pick_mode": "open", "draft_first_side": 1, "draw_count": 2,
                "max_basic_cost": 5, "char_independent_cost": 1, "place_capacity": 2,
                "hp_scale_pct": 50, "pause_limit_s": None, "hotseat_curtain": True,
            },
        )
        snap = match.snapshot()
        for pl in snap["frame"]["players"]:
            for ch in pl["characters"]:
                self.assertEqual(ch["initial_max_lightcore_hp"], ch["max_lightcore_hp"])
                self.assertEqual(ch["lightcore_hp"], ch["initial_max_lightcore_hp"])

        # Verify TableBridge includes active_form on cost_pay when card has forms
        p1 = match.game.players[0]
        p2 = match.game.players[1]
        lan_char = p2.characters[0]
        form_card = next(c for c in lan_char.skills if c.printed_data.get("forms"))
        first_form_key = next(iter(form_card.printed_data["forms"]))
        form_card.set_form(first_form_key)
        p2.common_cost = 10
        with match.game.context.binding(source=lan_char, side=2, card=form_card):
            match.game.context.pay_skill_cost(form_card)
        ev = next(e for e in reversed(match.presentation.events) if e["kind"] == "cost_pay")
        self.assertEqual(ev["active_form"], first_form_key)


if __name__ == "__main__":
    unittest.main()
