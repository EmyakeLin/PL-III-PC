"""Verification for pure-WebGL battle engine backend features and zero-DOM shell."""

import io
import json
import re
import shutil
import subprocess
import unittest
from contextlib import redirect_stdout
from http import HTTPStatus
from pathlib import Path

from battle_ui.__main__ import BattleSession, STATIC_DIR, _resolve_static
from battle_ui.match import BattleMatch
from loader import load_characters_from_packs


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
            "/engine/cost_hud.js",
            "/engine/formation.js",
            "/engine/combat_choreography.js",
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
        # Explicit defense-die blue tokens ordered by the game's die iconography spec
        allowed_defense_blues = {"2478cc", "eaf4fd", "4ca0eb", "1a5696"}
        hex_pattern = re.compile(r"(?:0x|#)([0-9a-fA-F]{6})\b")
        for path in files:
            text = path.read_text(encoding="utf-8")
            for match in hex_pattern.finditer(text):
                code = match.group(1).lower()
                if code in allowed_defense_blues:
                    continue
                r, g, b = int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16)
                # Exclude non-color bitmasks like 0x0001 (4 hex digits already ignored)
                self.assertGreaterEqual(max(r, g, b), 40, f"Forbidden black/near-black color {match.group(0)} in {path.name}")
                self.assertFalse(
                    b > r + 15 and b > g + 15,
                    f"Forbidden blue/purple color {match.group(0)} (r={r},g={g},b={b}) in {path.name}",
                )

    def test_character_colors_pack_override_and_public_card_ownership_without_leaking_content(self):
        from battle_ui.match import _assign_character_colors

        colors = _assign_character_colors({
            "configured_hero": {"id": "configured_hero", "color": "#11aa77"},
            "random_hero_a": {"id": "random_hero_a"},
            "random_hero_b": {"id": "random_hero_b"},
        })
        self.assertEqual(colors["configured_hero"], "#11aa77")
        self.assertRegex(colors["random_hero_a"], r"^#[0-9a-f]{6}$")
        self.assertRegex(colors["random_hero_b"], r"^#[0-9a-f]{6}$")
        self.assertNotEqual(colors["random_hero_a"], colors["random_hero_b"])

        session = BattleSession(seed=37)
        s = session.state()
        self.assertIn("character_colors", s)
        self.assertIn("card_owners", s)
        # Place 1 card as active side, then advance to opponent's placement view
        if s["mode"] == "handoff":
            _, s = session.command({"action": "ready", "revision": s["revision"], "side": s["active_side"]})
        placer_side = s["active_side"]
        _, s = session.command({"action": "place", "revision": s["revision"], "card_id": s["legal_cards"][0]})
        if s["mode"] == "handoff":
            _, s = session.command({"action": "ready", "revision": s["revision"], "side": s["active_side"]})
        # Opponent's view keeps the placed card strictly hidden in frame.duels,
        # while card_owners exposes ONLY public character ownership (no card id/name/cost!)
        duel1_sides = {entry["side"]: entry["cards"] for entry in s["frame"]["duels"][0]["sides"]}
        self.assertEqual(duel1_sides[placer_side], [{"hidden": True}])
        owners = s["card_owners"]["duels"][f"1:{placer_side}"]
        self.assertEqual(len(owners), 1)
        self.assertTrue(owners[0]["character_id"])
        self.assertTrue(owners[0]["character_name"])
        self.assertNotIn("name", owners[0])
        self.assertNotIn("cost", owners[0])

    def test_die_icons_uniform_red_hex_attack_and_blue_square_defense(self):
        ds_src = (STATIC_DIR / "engine" / "design_system.js").read_text(encoding="utf-8")
        cp_src = (STATIC_DIR / "engine" / "card_print.js").read_text(encoding="utf-8")
        for atk in ("slash", "pierce", "blunt"):
            self.assertRegex(ds_src, rf"{atk}:\s*\{{[^}}]*frame:\s*'hex'[^}}]*color:\s*ATTACK_DIE_COLOR")
        for dfn in ("block", "evade"):
            self.assertRegex(ds_src, rf"{dfn}:\s*\{{[^}}]*frame:\s*'square'[^}}]*color:\s*DEFENSE_DIE_COLOR")
        self.assertIn("HP_BAR_COLOR", ds_src)
        self.assertNotIn("highCost", cp_src)

    def test_passive_display_lines_in_roster_and_match_catalogs(self):
        roster = ["blank_boss", "waa_erkes"]
        groups = {group["name"]: group for actor in load_characters_from_packs()
                  if actor["id"] in roster for group in actor["passive_skills"]}
        expected = {
            "智脑": [groups["智脑"]["description"]],
            "纯能电池": [groups["纯能电池"]["description"]],
            "自发增压武器": [entry["description"] for entry in groups["自发增压武器"]["entries"]],
        }
        state = BattleMatch(roster, seed=37).snapshot()
        selected = [actor for player in state["catalog"]["players"] for actor in player["characters"]]
        for actors in (state["roster_catalog"], selected):
            lines = {group["name"]: group["display_lines"] for actor in actors for group in actor["passives"]}
            for name, original in expected.items():
                self.assertEqual(lines[name], original, name)

    @unittest.skipUnless(shutil.which("node"), "WebGL card text requires a JavaScript runtime")
    def test_liu_yin_prints_each_authored_character_on_cards_and_in_the_catalog(self):
        state = BattleMatch([["liu_yin"], ["lan_qing"]], seed=37).snapshot()
        actor = state["catalog"]["players"][0]["characters"][0]
        script = """
            import assert from 'node:assert/strict';
            import {readFileSync} from 'node:fs';
            import * as PIXI from './vendor/pixi.min.mjs';
            import {buildFullCard, buildBoardCardTag} from './engine/card_print.js';
            import {buildCodexOverlay, buildRosterOverlay} from './engine/table_overlays.js';
            const [actor, preview] = JSON.parse(readFileSync(0, 'utf8'));
            const measure = {measureText: t => ({width: t.length * 10,
                actualBoundingBoxAscent: 10, actualBoundingBoxDescent: 3})};
            PIXI.DOMAdapter.set({...PIXI.DOMAdapter.get(), getCanvasRenderingContext2D: () => class {},
                createCanvas: () => ({getContext: () => measure})});
            function text(node) {
                if (node instanceof PIXI.Text) return node.text;
                return (node.children || []).map(text).join('');
            }
            for (const card of actor.skills.flatMap(skill => [skill, ...skill.forms])) {
                const source = card.printed_text.replaceAll('\\n', '');
                for (const width of [240, 345]) {
                    assert.equal(text(buildFullCard(card, {width, ownerName: actor.name})), source);
                }
                assert.equal(text(buildBoardCardTag(card)), source);
                assert.ok(!text(buildFullCard(card, {rangeDeficit: 3})).includes('拼点逆转'));
            }
            const overlay = buildCodexOverlay(1024, 768, {tab: 'catalog', onClose: () => {},
                catalog: {players: [{side: 1, characters: [actor]}]}});
            assert.ok(text(overlay).includes(actor.printed_text.replaceAll('\\n', '')));
            const roster = buildRosterOverlay(1400, 900, {catalog: [preview]});
            const body = actor.printed_text.slice(preview.printed_profile.length).replaceAll('\\n', '');
            assert.ok(text(roster).includes(body));
        """
        preview = next(c for c in state["roster_catalog"] if c["id"] == actor["id"])
        result = subprocess.run([shutil.which("node"), "--input-type=module", "-e", script],
                                cwd=STATIC_DIR, input=json.dumps([actor, preview]), capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "WebGL card text requires a JavaScript runtime")
    def test_webgl_pre_reveal_labels_and_burn_fallback_match_the_catalog(self):
        state = BattleSession(seed=37).state()
        cards = {card["name"]: card for actor in state["roster_catalog"] for card in actor["skills"]}
        selection = [cards[name] for name in ("机动·贯彻长空", "抽刀", "开锋", "空断")]
        script = """
            import {readFileSync} from 'node:fs';
            import {exactSkillTraits, exactSkillTraitSpecs, OFFICIAL_STATUS_RULES}
                from './engine/design_system.js';
            const cards = JSON.parse(readFileSync(0, 'utf8'));
            console.log(JSON.stringify({
                traits: cards.map(exactSkillTraits),
                badges: cards.map(card => exactSkillTraitSpecs(card).map(spec => spec.label)),
                burn: OFFICIAL_STATUS_RULES['烧伤'],
            }));
        """
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script], cwd=STATIC_DIR,
            input=json.dumps(selection), capture_output=True, encoding="utf-8", check=True,
        )
        rendered = json.loads(result.stdout)
        expected = [
            [*cards["机动·贯彻长空"]["range_traits"], "凝聚达到3层时可在开牌前进攻"],
            ["开牌前打出"], [], [*cards["空断"]["range_traits"], "使用须付 2 隧道"],
        ]
        self.assertEqual(rendered["traits"], expected)
        self.assertEqual(rendered["badges"], expected)
        self.assertIn(rendered["burn"], state["catalog"]["statuses"]["烧伤"])

    @unittest.skipUnless(shutil.which("node"), "Status icon rendering requires JavaScript")
    def test_mounted_status_texture_follows_the_current_snapshot(self):
        match = BattleMatch(["liu_yin", "plan_b_heck"], seed=37)
        liu = match.game.players[0].characters[0]
        levels = []
        for delta in (0, 1, 1, 1, -1, -2, 3):
            liu.add_status("环境同调", delta)
            actor = match.snapshot()["frame"]["players"][0]["characters"][0]
            levels.append(actor["statuses"].get("环境同调"))
        self.assertEqual(levels, [None, 1, 2, 3, 2, None, 3])

        # Give each fetched SVG its URL as a texture label so the assertion reads
        # the sprite actually mounted by Pixi, including after a cached downgrade.
        script = """
            import assert from 'node:assert/strict';
            import {readFileSync} from 'node:fs';
            import * as PIXI from './vendor/pixi.min.mjs';
            import {mountStatusIcon, setStatusVisuals} from './engine/design_system.js';
            const {visuals, levels} = JSON.parse(readFileSync(0, 'utf8'));
            globalThis.fetch = async url => ({ok: true, text: async () => url});
            globalThis.Image = class {
                set src(value) { this.label = decodeURIComponent(value.split(',')[1]); this.onload(); }
            };
            globalThis.document = {createElement: () => {
                const canvas = {getContext: () => ({
                    clearRect() {}, drawImage(image) { canvas.label = image.label; },
                })};
                return canvas;
            }};
            PIXI.Texture.from = canvas => new PIXI.Texture({label: canvas.label});
            setStatusVisuals(visuals);
            const name = '环境同调';
            async function mounted(status, level) {
                const host = new PIXI.Container();
                mountStatusIcon(host, null, status, 8, 8, 6, null, level);
                await new Promise(resolve => setImmediate(resolve));
                const sprite = host.children.find(child => child instanceof PIXI.Sprite);
                assert.ok(sprite);
                const spriteLabel = sprite.texture.label;
                host.destroy({children: true});
                return spriteLabel;
            }
            for (const level of levels.filter(level => level !== null)) {
                assert.equal(await mounted(name, level), visuals[name].icon_urls_by_stack[level]);
            }
            assert.equal(await mounted(name), visuals[name].icon_url);
            assert.equal(await mounted(name, 7), visuals[name].icon_url);
            assert.equal(await mounted('战甲', 1), visuals['战甲'].icon_url);
        """
        visuals = match.table_assets()["status_visuals"]
        subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script], cwd=STATIC_DIR,
            input=json.dumps({"visuals": {key: visuals[key] for key in ("环境同调", "战甲")}, "levels": levels}),
            encoding="utf-8", check=True,
        )

    def test_no_paraphrasing_die_level_labels_or_filler_text(self):
        for name in (
            "design_system.js",
            "card_print.js",
            "cost_hud.js",
            "formation.js",
            "combat_choreography.js",
            "stage_actors.js",
            "table_overlays.js",
            "game_director.js",
            "three_world.js",
        ):
            raw = (STATIC_DIR / "engine" / name).read_text(encoding="utf-8")
            code = re.sub(r"/\*.*?\*/|//[^\n]*", "", raw, flags=re.S)
            for forbidden in ("Lv.", "无附加词条", "compactDieBadges", "compactSkillTag", "拖入扣置或双击", "被动 (", "placeLeft"):
                self.assertNotIn(forbidden, code, f"Forbidden text {forbidden!r} found in {name}")

    @unittest.skipUnless(shutil.which("node"), "Canvas choice controls require a JavaScript runtime")
    def test_board_selection_and_tray_confirm_the_same_private_option(self):
        script = """
            import assert from 'node:assert/strict';
            import * as PIXI from './vendor/pixi.min.mjs';
            import {GameDirector} from './engine/game_director.js';
            import {buildEffectChoice} from './engine/table_overlays.js';
            const measure = {measureText: text => ({
                width: text.length * 10, actualBoundingBoxAscent: 10, actualBoundingBoxDescent: 3,
            })};
            PIXI.DOMAdapter.set({...PIXI.DOMAdapter.get(), getCanvasRenderingContext2D: () => class {},
                createCanvas: () => ({getContext: () => measure})});
            const options = Array.from({length: 9}, (_, i) => ({
                kind: 'choose_card', label: '扣置技能',
                effect_target: {zone: 'board', side: 2, kind: 'regular', number: 1, position: i + 1},
            }));
            options.splice(3, 0, {kind: 'decline_card', label: '放弃'});
            for (const [w, h] of [[1366, 768], [800, 500], [390, 650]]) {
                const submissions = [], highlights = [];
                const tray = buildEffectChoice(w, h, {side: 1, safeTop: 246, options,
                    choice: {selection: 'board', source_name: '分界', description: '选择一张在场技能。'},
                    onPick: index => submissions.push(index), onInspect() {},
                    onSelectionChange: index => highlights.push(index)});
                assert.ok(tray.trayTop >= 246);
                assert.equal(tray.eventMode, 'passive');
                tray.confirmSelection();
                const board = new PIXI.Container();
                const director = {
                    state: {effect_choice: {selection: 'board'}, special_options: options, active_side: 1},
                    effectMarks: [], _activeOverlayNode: {node: tray},
                };
                GameDirector.prototype._markEffectTarget.call(director, board, 'regular', 1, 2, 8, 0, 0, 100, 140);
                assert.equal(board.children.length, 1);
                board.children[0].emit('pointertap', {stopPropagation() {}});
                assert.deepEqual(submissions, []);
                assert.equal(highlights.at(-1), 8);
                tray.confirmSelection();
                tray.cancelSelection();
                tray.confirmSelection();
                assert.deepEqual(submissions, [8]);
                tray.cancelSelection();
                assert.deepEqual(submissions, [8, 3]);
                board.destroy({children: true});
                tray.destroy({children: true});
            }
        """
        subprocess.run([shutil.which("node"), "--input-type=module", "-e", script],
                       cwd=STATIC_DIR, capture_output=True, check=True)

    def test_director_wires_all_wave1_modules_and_scalable_10v10_roster(self):
        director_src = (STATIC_DIR / "engine" / "game_director.js").read_text(encoding="utf-8")
        for symbol in (
            "createDiegeticTopBar",
            "createFactionCostHud",
            "createDiegeticDeckPiles",
            "computeFormationLayout",
            "createDelayedHpBar",
            "renderFocusSightlines",
            "buildScalableDuelRail",
            "buildHitstopBanner",
            "setIntent(",
            "setIntentFocus(",
            "emitShockwave(",
            "costMerge(",
            "passiveChime(",
            "cardFlick(",
            "pulsePile(",
            "setGalleryScroll(",
            "setInspectScroll(",
            "setScrollX(",
            "onSetMaxPerSide",
        ):
            self.assertIn(symbol, director_src, f"Expected Wave-1 integration symbol {symbol!r} in game_director.js")
        self.assertNotIn("每方最多选 3 名角色", director_src)
        self.assertNotIn("clearContainer(this.cornerHudLayer)", director_src)

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
        lost = target.take_damage(3, penetration="pierce", result_field="hp_lost")
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
        # Keep the pair fixed so an addition to the roster cannot end the fight
        # before the first turn's cards are recycled.
        status, s = session.command({
            "action": "new",
            "revision": s["revision"],
            "roster": ["plan_b_heck", "char_iron_vanguard"],
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

    def test_svg_sprites_discovery_static_serving_and_bone_schema(self):
        import xml.etree.ElementTree as ET
        from pathlib import Path
        from battle_ui.__main__ import _resolve_static, SPRITES_DIR

        session = BattleSession(seed=37)
        s = session.state()
        sprites = s.get("character_sprites", {})
        self.assertIn("plan_b_annolin", sprites)
        self.assertEqual(sprites["plan_b_annolin"], "/sprites/plan_b_annolin.svg")
        self.assertIn("iron_qi_zheng", sprites)
        self.assertIn("blank_boss", sprites)

        # Roster catalog and choices carry matching sprite_url
        by_id = {c["id"]: c for c in s["roster_catalog"]}
        self.assertEqual(by_id["plan_b_annolin"]["sprite_url"], "/sprites/plan_b_annolin.svg")

        # Static resolver serves valid SVG and blocks path traversal / non-SVG files
        resolved = _resolve_static("/sprites/plan_b_annolin.svg")
        self.assertIsNotNone(resolved)
        file_path, ctype = resolved
        self.assertEqual(ctype, "image/svg+xml")
        self.assertTrue(file_path.is_file())
        self.assertIsNone(_resolve_static("/sprites/../wind_plan_b.json"))
        self.assertIsNone(_resolve_static("/sprites/nonexistent.svg"))

        # Every SVG in _packs/sprites/ must parse cleanly with 160x160 viewBox & bone_* groups
        svg_files = sorted(Path(SPRITES_DIR).glob("*.svg"))
        self.assertGreaterEqual(len(svg_files), 6)
        for svg_path in svg_files:
            root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
            self.assertEqual(root.attrib.get("viewBox"), "0 0 160 160", svg_path.name)
            bone_ids = [
                el.attrib.get("id", "")
                for el in root.iter()
                if el.tag.endswith("g") and el.attrib.get("id", "").startswith("bone_")
            ]
            self.assertIn("bone_torso", bone_ids, svg_path.name)
            self.assertIn("bone_head", bone_ids, svg_path.name)
            self.assertIn("bone_weapon", bone_ids, svg_path.name)
