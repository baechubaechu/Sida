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
from sida.model_base import board
from sida.model_base.buildings import Building, buildings_from_context
from sida.model_base.nesting import nest
from sida.model_base.output import FORMATS, files, parse_formats, zip_files
from sida.model_base.pieces import contour_interval, slice_terrain
from sida.model_base.terraces import terrace_view
from sida.model_base.terrain import Terrain, terrain_from_grid, terrain_in_frame

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
              orient: str = context3d.DEFAULT_ORIENT, formats=FORMATS) -> tuple[bytes, dict]:
    """
    A zip of the laser files for the model ±radius m around the site (a circle of that radius for
    "circle") at 1:scale, one layer per sheet of material `thickness_mm` thick, laid on sheets of
    `sheet` (w, h) mm; and a summary.
    """
    interval = contour_interval(scale, thickness_mm)
    formats = parse_formats(formats)
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
    return zip_files(files(model, layout, formats=formats)), {**summary, "formats": list(formats)}


# ---------------------------------------------------------------------------
# A model board laid on the surroundings (sida/model_base/board.py)
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {"board": "W600x900", "width_mm": None, "height_mm": None, "orient": "landscape",
                    "scale": 500, "thickness_mm": 3.0, "center": None, "bed": None, "save_material": False}
_grounds: dict[tuple, tuple[float, dict]] = {}
_cuts: dict[tuple, tuple[float, tuple]] = {}  # the last board cuts: the files reuse what the plan made


def settings(raw: dict | None) -> dict:
    """Board settings as given (missing ones from DEFAULT_SETTINGS), checked: {board, width_mm,
    height_mm (a custom board's sides), orient, scale, thickness_mm, center [x, y] m or None (the
    site's middle), bed [w, h] mm or None (the board's size), save_material}. Raises ValueError."""
    s = {**DEFAULT_SETTINGS, **{k: v for k, v in (raw or {}).items() if k in DEFAULT_SETTINGS and v is not None}}
    s["board"], s["orient"] = str(s["board"]), str(s["orient"])
    custom = (s["width_mm"], s["height_mm"]) if s["board"] == board.CUSTOM else None
    board.board_size(s["board"], s["orient"], custom)
    s["scale"] = board.check_scale(s["scale"])
    s["thickness_mm"] = board.check_thickness(s["thickness_mm"])
    if s["center"] is not None:
        s["center"] = [float(v) for v in s["center"]]
        if len(s["center"]) != 2:
            raise ValueError("center is [x, y] in metres")
    if s["bed"] is not None:
        s["bed"] = [float(v) for v in s["bed"]]
        if len(s["bed"]) != 2 or not all(board.MIN_BOARD_MM <= v <= board.MAX_BOARD_MM for v in s["bed"]):
            raise ValueError(f"bed is [w, h], {board.MIN_BOARD_MM:g}–{board.MAX_BOARD_MM:g} mm")
    s["save_material"] = bool(s["save_material"])
    if s["board"] != board.CUSTOM:
        s["width_mm"] = s["height_mm"] = None
    return s


def _board_mm(s: dict) -> tuple[float, float]:
    custom = (s["width_mm"], s["height_mm"]) if s["board"] == board.CUSTOM else None
    return board.board_size(s["board"], s["orient"], custom)


def _range_poly(radius: float, shape: str, orient: str) -> Polygon:
    return range_outline(radius, shape, orient) or box(-radius, -radius, radius, radius)


def _ground(plan: dict, radius: float, folder: Path | None) -> dict:
    origin = plan["origin"]
    key = (origin["lon"], origin["lat"], float(radius), str(folder))
    hit = _grounds.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    g = context3d.ground(context3d.Frame(origin), radius, folder=folder)
    if g["grid"] is None:
        raise NoTerrain("no terrain pack covers this site")
    _grounds[key] = (time.time(), g)
    return g


def fit_board(plan: dict, *, radius: float, shape: str = context3d.DEFAULT_SHAPE,
              range_orient: str = context3d.DEFAULT_ORIENT, board_name: str = "W600x900",
              orient: str = "landscape", custom: tuple[float, float] | None = None) -> dict:
    """The standard scale at which the board covers as much of the range as it can, holding the
    site, and where it sits (board.fit): {"scale", "center", "frame_m", "board_mm"}. Raises
    ValueError (board.NoFit when no standard scale does)."""
    if not (plan or {}).get("origin"):
        raise ValueError("the site has no boundary to stand on")
    size = board.board_size(board_name, orient, custom)
    out = board.fit(size, _range_poly(float(radius), shape, range_orient), _site(plan))
    return {**out, "board_mm": list(size)}


