"""Resolve bundled battle assets shared by the local table and the room."""

from pathlib import Path
from urllib.parse import unquote

from loader import PACKS


STATIC_DIR = Path(__file__).with_name("static").resolve()
SPRITES_DIR = (PACKS / "sprites").resolve()
FX_SCRIPTS_DIR = (PACKS / "fx_scripts").resolve()
FX_ASSETS_DIR = (PACKS / "fx_assets").resolve()
SFX_DIR = (PACKS / "sfx").resolve()
STATUS_ICONS_DIR = (PACKS / "status_icons").resolve()
CONTENT_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}


def _resolve_pack_asset(root_dir, raw_rel, allowed_exts):
    rel = unquote(raw_rel)
    if not rel or "\\" in rel or ".." in rel.split("/"):
        return None
    target = (root_dir / rel).resolve()
    try:
        target.relative_to(root_dir)
    except ValueError:
        return None
    ext = target.suffix.lower()
    if ext not in allowed_exts or not target.is_file():
        return None
    return target, CONTENT_TYPES[ext]


def resolve_static(path):
    if path.startswith("/sprites/"):
        return _resolve_pack_asset(SPRITES_DIR, path[len("/sprites/"):], (".svg",))

    if path.startswith("/fx_scripts/"):
        return _resolve_pack_asset(FX_SCRIPTS_DIR, path[len("/fx_scripts/"):], (".js",))

    if path.startswith("/fx_assets/"):
        return _resolve_pack_asset(FX_ASSETS_DIR, path[len("/fx_assets/"):], (".svg", ".png"))

    if path.startswith("/sfx/"):
        return _resolve_pack_asset(SFX_DIR, path[len("/sfx/"):], (".ogg", ".wav", ".mp3"))

    if path.startswith("/status_icons/"):
        return _resolve_pack_asset(STATUS_ICONS_DIR, path[len("/status_icons/"):], (".svg",))

    rel = "index.html" if path == "/" else path.lstrip("/")
    if not rel or "\\" in rel or ".." in rel.split("/"):
        return None
    target = (STATIC_DIR / rel).resolve()
    try:
        target.relative_to(STATIC_DIR)
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = CONTENT_TYPES.get(target.suffix.lower())
    if ctype is None:
        return None
    return target, ctype

