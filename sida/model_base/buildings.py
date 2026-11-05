"""
Buildings around the site on the model base.

A building with a known height is cut as a stack of its footprint, one sheet per layer, standing
on the step of the lowest ground along its outline; the layers above that step get its footprint
cut out, so the stack sits flat and the cut-outs hold its sheets on the sheet layout. A building
without a height is never given a made-up one: only its footprint is engraved where it shows.

`buildings_from_context` reads the drawing table's surroundings (sida/experts/site/context3d.py:
"buildings" with outline, base, ground, height, height_source; "unknown_buildings" with outline)
in the table's frame. Heights taken from VWorld's API for the screen only ("api_estimate") are
not written into cutting files: such a building uses its offline estimate, or stays a footprint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon

ESTIMATES = ("estimate", "api_estimate", "map_estimate")  # floors × a storey height


@dataclass(frozen=True)
class Building:
    outline: Polygon  # the drawing table's metres
    base_z: float  # table z of the lowest ground along the outline
    top_z: float | None = None  # table z of the roof; None when the height is not known
    estimated: bool = False  # the height is floors × a storey height
    name: str = ""


def seat(b: Building, *, base: float, interval: float, datum: float, layers: int) -> tuple[int, int]:
    """
    (layer, sheets) for a building with a height: the step of its lowest ground (layer k is the
    ground at or above base + k × interval, metres above sea level) and how many sheets of one
    interval each reach its roof from that step's top, at least one.
    """
    k = min(layers - 1, max(0, math.floor((b.base_z + datum - base) / interval + 1e-9)))
    return k, max(1, round((b.top_z + datum - (base + k * interval)) / interval))


def _outline(points) -> Polygon | None:
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(pts) < 3:
        return None
    poly = Polygon(pts).buffer(0)
    return poly if isinstance(poly, Polygon) and poly.area > 0 else None


def buildings_from_context(around: dict, *, include_site: bool = False) -> list[Building]:
    """The surroundings' buildings for the model; those on the site are left out unless asked for."""
    out = []
    for b in around.get("buildings") or []:
        if b.get("on_site") and not include_site:
            continue
        outline = _outline(b.get("outline") or [])
        if outline is None:
            continue
        height, source = b.get("height"), b.get("height_source", "")
        if source == "api_estimate":
            offline = b.get("offline") or {}
            height, source = offline.get("height"), offline.get("source", "")
        top = float(b["ground"]) + float(height) if height else None
        out.append(Building(outline=outline, base_z=float(b["base"]), top_z=top,
                            estimated=source in ESTIMATES and top is not None, name=b.get("name") or ""))
    for b in around.get("unknown_buildings") or []:
        outline = _outline(b.get("outline") or [])
        if outline is not None:
            out.append(Building(outline=outline, base_z=float(b.get("base", 0.0)), name=b.get("name") or ""))
    return out