def _board_terrain(plan: dict, s: dict, radius: float, shape: str, range_orient: str,
                   folder: Path | None) -> tuple[Terrain, list[float], tuple[float, float], tuple[float, float]]:
    if not (plan or {}).get("origin"):
        raise ValueError("the site has no boundary to stand on")
    size = _board_mm(s)
    frame_m = board.frame_size(size, s["scale"])
    site = _site(plan)
    if s["center"] is not None:
        center = s["center"]
    elif site is not None:
        x0, y0, x1, y1 = site.bounds
        center = [(x0 + x1) / 2, (y0 + y1) / 2]
    else:
        center = [0.0, 0.0]
    board.check_frame(center, frame_m, _range_poly(float(radius), shape, range_orient))
    g = _ground(plan, radius, folder)
    terrain = terrain_in_frame(g["grid"], g["half"], g["step"], center=center, width_m=frame_m[0],
                               depth_m=frame_m[1], base_elev=g["ground_elev"], site=site, areas=g["areas"])
    return terrain, [round(v, 2) for v in center], frame_m, size


def board_cut(plan: dict, raw: dict | None, *, radius: float, shape: str = context3d.DEFAULT_SHAPE,
              range_orient: str = context3d.DEFAULT_ORIENT, folder: Path | None = None,
              around: dict | None = None) -> tuple[board.BoardCut, dict, Terrain]:
    """The board cut (board.cut) for these settings over the site's range, its summary and the
    ground under it. Raises board.FrameOutside when the board reaches past the range, ValueError
    for bad settings, NoTerrain without a terrain pack."""
    s = settings(raw)
    terrain, center, frame_m, size = _board_terrain(plan, s, radius, shape, range_orient, folder)
    rings = tuple(tuple(map(tuple, r)) for p in plan.get("parcels") or [] for r in p.get("rings") or [])
    key = (plan["origin"]["lon"], plan["origin"]["lat"], float(radius), shape, range_orient, str(folder), rings,
           repr(sorted({**s, "center": center}.items())))
    hit = _cuts.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    if around is None:
        around = context3d.build(plan, radius, folder=folder, for_export=True, shape=shape, orient=range_orient)
    made = board.cut(terrain, scale=s["scale"], thickness_mm=s["thickness_mm"], board_mm=size,
                     buildings=_buildings(around, for_files=True), bed_mm=tuple(s["bed"]) if s["bed"] else None,
                     save_material=s["save_material"])
    summary = {
        **made.summary(), "scale": s["scale"], "thickness_mm": s["thickness_mm"], "board": s["board"],
        "orient": s["orient"], "board_mm": list(size), "frame_m": [round(v, 2) for v in frame_m], "center": center,
        "buildings_left_out": not made.model.buildings and bool(around.get("buildings")),
    }
    _cuts.clear()  # one at a time: a cut holds every piece
    _cuts[key] = (time.time(), (made, summary, terrain))
    return made, summary, terrain


def board_plan(plan: dict, raw: dict | None, **range_kw) -> dict:
    """The board for drawing: the summary, the frame's outline and each layer's ground (table
    metres, terraces.terrace_view steps)."""
    made, summary, terrain = board_cut(plan, raw, **range_kw)
    x0, y0 = terrain.origin
    w, h = summary["frame_m"]
    view = terrace_view(terrain, made.model.interval_m)
    frame = [[round(x0, 2), round(y0, 2)], [round(x0 + w, 2), round(y0, 2)],
             [round(x0 + w, 2), round(y0 + h, 2)], [round(x0, 2), round(y0 + h, 2)]]
    return {**summary, "frame": frame, "steps": view["steps"], "base_elev": view["base_elev"]}


def board_files(plan: dict, raw: dict | None, *, formats=FORMATS, **range_kw) -> tuple[bytes, dict]:
    """A zip of the board's laser files in `formats` (output.FORMATS: dxf, pdf, svg) and its
    summary. Raises ValueError for an unknown format."""
    formats = parse_formats(formats)
    made, summary, _ = board_cut(plan, raw, **range_kw)
    return zip_files(files(made.model, made.layout, formats=formats)), {**summary, "formats": list(formats)}
