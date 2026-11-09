"""The designer's own screen preferences on this PC, in one file beside the other per-user files
(~/Sida/preferences.json), as desktop programs keep theirs in the user's folder (2026-11-09 지훈):
how the project list is sorted and ordered, and how the panels beside the drafting table are
docked. Nothing here belongs to a project; what does (its layers, whether its surroundings are on)
stays in the project folder.

Each part is a key of the file. A part saved before in the projects folder (`.project_list.json`,
`.panel_layout.json`, until 2026-11-09) is moved in the first time it is read.
"""

from __future__ import annotations

import json
from pathlib import Path

from sida.storage import atomic_write_text

PREFS_PATH = Path.home() / "Sida" / "preferences.json"


def read_all() -> dict:
    """The whole file ({} when there is none or it is unreadable)."""
    try:
        data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, old_file: Path | None = None):
    """One part (None when never saved). `old_file`: where it was kept before; moved in once."""
    data = read_all()
    if key in data:
        return data[key]
    if old_file is None:
        return None
    try:
        moved = json.loads(Path(old_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    put(key, moved)
    try:
        Path(old_file).unlink()
    except OSError:
        pass
    return moved


def put(key: str, value) -> None:
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(PREFS_PATH, json.dumps({**read_all(), key: value}, ensure_ascii=False, indent=1) + "\n")
