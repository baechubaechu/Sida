"""A landscape layout in a region of the site, by rule (2026-11-20 지훈: "영역 지정하면 조경 알아서 해주는
그런거"). Three styles from the same inputs; nothing is drawn by a model.

Inputs (`Inputs`, the table's metres: x east, y north): the region to lay out (the buildings already
taken out), the lot (what the law counts), the buildings with their heights, the lot edges that face
a road and what the rules ask (rules.requirement). The steps, the same for every style with the
style's own settings (`STYLES`):

1. 길: from each building's door (the middle of the side that faces the nearest road) to the
   nearest point of the road edge. Straight, or a gentle curve for the 자연형.
2. 광장: by the widest road; at least the 공개 공지 asked (and its least width when it can), else a
   share of the region. The 정형 puts it in front of the main door, the 자연형 makes a round rest
   spot on the main path, the 광장형 opens the whole road side.
3. 경계 관목 띠: 1.5 m along the lot edges that face neighbours.
4. 남은 땅: where the buildings shade it 5 hours or more between 9 and 15 on the winter solstice,
   음지 지피; elsewhere 잔디·초화. A piece narrower than 1 m a side is paved (조경기준 제4조: one
   planted piece is at least 1 m a side).
5. 교목: in rows along the paths and edges (정형), scattered (자연형) or on a grid of planters in the
   광장 (광장형); 2.5 m off the buildings, clear of the paths, apart from each other. Then more
   where room is left until the 조경기준's count is met, or as many as fit.

Every tree counts as one (조경기준 제7조② counts big trees as more: the count is the least).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.affinity import translate
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, substring, unary_union

STYLES = {
    # path width (m), tree crown radius (m), tree spacing (m), plaza share of the region without a
    # 공개 공지 to keep, and the least plaza (㎡)
    "formal": {"label": "정형 · 축선", "path": 3.0, "crown": 2.0, "spacing": 5.5, "plaza_share": 0.10, "plaza_least": 40.0,
               "about": "정문에서 도로까지 곧은 축, 앞마당은 포장 광장, 축과 경계를 따라 줄지은 나무"},
    "natural": {"label": "자연형 · 산책", "path": 2.4, "crown": 2.2, "spacing": 4.4, "plaza_share": 0.06, "plaza_least": 25.0,
                "about": "굽은 길과 무리 지은 나무, 길가의 둥근 쉼터, 넓은 잔디"},
    "plaza": {"label": "광장형 · 도로변 개방", "path": 2.4, "crown": 1.8, "spacing": 6.0, "plaza_share": 0.35, "plaza_least": 60.0,
              "about": "도로 쪽을 넓게 포장하고 나무는 식재함에, 녹지는 이웃 경계 쪽 띠로"},
}
HEDGE = 1.5  # m: the shrub band along the neighbours' edges
TREE_OFF_BUILDING = 2.5  # m from a wall to a trunk
TREE_OFF_PATH = 1.0  # m from a path's edge to a trunk
TREE_OFF_EDGE = 1.5  # m from the region's edge to a trunk
PLANTER = 2.0  # m: the side of a planter in the plaza
LEAST_SIDE = 1.0  # m: a planted piece narrower than this is paved
SHADE_HOURS = 5  # of the 7 hours 9–15 on the winter solstice
SHADE_STEP = 1.0  # m: the grid the shade is counted on
MAX_TREES = 400
KINDS = ("lawn", "shade", "hedge", "path", "plaza", "paving")


@dataclass
class Inputs:
    region: Polygon | MultiPolygon
    lot: Polygon | MultiPolygon
    buildings: list[tuple[Polygon, float]] = field(default_factory=list)  # footprint, height (m)
    roads: list[dict] = field(default_factory=list)  # {"line": LineString | MultiLineString, "width": m | None}
    latitude: float = 37.5
    open_space_m2: float | None = None  # the 공개 공지 asked
    open_space_width: float | None = None  # its least width
    trees_needed: int | None = None  # the 조경기준's count for the 조경 asked
    seed: int = 1


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _clean(geom):
    """Polygons only, valid, without specks."""
    if geom is None or geom.is_empty:
        return Polygon()
    geom = shapely.make_valid(geom)
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type in ("Polygon", "MultiPolygon")]
    out = unary_union(parts) if parts else Polygon()
    polys = [p for p in getattr(out, "geoms", [out]) if p.area >= 0.25]
    return unary_union(polys) if polys else Polygon()


def _opening(geom, side: float):
    """What is left of `geom` that is at least `side` wide (buffer in, then out)."""
    return _clean(geom.buffer(-side / 2, join_style="mitre").buffer(side / 2, join_style="mitre").intersection(geom))


def sun(hour: float, latitude: float) -> tuple[float, float]:
    """(altitude, azimuth) in radians on the winter solstice at a solar `hour`; azimuth from south, west positive."""
    h, lat, dec = math.radians(15 * (hour - 12)), math.radians(latitude), math.radians(-23.44)
    alt = math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(h))
    az = math.atan2(math.sin(h), math.cos(h) * math.sin(lat) - math.tan(dec) * math.cos(lat))
    return alt, az


def shadows(buildings: list[tuple[Polygon, float]], hour: float, latitude: float):
    """The ground the buildings shade at one hour (a flat site)."""
    alt, az = sun(hour, latitude)
    if alt <= 0.02:
        return None
    reach = 1 / math.tan(alt)
    # the sun is toward (-sin az, -cos az); the shadow falls the other way
    dx, dy = math.sin(az) * reach, math.cos(az) * reach
    parts = []
    for foot, height in buildings:
        # a block is a box: its shadow is the hull of its footprint and the footprint moved by the shadow
        parts.append(unary_union([foot, translate(foot, dx * height, dy * height)]).convex_hull)
    return unary_union(parts) if parts else None


def shade_area(region, buildings: list[tuple[Polygon, float]], latitude: float):
    """The part of `region` shaded SHADE_HOURS or more of the hours 9–15 on the winter solstice."""
    if region.is_empty or not buildings:
        return Polygon()
    x0, y0, x1, y1 = region.bounds
    xs = np.arange(x0 + SHADE_STEP / 2, x1, SHADE_STEP)
    ys = np.arange(y0 + SHADE_STEP / 2, y1, SHADE_STEP)
    if not len(xs) or not len(ys):
        return Polygon()
    gx, gy = np.meshgrid(xs, ys)
    count = np.zeros(gx.shape, dtype=int)
    for hour in range(9, 16):
        shade = shadows(buildings, hour, latitude)
        if shade is not None and not shade.is_empty:
            shapely.prepare(shade)
            count += shapely.contains_xy(shade, gx, gy)
    cells = [box(x - SHADE_STEP / 2, y - SHADE_STEP / 2, x + SHADE_STEP / 2, y + SHADE_STEP / 2)
             for x, y in zip(gx[count >= SHADE_HOURS], gy[count >= SHADE_HOURS], strict=True)]
    if not cells:
        return Polygon()
    return _clean(unary_union(cells).simplify(SHADE_STEP / 3).intersection(region))


def _edge_facing(foot: Polygon, target) -> tuple[Point, tuple[float, float]]:
    """The middle of the footprint side that faces `target` best, with that side's outward normal."""
    pts = list(orient(foot, 1.0).exterior.coords)[:-1]
    best, best_d = None, math.inf
    for a, b in zip(pts, pts[1:] + pts[:1], strict=True):
        length = math.dist(a, b)
        if length < 2.0:
            continue
        nx, ny = (b[1] - a[1]) / length, -(b[0] - a[0]) / length  # outward for a counter-clockwise ring
        mid = Point((a[0] + b[0]) / 2 + nx * 0.3, (a[1] + b[1]) / 2 + ny * 0.3)
        d = mid.distance(target)
        if d < best_d - 1e-6:
            best, best_d = (mid, (nx, ny)), d
    if best is None:
        c = foot.centroid
        return Point(c.x, c.y), (0.0, -1.0)
    return best


