"""Declarative FX DSL schema validator, Natural-Language -> FX compiler, and pack FX loader.

Supports three authoring tiers for 《光点计划 III》:
  1. Standalone FX packs in `_packs/fx/<char_id>.json` (zero edits to `_packs/*.json` game logic)
  2. Inline `"fx"` / `"fx_prompt"` fields inside `_packs/*.json` (character, skills, dice, passives)
  3. Custom Three.js/Audio JS hooks in `_packs/fx_scripts/<script>.js` referenced via `"script": "name#fn"`

Run as CLI to inspect or compile natural-language prompts:
    python3.12 -m battle_ui.fx_compiler --prompt "翠绿双弧回旋风刃连斩，伴随金色粒子与清脆风鸣"
"""

import argparse
import json
from pathlib import Path
import re

from loader import PACKS


FX_DIR = PACKS / "fx"
FX_SCRIPTS_DIR = PACKS / "fx_scripts"

VALID_PRIMITIVES = frozenset({
    "slash_arc",
    "pierce_lance",
    "ground_shockwave",
    "beam",
    "shockwave_ring",
    "ripple",
    "sparks",
    "shield_dome",
    "block_barrier",
    "shards",
    "banner",
})

VALID_ANCHORS = frozenset({
    "attacker.bone_weapon",
    "attacker.bone_head",
    "attacker.bone_torso",
    "attacker.center",
    "defender.center",
    "defender.bone_torso",
    "defender.bone_head",
    "clash.center",
    "actor.center",
    "actor.bone_weapon",
})

VALID_WAVEFORMS = frozenset({"sine", "triangle", "sawtooth", "square", "noise"})
VALID_SFX_PRESETS = frozenset({
    "slash", "pierce", "blunt", "clash", "clash_heavy",
    "bell", "passive", "shield", "shatter", "heal", "wind", "coin",
})

DEFAULT_GOLD_HEX = "#d99426"

# Lexicons for deterministic offline Chinese/English natural-language FX compilation
_COLOR_LEXICON = (
    (("翠绿", "翡翠", "青翠", "苍翠", "碧绿", "emerald", "jade"), "#1c946b"),
    (("青绿", "青铜", "铜绿", "verdigris", "teal"), "#2b8578"),
    (("烈焰", "火焰", "灼燃", "炽焰", "炎", "flame", "fire", "ember"), "#d95724"),
    (("猩红", "绯红", "赤红", "血红", "赤", "红", "crimson", "scarlet", "red"), "#c93832"),
    (("琥珀", "橙金", "暖橙", "橙", "amber", "orange"), "#e08e24"),
    (("暗金", "鎏金", "金缮", "金色", "金", "gold", "gilded"), "#d99b26"),
    (("瓷白", "象牙", "纯白", "银白", "白", "ivory", "white", "prism"), "#e6d8b8"),
    (("青灰", "钢铁", "铁灰", "steel", "iron"), "#7d7264"),
    (("浅蓝", "天蓝", "苍蓝", "水蓝", "blue", "cyan"), "#2478cc"),
)

_COUNT_WORDS = (
    (("五连", "五道", "五圈", "5连", "5道", "5圈"), 5),
    (("四连", "四道", "四圈", "4连", "4道", "4圈"), 4),
    (("三连", "三道", "三圈", "三重", "3连", "3道", "3圈"), 3),
    (("双弧", "双连", "两道", "双道", "二连", "两圈", "双圈", "2连", "twin", "double"), 2),
)


def sanitize_bright_hex(raw, fallback=DEFAULT_GOLD_HEX):
    """Parse hex color and enforce the bright sunlit non-black palette."""
    if isinstance(raw, int) and 0 <= raw <= 0xFFFFFF:
        r, g, b = (raw >> 16) & 255, (raw >> 8) & 255, raw & 255
    elif isinstance(raw, str):
        text = raw.strip().lower()
        if text.startswith("0x"):
            text = text[2:]
        elif text.startswith("#"):
            text = text[1:]
        if len(text) != 6 or not all(ch in "0123456789abcdef" for ch in text):
            return fallback
        val = int(text, 16)
        r, g, b = (val >> 16) & 255, (val >> 8) & 255, val & 255
    else:
        return fallback

    # Keep colors bright & legible against warm parchment (lift near-black tones)
    peak = max(r, g, b)
    if peak < 64:
        lift = 64 - peak
        r = min(255, r + lift + 12)
        g = min(255, g + lift + 8)
        b = min(255, b + lift)
    return f"#{r:02x}{g:02x}{b:02x}"


