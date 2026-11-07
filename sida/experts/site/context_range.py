"""The range of a site's surroundings the designer picked (size, shape and, for a rectangle, its
orientation), kept per project.

The site domain owns it: site_context.json in the project folder, {"size", "shape", "orient"}
(other keys in the file, such as the model settings, are kept). Without one, the surroundings are
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


MODEL = "model"  # the last model board settings (sida/experts/site/model_base.settings), as given


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
