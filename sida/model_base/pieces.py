"""
The ground sliced into layers one material thickness apart, and each layer into pieces.

Units from here on are millimetres on the model: 1 m on the ground is 1000 / scale mm, and the
south-west corner of the model is (0, 0), x east and y north. A layer k is the ground at or
above `base + k × interval`, where the interval is the height one sheet of material stands for
(thickness × scale / 1000 m). Layer 0 is the whole model area: the base plate.

Every piece carries what the designer needs to put it back:
- `id` like "03B": layer 3, its second part (parts read north to south, then west to east);
  a piece too big for a sheet is cut into tiles "03B1", "03B2"…
- `engrave`: lines scored on the piece: where the next layer sits (to line it up), and the
  part of the site boundary that shows on this piece
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
    engrave: list[LineString] = field(default_factory=list)
    label_at: tuple[float, float] = (0.0, 0.0)
    label_room: float = 0.0
    label_hidden: bool = True  # the id sits where the next layer covers it
    show_at: tuple[float, float] = (0.0, 0.0)  # where the id is written on the assembly map (a part that shows)
    show_room: float = 0.0
    tile: str = ""  # "2/4" when a big piece was cut into tiles

    @property
    def area(self) -> float:
        return self.shape.area


@dataclass
class ModelPlan:
    scale: int
    thickness_mm: float
    interval_m: float
    base_m: float
    size_mm: tuple[float, float]
    layers: list[MultiPolygon]  # layer regions (before hollowing), model mm
    pieces: list[Piece]
    site_mm: Polygon | None
    dropped: int = 0  # bits too small to cut


def contour_interval(scale: int, thickness_mm: float) -> float:
    """Metres of ground one sheet of material stands for: 3 mm at 1:500 is 1.5 m."""
    if scale <= 0 or thickness_mm <= 0:
        raise ValueError("scale and thickness must be positive")
    return thickness_mm * scale / 1000.0


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


def slice_terrain(terrain: Terrain, *, scale: int = 500, thickness_mm: float = 3.0,
                  hollow_rim_mm: float = 0.0) -> ModelPlan:
    """
    The ground as stacked layers and their pieces. With `hollow_rim_mm` > 0 each layer above
    the base keeps only a rim that far inside the layer above it, so the hidden middle is not
    cut from material (the hole can hold other pieces when laid out).
    """
    interval = contour_interval(scale, thickness_mm)
    mm = 1000.0 / scale
    x0, y0 = float(terrain.xs[0]), float(terrain.ys[0])

    def to_mm(geom):
        return affinity.scale(affinity.translate(geom, -x0, -y0), mm, mm, origin=(0, 0))

    zmin, zmax = float(np.nanmin(terrain.z)), float(np.nanmax(terrain.z))
    base = math.floor(zmin / interval) * interval
    count = max(1, math.ceil((zmax - base) / interval - 1e-9))
    cg = contourpy.contour_generator(terrain.xs, terrain.ys, terrain.z, fill_type=contourpy.FillType.OuterOffset)
    extent = terrain.extent
    regions = [to_mm(extent)]
    for k in range(1, count + 1):
        if base + k * interval >= zmax:  # no ground reaches this level
            break
        region = _region_at(cg, base + k * interval, zmax + 1.0).intersection(extent)
        regions.append(to_mm(region))
    regions = [r for r in regions if not r.is_empty]
    site = to_mm(terrain.site) if terrain.site is not None else None

    pieces: list[Piece] = []
    dropped = 0
    for k, region in enumerate(regions):
        above = regions[k + 1] if k + 1 < len(regions) else Polygon()
        parts = [p for p in _polygons(region)]
        small = [p for p in parts if p.area < MIN_PIECE_MM2]
        dropped += len(small)
        parts = [p for p in parts if p.area >= MIN_PIECE_MM2]
        parts.sort(key=lambda p: (-round(p.centroid.y / 20), p.centroid.x))  # north to south, west to east
        for i, part in enumerate(parts):
            covered = part.intersection(above)
            shape = part
            if hollow_rim_mm > 0 and k > 0 and not covered.is_empty:
                inner = above.buffer(-hollow_rim_mm).intersection(part)
                if inner.area > MIN_PIECE_MM2 * 4:
                    shape = part.difference(inner).buffer(0)
            engrave = _lines(above.boundary.intersection(part.buffer(OVERLAP)))
            if site is not None:
                engrave += _lines(site.boundary.intersection(part.difference(above).buffer(OVERLAP)))
            hidden_room = covered.intersection(shape) if not covered.is_empty else Polygon()
            at, room = _label_spot(hidden_room)
            label_hidden = True
            if room < MIN_LABEL_ROOM:
                at, room = _label_spot(shape.difference(above))
                label_hidden = False
            if room < MIN_LABEL_ROOM:
                at, room = _label_spot(shape)
            show_at, show_room = _label_spot(shape.difference(above))
            if show_room < 1:
                show_at, show_room = at, room
            pieces.append(Piece(
                id=f"{k:02d}{_letters(i)}", layer=k, level_m=round(base + k * interval, 3),
                shape=shape, engrave=engrave, label_at=at, label_room=room, label_hidden=label_hidden,
                show_at=show_at, show_room=show_room,
            ))
    width = (float(terrain.xs[-1]) - x0) * mm
    depth = (float(terrain.ys[-1]) - y0) * mm
    return ModelPlan(scale=scale, thickness_mm=thickness_mm, interval_m=interval, base_m=base,
                     size_mm=(width, depth), layers=regions, pieces=pieces, site_mm=site, dropped=dropped)


def is_thin(shape: Polygon, chunk: float) -> bool:
    """A wide ring or strip: it spans more than `chunk` but fills little of its outline."""
    hull = shape.convex_hull
    x0, y0, x1, y1 = shape.bounds
    return max(x1 - x0, y1 - y0) > chunk * 1.3 and shape.area < 0.4 * hull.area


def split_to_fit(pieces: list[Piece], max_w: float, max_h: float, *, chunk: float | None = None) -> list[Piece]:
    """
    Pieces larger than a sheet in every orientation, cut along a grid into tiles that fit.
    With `chunk`, wide thin pieces (the rims of hollowed layers) are also cut into tiles about
    that size, which lay out far tighter; they are glued down on the layer below, so the cuts
    do not weaken the model. Each tile keeps its piece's id with a tile number and the lines
    that fall on it.
    """
    out: list[Piece] = []
    for piece in pieces:
        thin = chunk is not None and is_thin(piece.shape, chunk)
        if not thin and fits_somehow(piece.shape, max_w, max_h):
            out.append(piece)
            continue
        cell_w = min(max_w, chunk) if thin else max_w
        cell_h = min(max_h, chunk) if thin else max_h
        x0, y0, x1, y1 = piece.shape.bounds
        cols = math.ceil((x1 - x0) / cell_w)
        rows = math.ceil((y1 - y0) / cell_h)
        cw, ch = (x1 - x0) / cols, (y1 - y0) / rows
        tiles = []
        for r in range(rows - 1, -1, -1):  # north row first, like the part letters
            for c in range(cols):
                cell = box(x0 + c * cw, y0 + r * ch, x0 + (c + 1) * cw, y0 + (r + 1) * ch)
                part = piece.shape.intersection(cell)
                for poly in _polygons(part):
                    if poly.area >= MIN_PIECE_MM2:
                        tiles.append((poly, cell))
        for n, (poly, cell) in enumerate(tiles, start=1):
            at, room = _label_spot(poly)
            out.append(Piece(
                id=f"{piece.id}{n}", layer=piece.layer, level_m=piece.level_m, shape=poly,
                engrave=[ln for e in piece.engrave for ln in _lines(e.intersection(cell.buffer(OVERLAP)))],
                label_at=at, label_room=room, label_hidden=False, show_at=at, show_room=room,
                tile=f"{n}/{len(tiles)}",
            ))
    return out


def fits_somehow(shape: Polygon, max_w: float, max_h: float, angles: int = 8) -> bool:
    for i in range(angles):
        x0, y0, x1, y1 = affinity.rotate(shape, i * 180 / angles, origin=(0, 0)).bounds
        w, h = x1 - x0, y1 - y0
        if (w <= max_w and h <= max_h) or (h <= max_w and w <= max_h):
            return True
    return False
