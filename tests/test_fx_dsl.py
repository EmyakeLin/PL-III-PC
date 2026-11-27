"""Tests for PR #2 declarative FX DSL, natural-language FX compiler, and /fx_scripts security."""

import unittest

from battle_ui.assets import resolve_static as _resolve_static
from battle_ui.match import BattleMatch
from battle_ui.fx_compiler import (
    compile_prompt_to_recipe,
    discover_character_fx,
    discover_fx_scripts,
    normalize_character_fx_manifest,
    sanitize_bright_hex,
    validate_fx_recipe,
)
from battle_ui.status_icons import discover_status_visuals
from loader import load_characters_from_packs


class FxDslInterfaceTests(unittest.TestCase):
    def test_void_cut_ring_is_served_for_both_effects(self):
        import http.client
        import threading
        from xml.etree import ElementTree
        from battle_mcp.transport import ArenaServer

        pool = {spec["id"]: spec for spec in load_characters_from_packs()}
        recipe = discover_character_fx(pool)["nova_lin_qiu"]["skills"]["空断"]
        with ArenaServer(None, port=0) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            worker.start()
            try:
                for hook, anchor in (("on_form_change", "attacker.center"), ("on_strike", "defender.center")):
                    with self.subTest(hook=hook):
                        ring, = [atom for atom in recipe[hook]["vfx"] if atom["primitive"] == "sprite_vfx"]
                        self.assertEqual(ring["to"], anchor)
                        self.assertEqual(ring["url"], "/fx_assets/star_knot_ring.svg")
                        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                        try:
                            conn.request("GET", ring["url"])
                            response = conn.getresponse()
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.getheader("Content-Type").split(";")[0], "image/svg+xml")
                            self.assertEqual(ElementTree.fromstring(response.read()).tag, "{http://www.w3.org/2000/svg}svg")
                        finally:
                            conn.close()
            finally:
                server.shutdown()
                worker.join()

    def test_natural_language_prompt_compiles_multi_hit_vfx_and_synth_audio(self):
        rec = compile_prompt_to_recipe("翠绿三连风刃回旋重斩，伴随金色散射粒子与清脆风鸣")
        self.assertIn("vfx", rec)
        prims = {atom["primitive"]: atom for atom in rec["vfx"]}
        self.assertIn("slash_arc", prims)
        self.assertEqual(prims["slash_arc"]["count"], 3)
        self.assertEqual(prims["slash_arc"]["color"], "#1c946b")
        self.assertEqual(prims["slash_arc"]["from"], "attacker.bone_weapon")
        self.assertIn("sparks", prims)
        self.assertEqual(prims["sparks"]["color"], "#d99b26")
        self.assertEqual(rec["sfx"]["waveform"], "noise")
        self.assertGreaterEqual(rec["camera"]["shake"], 7.0)

        bell = compile_prompt_to_recipe("青铜重锤砸地激起两圈共鸣波纹与低沉钟鸣")
        bell_prims = {atom["primitive"]: atom for atom in bell["vfx"]}
        self.assertIn("ground_shockwave", bell_prims)
        self.assertIn("shockwave_ring", bell_prims)
        self.assertEqual(bell_prims["shockwave_ring"]["count"], 2)
        self.assertEqual(bell["sfx"]["waveform"], "sine")
        self.assertTrue(bell["sfx"]["harmonics"])

    def test_validator_clamps_bounds_and_rejects_unsafe_scripts_and_black_colors(self):
        self.assertNotEqual(sanitize_bright_hex("#000000"), "#000000")
        rec = validate_fx_recipe({
            "vfx": [
                {"primitive": "sparks", "count": 9999, "color": "#000000"},
                {"primitive": "invalid_primitive", "count": 3},
            ],
            "camera": {"shake": 999, "duration_ms": 99999},
            "sfx": {"waveform": "sine", "freq_start": 99999, "gain": 5.0, "duration_ms": 99999},
            "script": "../evil.js#hack",
        })
        self.assertEqual(len(rec["vfx"]), 1)
        self.assertLessEqual(rec["vfx"][0]["count"], 64)
        self.assertNotEqual(rec["vfx"][0]["color"], "#000000")
        self.assertLessEqual(rec["camera"]["shake"], 18.0)
        self.assertLessEqual(rec["camera"]["duration_ms"], 700)
        self.assertLessEqual(rec["sfx"]["gain"], 0.26)
        self.assertLessEqual(rec["sfx"]["freq_start"], 5000.0)
        self.assertNotIn("script", rec)

        ok_script = validate_fx_recipe({"script": "blank_prism_resonance#onPrismStrike"})
        self.assertEqual(
            ok_script["script"],
            {"url": "/fx_scripts/blank_prism_resonance.js", "export": "onPrismStrike"},
        )

    def test_inline_fx_and_external_fx_discovery_and_snapshot_delivery(self):
        pool = {c["id"]: c for c in load_characters_from_packs()}
        fx_map = discover_character_fx(pool)
        self.assertIn("plan_b_annolin", fx_map)
        self.assertIn("plan_b_heck", fx_map)
        self.assertIn("翠流迸发", fx_map["plan_b_annolin"]["skills"])

        # Inline `fx_prompt` on a synthetic character compiles without needing external file
        synthetic = {
            "custom_hero": {
                "id": "custom_hero",
                "color": "#2478cc",
                "fx_prompt": "浅蓝三连突刺破空与清脆金属蜂鸣",
                "skills": [{"id": "sk1", "name": "连刺", "fx_prompt": "金色光束与粒子"}],
                "passive_skills": [{"name": "共鸣", "fx_prompt": "青铜钟鸣波纹"}],
            }
        }
        syn_fx = discover_character_fx(synthetic)
        self.assertIn("custom_hero", syn_fx)
        self.assertIn("strike", syn_fx["custom_hero"]["defaults"])
        self.assertIn("sk1", syn_fx["custom_hero"]["skills"])
        self.assertIn("共鸣", syn_fx["custom_hero"]["passives"])

        # End-to-end table_assets snapshot & /fx_scripts static security
        snap = BattleMatch(seed=37).table_assets()
        self.assertIn("plan_b_annolin", snap["character_fx"])
        self.assertIn("blank_prism_resonance", snap["fx_scripts"])
        resolved = _resolve_static("/fx_scripts/blank_prism_resonance.js")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[1], "text/javascript")
        self.assertIsNone(_resolve_static("/fx_scripts/../wind_plan_b.json"))
        self.assertIsNone(_resolve_static("/fx_scripts/missing.js"))

    def test_manifest_normalization_preserves_dice_specific_hooks(self):
        m = normalize_character_fx_manifest({
            "color": "#c93832",
            "skills": {
                "skill_x": {
                    "on_clash_win": "猩红重斩与碎裂",
                    "dice": {
                        "1": "猩红刀光",
                        "2": "暗金三连突刺破空",
                    },
                }
            },
        })
        sk = m["skills"]["skill_x"]
        self.assertIn("on_clash_win", sk)
        self.assertIn("1", sk["dice"])
        self.assertIn("2", sk["dice"])
        self.assertEqual(sk["dice"]["2"]["vfx"][0]["primitive"], "pierce_lance")
        self.assertEqual(sk["dice"]["2"]["vfx"][0]["count"], 3)

    def test_battle_snapshot_serves_each_approved_status_icon(self):
        visuals = BattleMatch(seed=37).table_assets()["status_visuals"]
        names = (
            "麻痹", "弹药", "威压", "电击", "电流", "堆芯熔毁", "隧道", "星结",
            "全开", "载体容器", "伤害提升",
        )
        for name in names:
            with self.subTest(status=name):
                self.assertIn(name, visuals)
                asset, content_type = _resolve_static(visuals[name]["icon_url"])
                self.assertEqual(asset.name, f"{name}.svg")
                self.assertEqual(content_type, "image/svg+xml")

    def test_lan_qing_sprite_and_four_activation_faces_have_their_own_assets(self):
        from xml.etree import ElementTree

        state = BattleMatch(seed=37).table_assets()
        sprite, mime = _resolve_static(state["character_sprites"]["lan_qing"])
        self.assertEqual((sprite.name, mime), ("lan_qing.svg", "image/svg+xml"))
        root = ElementTree.parse(sprite).getroot()
        self.assertEqual((root.get("viewBox"), root.get("data-foot")), ("0 0 160 160", "80,136"))
        self.assertEqual([g.get("id") for g in root.findall("{*}g")], [
            "bone_back_hair", "bone_cape_back", "bone_arm_back", "bone_torso", "bone_head", "bone_weapon"])
        actor = next(c for c in load_characters_from_packs() if c["id"] == "lan_qing")
        charges = {skill["form_when"]["status"] for skill in actor["skills"] if "form_when" in skill}
        self.assertEqual(len(charges), 4)
        for name in charges:
            with self.subTest(status=name):
                icon, mime = _resolve_static(state["status_visuals"][name]["icon_url"])
                self.assertEqual((icon.stem, mime), (name, "image/svg+xml"))
                self.assertEqual(ElementTree.parse(icon).getroot().get("viewBox"), "0 0 24 24")

    def test_status_icons_discovery_inline_sanitization_and_static_serving(self):
        snap = BattleMatch(seed=37).table_assets()
        visuals = snap.get("status_visuals", {})
        self.assertIn("凝聚", visuals)
        self.assertIn("烧伤", visuals)
        self.assertIn("限制", visuals)
        self.assertEqual(visuals["凝聚"]["color"], "#248277")
        self.assertTrue(visuals["凝聚"]["icon_url"].startswith("/status_icons/"))
        self.assertIn("icon_path", visuals["限制"])

        # Static resolver handles URL-encoded CJK SVG names and blocks traversal
        resolved = _resolve_static(visuals["凝聚"]["icon_url"])
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[1], "image/svg+xml")
        self.assertIsNone(_resolve_static("/status_icons/../wind_plan_b.json"))
        self.assertIsNone(_resolve_static("/status_icons/manifest.json"))

        # Inline status_rules visuals support safe SVG/path/symbol and strip unsafe <script> SVG
        synthetic_pool = {
            "hero_x": {
                "id": "hero_x",
                "status_rules": {
                    "霜痕": {
                        "color": "#2478cc",
                        "icon_svg": "<svg viewBox='0 0 24 24'><circle cx='12' cy='12' r='8'/></svg>",
                    },
                    "恶意状态": {
                        "icon_svg": "<svg><script>alert(1)</script></svg>",
                        "icon_symbol": "★",
                    },
                },
            }
        }
        syn = discover_status_visuals(synthetic_pool)
        self.assertIn("icon_svg", syn["霜痕"])
        self.assertEqual(syn["霜痕"]["color"], "#2478cc")
        self.assertNotIn("icon_svg", syn["恶意状态"])
        self.assertEqual(syn["恶意状态"]["icon_symbol"], "★")

    def test_liu_yin_status_art_is_served_with_exact_stack_variants(self):
        from xml.etree import ElementTree

        visuals = BattleMatch(seed=37).table_assets()["status_visuals"]
        for name in ("领域洞悉", "环境压制", "战甲"):
            with self.subTest(status=name):
                asset, mime = _resolve_static(visuals[name]["icon_url"])
                self.assertEqual((asset.stem, mime), (name, "image/svg+xml"))

        visual = visuals["环境同调"]
        variants = visual["icon_urls_by_stack"]
        self.assertEqual(set(variants), {"1", "2", "3"})
        self.assertEqual(visual["icon_url"], variants["1"])
        self.assertEqual(len(set(variants.values())), 3)
        for level, url in variants.items():
            with self.subTest(level=level):
                asset, mime = _resolve_static(url)
                self.assertEqual(mime, "image/svg+xml")
                svg = ElementTree.parse(asset).getroot()
                self.assertIn(f"{level} 层", svg.findtext("{*}title"))
                self.assertEqual(len(svg.findall(".//{*}path[@fill='#79AC93']")), int(level) - 1)
                self.assertEqual(bool(svg.findall(".//{*}path[@fill='#FFFDF8']")), level == "3")
                self.assertIsNone(svg.find(".//{*}animate"))

    def test_stack_icon_map_resolves_only_existing_files_and_positive_stack_keys(self):
        mapping = {"7": "凝聚.svg", "0": "凝聚.svg", "1.5": "凝聚.svg", "2": "missing.svg"}
        pool = {"fixture": {"status_rules": {"测试图标": {"icons_by_stack": mapping}}}}
        visuals = discover_status_visuals(pool)
        self.assertEqual(visuals["测试图标"]["icon_urls_by_stack"], {"7": visuals["凝聚"]["icon_url"]})

    def test_extended_fx_hooks_primitives_hitstop_auras_and_fx_assets_security(self):
        rec = validate_fx_recipe({
            "hitstop_ms": 999,
            "threshold": 7,
            "vfx": [
                {"primitive": "cross_slash", "count": 2, "color": "#238a9e"},
                {"primitive": "sprite_vfx", "asset": "star_knot_ring.svg", "scale": 1.2, "spin": 3.0},
                {"primitive": "sprite_vfx", "asset": "../secret.svg"},
                {"primitive": "skill_banner", "text": "空断", "subtext": "林秋"},
            ],
            "camera": {"shake": 9.5, "zoom_punch": 0.9},
            "sfx": {"url": "clang.ogg", "gain": 2.0},
        })
        self.assertEqual(rec["hitstop_ms"], 140)
        self.assertEqual(rec["threshold"], 7)
        self.assertEqual(rec["camera"]["zoom_punch"], 0.045)
        self.assertEqual(rec["sfx"], {"url": "/sfx/clang.ogg", "gain": 0.6})
        prims = [a["primitive"] for a in rec["vfx"]]
        self.assertEqual(prims, ["cross_slash", "sprite_vfx", "skill_banner"])
        sprite_atom = rec["vfx"][1]
        self.assertEqual(sprite_atom["url"], "/fx_assets/star_knot_ring.svg")

        # Static asset serving resolves `/fx_assets/star_knot_ring.svg` and blocks traversal
        fx_asset = _resolve_static("/fx_assets/star_knot_ring.svg")
        self.assertIsNotNone(fx_asset)
        self.assertEqual(fx_asset[1], "image/svg+xml")
        self.assertIsNone(_resolve_static("/fx_assets/../lan_qing.json"))
        self.assertIsNone(_resolve_static("/sfx/../lan_qing.json"))

        # Verify authored character FX packs normalize with status_auras, dice_style, and lifecycle hooks
        pool = {c["id"]: c for c in load_characters_from_packs() if "emyake" not in c["id"]}
        fx_map = discover_character_fx(pool)
        for cid in ("lan_qing", "nova_lin_qiu", "liu_yin", "cang_feng_he_lian"):
            with self.subTest(character=cid):
                self.assertIn(cid, fx_map)
                self.assertIn("status_auras", fx_map[cid])
                self.assertIn("skills", fx_map[cid])
        self.assertIn("on_form_change", fx_map["nova_lin_qiu"]["skills"]["空断"])
        self.assertEqual(fx_map["cang_feng_he_lian"]["defaults"]["on_heavy_hit"]["threshold"], 7)

    def test_emyake_lin_yu_sprite_palette_and_eleven_status_icons(self):
        from xml.etree import ElementTree

        state = BattleMatch(seed=37).table_assets()
        self.assertEqual(state["character_colors"]["emyake_lin_yu"], "#2563eb")
        sprite, mime = _resolve_static(state["character_sprites"]["emyake_lin_yu"])
        self.assertEqual((sprite.name, mime), ("emyake_lin_yu.svg", "image/svg+xml"))
        root = ElementTree.parse(sprite).getroot()
        self.assertEqual((root.get("viewBox"), root.get("data-foot")), ("0 0 160 160", "80,136"))
        self.assertEqual(
            [g.get("id") for g in root.findall("{*}g") if (g.get("id") or "").startswith("bone_")],
            ["bone_back_hair", "bone_cape_back", "bone_torso", "bone_head", "bone_weapon"],
        )

        visuals = state["status_visuals"]
        exclusive = ("羽流·势", "羽流·延攻", "羽流·反制", "羽流·制衡", "羽流·终", "铭刻", "折影化铭刻", "折影")
        generic = ("裂伤", "裂伤拘束", "破甲")
        for name in (*exclusive, *generic):
            with self.subTest(status=name):
                self.assertIn(name, visuals)
                self.assertIn("color", visuals[name])
                icon, mime = _resolve_static(visuals[name]["icon_url"])
                self.assertEqual((icon.name, mime), (f"{name}.svg", "image/svg+xml"))
                self.assertEqual(ElementTree.parse(icon).getroot().get("viewBox"), "0 0 32 32")

        self.assertEqual(visuals["羽流·势"]["color"], "#ec2892")
        for stance in ("羽流·延攻", "羽流·反制", "羽流·制衡", "羽流·终"):
            self.assertEqual(visuals[stance]["color"], "#2563eb")

        empty_pool_visuals = discover_status_visuals({})
        lin_yu_palette = ("#38bdf8", "#2563eb", "#1d4ed8", "#7c3aed", "#ec2892")
        for name in generic:
            with self.subTest(generic_status=name):
                self.assertIn(name, empty_pool_visuals)
                self.assertIn("color", empty_pool_visuals[name])
                icon, _ = _resolve_static(empty_pool_visuals[name]["icon_url"])
                svg_text = icon.read_text(encoding="utf-8").lower()
                for forbidden in lin_yu_palette:
                    self.assertNotIn(forbidden, svg_text)


if __name__ == "__main__":
    unittest.main()