def _curve(a: Point, b: Point, bend: float, steps: int = 24) -> LineString:
    """A quadratic curve from a to b, its middle pushed sideways by `bend` × its length."""
    mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
    length = a.distance(b) or 1.0
    nx, ny = -(b.y - a.y) / length, (b.x - a.x) / length
    cx, cy = mx + nx * bend * length, my + ny * bend * length
    pts = []
    for k in range(steps + 1):
        t = k / steps
        pts.append(((1 - t) ** 2 * a.x + 2 * (1 - t) * t * cx + t * t * b.x, (1 - t) ** 2 * a.y + 2 * (1 - t) * t * cy + t * t * b.y))
    return LineString(pts)


def _grow(make, target: float, low: float, high: float, steps: int = 18):
    """The smallest shape make(d) for d in [low, high] whose area reaches `target` (or make(high))."""
    best = make(high)
    if best.area < target:
        return best
    for _ in range(steps):
        mid = (low + high) / 2
        shape = make(mid)
        if shape.area >= target:
            best, high = shape, mid
        else:
            low = mid
    return best


# ---------------------------------------------------------------------------
# the layout
# ---------------------------------------------------------------------------


def _doors(inputs: Inputs, road_union) -> list[dict]:
    """A door on each building (the largest first, at most 6) and the road point it leads to."""
    target = road_union if road_union is not None else inputs.lot.boundary
    widest = _widest_road(inputs)
    out = []
    for k, (foot, _height) in enumerate(sorted(inputs.buildings, key=lambda b: -b[0].area)[:6]):
        # the main building's door faces the widest road; the others the nearest
        door, normal = _edge_facing(foot, widest if k == 0 and widest is not None else target)
        gate = nearest_points(door, target)[1]
        out.append({"door": door, "gate": gate, "normal": normal})
    if not out:  # no building: one way in from the road's middle to the region's middle
        middle = inputs.region.representative_point() if not inputs.region.is_empty else inputs.lot.centroid
        gate = nearest_points(middle, target)[1]
        out.append({"door": middle, "gate": gate, "normal": (0.0, 0.0)})
    return out


