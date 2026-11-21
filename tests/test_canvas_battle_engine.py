"""Verification for pure-WebGL battle engine backend features and zero-DOM shell."""

import io
import re
import unittest
from contextlib import redirect_stdout
from http import HTTPStatus
from pathlib import Path

from battle_ui.__main__ import BattleSession, STATIC_DIR, _resolve_static


class CanvasBattleEngineTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))

    def test_zero_dom_controls_in_index_html_and_vendor_bundles_present(self):
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        body_match = re.search(r"<body[^>]*>(.*?)</body>", html, flags=re.S | re.I)
        self.assertIsNotNone(body_match)
        body = body_match.group(1)
        # Body must ONLY contain canvas elements — zero buttons, divs, headers, forms, or SVG UI.
        tags = re.findall(r"<\s*([a-zA-Z0-9]+)\b", body)
        self.assertTrue(tags, "Body must mount WebGL canvas elements.")
        self.assertTrue(all(tag.lower() == "canvas" for tag in tags), f"Forbidden DOM tags in body: {tags}")

        for asset in (
            "/",
            "/style.css",
            "/app.js",
            "/engine/transport.js",
            "/engine/audio.js",
            "/engine/physics.js",
            "/engine/three_world.js",
            "/engine/design_system.js",
            "/engine/card_print.js",
            "/engine/stage_actors.js",
            "/engine/table_overlays.js",
            "/engine/game_director.js",
            "/vendor/matter.min.js",
            "/vendor/three.module.js",
            "/vendor/three.core.js",
            "/vendor/pixi.min.mjs",
        ):
            resolved = _resolve_static(asset)
            self.assertIsNotNone(resolved, f"Missing static asset {asset}")
            self.assertTrue(Path(resolved[0]).is_file())
        self.assertIsNone(_resolve_static("/../match.py"))

    def test_bright_palette_contains_no_black_or_blue_purple_colors(self):
        files = [
            STATIC_DIR / "style.css",
            STATIC_DIR / "app.js",
            *(STATIC_DIR / "engine").glob("*.js"),
        ]
        hex_pattern = re.compile(r"(?:0x|#)([0-9a-fA-F]{6})\b")
        for path in files:
            text = path.read_text(encoding="utf-8")
            for match in hex_pattern.finditer(text):
                code = match.group(1)
                r, g, b = int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16)
                # Exclude non-color bitmasks like 0x0001 (4 hex digits already ignored)
                self.assertGreaterEqual(max(r, g, b), 40, f"Forbidden black/near-black color {match.group(0)} in {path.name}")
                self.assertFalse(
                    b > r + 15 and b > g + 15,
                    f"Forbidden blue/purple color {match.group(0)} (r={r},g={g},b={b}) in {path.name}",
                )

    def test_no_paraphrasing_die_level_labels_or_filler_text(self):
        for name in ("design_system.js", "card_print.js", "stage_actors.js", "table_overlays.js", "game_director.js", "three_world.js"):
            raw = (STATIC_DIR / "engine" / name).read_text(encoding="utf-8")
            code = re.sub(r"/\*.*?\*/|//[^\n]*", "", raw, flags=re.S)
            for forbidden in ("Lv.", "无附加词条", "compactDieBadges", "compactSkillTag", "拖入扣置或双击", "被动 (", "placeLeft"):
                self.assertNotIn(forbidden, code, f"Forbidden text {forbidden!r} found in {name}")

    def test_multi_character_roster_draw_peek_bottom_and_speed_rolls(self):
        session = BattleSession(seed=37)
        s = session.state()
        status, s = session.command({
            "action": "new",
            "revision": s["revision"],
            "roster": [["plan_b_annolin", "waa_lake"], ["mistport_cen_yao", "ember_wen_sheng"]],
        })
        self.assertEqual(status, HTTPStatus.OK)
        # Advance past any before_turn_start timing pause (since Wen Sheng has anytime cards)
        while s["mode"] == "timing":
            status, s = session.command({"action": "next", "revision": s["revision"]})
            self.assertEqual(status, HTTPStatus.OK)
        # Handoff for Player 1's 2-character draw peek & bottom (look 4, bottom 1, keep 3)
        self.assertEqual(s["mode"], "handoff")
        self.assertIsNone(s["draw_select"])
        status, s = session.command({"action": "ready", "revision": s["revision"], "side": 1})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(s["mode"], "draw_select")
        prompt1 = s["draw_select"]
        self.assertEqual(prompt1["side"], 1)
        self.assertEqual(prompt1["discard_count"], 1)
        self.assertEqual(prompt1["keep"], 3)
        self.assertEqual(len(prompt1["candidates"]), 4)

        bottom_id_1 = prompt1["candidates"][0]["id"]
        status, s = session.command({
            "action": "draw_bottom",
            "revision": s["revision"],
            "card_ids": [bottom_id_1],
        })
        self.assertEqual(status, HTTPStatus.OK)
        # Now Player 2 must privately pick 1 of 4 to bottom
        self.assertEqual(s["mode"], "handoff")
        status, s = session.command({"action": "ready", "revision": s["revision"], "side": 2})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(s["mode"], "draw_select")
        prompt2 = s["draw_select"]
        self.assertEqual(prompt2["side"], 2)
        bottom_id_2 = prompt2["candidates"][0]["id"]
        status, s = session.command({
            "action": "draw_bottom",
            "revision": s["revision"],
            "card_ids": [bottom_id_2],
        })
        self.assertEqual(status, HTTPStatus.OK)
        while s["mode"] == "timing":
            status, s = session.command({"action": "next", "revision": s["revision"]})
            self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(s["mode"], ("handoff", "placement"))
        # Speed roll telemetry recorded with team averages and dropped lowest char
        self.assertTrue(s["speed_rolls"])
        final_roll = s["speed_rolls"][-1]
        self.assertIn(final_roll["winner_side"], (1, 2))
        self.assertTrue(all(side["dropped_id"] is not None for side in final_roll["sides"]))
        kinds = {ev["kind"] for ev in s["fx_events"]}
        self.assertTrue({"draw_bottom", "draw", "speed_roll", "cost_refill"} <= kinds)

    def test_shield_wear_vs_absorption_emits_distinct_damage_telemetry(self):
        session = BattleSession(seed=37)
        target = session.match.game.players[1].characters[0]
        target.add_shield("normal", 3)
        target.add_shield("reinforced", 2)
        target.add_shield("concept", 1)
        lost = target.take_damage(3, penetration="pierce")
        self.assertEqual(lost, 1)
        self.assertEqual((target.shield, target.reinforced_shield, target.concept_shield), (0, 0, 1))
        dmg_ev = next(ev for ev in reversed(session.state()["fx_events"]) if ev["kind"] == "damage")
        self.assertEqual(dmg_ev["grade"], "pierce")
        self.assertEqual(dmg_ev["absorbed"], {"normal": 0, "reinforced": 2, "concept": 0})
        self.assertEqual(dmg_ev["eroded"], {"normal": 3, "reinforced": 0})
        self.assertEqual(dmg_ev["hp_lost"], 1)
        kinds = {ev["kind"] for ev in session.state()["fx_events"]}
        self.assertIn("shield_gain", kinds)
        self.assertIn("passive_trigger", kinds)
        self.assertIn("status_change", kinds)

    def test_full_match_emits_reveal_clash_and_recycle_fx_events(self):
        session = BattleSession(seed=37)
        s = session.state()
        # Use two high-HP characters so Turn 1 definitely reaches turn_end & recycling
        status, s = session.command({
            "action": "new",
            "revision": s["revision"],
            "roster": [s["choices"][0]["id"], s["choices"][1]["id"]],
        })
        self.assertEqual(status, HTTPStatus.OK)
        seen_kinds = set()
        for _ in range(240):
            for ev in s["fx_events"]:
                seen_kinds.add(ev["kind"])
            if s["mode"] == "finished":
                break
            mode = s["mode"]
            if mode == "placement":
                cmd = {"action": "place", "card_id": s["legal_cards"][0]}
            elif mode == "handoff":
                cmd = {"action": "ready"}
            elif mode in ("pre_attack", "intercept"):
                cmd = {"action": "end_attack"} if s["can_end_attack"] else {"action": "let_through"}
            else:
                cmd = {"action": "next"}
            status, s = session.command({**cmd, "revision": s["revision"]})
            self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(
            {"speed_roll", "cost_refill", "cards_reveal", "cost_pay", "dice_clash", "combat_strike", "damage", "turn_recycle"}
            <= seen_kinds,
            seen_kinds,
        )
