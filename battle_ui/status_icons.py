"""Custom status-effect icon & color discovery for 《光点计划 III》.

Allows any status effect to provide its own icon and color via three zero-code paths:
  1. Convention SVG file: `_packs/status_icons/<status_name>.svg` or `<alias>.svg`
  2. Inline fields inside `status_rules[<name>]` (in `_packs/effects/*.json` or any `_packs/*.json`):
       - `color`: hex color (sanitized to bright sunlit palette)
       - `icon_svg`: filename under `_packs/status_icons/` OR inline `<svg ...>...</svg>` markup
       - `icon_path`: SVG path `d` string (or list of `d` strings) inside standard `viewBox="0 0 24 24"`
       - `icon_symbol`: 1-2 char crisp text glyph fallback
  3. Optional manifest `_packs/status_icons/manifest.json` mapping status names to the fields above.
"""

import json
import re
from pathlib import Path
from urllib.parse import quote

from loader import PACKS, base_effects

from .fx_compiler import sanitize_bright_hex


STATUS_ICONS_DIR = PACKS / "status_icons"
_SAFE_INLINE_SVG_BLOCKLIST = re.compile(r"<\s*script|on[a-z]+\s*=|javascript:", re.IGNORECASE)


def _resolve_icon_file(filename, root):
    if not isinstance(filename, str):
        return None
    rel = filename.strip().lstrip("/")
    if not rel or "\\" in rel or ".." in rel.split("/") or not rel.lower().endswith(".svg"):
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    rel_posix = target.relative_to(root).as_posix()
    return f"/status_icons/{quote(rel_posix, safe='/')}"


def _sanitize_inline_svg(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text.lower().startswith("<svg") or not text.lower().endswith("</svg>"):
        return None
    if len(text) > 16384 or _SAFE_INLINE_SVG_BLOCKLIST.search(text):
        return None
    return text


def _sanitize_icon_path(raw):
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()[:1024]]
    if isinstance(raw, list):
        cleaned = [item.strip()[:1024] for item in raw[:8] if isinstance(item, str) and item.strip()]
        return cleaned or None
    return None


def _normalize_status_visual(spec, *, root):
    if not isinstance(spec, dict):
        return {}
    out = {}
    if "color" in spec:
        col = sanitize_bright_hex(spec["color"], None)
        if col:
            out["color"] = col

    raw_svg = spec.get("icon_svg") or spec.get("icon")
    if isinstance(raw_svg, str) and raw_svg.strip():
        inline = _sanitize_inline_svg(raw_svg)
        if inline:
            out["icon_svg"] = inline
        else:
            url = _resolve_icon_file(raw_svg, root)
            if url:
                out["icon_url"] = url

    paths = _sanitize_icon_path(spec.get("icon_path"))
    if paths:
        out["icon_path"] = paths

    sym = spec.get("icon_symbol")
    if isinstance(sym, str) and sym.strip():
        out["icon_symbol"] = sym.strip()[:2]

    return out


def discover_status_visuals(pool=None, *, icons_dir=None):
    """Collect custom status colors & SVG/path/symbol icons from packs, manifest, and `_packs/status_icons/*.svg`."""
    root = (icons_dir if icons_dir is not None else STATUS_ICONS_DIR).resolve()
    visuals = {}

    # 1. Gather all known status_rules (shared effects + any character pack status_rules)
    all_rules = dict(base_effects().status_rules)
    if isinstance(pool, dict):
        for spec in pool.values():
            if isinstance(spec, dict) and isinstance(spec.get("status_rules"), dict):
                for sname, rule in spec["status_rules"].items():
                    all_rules.setdefault(sname, rule)

    # 2. Extract inline visual hints from status_rules
    for sname, rule in all_rules.items():
        if not isinstance(rule, dict):
            continue
        vis = _normalize_status_visual(rule, root=root)
        if vis:
            visuals[sname] = vis

    # 3. Overlay optional `_packs/status_icons/manifest.json`
    if root.is_dir():
        manifest_path = root / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except (ValueError, OSError):
                manifest = {}
            if isinstance(manifest, dict):
                for sname, spec in manifest.items():
                    if isinstance(sname, str) and sname.strip():
                        vis = _normalize_status_visual(spec, root=root)
                        if vis:
                            visuals[sname] = {**visuals.get(sname, {}), **vis}

        # 4. Convention-based `_packs/status_icons/<name>.svg` (and `<alias>.svg`)
        #    Auto-discovers every `.svg` in `_packs/status_icons/` even for statuses not listed in base_effects!
        for svg_file in sorted(root.glob("*.svg")):
            if not svg_file.is_file():
                continue
            stem = svg_file.stem
            url = _resolve_icon_file(svg_file.name, root)
            if not url:
                continue
            # Direct status name match
            if stem not in visuals or ("icon_url" not in visuals[stem] and "icon_svg" not in visuals[stem]):
                visuals.setdefault(stem, {})["icon_url"] = url

        # Also map alias filenames (e.g. `burn.svg` -> `烧伤`) when canonical name lacks a file
        for sname, rule in all_rules.items():
            if not isinstance(rule, dict):
                continue
            if "icon_url" in visuals.get(sname, {}) or "icon_svg" in visuals.get(sname, {}):
                continue
            for alias in rule.get("aliases") or ():
                url = _resolve_icon_file(f"{alias}.svg", root)
                if url:
                    visuals.setdefault(sname, {})["icon_url"] = url
                    break

    return visuals