def _paths(style: str, doors: list[dict], region, rng: random.Random) -> list[LineString]:
    lines = []
    inside = region.buffer(0.2)
    for d in doors:
        a, b = d["door"], d["gate"]
        if a.distance(b) < 0.5:
            continue
        line = LineString([a, b])
        if style == "natural":
            curve = _curve(a, b, rng.choice((-1, 1)) * 0.22)
            if curve.difference(inside).length <= 0.1 * curve.length:
                line = curve
        lines.append(line)
    return lines


def _widest_road(inputs: Inputs):
    if not inputs.roads:
        return None
    return max(inputs.roads, key=lambda r: ((r["width"] or 0), r["line"].length))["line"]


def _plaza(style: str, inputs: Inputs, region, doors: list[dict], lines: list[LineString]):
    s = STYLES[style]
    target = max(inputs.open_space_m2 or 0.0, s["plaza_share"] * region.area, s["plaza_least"])
    target = min(target, 0.6 * region.area)
    road = _widest_road(inputs)
    edge = road if road is not None else inputs.lot.boundary
    width = inputs.open_space_width or (6.0 if style == "formal" else 8.0)
    if style == "plaza":  # the whole widest road side, as deep as it takes
        least = (inputs.open_space_width or 2.0) + 0.3  # at least the 공개 공지's width deep
        return _clean(_grow(lambda d: _clean(edge.buffer(d, cap_style="flat").intersection(region)), target, least, 40.0))
    if style == "formal":
        gate = doors[0]["gate"]
        line = edge if edge.geom_type == "LineString" else LineString(list(getattr(edge, "geoms", [edge])[0].coords))
        at = line.project(gate)

        def front(r):  # the stretch of the road edge 2r long around the gate, the width deep
            part = substring(line, max(0.0, at - r), min(line.length, at + r))
            return _clean(part.buffer(width + 0.3, cap_style="flat").intersection(region))

        shape = _grow(front, target, 1.0, 80.0)
        if shape.area < target:  # the band is too thin to hold it: deeper
            shape = _grow(lambda d: _clean(edge.buffer(d, cap_style="flat").intersection(region).intersection(gate.buffer(max(width * 2, 20)))),
                          target, width, 30.0)
        return shape
    # natural: a round rest spot a third of the way from the gate up the main path, near the road
    main = lines[0] if lines else LineString([doors[0]["gate"], doors[0]["door"]])
    at = main.interpolate(0.35 if main.coords[0] != doors[0]["gate"].coords[0] else 0.65, normalized=True)
    side = 1 if len(lines) % 2 == 0 else -1
    ox, oy = doors[0]["normal"]
    centre = Point(at.x + side * -oy * (STYLES[style]["path"] + 1), at.y + side * ox * (STYLES[style]["path"] + 1))
    return _clean(_grow(lambda r: _clean(centre.buffer(r, 24).intersection(region)), target, 1.0, 40.0))