def _clamp_num(value, lo, hi, default):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(lo, min(hi, float(value)))


def _clamp_int(value, lo, hi, default):
    return int(round(_clamp_num(value, lo, hi, default)))


def compile_prompt_to_recipe(prompt, *, base_color=None):
    """Deterministically compile a Chinese/English natural-language FX description into an FX DSL recipe."""
    text = str(prompt or "").strip()
    low = text.lower()
    if not text:
        return {}

    # 1. Extract primary & accent colors
    matched_colors = []
    for keywords, hex_col in _COLOR_LEXICON:
        if any(kw in text or kw in low for kw in keywords):
            if hex_col not in matched_colors:
                matched_colors.append(hex_col)
    primary = matched_colors[0] if matched_colors else sanitize_bright_hex(base_color, DEFAULT_GOLD_HEX)
    secondary = matched_colors[1] if len(matched_colors) > 1 else (
        "#e8a430" if primary != "#d99b26" else "#f2d272"
    )

    # 2. Extract repeat count (e.g., 双弧 / 三连刺 / 三圈)
    repeat_count = 1
    for keywords, cnt in _COUNT_WORDS:
        if any(kw in text or kw in low for kw in keywords):
            repeat_count = cnt
            break

    heavy = any(k in text or k in low for k in (
        "重击", "重斩", "重锤", "砸地", "剧烈", "爆裂", "猛烈", "暴击", "轰鸣", "沉重", "碎裂", "heavy", "massive",
    ))
    swift = any(k in text or k in low for k in (
        "疾速", "极速", "轻盈", "迅疾", "连刺", "回旋", "掠过", "swift", "fast",
    ))

    vfx = []
    sfx = None
    motion = {"lunge": 1.0 if not heavy else 1.2, "recoil": 0.9 if heavy else 0.72, "hitFlash": 0.95 if heavy else 0.75}
    camera = {}

    # 3. Extract trajectory & impact visual atoms
    has_slash = any(k in text or k in low for k in ("斩", "刀光", "风刃", "剑弧", "弧", "挥砍", "回旋", "slash", "arc", "blade"))
    has_pierce = any(k in text or k in low for k in ("刺", "突刺", "穿刺", "长枪", "细剑", "破空", "激波", "pierce", "thrust", "lance"))
    has_blunt = any(k in text or k in low for k in ("锤", "砸", "打击", "地面", "震地", "冲击柱", "blunt", "hammer", "slam", "smash"))
    has_beam = any(k in text or k in low for k in ("光束", "射线", "激光", "棱镜", "星芒", "炮", "beam", "ray", "laser", "prism"))
    has_bell = any(k in text or k in low for k in ("钟", "共鸣", "波纹", "扩散", "圆环", "光环", "涡流", "bell", "ring", "ripple", "wave", "vortex"))
    has_sparks = any(k in text or k in low for k in ("粒子", "火星", "火花", "余烬", "飞溅", "散射", "火焰", "烈焰", "spark", "ember", "burst"))
    has_shards = any(k in text or k in low for k in ("碎裂", "碎片", "碎石", "崩裂", "shatter", "shard", "debris"))
    has_shield = any(k in text or k in low for k in ("护盾", "屏障", "结界", "盾", "招架", "shield", "barrier", "dome"))

    if has_slash:
        vfx.append({
            "primitive": "slash_arc",
            "from": "attacker.bone_weapon",
            "to": "defender.center",
            "color": primary,
            "count": min(4, repeat_count),
            "stagger_ms": 85 if swift else 115,
        })
    if has_pierce:
        vfx.append({
            "primitive": "pierce_lance",
            "from": "attacker.bone_weapon",
            "to": "defender.center",
            "color": primary,
            "count": min(4, repeat_count),
            "stagger_ms": 75 if swift else 105,
        })
    if has_blunt:
        vfx.append({
            "primitive": "ground_shockwave",
            "to": "defender.center",
            "color": primary,
            "count": min(3, repeat_count),
            "stagger_ms": 110,
        })
    if has_beam:
        vfx.append({
            "primitive": "beam",
            "from": "attacker.bone_weapon",
            "to": "defender.center",
            "color": primary,
            "duration_ms": 380 if swift else 480,
            "count": min(3, repeat_count),
            "stagger_ms": 95,
        })
    if has_bell or has_blunt:
        vfx.append({
            "primitive": "shockwave_ring",
            "to": "defender.center",
            "color": secondary if has_slash or has_pierce or has_beam else primary,
            "count": min(3, max(1, repeat_count if has_bell else 1)),
            "stagger_ms": 130,
        })
    if has_shield:
        vfx.append({
            "primitive": "shield_dome",
            "to": "attacker.center",
            "color": primary,
            "radius": 62,
        })
    if has_sparks or not vfx:
        vfx.append({
            "primitive": "sparks",
            "to": "defender.center",
            "color": secondary if vfx else primary,
            "count": 34 if heavy else 22,
            "heavy": heavy,
        })
    if has_shards:
        vfx.append({
            "primitive": "shards",
            "to": "defender.center",
            "color": primary,
            "count": 14 if heavy else 9,
        })

    # 4. Camera feedback
    if heavy or has_blunt:
        camera["shake"] = 10.0 if heavy else 7.5
        camera["duration_ms"] = 280
    elif has_slash or has_pierce or has_beam:
        camera["shake"] = 5.0
        camera["duration_ms"] = 180

    # 5. Synthesized audio recipe
    if any(k in text or k in low for k in ("钟鸣", "钟声", "共鸣", "余音", "bell", "chime")):
        sfx = {
            "waveform": "sine",
            "freq_start": 330 if heavy else 440,
            "freq_end": 326 if heavy else 436,
            "harmonics": [1.0, 1.5, 2.006, 2.98],
            "duration_ms": 620,
            "gain": 0.14,
        }
    elif any(k in text or k in low for k in ("风鸣", "风啸", "呼啸", "涡流", "wind", "whoosh")):
        sfx = {
            "waveform": "noise",
            "freq_start": 1650 if swift else 1100,
            "freq_end": 420,
            "duration_ms": 280,
            "gain": 0.15,
        }
    elif any(k in text or k in low for k in ("蜂鸣", "高频", "清脆", "金属", "琴鸣", "metal", "ring")):
        sfx = {
            "waveform": "triangle",
            "freq_start": 1320,
            "freq_end": 780,
            "harmonics": [1.0, 1.48, 2.24],
            "duration_ms": 240,
            "gain": 0.13,
        }
    elif any(k in text or k in low for k in ("低沉", "轰鸣", "沉重", "砸", "锤", "boom", "slam")):
        sfx = {
            "waveform": "sine",
            "freq_start": 160,
            "freq_end": 54,
            "noise_freq": 680,
            "duration_ms": 340,
            "gain": 0.20,
        }
    elif has_pierce:
        sfx = {"preset": "pierce"}
    elif has_blunt:
        sfx = {"preset": "blunt"}
    elif has_shield:
        sfx = {"preset": "shield"}
    else:
        sfx = {"preset": "clash_heavy" if heavy else "slash"}

    recipe = {
        "prompt": text,
        "vfx": vfx,
        "motion": motion,
        "sfx": sfx,
    }
    if camera:
        recipe["camera"] = camera
    return validate_fx_recipe(recipe, base_color=primary)


