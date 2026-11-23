"""Resolve bundled battle assets shared by the local table and the room."""

from pathlib import Path
from urllib.parse import unquote

from loader import PACKS


STATIC_DIR = Path(__file__).with_name("static").resolve()
SPRITES_DIR = (PACKS / "sprites").resolve()
FX_SCRIPTS_DIR = (PACKS / "fx_scripts").resolve()
STATUS_ICONS_DIR = (PACKS / "status_icons").resolve()
CONTENT_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


def resolve_static(path):
    if path.startswith("/sprites/"):
        rel = path[len("/sprites/"):]
        if not rel or "\\" in rel or ".." in rel.split("/") or not rel.lower().endswith(".svg"):
            return None
        target = (SPRITES_DIR / rel).resolve()
        try:
            target.relative_to(SPRITES_DIR)
        except ValueError:
            return None
        if not target.is_file():
            return None
        return target, CONTENT_TYPES[".svg"]

    if path.startswith("/fx_scripts/"):
        rel = path[len("/fx_scripts/"):]
        if not rel or "\\" in rel or ".." in rel.split("/") or not rel.lower().endswith(".js"):
            return None
        target = (FX_SCRIPTS_DIR / rel).resolve()
        try:
            target.relative_to(FX_SCRIPTS_DIR)
        except ValueError:
            return None
        if not target.is_file():
            return None
        return target, CONTENT_TYPES[".js"]

    if path.startswith("/status_icons/"):
        rel = unquote(path[len("/status_icons/"):])
        if not rel or "\\" in rel or ".." in rel.split("/") or not rel.lower().endswith(".svg"):
            return None
        target = (STATUS_ICONS_DIR / rel).resolve()
        try:
            target.relative_to(STATUS_ICONS_DIR)
        except ValueError:
            return None
        if not target.is_file():
            return None
        return target, CONTENT_TYPES[".svg"]

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

