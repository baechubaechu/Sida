"""
The ground sliced into layers one material thickness apart, and each layer into pieces.

Units from here on are millimetres on the model: 1 m on the ground is 1000 / scale mm, and the
south-west corner of the model is (0, 0), x east and y north. A layer k is the ground at or
above `base + k × interval`, where the interval is the height one sheet of material stands for
(thickness × scale / 1000 m). Layer 0 is the whole model area: the base plate.

When the model is bigger than a sheet, the whole model is first cut into modules (halves, then
quarters…) along straight lines right through every layer, as a study model made of two boards
is. Within a module every layer piece fits a sheet, so nothing else is cut.

Every piece carries what the designer needs to put it back:
- `id` like "1-03B": module 1, layer 3, its second part (parts read north to south, then west to
  east). With one module the id is just "03B".
- `engrave`: lines scored on the piece: where the next layer sits (to line it up), and the
  parts of the site boundary and of the edges of roads, pavements and water that show on
  this piece
- `label_at` / `label_room`: a spot for the id, preferably where the next layer will cover
  it, and the radius free around it
"""

from __future__ import annotations

import math
import string
from dataclasses import dataclass, field

import contourpy
import numpy as np
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box
from shapely.ops import polylabel, unary_union

from sida.model_base.terrain import Terrain

MIN_PIECE_MM2 = 12.0  # smaller bits are not worth cutting (and fall through the laser grid)
MIN_LABEL_ROOM = 2.2  # mm of free radius needed to engrave an id
OVERLAP = 0.05  # mm: tolerance for "inside" tests


@dataclass
class Piece:
    id: str
    layer: int
    level_m: float  # contour height this layer stands for: the ground at or above it
    shape: Polygon  # model mm
    module: int = 1
    engrave: list[LineString] = field(default_factory=list)
    label_at: tuple[float, float] = (0.0, 0.0)
    label_room: float = 0.0
    label_hidden: bool = True  # the id sits where the next layer covers it
    show_at: tuple[float, float] = (0.0, 0.0)  # where the id is written on the assembly map (a part that shows)
    show_room: float = 0.0

    @property
    def area(self) -> float:
        return self.shape.area

    @property
    def holed(self) -> bool:
        return bool(self.shape.interiors)


@dataclass
class ModelPlan:
    scale: int
    thickness_mm: float
    interval_m: float
    base_m: float
    size_mm: tuple[float, float]
    modules: list[Polygon]  # the model cut into these rectangles, numbered from 1, north-west first
    layers: list[MultiPolygon]  # layer regions over the whole model, model mm
    pieces: list[Piece]
    site_mm: Polygon | None
    dropped: int = 0  # bits too small to cut
    areas_mm: list[tuple[str, Polygon | MultiPolygon]] = field(default_factory=list)  # road, sidewalk, water


def contour_interval(scale: int, thickness_mm: float) -> float:
    """Metres of ground one sheet of material stands for: 3 mm at 1:500 is 1.5 m."""
    if scale <= 0 or thickness_mm <= 0:
        raise ValueError("scale and thickness must be positive")
    return thickness_mm * scale / 1000.0


def fits(w: float, h: float, room_w: float, room_h: float) -> bool:
    return (w <= room_w and h <= room_h) or (h <= room_w and w <= room_h)