def _validate_script_ref(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    module_part, _, fn_part = text.partition("#")
    module_part = module_part.strip()
    fn_part = (fn_part or "run").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.js)?", module_part):
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", fn_part):
        return None
    filename = module_part if module_part.endswith(".js") else f"{module_part}.js"
    return {"url": f"/fx_scripts/{filename}", "export": fn_part}


def validate_fx_recipe(raw, *, base_color=None):
    """Validate and normalize a single FX recipe block (supports string `fx_prompt` shorthand or dict)."""
    if isinstance(raw, str):
        return compile_prompt_to_recipe(raw, base_color=base_color)
    if not isinstance(raw, dict):
        return {}

    fallback_hex = sanitize_bright_hex(base_color, DEFAULT_GOLD_HEX)

    # If a dict specifies `fx_prompt` without explicit `vfx`, compile prompt first and overlay explicit fields
    compiled_base = {}
    prompt_text = raw.get("fx_prompt") or raw.get("prompt")
    if isinstance(prompt_text, str) and prompt_text.strip() and "vfx" not in raw:
        compiled_base = compile_prompt_to_recipe(prompt_text, base_color=fallback_hex)

    merged = {**compiled_base, **raw}
    out = {}

    if isinstance(merged.get("prompt"), str) and merged["prompt"].strip():
        out["prompt"] = merged["prompt"].strip()[:240]
    elif isinstance(merged.get("fx_prompt"), str) and merged["fx_prompt"].strip():
        out["prompt"] = merged["fx_prompt"].strip()[:240]

    # 1. VFX primitives list (bounded to max 8 atoms per event)
    vfx_in = merged.get("vfx")
    if isinstance(vfx_in, list):
        clean_vfx = []
        for item in vfx_in[:8]:
            if not isinstance(item, dict):
                continue
            prim = item.get("primitive")
            if prim not in VALID_PRIMITIVES:
                continue
            atom = {
                "primitive": prim,
                "color": sanitize_bright_hex(item.get("color"), fallback_hex),
                "count": _clamp_int(item.get("count"), 1, 6 if prim != "sparks" and prim != "shards" else 64, 1 if prim not in ("sparks", "shards") else 24),
                "delay_ms": _clamp_int(item.get("delay_ms"), 0, 800, 0),
                "stagger_ms": _clamp_int(item.get("stagger_ms"), 0, 400, 90),
            }
            if item.get("from") in VALID_ANCHORS:
                atom["from"] = item["from"]
            if item.get("to") in VALID_ANCHORS:
                atom["to"] = item["to"]
            if "duration_ms" in item:
                atom["duration_ms"] = _clamp_int(item["duration_ms"], 80, 1400, 440)
            if "radius" in item:
                atom["radius"] = _clamp_int(item["radius"], 20, 160, 58)
            if "heavy" in item:
                atom["heavy"] = bool(item["heavy"])
            if prim == "banner" and isinstance(item.get("text"), str) and item["text"].strip():
                atom["text"] = item["text"].strip()[:28]
                if item.get("kind") in ("status", "clash", "heavy", "passive", "shield"):
                    atom["kind"] = item["kind"]
            clean_vfx.append(atom)
        if clean_vfx:
            out["vfx"] = clean_vfx

    # 2. Actor motion overrides
    motion_in = merged.get("motion")
    if isinstance(motion_in, dict):
        clean_motion = {}
        for key in ("lunge", "recoil", "evade", "hitFlash", "healGlow", "passiveFlare"):
            if key in motion_in:
                clean_motion[key] = round(_clamp_num(motion_in[key], 0.0, 1.5, 0.0), 3)
        if clean_motion:
            out["motion"] = clean_motion

    # 3. Camera feedback
    cam_in = merged.get("camera")
    if isinstance(cam_in, dict):
        clean_cam = {}
        if "shake" in cam_in:
            clean_cam["shake"] = round(_clamp_num(cam_in["shake"], 0.0, 18.0, 0.0), 2)
        if "duration_ms" in cam_in:
            clean_cam["duration_ms"] = _clamp_int(cam_in["duration_ms"], 60, 700, 220)
        if "tint" in cam_in:
            clean_cam["tint"] = sanitize_bright_hex(cam_in["tint"], fallback_hex)
        if clean_cam:
            out["camera"] = clean_cam

    # 4. Audio preset or procedural WebAudio synth recipe
    sfx_in = merged.get("sfx")
    if isinstance(sfx_in, str) and sfx_in in VALID_SFX_PRESETS:
        out["sfx"] = {"preset": sfx_in}
    elif isinstance(sfx_in, dict):
        clean_sfx = {}
        if sfx_in.get("preset") in VALID_SFX_PRESETS:
            clean_sfx["preset"] = sfx_in["preset"]
        if sfx_in.get("waveform") in VALID_WAVEFORMS:
            clean_sfx["waveform"] = sfx_in["waveform"]
            clean_sfx["freq_start"] = round(_clamp_num(sfx_in.get("freq_start"), 45.0, 5000.0, 440.0), 1)
            clean_sfx["freq_end"] = round(_clamp_num(sfx_in.get("freq_end"), 40.0, 5000.0, clean_sfx["freq_start"]), 1)
            clean_sfx["duration_ms"] = _clamp_int(sfx_in.get("duration_ms"), 40, 1200, 240)
            clean_sfx["gain"] = round(_clamp_num(sfx_in.get("gain"), 0.02, 0.26, 0.13), 3)
            if isinstance(sfx_in.get("harmonics"), list):
                clean_sfx["harmonics"] = [
                    round(_clamp_num(h, 0.25, 6.0, 1.0), 3)
                    for h in sfx_in["harmonics"][:6]
                    if isinstance(h, (int, float)) and not isinstance(h, bool)
                ]
            if "noise_freq" in sfx_in:
                clean_sfx["noise_freq"] = round(_clamp_num(sfx_in["noise_freq"], 120.0, 6000.0, 900.0), 1)
        if clean_sfx:
            out["sfx"] = clean_sfx

    # 5. Optional custom JS FX script reference (`"script": "blank_prism_resonance#onStrike"`)
    script_ref = _validate_script_ref(merged.get("script") or merged.get("fx_script"))
    if script_ref:
        out["script"] = script_ref

    return out


