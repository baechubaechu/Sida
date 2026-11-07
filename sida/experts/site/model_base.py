"""
Model bases for a site: the ground around it stepped by a contour interval the designer picks,
the buildings standing on it, and laser files to cut it (the slicing is sida/model_base).

The ground is the terrain packs' 2 m grid (context3d.ground), the buildings are the drawing
table's surroundings (context3d.build). Both are in the table's frame, so the stepped model
lines up with the site and the schemes on the table.

Cutting files are written down and kept by the designer, so they hold only what may be: the
ground from the packs and, when the buildings come from a GIS건물통합정보 pack, those buildings.
VWorld's live outlines and floors (이용약관 제19조) stay on the screen.
"""

from __future__ import annotations

import time
from pathlib import Path

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from sida.experts.site import context3d
from sida.model_base.buildings import Building, buildings_from_context
from sida.model_base.nesting import nest
from sida.model_base.output import files, zip_files
from sida.model_base.pieces import contour_interval, slice_terrain
from sida.model_base.terraces import terrace_view
from sida.model_base.terrain import Terrain, terrain_from_grid

CACHE_SECONDS = 600
MIN_INTERVAL, MAX_INTERVAL = 0.2, 20.0  # m
_cache: dict[tuple, tuple[float, Terrain]] = {}


class NoTerrain(ValueError):
    """No terrain pack covers the site."""


def _site(plan: dict):
    rings = [r for p in plan.get("parcels") or [] for r in p.get("rings") or [] if len(r) >= 3]
    return unary_union([Polygon(r).buffer(0) for r in rings]) if rings else None


def range_outline(radius: float, shape: str = context3d.DEFAULT_SHAPE, orient: str = context3d.DEFAULT_ORIENT):
    """The range as a shapely outline in the table frame (m), or None for a square (the grid's own
    edge). Raises ValueError for an unknown shape or orientation."""
    key = context3d.range_key(shape, orient)
    if key == "circle":
        return Point(0.0, 0.0).buffer(radius, quad_segs=32)
    if key == "square":
        return None
    hx, hy = context3d.half_sides(radius, key)
    return box(-hx, -hy, hx, hy)


def site_terrain(plan: dict, radius: float, *, folder: Path | None = None, use_cache: bool = True,
                 shape: str = context3d.DEFAULT_SHAPE, orient: str = context3d.DEFAULT_ORIENT) -> Terrain:
    """The ground ±radius m around the site's middle (a circle of that radius for "circle", the
    rectangle of context3d.half_sides for "rect"), as the model slices it."""
    origin = (plan or {}).get("origin")
    if not origin:
        raise ValueError("the site has no boundary to stand on")
    radius = float(radius)
    if not 50 <= radius <= context3d.MAX_RADIUS:
        raise ValueError(f"radius must be 50–{context3d.MAX_RADIUS:g} m")
    shape_key = context3d.range_key(shape, orient)
    hx, hy = context3d.half_sides(radius, shape_key)
    boundary = range_outline(radius, shape, orient) if shape_key == "circle" else None  # a rectangle is the grid cut to it
    rings = tuple(tuple(map(tuple, r)) for p in plan.get("parcels") or [] for r in p.get("rings") or [])
    key = (origin["lon"], origin["lat"], radius, shape_key, str(folder), rings)
    hit = _cache.get(key)
    if use_cache and hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    g = context3d.ground(context3d.Frame(origin), radius, folder=folder)
    if g["grid"] is None:
        raise NoTerrain("no terrain pack covers this site")
    terrain = terrain_from_grid(g["grid"], g["half"], g["step"], width_m=2 * hx, depth_m=2 * hy,
                                base_elev=g["ground_elev"], site=_site(plan), areas=g["areas"],
                                boundary=boundary)
    _cache[key] = (time.time(), terrain)
    return terrain


def _buildings(around: dict, *, for_files: bool) -> list[Building]:
    if for_files and not (around.get("building_source") or {}).get("pack"):
        return []  # VWorld's live outlines are for the screen only
    return buildings_from_context(around)


def stepped(plan: dict, interval: float, radius: float = context3d.DEFAULT_RADIUS, *,
            folder: Path | None = None, around: dict | None = None, shape: str = context3d.DEFAULT_SHAPE,
            orient: str = context3d.DEFAULT_ORIENT) -> dict:
    """The stepped ground and its buildings for the drawing table (terraces.terrace_view), cut to
    the range's square, circle or rectangle."""
    if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
        raise ValueError(f"interval must be {MIN_INTERVAL:g}–{MAX_INTERVAL:g} m")
    terrain = site_terrain(plan, radius, folder=folder, shape=shape, orient=orient)
    if around is None:
        around = context3d.build(plan, radius, folder=folder, shape=shape, orient=orient)
    view = terrace_view(terrain, interval, buildings=_buildings(around, for_files=False))
    return {**view, "radius": float(radius), "shape": shape, "orient": orient}


def cut_files(plan: dict, *, radius: float, scale: int, thickness_mm: float, sheet: tuple[float, float],
              hollow_rim_mm: float = 0.0, folder: Path | None = None, around: dict | None = None,
              res: float = 2.0, rotations: int = 4, shape: str = context3d.DEFAULT_SHAPE,
              orient: str = context3d.DEFAULT_ORIENT) -> tuple[bytes, dict]:
    """
    A zip of the laser files for the model ±radius m around the site (a circle of that radius for
    "circle") at 1:scale, one layer per sheet of material `thickness_mm` thick, laid on sheets of
    `sheet` (w, h) mm; and a summary.
    """
    interval = contour_interval(scale, thickness_mm)
    terrain = site_terrain(plan, radius, folder=folder, shape=shape, orient=orient)
    if around is None:
        around = context3d.build(plan, radius, folder=folder, for_export=True, shape=shape, orient=orient)
    buildings = _buildings(around, for_files=True)
    margin, gap = 5.0, 2.0
    w, h = sheet
    model = slice_terrain(terrain, scale=scale, thickness_mm=thickness_mm, hollow_rim_mm=hollow_rim_mm,
                          room=(w - 2 * margin - gap, h - 2 * margin - gap), buildings=buildings)
    layout = nest(model.pieces, w, h, gap=gap, margin=margin, res=res, rotations=rotations)
    summary = {
        "interval": interval, "layers": len(model.layers), "pieces": len(model.pieces),
        "sheets": layout.sheets, "modules": len(model.modules), "buildings": len(model.buildings),
        "buildings_left_out": not buildings and bool(around.get("buildings")),
        "utilisation": round(layout.utilisation(), 3), "size_mm": [round(v, 1) for v in model.size_mm],
        "radius": float(radius), "shape": shape, "orient": orient,
        "size": next((name for name, r in context3d.SIZES.items() if r == float(radius)), None),
    }
    return zip_files(files(model, layout)), summary