def _place_trees(style: str, inputs: Inputs, zones: dict, lines: list[LineString], shade, rng: random.Random) -> list[dict]:
    s = STYLES[style]
    planted = _clean(unary_union([zones["lawn"], zones["shade"], zones["hedge"]]))
    walls = unary_union([b for b, _ in inputs.buildings]) if inputs.buildings else None
    path_union = unary_union(lines) if lines else None
    room = inputs.region.buffer(-TREE_OFF_EDGE)
    trees: list[dict] = []
    pts: list[tuple[float, float]] = []
    shapely.prepare(planted)
    shapely.prepare(room)

    def fits(x: float, y: float, spacing: float, ground=planted, off_path: float | None = None) -> bool:
        p = Point(x, y)
        if not ground.contains(p) or not room.contains(p):
            return False
        if walls is not None and walls.distance(p) < TREE_OFF_BUILDING:
            return False
        if path_union is not None and path_union.distance(p) < (off_path if off_path is not None else s["path"] / 2 + TREE_OFF_PATH):
            return False
        return all((x - a) ** 2 + (y - b) ** 2 >= spacing * spacing for a, b in pts)

    in_plaza = zones["plaza"].buffer(-PLANTER / 2) if not zones["plaza"].is_empty else Polygon()

    def add(x: float, y: float, kind: str | None = None) -> None:
        if kind is None and not in_plaza.is_empty and in_plaza.contains(Point(x, y)):
            kind = "planter"
        if kind is None:
            kind = "shade" if not shade.is_empty and shade.contains(Point(x, y)) else "sun"
        pts.append((x, y))
        trees.append({"x": round(x, 2), "y": round(y, 2), "r": 1.6 if kind == "planter" else s["crown"], "kind": kind})

    def along(lines_, offset: float, step: float, spacing: float, ground=planted) -> None:
        for line, side in ((ln, side) for ln in getattr(lines_, "geoms", [lines_]) for side in (-1, 1)):
            if line.length <= 0:
                continue
            moved = line.offset_curve(side * offset)
            if moved.is_empty:
                continue
            for part in getattr(moved, "geoms", [moved]):
                n = int(part.length // step)
                for k in range(n + 1):
                    p = part.interpolate(min(step / 2 + k * step, part.length))
                    if len(trees) < MAX_TREES and fits(p.x, p.y, spacing, ground):
                        add(p.x, p.y)

    neighbours = inputs.lot.boundary
    if inputs.roads:
        neighbours = neighbours.difference(unary_union([r["line"] for r in inputs.roads]).buffer(0.5))
    if style == "formal":
        avenue = _clean(unary_union([planted, in_plaza]))  # the axis' trees stand in planters across the forecourt
        for line in lines:
            along(line, s["path"] / 2 + TREE_OFF_PATH + 0.6, s["spacing"], s["spacing"] - 0.5, avenue)
        if not neighbours.is_empty:
            for part in getattr(neighbours, "geoms", [neighbours]):
                if part.length >= 3:
                    edge_room = inputs.region.buffer(-HEDGE / 2 - 0.3).boundary
                    near = edge_room.intersection(part.buffer(HEDGE + 1.5))
                    for seg in getattr(near, "geoms", [near]):
                        if seg.geom_type == "LineString" and seg.length >= 1:
                            for k in range(int(seg.length // s["spacing"]) + 1):
                                p = seg.interpolate(k * s["spacing"])
                                if fits(p.x, p.y, s["spacing"] - 0.5):
                                    add(p.x, p.y)
    elif style == "plaza":
        plaza = zones["plaza"]
        if not plaza.is_empty:
            road = _widest_road(inputs)
            angle = 0.0
            if road is not None:
                c = list(getattr(road, "geoms", [road])[0].coords)
                angle = math.atan2(c[-1][1] - c[0][1], c[-1][0] - c[0][0])
            inner = plaza.buffer(-PLANTER)
            x0, y0, x1, y1 = plaza.bounds
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            span = max(x1 - x0, y1 - y0)
            ca, sa = math.cos(angle), math.sin(angle)
            n = int(span // s["spacing"]) + 2
            for i in range(-n, n + 1):
                for j in range(-n, n + 1):
                    u, v = i * s["spacing"], j * s["spacing"]
                    x, y = cx + u * ca - v * sa, cy + u * sa + v * ca
                    if len(trees) < MAX_TREES and fits(x, y, s["spacing"] - 0.5, inner, off_path=s["path"] / 2 + PLANTER / 2 + 0.3):
                        add(x, y, "planter")
        if not neighbours.is_empty:
            along(neighbours, HEDGE + 1.2, s["spacing"] - 1, s["spacing"] - 1.5)
    # scattered (the 자연형's own, and every style's top-up to the count)
    need = inputs.trees_needed if inputs.trees_needed else int(planted.area // 45)
    spacing = s["spacing"] if style == "natural" else s["spacing"] - 1.5
    x0, y0, x1, y1 = planted.bounds if not planted.is_empty else (0, 0, 0, 0)
    tries = 0
    want = max(need, int(planted.area // 30)) if style == "natural" else need
    while len(trees) < min(want, MAX_TREES) and tries < 6000 and not planted.is_empty:
        tries += 1
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        if style == "natural" and inputs.lot.boundary.distance(Point(x, y)) > 8 and rng.random() < 0.5:
            continue  # the 자연형 gathers its trees toward the edges, leaving open lawn in the middle
        if fits(x, y, spacing if tries < 2000 else max(3.6, spacing * (0.85 if tries < 4000 else 0.7))):
            add(x, y)
    return trees


def _rings(geom) -> list[dict]:
    out = []
    for poly in getattr(geom, "geoms", [geom]):
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        poly = poly.simplify(0.05)
        out.append({"outer": [[round(x, 2), round(y, 2)] for x, y in poly.exterior.coords[:-1]],
                    "holes": [[[round(x, 2), round(y, 2)] for x, y in r.coords[:-1]] for r in poly.interiors]})
    return out


def generate(inputs: Inputs, style: str) -> dict:
    """
    One layout: {"style", "label", "about", "zones": {kind: [{"outer", "holes"}]}, "paths": [{"line",
    "width"}], "trees": [{"x", "y", "r", "kind"}], "doors": [[x, y]], "areas": {kind: ㎡ in the lot},
    "planting_m2", "trees_in_lot", "plaza_m2", "plaza_width_ok"}.
    """
    s = STYLES[style]
    rng = random.Random(inputs.seed * 101 + list(STYLES).index(style))
    region = _clean(inputs.region)
    road_union = unary_union([r["line"] for r in inputs.roads]) if inputs.roads else None
    doors = _doors(inputs, road_union)
    lines = _paths(style, doors, region, rng)
    path_area = _clean(unary_union([ln.buffer(s["path"] / 2, cap_style="flat") for ln in lines]).intersection(region)) if lines else Polygon()
    # the plaza is paved through: the paths stop at it (so its width is not cut by them)
    plaza = _clean(_plaza(style, inputs, region, doors, lines).intersection(region))
    path_area = _clean(path_area.difference(plaza))
    free = _clean(region.difference(path_area).difference(plaza))
    neighbours = inputs.lot.boundary
    if road_union is not None:
        neighbours = neighbours.difference(road_union.buffer(0.5))
    hedge = _clean(neighbours.buffer(HEDGE).intersection(free)) if not neighbours.is_empty else Polygon()
    hedge = _opening(hedge, LEAST_SIDE)
    free = _clean(free.difference(hedge))
    green = _opening(free, LEAST_SIDE)
    paving = _clean(free.difference(green))  # what is too thin to plant
    shade = shade_area(green, inputs.buildings, inputs.latitude)
    zones = {"lawn": _clean(green.difference(shade)), "shade": shade, "hedge": hedge, "path": path_area, "plaza": plaza, "paving": paving}
    trees = _place_trees(style, inputs, zones, lines, shade, rng)
    lot = inputs.lot
    areas = {k: round(v.intersection(lot).area, 1) for k, v in zones.items()}
    in_lot = [t for t in trees if lot.contains(Point(t["x"], t["y"]))]
    planters = sum(1 for t in in_lot if t["kind"] == "planter") * PLANTER * PLANTER
    width = inputs.open_space_width
    plaza_width_ok = None if not width else not _clean(plaza.buffer(-width / 2 + 0.05)).is_empty
    return {
        "style": style, "label": s["label"], "about": s["about"],
        "zones": {k: _rings(v) for k, v in zones.items()},
        "paths": [{"line": [[round(x, 2), round(y, 2)] for x, y in ln.coords], "width": s["path"]} for ln in lines],
        "trees": trees,
        "doors": [[round(d["door"].x, 2), round(d["door"].y, 2)] for d in doors if inputs.buildings],
        "areas": areas,
        "planting_m2": round(areas["lawn"] + areas["shade"] + areas["hedge"] + planters, 1),
        "trees_in_lot": len(in_lot),
        "plaza_m2": areas["plaza"],
        "plaza_width_ok": plaza_width_ok,
    }