def normalize_character_fx_manifest(raw, *, base_color=None):
    """Normalize a full per-character FX manifest (`defaults`, `skills`, `passives`)."""
    if not isinstance(raw, dict):
        return {}
    color = sanitize_bright_hex(raw.get("color") or base_color, DEFAULT_GOLD_HEX)
    manifest = {}

    # Character-level defaults (`slash`, `pierce`, `blunt`, `strike`, `passive`, `status:<name>`)
    defaults_out = {}
    defaults_in = raw.get("defaults")
    if isinstance(defaults_in, dict):
        for hook, spec in defaults_in.items():
            if isinstance(hook, str) and hook.strip():
                rec = validate_fx_recipe(spec, base_color=color)
                if rec:
                    defaults_out[hook.strip()] = rec
    if defaults_out:
        manifest["defaults"] = defaults_out

    # Skill-level FX keyed by card_id or card_name
    skills_out = {}
    skills_in = raw.get("skills")
    if isinstance(skills_in, dict):
        for skey, sspec in skills_in.items():
            if not isinstance(skey, str) or not skey.strip():
                continue
            entry = {}
            if isinstance(sspec, str):
                rec = validate_fx_recipe(sspec, base_color=color)
                if rec:
                    entry["on_strike"] = rec
            elif isinstance(sspec, dict):
                # Support direct recipe shorthand on a skill or explicit event hooks
                if any(k in sspec for k in ("vfx", "sfx", "motion", "camera", "script", "fx_script", "fx_prompt", "prompt")):
                    rec = validate_fx_recipe(sspec, base_color=color)
                    if rec:
                        entry["on_strike"] = rec
                for hook in ("on_cast", "on_strike", "on_hit", "on_clash_win", "on_clash_lose"):
                    if hook in sspec:
                        rec = validate_fx_recipe(sspec[hook], base_color=color)
                        if rec:
                            entry[hook] = rec
                dice_in = sspec.get("dice")
                if isinstance(dice_in, dict):
                    dice_out = {}
                    for dkey, dspec in dice_in.items():
                        rec = validate_fx_recipe(dspec, base_color=color)
                        if rec:
                            dice_out[str(dkey)] = rec
                    if dice_out:
                        entry["dice"] = dice_out
            if entry:
                skills_out[skey.strip()] = entry
    if skills_out:
        manifest["skills"] = skills_out

    # Passive-level FX keyed by passive name
    passives_out = {}
    passives_in = raw.get("passives")
    if isinstance(passives_in, dict):
        for pkey, pspec in passives_in.items():
            if not isinstance(pkey, str) or not pkey.strip():
                continue
            rec = validate_fx_recipe(pspec, base_color=color)
            if rec:
                passives_out[pkey.strip()] = rec
    if passives_out:
        manifest["passives"] = passives_out

    return manifest


