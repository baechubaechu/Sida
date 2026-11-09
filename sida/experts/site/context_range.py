"""The range of a site's surroundings the designer picked (size, shape and, for a rectangle, its
orientation), kept per project.

The site domain owns it: site_context.json in the project folder, {"size", "shape", "orient"}
(other keys in the file, such as the model settings, are kept). `shown` (2026-11-09 지훈) says the
surroundings were on when the designer last left the table, so they come back after a reload. Without one, the surroundings are
context3d.DEFAULT_SIZE (200 m), DEFAULT_SHAPE (square) and DEFAULT_ORIENT (landscape).
"""

from __future__ import annotations

import json
from pathlib import Path

from sida.experts.site import context3d
from sida.storage import atomic_write_text

FILE = "site_context.json"


def check(size: str, shape: str, orient: str = context3d.DEFAULT_ORIENT) -> tuple[str, str, str]:
    """The size, shape and orientation if all are known ones; ValueError otherwise."""
    if size not in context3d.SIZES:
        raise ValueError(f"size must be one of {', '.join(context3d.SIZES)}")
    context3d.range_key(shape, orient)
    return size, shape, orient


def read(project_dir: Path) -> dict:
    """The whole file ({} when there is none or it is unreadable)."""
    try:
        data = json.loads((Path(project_dir) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(project_dir: Path, data: dict) -> None:
    atomic_write_text(Path(project_dir) / FILE, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _out(size: str, shape: str, orient: str) -> dict:
    return {"size": size, "shape": shape, "orient": orient, "radius": context3d.SIZES[size]}


def load(project_dir: Path) -> dict:
    """{"size", "shape", "orient", "radius"}: the saved range, or the default (also for an
    unreadable file)."""
    data = read(project_dir)
    try:
        return _out(*check(str(data.get("size")), str(data.get("shape")),
                           str(data.get("orient") or context3d.DEFAULT_ORIENT)))
    except ValueError:
        return _out(context3d.DEFAULT_SIZE, context3d.DEFAULT_SHAPE, context3d.DEFAULT_ORIENT)


SHOWN = "shown"


def shown(project_dir: Path) -> bool:
    """Were the surroundings on the table when last left?"""
    return read(project_dir).get(SHOWN) is True


def save_shown(project_dir: Path, on: bool) -> bool:
    write(project_dir, {**read(project_dir), SHOWN: bool(on)})
    return bool(on)


HIDDEN_PARTS = "hidden_parts"  # parts of the surroundings turned off in the 레이어 panel (ground, contours, ...)
MAX_PARTS = 12


def hidden_parts(project_dir: Path) -> list[str]:
    saved = read(project_dir).get(HIDDEN_PARTS)
    return [p for p in saved if isinstance(p, str)][:MAX_PARTS] if isinstance(saved, list) else []


def save_hidden_parts(project_dir: Path, parts: list) -> list[str]:
    """Keep which parts are off. Raises ValueError for something that is not a list of short names."""
    if not isinstance(parts, list) or not all(isinstance(p, str) and 0 < len(p) <= 20 for p in parts):
        raise ValueError("hidden parts must be a list of short names")
    kept = list(dict.fromkeys(parts))[:MAX_PARTS]
    write(project_dir, {**read(project_dir), HIDDEN_PARTS: kept})
    return kept


MODEL = "model"  # the last model board settings (sida/experts/model/model_base.settings), as given


def model(project_dir: Path) -> dict:
    """The model board settings kept for the project ({} when none)."""
    saved = read(project_dir).get(MODEL)
    return saved if isinstance(saved, dict) else {}


def save_model(project_dir: Path, settings: dict) -> None:
    write(project_dir, {**read(project_dir), MODEL: settings})


def save(project_dir: Path, size: str, shape: str, orient: str = context3d.DEFAULT_ORIENT) -> dict:
    """Keep this range for the project. Returns {"size", "shape", "orient", "radius"}. Raises
    ValueError."""
    size, shape, orient = check(size, shape, orient)
    write(project_dir, {**read(project_dir), "size": size, "shape": shape, "orient": orient})
    return _out(size, shape, orient)