def module_grid(size_mm: tuple[float, float], room_w: float, room_h: float) -> tuple[int, int]:
    """
    How to cut the model so each module fits the room on a sheet: (columns, rows), as few modules
    as possible, halving the long side first. (1, 1) when the model fits whole.
    """
    w, h = size_mm
    for count in range(1, 65):
        options = [(c, count // c) for c in range(1, count + 1) if count % c == 0]
        options.sort(key=lambda cr: abs(w / cr[0] - h / cr[1]))  # squarest modules first
        for cols, rows in options:
            if fits(w / cols, h / rows, room_w, room_h):
                return cols, rows
    raise ValueError("the model needs more than 64 modules for this sheet")


def module_boxes(size_mm: tuple[float, float], cols: int, rows: int) -> list[Polygon]:
    w, h = size_mm
    return [box(c * w / cols, r * h / rows, (c + 1) * w / cols, (r + 1) * h / rows)
            for r in range(rows - 1, -1, -1) for c in range(cols)]  # north row first, west to east


def _polygons(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]


def _lines(geom) -> list[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]


def _region_at(cg, level: float, top: float) -> Polygon | MultiPolygon:
    points, offsets = cg.filled(level, top)
    shapes = []
    for pts, offs in zip(points, offsets, strict=True):
        rings = [pts[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
        if len(rings[0]) >= 4:
            shapes.append(Polygon(rings[0], [r for r in rings[1:] if len(r) >= 4]).buffer(0))
    return unary_union(shapes) if shapes else Polygon()


def _letters(i: int) -> str:
    letters = string.ascii_uppercase
    return letters[i] if i < 26 else letters[i // 26 - 1] + letters[i % 26]


def _label_spot(region) -> tuple[tuple[float, float], float]:
    best = (0.0, 0.0), 0.0
    for poly in _polygons(region):
        if poly.area < 1:
            continue
        p = polylabel(poly, tolerance=0.2)
        room = poly.boundary.distance(p)
        if room > best[1]:
            best = (p.x, p.y), room
    return best


def layer_regions(terrain: Terrain, interval: float) -> tuple[float, list[Polygon | MultiPolygon]]:
    """
    The ground as steps `interval` m apart, in the terrain's own metres: (base, regions), where
    region k is the ground at or above base + k × interval and region 0 is the whole extent.
    `base` is the highest multiple of the interval at or below the lowest ground, so layers fall
    on round heights.
    """
    if interval <= 0:
        raise ValueError("the interval must be positive")
    zmin, zmax = float(np.nanmin(terrain.z)), float(np.nanmax(terrain.z))
    base = math.floor(zmin / interval + 1e-9) * interval
    count = max(1, math.ceil((zmax - base) / interval - 1e-9))
    cg = contourpy.contour_generator(terrain.xs, terrain.ys, terrain.z, fill_type=contourpy.FillType.OuterOffset)
    extent = terrain.extent
    regions = [extent]
    for k in range(1, count + 1):
        if base + k * interval >= zmax:  # no ground reaches this level
            break
        regions.append(_region_at(cg, base + k * interval, zmax + 1.0).intersection(extent))
    return base, [r for r in regions if not r.is_empty]


def slice_terrain(terrain: Terrain, *, scale: int = 500, thickness_mm: float = 3.0,
                  room: tuple[float, float] | None = None, hollow_rim_mm: float = 0.0) -> ModelPlan:
    """
    The ground as stacked layers and their pieces. With `room` (the usable width and height of a
    sheet, mm) a model bigger than that is first cut into modules that fit (see `module_grid`).
    With `hollow_rim_mm` > 0 each layer above the base keeps only a rim that wide under the layer
    above it, so its hidden middle is not cut from material.
    """
    interval = contour_interval(scale, thickness_mm)
    mm = 1000.0 / scale
    x0, y0 = float(terrain.xs[0]), float(terrain.ys[0])

    def to_mm(geom):
        return affinity.scale(affinity.translate(geom, -x0, -y0), mm, mm, origin=(0, 0))

    extent = terrain.extent
    base, regions_m = layer_regions(terrain, interval)
    regions = [to_mm(r) for r in regions_m]
    site = to_mm(terrain.site) if terrain.site is not None else None
    size = ((float(terrain.xs[-1]) - x0) * mm, (float(terrain.ys[-1]) - y0) * mm)
    cols, rows = module_grid(size, *room) if room else (1, 1)
    modules = module_boxes(size, cols, rows)

    edge = to_mm(extent).boundary.buffer(0.2)
    areas = [(kind, to_mm(shape)) for kind, shape in terrain.areas]
    # The edges of roads, pavements and water, scored where they show; the model's edge is cut anyway.
    area_edges = unary_union([shape.boundary for _, shape in areas]).difference(edge) if areas else LineString()
    if site is not None and not area_edges.is_empty:  # a site on a road is scored once
        area_edges = area_edges.difference(site.boundary.buffer(0.2))
    # Where each next layer meets the one below: its outline, less the model's own edges.
    steps = [regions[k + 1].boundary.difference(edge) if k + 1 < len(regions) else LineString() for k in range(len(regions))]

    pieces: list[Piece] = []
    dropped = 0
    for m, module in enumerate(modules, start=1):
        prefix = f"{m}-" if len(modules) > 1 else ""
        for k, whole in enumerate(regions):
            region = whole.intersection(module)
            above = regions[k + 1].intersection(module) if k + 1 < len(regions) else Polygon()
            parts = _polygons(region)
            dropped += sum(1 for p in parts if p.area < MIN_PIECE_MM2)
            parts = [p for p in parts if p.area >= MIN_PIECE_MM2]
            parts.sort(key=lambda p: (-round(p.centroid.y / 20), p.centroid.x))  # north to south, west to east
            for i, part in enumerate(parts):
                covered = part.intersection(above)
                shape = part
                if hollow_rim_mm > 0 and k > 0 and not covered.is_empty:
                    inner = above.buffer(-hollow_rim_mm).intersection(part)
                    if inner.area > MIN_PIECE_MM2 * 4:
                        shape = part.difference(inner).buffer(0)
                engrave = _lines(steps[k].intersection(part.buffer(OVERLAP)))
                shows = part.difference(above).buffer(OVERLAP)
                if site is not None:
                    engrave += _lines(site.boundary.intersection(shows))
                if not area_edges.is_empty:
                    engrave += _lines(area_edges.intersection(shows))
                at, room_ = _label_spot(covered.intersection(shape) if not covered.is_empty else Polygon())
                label_hidden = True
                if room_ < MIN_LABEL_ROOM:
                    at, room_ = _label_spot(shape.difference(above))
                    label_hidden = False
                if room_ < MIN_LABEL_ROOM:
                    at, room_ = _label_spot(shape)
                show_at, show_room = _label_spot(shape.difference(above))
                if show_room < 1:
                    show_at, show_room = at, room_
                pieces.append(Piece(
                    id=f"{prefix}{k:02d}{_letters(i)}", layer=k, level_m=round(base + k * interval, 3),
                    shape=shape, module=m, engrave=engrave, label_at=at, label_room=room_,
                    label_hidden=label_hidden, show_at=show_at, show_room=show_room,
                ))
    return ModelPlan(scale=scale, thickness_mm=thickness_mm, interval_m=interval, base_m=base, size_mm=size,
                     modules=modules, layers=regions, pieces=pieces, site_mm=site, dropped=dropped,
                     areas_mm=areas)
