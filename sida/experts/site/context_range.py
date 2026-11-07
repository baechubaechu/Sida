"""The range of a site's surroundings the designer picked (size and shape), kept per project.

The site domain owns it: site_context.json in the project folder, {"size", "shape"}. Without
one, the surroundings are context3d.DEFAULT_SIZE (200 m) and DEFAULT_SHAPE (square).
"""

from __future__ import annotations

import json
from pathlib import Path

from sida.experts.site import context3d
from sida.storage import atomic_write_text

FILE = "site_context.json"


def check(size: str, shape: str) -> tuple[str, str]:
    """The size and shape if both are known ones; ValueError otherwise."""
    if size not in context3d.SIZES:
        raise ValueError(f"size must be one of {', '.join(context3d.SIZES)}")
    if shape not in context3d.SHAPES:
        raise ValueError(f"shape must be one of {', '.join(context3d.SHAPES)}")
    return size, shape


def load(project_dir: Path) -> dict:
    """{"size", "shape", "radius"}: the saved range, or the default (also for an unreadable file)."""
    size, shape = context3d.DEFAULT_SIZE, context3d.DEFAULT_SHAPE
    try:
        data = json.loads((Path(project_dir) / FILE).read_text(encoding="utf-8"))
        size, shape = check(str(data.get("size")), str(data.get("shape")))
    except (OSError, ValueError, AttributeError):
        pass
    return {"size": size, "shape": shape, "radius": context3d.SIZES[size]}


def save(project_dir: Path, size: str, shape: str) -> dict:
    """Keep this range for the project. Returns {"size", "shape", "radius"}. Raises ValueError."""
    size, shape = check(size, shape)
    atomic_write_text(Path(project_dir) / FILE, json.dumps({"size": size, "shape": shape}, ensure_ascii=False) + "\n")
    return {"size": size, "shape": shape, "radius": context3d.SIZES[size]}
