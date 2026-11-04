"""
The ground sliced into layers one material thickness apart, and each layer into pieces.

Units from here on are millimetres on the model: 1 m on the ground is 1000 / scale mm, and the
south-west corner of the model is (0, 0), x east and y north. A layer k is the ground at or
above `base + k × interval`, where the interval is the height one sheet of material stands for
(thickness × scale / 1000 m). Layer 0 is the whole model area: the base plate.

Every piece carries what the designer needs to put it back:
- `id` like "03B": layer 3, its second part (parts read north to south, then west to east).
  A layer is cut into more than one piece only when it does not fit the sheet, because the
  joint shows on the model; the cut then runs where it shows least ("03B1", "03B2"…)
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
    exposed: Polygon | None = None  # the part of the piece that shows on the finished model
    tile: str = ""  # "2/4" when a piece too big for the sheet was cut
    seam_mm: float = 0.0  # length of this piece's cut joints that shows on the model

    @property
    def holed(self) -> bool:
        return bool(self.shape.interiors) if isinstance(self.shape, Polygon) else True

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


HOLLOW_MODES = ("none", "all", "alternate")


def hollowed(mode: str, layer: int) -> bool:
    """Which layers lose their hidden middle: none, all above the base, or every other one
    (1, 3, 5…), so that solid pieces of the layers between can sit in their holes."""
    if mode not in HOLLOW_MODES:
        raise ValueError(f"hollow must be one of {HOLLOW_MODES}")
    return layer > 0 and (mode == "all" or (mode == "alternate" and layer % 2 == 1))


def slice_terrain(terrain: Terrain, *, scale: int = 500, thickness_mm: float = 3.0,
                  hollow: str = "none", hollow_rim_mm: float = 8.0) -> ModelPlan:
    """
    The ground as stacked layers and their pieces. A hollowed layer (see `hollowed`) keeps only
    a rim `hollow_rim_mm` wide inside the layer above it, so its hidden middle is not cut from
    material; the hole can hold a piece without holes when laid out.
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
            if hollow_rim_mm > 0 and hollowed(hollow, k) and not covered.is_empty:
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
                show_at=show_at, show_room=show_room, exposed=shape.difference(above),
            ))
    width = (float(terrain.xs[-1]) - x0) * mm
    depth = (float(terrain.ys[-1]) - y0) * mm
    return ModelPlan(scale=scale, thickness_mm=thickness_mm, interval_m=interval, base_m=base,
                     size_mm=(width, depth), layers=regions, pieces=pieces, site_mm=site, dropped=dropped)


def _cut_options(shape: Polygon, step: float):
    """Straight cuts across the piece, east-west and north-south, every `step` mm."""
    x0, y0, x1, y1 = shape.bounds
    for c in np.arange(x0 + step, x1 - step / 2, step):
        yield LineString([(c, y0 - 1), (c, y1 + 1)]), (box(x0 - 1, y0 - 1, c, y1 + 1), box(c, y0 - 1, x1 + 1, y1 + 1))
    for c in np.arange(y0 + step, y1 - step / 2, step):
        yield LineString([(x0 - 1, c), (x1 + 1, c)]), (box(x0 - 1, c, x1 + 1, y1 + 1), box(x0 - 1, y0 - 1, x1 + 1, c))


def _split_once(shape: Polygon, exposed, max_w: float, max_h: float, step: float):
    """The cut whose joint shows least on the model, favouring cuts after which both sides fit."""
    best = None
    for line, halves in _cut_options(shape, step):
        parts = [poly for half in halves for poly in _polygons(shape.intersection(half)) if poly.area >= MIN_PIECE_MM2]
        if len(parts) < 2:
            continue
        seen = line.intersection(exposed).length if exposed is not None else line.intersection(shape).length
        misfits = sum(1 for p in parts if not fits_somehow(p, max_w, max_h))
        cost = (misfits, round(seen, 1), round(line.intersection(shape).length, 1))
        if best is None or cost < best[0]:
            best = (cost, parts, seen)
    return best


def split_to_fit(pieces: list[Piece], max_w: float, max_h: float, *, step: float = 2.0) -> list[Piece]:
    """
    Pieces larger than a sheet in every orientation, cut into parts that fit. A joint shows on
    the model, so each cut is the straight line, of all tried every `step` mm, that runs least
    through the part of the piece that shows (under the next layer it is hidden). Pieces that
    fit are left whole. Each part keeps its piece's id with a number and the lines on it.
    """
    out: list[Piece] = []
    for piece in pieces:
        if fits_somehow(piece.shape, max_w, max_h):
            out.append(piece)
            continue
        todo, done, seam = [piece.shape], [], 0.0
        while todo:
            shape = todo.pop()
            if fits_somehow(shape, max_w, max_h):
                done.append(shape)
                continue
            cut = _split_once(shape, piece.exposed, max_w, max_h, step)
            if cut is None:
                raise ValueError(f"piece {piece.id} cannot be cut to fit the sheet")
            _, parts, seen = cut
            seam += seen
            todo += parts
        done.sort(key=lambda p: (-round(p.centroid.y / 20), p.centroid.x))  # north to south, west to east
        for n, poly in enumerate(done, start=1):
            exposed = poly.intersection(piece.exposed) if piece.exposed is not None else None
            hidden = poly.difference(exposed) if exposed is not None else Polygon()
            at, room = _label_spot(hidden)
            hidden_label = room >= MIN_LABEL_ROOM
            if not hidden_label:
                at, room = _label_spot(poly)
            show_at, show_room = _label_spot(exposed) if exposed is not None and not exposed.is_empty else (at, room)
            out.append(Piece(
                id=f"{piece.id}{n}", layer=piece.layer, level_m=piece.level_m, shape=poly,
                engrave=[ln for e in piece.engrave for ln in _lines(e.intersection(poly.buffer(OVERLAP)))],
                label_at=at, label_room=room, label_hidden=hidden_label, show_at=show_at, show_room=show_room,
                exposed=exposed, tile=f"{n}/{len(done)}", seam_mm=round(seam, 1),
            ))
    return out