def _extract_inline_character_fx(spec, *, base_color=None):
    """Extract optional inline `fx` / `fx_prompt` definitions embedded inside a character pack spec."""
    raw = {}
    if isinstance(spec.get("fx"), dict):
        raw = dict(spec["fx"])
    elif isinstance(spec.get("fx_prompt"), str):
        raw = {"defaults": {"strike": spec["fx_prompt"]}}

    skills_map = dict(raw.get("skills") or {})
    for skill in spec.get("skills") or ():
        sid = skill.get("id")
        if not sid:
            continue
        if "fx" in skill or "fx_prompt" in skill:
            skills_map[sid] = skill.get("fx") if "fx" in skill else skill.get("fx_prompt")
        else:
            dice_fx = {}
            for idx, die in enumerate(skill.get("dice") or (), 1):
                if "fx" in die or "fx_prompt" in die:
                    dice_fx[str(idx)] = die.get("fx") if "fx" in die else die.get("fx_prompt")
            if dice_fx:
                skills_map[sid] = {"dice": dice_fx}
    if skills_map:
        raw["skills"] = skills_map

    passives_map = dict(raw.get("passives") or {})
    for passive in spec.get("passive_skills") or ():
        pname = passive.get("name")
        if pname and ("fx" in passive or "fx_prompt" in passive):
            passives_map[pname] = passive.get("fx") if "fx" in passive else passive.get("fx_prompt")
    if passives_map:
        raw["passives"] = passives_map

    return normalize_character_fx_manifest(raw, base_color=base_color)


def _merge_manifests(base, override):
    out = {
        "defaults": {**(base.get("defaults") or {}), **(override.get("defaults") or {})},
        "skills": {**(base.get("skills") or {}), **(override.get("skills") or {})},
        "passives": {**(base.get("passives") or {}), **(override.get("passives") or {})},
    }
    return {k: v for k, v in out.items() if v}


def discover_character_fx(pool, character_colors=None, *, fx_dir=None):
    """Load & compile FX manifests from inline pack specs + `_packs/fx/<char_id>.json`."""
    root = (fx_dir if fx_dir is not None else FX_DIR).resolve()
    colors = character_colors or {}
    manifests = {}

    for cid, spec in pool.items():
        base_col = colors.get(cid) or spec.get("color") or spec.get("card_color")
        inline_manifest = _extract_inline_character_fx(spec, base_color=base_col)
        external_manifest = {}
        if root.is_dir():
            candidates = []
            explicit = spec.get("fx_file")
            if isinstance(explicit, str) and explicit.strip():
                candidates.append(explicit.strip().lstrip("/"))
            candidates.append(f"{cid}.json")
            for rel in candidates:
                if "\\" in rel or ".." in rel.split("/") or not rel.lower().endswith(".json"):
                    continue
                target = (root / rel).resolve()
                try:
                    target.relative_to(root)
                except ValueError:
                    continue
                if target.is_file():
                    data = json.loads(target.read_text(encoding="utf-8-sig"))
                    external_manifest = normalize_character_fx_manifest(data, base_color=base_col)
                    break
        merged = _merge_manifests(inline_manifest, external_manifest)
        if merged:
            manifests[cid] = merged

    return manifests


def discover_fx_scripts(*, scripts_dir=None):
    """List available custom JS FX script URLs under `_packs/fx_scripts/*.js`."""
    root = (scripts_dir if scripts_dir is not None else FX_SCRIPTS_DIR).resolve()
    if not root.is_dir():
        return {}
    found = {}
    for path in sorted(root.glob("*.js")):
        if path.is_file():
            found[path.stem] = f"/fx_scripts/{path.name}"
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description="光点计划 III · 自然语言特效编译器")
    parser.add_argument("--prompt", type=str, help="将中文/英文自然语言特效描述编译为标准 FX DSL JSON")
    parser.add_argument("--color", type=str, default=DEFAULT_GOLD_HEX, help="角色默认主色（如 #1c946b）")
    parser.add_argument("--compile-pack", type=str, help="读取包含 fx_prompt 的 JSON 文件并输出编译后的标准 FX JSON")
    parser.add_argument("--write", action="store_true", help="与 --compile-pack 联用，直接写回目标文件")
    args = parser.parse_args(argv)

    if args.prompt:
        compiled = compile_prompt_to_recipe(args.prompt, base_color=args.color)
        print(json.dumps(compiled, ensure_ascii=False, indent=2))
        return 0

    if args.compile_pack:
        path = Path(args.compile_pack)
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        compiled = normalize_character_fx_manifest(raw, base_color=args.color)
        text = json.dumps(compiled, ensure_ascii=False, indent=2) + "\n"
        if args.write:
            path.write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