def fits_somehow(shape: Polygon, max_w: float, max_h: float, angles: int = 8) -> bool:
    for i in range(angles):
        x0, y0, x1, y1 = affinity.rotate(shape, i * 180 / angles, origin=(0, 0)).bounds
        w, h = x1 - x0, y1 - y0
        if (w <= max_w and h <= max_h) or (h <= max_w and w <= max_h):
            return True
    return False


SLIT_MM = 0.3  # width of the laser cut that opens a ring: a single cut line, closed again when glued


def _slit(shape: Polygon, hole, exposed, samples: int = 120):
    """The shortest-showing straight cut from a hole to the outside of the piece."""
    outside = shape.exterior
    best = None
    ring = hole if hasattr(hole, "interpolate") else LineString(hole.coords)
    for i in range(samples):
        a = ring.interpolate(i / samples, normalized=True)
        b = outside.interpolate(outside.project(a))
        seg = LineString([a, b])
        if seg.length < 1e-6:
            continue
        crosses_hole = shape.difference(seg.buffer(SLIT_MM / 2)).geom_type != "Polygon"
        seen = seg.intersection(exposed).length if exposed is not None else seg.length
        cost = (round(seen, 1), round(seg.length, 1), crosses_hole)
        if best is None or cost < best[0]:
            best = (cost, seg, seen)
    return best


def open_rings(pieces: list[Piece]) -> list[Piece]:
    """
    Pieces with holes, each hole opened to the outside by one straight laser cut where it shows
    least (under the next layer it does not show at all). An opened ring has no hole, so other
    pieces can lie in its middle as ordinary outer pieces, whatever their own shape, and the
    two-pass cut order (inner, then outer) never has a piece inside a hole.
    The length of the cuts that shows is kept in `seam_mm`.
    """
    out = []
    for piece in pieces:
        shape = piece.shape
        if not isinstance(shape, Polygon) or not shape.interiors:
            out.append(piece)
            continue
        seen_total = 0.0
        for _ in range(len(shape.interiors)):
            if not shape.interiors:
                break
            slit = _slit(shape, LineString(shape.interiors[0].coords), piece.exposed)
            if slit is None:
                break
            _, seg, seen = slit
            opened = shape.difference(seg.buffer(SLIT_MM / 2, cap_style=2))
            parts = _polygons(opened)
            if len(parts) != 1:  # the cut would split the piece: leave this hole
                break
            shape = parts[0]
            seen_total += seen
        if shape.interiors:
            out.append(piece)
            continue
        out.append(Piece(**{**piece.__dict__, "shape": shape, "seam_mm": round(piece.seam_mm + seen_total, 1)}))
    return out


def split_hidden(pieces: list[Piece], max_hull: float, *, step: float = 4.0, stagger: float = 25.0) -> list[Piece]:
    """
    Big pieces cut in two, again and again while a part still takes more than `max_hull` mm² of
    sheet, but only along straight lines that run wholly under the next layer: from above no
    joint shows (only a line on the model's side). Cuts keep `stagger` mm away from the cuts of
    the layer below, so joints do not line up through the stack. Pieces with no such cut stay whole.
    """
    seams_by_layer: dict[int, list[LineString]] = {}
    out: list[Piece] = []
    for piece in sorted(pieces, key=lambda p: p.layer):
        if piece.exposed is None:
            out.append(piece)
            continue
        below = seams_by_layer.get(piece.layer - 1, [])
        todo, done, cuts = [piece.shape], [], []
        while todo:
            shape = todo.pop()
            if shape.convex_hull.area <= max_hull:
                done.append(shape)
                continue
            best = None
            for line, halves in _cut_options(shape, step):
                parts = [p for h in halves for p in _polygons(shape.intersection(h)) if p.area >= MIN_PIECE_MM2]
                if len(parts) != 2 or line.intersection(piece.exposed).length > 0.5:
                    continue
                near = min((line.distance(s) for s in below), default=stagger)
                cost = (near < stagger, max(p.convex_hull.area for p in parts))  # off the joints below first
                if best is None or cost < best[0]:
                    best = (cost, parts, line.intersection(shape))
            if best is None:
                done.append(shape)
                continue
            todo += best[1]
            cuts.append(best[2])
        seams_by_layer.setdefault(piece.layer, []).extend(cuts)
        if len(done) == 1:
            out.append(piece)
            continue
        done.sort(key=lambda p: (-round(p.centroid.y / 20), p.centroid.x))
        for n, poly in enumerate(done, start=1):
            exposed = poly.intersection(piece.exposed)
            at, room = _label_spot(poly.difference(exposed))
            hidden_label = room >= MIN_LABEL_ROOM
            if not hidden_label:
                at, room = _label_spot(poly)
            show_at, show_room = _label_spot(exposed) if not exposed.is_empty else (at, room)
            out.append(Piece(
                id=f"{piece.id}{n}", layer=piece.layer, level_m=piece.level_m, shape=poly,
                engrave=[ln for e in piece.engrave for ln in _lines(e.intersection(poly.buffer(OVERLAP)))],
                label_at=at, label_room=room, label_hidden=hidden_label, show_at=show_at, show_room=show_room,
                exposed=exposed, tile=f"{n}/{len(done)}", seam_mm=piece.seam_mm,
            ))
    return out
