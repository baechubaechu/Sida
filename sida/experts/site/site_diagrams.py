"""Site analysis diagrams (대지분석 다이어그램, 2026-11-17 지훈: GROUNDKIT의 다이어그램 묶음을 본받기).

Each is a flat drawing of the site's surroundings, made by rule from what Sida already has: the
surroundings of context3d (buildings with their height and use, road / sidewalk / water areas,
road paint, rule-set street trees, contours and the ground) and the site's position for the sun.
A drawing is a list of layers (one fill or line per class of things, in metres) with its legend
and footer (`drawing`), and site_sheet.py sets it on one sheet layout shared by every kind
(title, the map cut to its range, legend with figures, sources), as SVG; the table and the
presentation take that picture.

Only what a file may hold is drawn (as context3d.export_layers and file_buildings): the map packs
(GIS건물통합정보, 수치지형도, 정밀도로지도), never VWorld's live outlines or floors (이용약관
제19조). Nothing is estimated here: a building's height is the one the surroundings give (floors ×
a storey height is marked as such and drawn lighter), a building without a height is a dashed
outline that casts no shadow, and the sun is placed by the usual low-precision solar formulae
(about ±0.1°). Where a diagram cannot be drawn, `available` says why.

The kinds (KINDS): figure_ground, figure_nolli, heights, uses, streets, water_trees, terrain, shadow
(동지 9~15시, one hour or all of them layered), sun_path and distance. Each has the range that suits
it (SCALE: the shadow reads close to the site, the figure-ground far around it) and can be drawn
one step smaller or larger (SCALES), cut exactly to the shape picked for 주변 3D (a square, a
circle or a rectangle). The surroundings are read straight from the map packs out to the largest
step (`gather`), apart from 주변 3D's own range. The site lies over the drawing (its own old
buildings under it), so it reads at a glance.

Independent of HTTP and the screen; coordinates are the table's metres (board.site_plan: x east,
y north, the site's middle at 0, 0).
"""

from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry import box as shapely_box
from shapely.ops import unary_union
from shapely.prepared import prep

from sida.experts.site import context3d, context_range

KINDS: dict[str, str] = {
    "figure_ground": "피겨-그라운드",
    "figure_nolli": "피겨-그라운드 · 놀리",
    "heights": "건물 높이",
    "uses": "건물 용도",
    "streets": "도로·보행",
    "water_trees": "물·나무",
    "terrain": "지형·경사",
    "shadow": "그림자 · 동지",
    "sun_path": "태양 궤적",
    "distance": "거리 반경",
}
RANGES = ("small", "default", "large")  # one step under the kind's range, its range, one step over
SCALES = (75.0, 100.0, 150.0, 200.0, 300.0, 400.0, 500.0, 1000.0)  # m from the site's middle to the range's edge
GATHER = SCALES[-1]  # m: how far the surroundings are read for the diagrams
TERRAIN_STEP = 8.0  # m: the ground grid the diagrams read (2 km across)
SCALE = {  # the range that suits each kind (m from the middle): 1 km across, as a site analysis sheet is read
    "figure_ground": 500.0, "figure_nolli": 500.0, "heights": 500.0, "uses": 500.0, "streets": 500.0,
    "water_trees": 500.0, "terrain": 500.0, "distance": 500.0, "sun_path": 0.0,
    "shadow": 100.0,  # only when no building's shadow reaches the site: the shadow is fitted to the site (shadow_reach)
}
SHADOW_FIT = (100.0, 300.0)  # the shadow's own range is kept within these
SHADOW_HOURS = tuple(range(9, 16))  # 동지 9~15시, the hours the 일조 rules look at
KST = dt.timezone(dt.timedelta(hours=9))
WALK = 80.0  # m a minute on foot, for the distance rings
CHOICES = "diagrams"  # key in site_context.json: {kind: {"range", "hour"}}

# Colours (placeholders: the team's designer owns them). Every sheet shares the frame, the site and the ink.
INK = "#1d1d1b"
MUTED = "#8a877f"
FRAME = "#bdb8ad"
LOT = "#d6402b"  # the site: a red apart from every other colour
SHADE = "#1d2a36"
SUN = "#f2b33d"  # the sun's place at each hour, on the range's edge
SHADE_BANDS = (  # hours in shade on 동지 9~15시: (from, to, colour, label)
    (1, 2, "#e1e5ea", "1~2시간"), (3, 4, "#a9b4c1", "3~4시간"), (5, 7, "#5d6d81", "5시간 이상"),
)
UNKNOWN = "#c46d2a"  # the dashed outline of a building without a height (the shadow)
HATCH = "hatch"  # a fill drawn as the sheet's 45° hatch: what is not known
OUTLINE = "#b5b0a5"  # outlines of white buildings
GHOST = "#dcd8cf"  # buildings in the background of another subject
YARD = "#d3cfc6"  # open ground held inside a block (the Nolli figure-ground)
# The streets under a plan of buildings: quiet enough that the buildings stay the subject
BASE = {"road": "#e4e1da", "sidewalk": "#f1efea", "water": "#cae5e1"}
# The street plan itself
ROAD, WALKWAY, WATER, TREE = "#62666b", "#e6dcc8", "#a9cbe6", "#5f9a4a"
PAINT = {"yellow": "#f2c230", "white": "#ffffff", "blue": "#2f6fd6"}
# Heights, low to high: (from m, below m, colour, label)
HEIGHT_BANDS = (
    (0.0, 12.0, "#dde8f2", "12 m 미만"),
    (12.0, 30.0, "#a9c8e3", "12~30 m"),
    (30.0, 60.0, "#6fa2cf", "30~60 m"),
    (60.0, 100.0, "#3f7bb5", "60~100 m"),
    (100.0, math.inf, "#163f75", "100 m 이상"),
)
# Uses: a 건축물대장 주용도 belongs to the first group with a word in its name; the rest is "그 밖의 용도".
USE_GROUPS = (
    ("주거", ("주택", "아파트", "다세대", "연립", "다가구", "기숙사"), "#f2c14e"),
    ("근린생활", ("근린생활",), "#ee8576"),
    ("판매·숙박", ("판매", "숙박", "위락", "운수"), "#c8364a"),
    ("업무", ("업무",), "#7d2a8c"),
    ("공공·교육·문화", ("교육", "연구", "문화", "집회", "종교", "의료", "노유자", "수련", "운동", "방송", "교정", "국방",
                  "공공", "관광", "장례", "묘지"), "#2c7fb8"),
)
USE_OTHER = ("그 밖의 용도", "#8c96a0")
USE_UNKNOWN = ("용도 미확인", HATCH)
SLOPE_BANDS = (  # percent: (from, below, colour, label)
    (0.0, 5.0, "#f4f1e8", "5% 미만"),
    (5.0, 10.0, "#e8dcb5", "5~10%"),
    (10.0, 15.0, "#d9b77a", "10~15%"),
    (15.0, 25.0, "#c98d4e", "15~25%"),
    (25.0, math.inf, "#a85e34", "25% 이상"),
)
CONTOUR, CONTOUR_INDEX, CONTOUR_WORD = "#b9ad98", "#8f8170", "#5b4630"
RINGS = "#2f5d7c"  # distance rings
SUN_DAYS = (("하지", 6, 21, "#2c64b8"), ("춘추분", 3, 20, "#7fa7cf"), ("동지", 12, 22, "#e0703a"))
SUN_RADIUS = 100.0  # the sun path is drawn this many units from the zenith to the horizon
MAX_BUILDINGS = 40000
MAX_TREES = 4000

NOT_READY = {
    "no_buildings": "파일에 담을 수 있는 건물 자료(GIS건물통합정보 묶음)가 이 범위에 없습니다.",
    "no_uses": "건물마다 용도(건축물대장 주용도)를 찾지 못했습니다.",
    "no_streets": "도로·인도 면 자료(수치지형도 묶음)가 이 범위에 없습니다.",
    "no_water_trees": "물 면도, 나무를 세울 인도도 이 범위에 없습니다.",
    "no_terrain": "지형 묶음(등고선)이 이 범위에 없습니다.",
}


# ---------------------------------------------------------------------------
# What the diagrams are drawn from
# ---------------------------------------------------------------------------


def materials(project_dir: Path, *, gather_fn=None) -> dict | None:
    """
    What the diagrams draw from: {"plan", "around"}, the surroundings read straight from the map
    packs out to the largest range a diagram may take (`gather`), in the shape the designer
    picked for 주변 3D. None when no site has been looked up. Raises ValueError for a site
    without a boundary.
    """
    from sida.board import site_plan
    from sida.experts.site import site_facts

    facts = site_facts.load_facts(project_dir)
    plan = site_plan(site_facts.board_summary(facts)["parcels"]) if facts else None
    if not plan:
        return None
    picked = context_range.load(project_dir)
    return {"plan": plan, "around": (gather_fn or gather)(plan, shape=picked["shape"], orient=picked["orient"])}


_gathered: dict[tuple, tuple[float, dict]] = {}


def gather(plan: dict, *, shape: str = context3d.DEFAULT_SHAPE, orient: str = context3d.DEFAULT_ORIENT,
           folder: Path | None = None) -> dict:
    """
    The surroundings within GATHER m of the site's middle, from the map packs alone (one query of
    the GIS건물통합정보 and 수치지형도 packs, the ground from its tiles or solved once): no 3D
    build, no 건축물대장 or VWorld call, so a wide range costs little. The same shape as
    context3d.build's (buildings with height, height_source and use, areas, contours, terrain,
    road marks, rule-set trees), each building's height its GIS height, else its floors × a
    storey height for its use (an estimate), else none. Kept in memory for context3d.CACHE_SECONDS.
    """
    origin = (plan or {}).get("origin")
    if not origin:
        raise ValueError("the site has no boundary to stand on")
    site = [np.asarray(r, dtype=float) for p in plan.get("parcels") or [] for r in p.get("rings") or []]
    key = (origin["lon"], origin["lat"], tuple(r.tobytes() for r in site), str(folder))
    hit = _gathered.get(key)
    if hit and time.time() - hit[0] < context3d.CACHE_SECONDS:
        return {**hit[1], "shape": shape, "orient": orient}
    frame = context3d.Frame(origin)
    g = context3d.ground(frame, GATHER, folder=folder, shape="square")
    lot = unary_union([_polygon(r) for r in site if len(r) >= 3]) if site else None
    found, unknown = [], []
    for b in g["buildings"]:
        ring = frame.local(b["ring"])
        if len(ring) < 3 or not context3d.in_range(ring.mean(axis=0), GATHER, "square")[0]:
            continue
        outline = [[round(float(x), 2), round(float(y), 2)] for x, y in ring]
        on_site = bool(lot is not None and lot.contains(Point(*ring.mean(axis=0))))
        use = str(b.get("use") or "").strip()
        height, floors = float(b.get("height") or 0), float(b.get("floors") or 0)
        if height > 0:
            found.append({"outline": outline, "height": round(height, 2), "height_source": "file", "use": use, "on_site": on_site})
        elif floors > 0:
            found.append({"outline": outline, "height": round(floors * context3d.storey_height(use), 2),
                          "height_source": "estimate", "use": use, "on_site": on_site})
        else:
            unknown.append({"outline": outline, "on_site": on_site})
    packs = [s for s in g["sources"] if s.get("kind") == "buildings"]
    terrain = context3d.view_grid(g, GATHER, g["areas"], step=TERRAIN_STEP, shape="square")
    outlines = [b["outline"] for b in found + unknown]
    around = {
        "origin": {"lon": origin["lon"], "lat": origin["lat"]}, "radius": GATHER,
        "ground_elev": g["ground_elev"], "terrain": terrain,
        "terrain_sources": [{"name": s.get("source", "")} for s in g["sources"]
                            if s.get("kind", "contours") in ("contours", "areas", "roads")],
        "building_source": {"name": packs[0].get("source", ""), "pack": packs[0].get("name", "")} if packs else {"pack": ""},
        "buildings": found, "unknown_buildings": unknown,
        "areas": [{"kind": kind, "ring": [[round(float(x), 2), round(float(y), 2)] for x, y in ring]}
                  for kind, ring in g["areas"] if len(ring) >= 3],
        "contours": g["contours"],
        "road_marks": context3d.paint_on(g["paint"], terrain, GATHER, "square"),
        "trees": context3d.trees_on(g["areas"], outlines, terrain, GATHER, "square"),
    }
    _gathered[key] = (time.time(), around)
    return {**around, "shape": shape, "orient": orient}


def buildings(around: dict) -> tuple[list[dict], list[dict]]:
    """
    The buildings a file may hold: [{outline, height, estimate, on_site, use}] (height in m above
    its ground) and those without a height: [{outline, on_site}]. Nothing when the buildings did
    not come from the map packs. VWorld's outlines are left out, and VWorld's floors fall back to
    the 1:5,000 map's (context3d `offline`) or to no height.
    """
    if not (around.get("building_source") or {}).get("pack"):
        return [], []
    known, unknown = [], []
    for b in around.get("buildings") or []:
        if b.get("display_only") or len(b.get("outline") or []) < 3:
            continue
        height, source = b.get("height"), b.get("height_source")
        if source == "api_estimate":
            if not b.get("offline"):
                unknown.append({"outline": b["outline"], "on_site": bool(b.get("on_site"))})
                continue
            height, source = b["offline"]["height"], b["offline"]["source"]
        if not height or height <= 0:
            unknown.append({"outline": b["outline"], "on_site": bool(b.get("on_site"))})
            continue
        known.append({"outline": b["outline"], "height": float(height), "estimate": source in context3d.ESTIMATES,
                      "on_site": bool(b.get("on_site")), "use": str(b.get("use") or "").strip()})
    for b in around.get("unknown_buildings") or []:
        if len(b.get("outline") or []) >= 3:
            unknown.append({"outline": b["outline"], "on_site": bool(b.get("on_site"))})
    return known[:MAX_BUILDINGS], unknown[:MAX_BUILDINGS]


def use_group(use: str) -> tuple[str, str]:
    """The group a 건축물대장 주용도 is drawn in: (label, colour)."""
    if not use:
        return USE_UNKNOWN
    for label, words, color in USE_GROUPS:
        if any(word in use for word in words):
            return label, color
    return USE_OTHER


@dataclass
class Region:
    """The ground a diagram shows: its shape, that shape's box, and a fast test against it."""

    shape: object
    box: tuple = field(init=False)
    inside: object = field(init=False, repr=False)

    def __post_init__(self):
        self.box = tuple(self.shape.bounds)
        self.inside = prep(self.shape)


def reach(kind: str, scope: str, base: float | None = None) -> float:
    """
    How far (m from the site's middle) a kind is drawn: its range for this site (`base`, else its
    SCALE), or one step of SCALES under or over it.
    """
    if scope not in RANGES:
        raise ValueError("range must be small, default or large")
    base = base if base is not None else SCALE.get(kind, 200.0)
    at = min(range(len(SCALES)), key=lambda i: abs(SCALES[i] - base))
    return SCALES[min(max(at + RANGES.index(scope) - 1, 0), len(SCALES) - 1)]


def shadow_reach(around: dict, plan: dict | None, *, year: int | None = None) -> float:
    """
    The shadow's range for this site: the smallest step of SCALES (within SHADOW_FIT) that holds
    every building whose shadow falls on the lot at some hour of 동지 9~15시, by its height.
    SCALE["shadow"] when no shadow reaches the lot or there is no lot.
    """
    rings = _lot(plan or {})
    lot = unary_union([_polygon(r) for r in rings if len(r) >= 3]) if rings else None
    if lot is None or lot.is_empty:
        return SCALE["shadow"]
    origin = around.get("origin") or (plan or {}).get("origin") or {}
    lon, lat = float(origin.get("lon", 127.0)), float(origin.get("lat", 37.5))
    day = winter_solstice(int(year or dt.date.today().year))
    suns = [s for s in (sun_position(dt.datetime(day.year, day.month, day.day, h, tzinfo=KST), lon, lat)
                        for h in SHADOW_HOURS) if s[0] > 1]
    if not suns:
        return SCALE["shadow"]
    longest = 1 / math.tan(math.radians(min(alt for alt, _az in suns)))
    lot_reach = max(math.hypot(x, y) for ring in rings for x, y in ring)
    need = 0.0
    for b in buildings(around)[0]:
        if b["on_site"]:
            continue
        pts = np.asarray(b["outline"], dtype=float)
        far = float(np.hypot(pts[:, 0], pts[:, 1]).max())
        if far <= need or float(np.hypot(pts[:, 0], pts[:, 1]).min()) - lot_reach > b["height"] * longest:
            continue
        if any(_shadow(b["outline"], b["height"], alt, az).intersects(lot) for alt, az in suns):
            need = far
    low, high = SHADOW_FIT
    fits = [step for step in SCALES if low <= step <= high]
    return next((step for step in fits if step >= need), fits[-1])


def fit(around: dict, kind: str, plan: dict | None = None) -> float:
    """The range that suits a kind at this site (m from the middle): the shadow's from the heights around, else SCALE."""
    if kind == "shadow" and plan is not None:
        return shadow_reach(around, plan)
    return SCALE.get(kind, 200.0)


def region(around: dict, kind: str, scope: str, plan: dict | None = None) -> Region:
    """
    The ground a kind is drawn over: its reach in the shape picked for 주변 3D (a square, a circle
    or a rectangle, turned as picked) around the site's middle.
    """
    shape = around.get("shape") or context3d.DEFAULT_SHAPE
    hx, hy = context3d.half_sides(reach(kind, scope, fit(around, kind, plan)),
                                  context3d.range_key(shape, around.get("orient") or context3d.DEFAULT_ORIENT))
    if shape == "circle":
        return Region(Point(0.0, 0.0).buffer(hx, quad_segs=32))
    return Region(shapely_box(-hx, -hy, hx, hy))


def frame(around: dict, kind: str, scope: str, plan: dict | None = None) -> tuple[float, float, float, float]:
    """The box around the ground a kind is drawn over (a circle's square)."""
    return region(around, kind, scope, plan).box


def available(around: dict) -> list[dict]:
    """Every kind with whether it can be drawn here: [{kind, title, ready, reason}]."""
    known, unknown = buildings(around)
    kinds = {a["kind"] for a in around.get("areas") or []}
    why = {
        "figure_ground": "" if known or unknown else "no_buildings",
        "figure_nolli": ("" if kinds & {"road", "sidewalk"} else "no_streets") if known or unknown else "no_buildings",
        "heights": "" if known or unknown else "no_buildings",
        "uses": ("" if any(b["use"] for b in known) else "no_uses") if known else "no_buildings",
        "streets": "" if kinds & {"road", "sidewalk"} else "no_streets",
        "water_trees": "" if "water" in kinds or (around.get("trees") or {}).get("points") else "no_water_trees",
        "terrain": "" if around.get("terrain") and around.get("contours") is not None else "no_terrain",
        "shadow": "" if known else "no_buildings",
        "sun_path": "",
        "distance": "",
    }
    return [{"kind": kind, "title": title, "ready": not why[kind], "reason": NOT_READY.get(why[kind], "")}
            for kind, title in KINDS.items()]


# ---------------------------------------------------------------------------
# The sun
# ---------------------------------------------------------------------------


def _solar(when: dt.datetime) -> tuple[float, float, float]:
    """(days from J2000, right ascension, declination in radians) by the Almanac's low-precision formulae."""
    rad = math.pi / 180
    n = when.timestamp() / 86400.0 + 2440587.5 - 2451545.0
    mean_lon = (280.460 + 0.9856474 * n) % 360
    anomaly = (357.528 + 0.9856003 * n) * rad
    ecliptic = (mean_lon + 1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly)) * rad
    tilt = (23.439 - 0.0000004 * n) * rad
    ra = math.atan2(math.cos(tilt) * math.sin(ecliptic), math.cos(ecliptic))
    return n, ra, math.asin(math.sin(tilt) * math.sin(ecliptic))


def sun_position(when: dt.datetime, lon: float, lat: float) -> tuple[float, float]:
    """
    The sun's altitude and azimuth in degrees (azimuth clockwise from north) at an aware time, by
    the low-precision formulae of the Astronomical Almanac (about ±0.1° in this century).
    """
    rad = math.pi / 180
    n, ra, dec = _solar(when)
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    hour_angle = (gmst * 15 + lon) * rad - ra
    phi = lat * rad
    alt = math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(hour_angle))
    az = math.atan2(-math.sin(hour_angle), math.tan(dec) * math.cos(phi) - math.sin(phi) * math.cos(hour_angle))
    return alt / rad, (az / rad) % 360


def winter_solstice(year: int) -> dt.date:
    """The day (KST) of the December solstice: the day of 20~23 December whose noon has the sun furthest south."""
    return dt.date(year, 12, min(range(20, 24), key=lambda day: _solar(dt.datetime(year, 12, day, 12, tzinfo=KST))[2]))


def _shadow(outline: list, height: float, alt: float, az: float):
    """The shadow a prism casts on flat ground: the footprint swept along the sun's direction."""
    reach = height / math.tan(math.radians(alt))
    dx, dy = -math.sin(math.radians(az)) * reach, -math.cos(math.radians(az)) * reach
    pts = [(float(x), float(y)) for x, y in outline]
    pieces = [Polygon(pts), Polygon([(x + dx, y + dy) for x, y in pts])]
    for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1], strict=True):
        quad = Polygon([(ax, ay), (bx, by), (bx + dx, by + dy), (ax + dx, ay + dy)])
        if quad.area > 1e-6:
            pieces.append(quad)
    return unary_union([p if p.is_valid else p.buffer(0) for p in pieces])


# ---------------------------------------------------------------------------
# Layers: what a sheet paints, in order (site_sheet.py sets them on the page)
# ---------------------------------------------------------------------------


def _r(v: float) -> float:
    return round(float(v), 2)


def _ring(ring, *, hole: bool = False) -> list[list[float]]:
    """A ring turned so that a fill of many polygons is their union (outside anticlockwise, holes clockwise)."""
    pts = [[_r(p[0]), _r(p[1])] for p in ring]
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True))
    return pts[::-1] if (area < 0) != hole else pts


def _fill(polygons, color: str, *, opacity: float | None = None, stroke: str | None = None, width: float = 0.0,
          stroke_opacity: float | None = None, dashed: bool = False, name: str = "") -> dict:
    """
    One fill layer: many polygons (each its outside ring then its holes) in one colour, painted as
    their union. `color` may be HATCH; `stroke` and `width` (px on the sheet) outline every polygon.
    """
    layer = {"type": "fill", "polygons": [[_ring(r, hole=i > 0) for i, r in enumerate(poly)] for poly in polygons if poly],
             "color": color, "name": name}
    for key, value in (("opacity", opacity), ("stroke", stroke), ("stroke_opacity", stroke_opacity)):
        if value is not None:
            layer[key] = value
    if stroke:
        layer["width"] = width
    if dashed:
        layer["dashed"] = True
    return layer


def _line(lines, color: str, width: float, *, dashed: bool = False, opacity: float | None = None, name: str = "") -> dict:
    """One line layer: many polylines in one colour and width (px on the sheet)."""
    layer = {"type": "line", "lines": [[[_r(p[0]), _r(p[1])] for p in run] for run in lines if len(run) >= 2],
             "color": color, "width": width, "name": name}
    if dashed:
        layer["dashed"] = True
    if opacity is not None:
        layer["opacity"] = opacity
    return layer


def _label(at, text: str, px: float, *, color: str = INK, weight: int = 400, anchor: str = "middle",
           halo: bool = True) -> dict:
    """A word on the map, with a white halo so it reads over anything (unless not `halo`)."""
    return {"type": "text", "at": [_r(at[0]), _r(at[1])], "text": text, "px": px, "color": color, "weight": weight,
            "anchor": anchor, "halo": halo}


def _key(color: str, label: str, note: str = "", *, mark: str = "fill", outline: str | None = None) -> dict:
    """A legend entry: its swatch (a fill, a line or a dot), its name and a figure in grey after it."""
    return {"color": color, "label": label, "note": note, "mark": mark, "outline": outline}


def _rings_of(shape) -> list[list[list[list[float]]]]:
    """A shapely shape as polygons: one list per polygon, its outside then its holes."""
    out = []
    for part in getattr(shape, "geoms", [shape]):
        if part.geom_type == "Polygon" and not part.is_empty and part.area > 0.01:
            out.append([list(part.exterior.coords)[:-1], *(list(h.coords)[:-1] for h in part.interiors)])
        elif hasattr(part, "geoms"):
            out += _rings_of(part)
    return out


def _outside(ring, box) -> bool:
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return max(xs) <= box[0] or min(xs) >= box[2] or max(ys) <= box[1] or min(ys) >= box[3]


def _polygon(ring) -> Polygon:
    shape = Polygon([p[:2] for p in ring])
    return shape if shape.is_valid else shape.buffer(0)


def _clip(ring, area: Region) -> list[list[list[list[float]]]]:
    """A ring as far as it lies in the ground drawn: polygons (itself, its cut pieces, or none)."""
    if len(ring) < 3 or _outside(ring, area.box):
        return []
    shape = _polygon(ring)
    if area.inside.contains(shape):
        return [[[list(p[:2]) for p in ring]]]
    return _rings_of(shape.intersection(area.shape))


def _clip_all(rings, area: Region) -> list:
    return [poly for ring in rings for poly in _clip(ring, area)]


def _clip_line(points, area: Region) -> list[list]:
    """A line's runs inside the ground drawn, cut exactly where the line leaves it."""
    if len(points) < 2 or _outside(points, area.box):
        return []
    line = LineString([p[:2] for p in points])
    if area.inside.contains(line):
        return [[list(p[:2]) for p in points]]
    cut = line.intersection(area.shape)
    return [[list(xy) for xy in part.coords] for part in getattr(cut, "geoms", [cut])
            if part.geom_type == "LineString" and len(part.coords) >= 2]


def _shown(found: list[dict], area: Region, *, on_site: bool = False) -> list[dict]:
    """
    The buildings that reach into the ground drawn (so the figures under a drawing count what it
    shows), leaving out the site's own old buildings unless `on_site`: the site is drawn over them.
    """
    return [b for b in found if (on_site or not b["on_site"]) and not _outside(b["outline"], area.box)
            and area.inside.intersects(_polygon(b["outline"]))]


def _lot(plan: dict) -> list:
    return [ring for parcel in (plan or {}).get("parcels") or [] for ring in parcel.get("rings") or []]


def _site(plan: dict, area: Region) -> list[dict]:
    """The site over everything: a light red face and a firm red edge."""
    polys = _clip_all(_lot(plan), area)
    return [_fill(polys, LOT, opacity=0.14, stroke=LOT, width=3.5, name="site")] if polys else []


def _sources(around: dict) -> str:
    names = [s.get("name") for s in around.get("terrain_sources") or [] if s.get("name")]
    pack = (around.get("building_source") or {}).get("name")
    return " · ".join(dict.fromkeys([*names, *([pack] if pack else [])]))


def _share(count: int, total: int) -> str:
    return f"{count:,}동 · {count / total * 100:.0f}%" if total else f"{count:,}동"


def _ground(around: dict, area: Region) -> tuple[list[dict], list[dict]]:
    """
    The streets under a plan of buildings: the road, sidewalk and water faces of the 1:5,000 map
    in quiet colours, and their legend entries.
    """
    layers, keys = [], []
    words = {"road": "도로", "sidewalk": "인도", "water": "수계"}
    for kind in ("road", "sidewalk", "water"):
        polys = _clip_all([face["ring"] for face in around.get("areas") or [] if face["kind"] == kind], area)
        if polys:
            layers.append(_fill(polys, BASE[kind], name=kind))
            keys.append(_key(BASE[kind], words[kind], outline="#c9c6bd" if kind != "water" else None))
    return layers, keys


def _built_share(polys: list, area: Region) -> float:
    covered = unary_union([Polygon(poly[0], poly[1:]).buffer(0) for poly in polys]) if polys else None
    return covered.intersection(area.shape).area / area.shape.area * 100 if covered is not None else 0.0


# ---------------------------------------------------------------------------
# The kinds: each gives (layers, legend, footer lines, notes)
# ---------------------------------------------------------------------------


def _figure_ground(around, plan, area, _opts):
    """Buildings black on white, nothing else: the grain of the blocks."""
    known, unknown = (_shown(found, area) for found in buildings(around))
    rings = [b["outline"] for b in known + unknown]
    polys = _clip_all(rings, area)
    legend = [_key(INK, "건물", f"{len(rings):,}동"),
              _key("#ffffff", "건폐 비율 (범위 안)", f"{_built_share(polys, area):.1f}%", outline=INK)]
    return [_fill(polys, INK, name="buildings")], legend, ["범위 안 건물 바닥 면적 ÷ 범위 넓이"], []


def _figure_nolli(around, plan, area, _opts):
    """
    Nolli's figure-ground: buildings black, the ground everyone may walk (the 1:5,000 map's road
    and sidewalk faces, and water) white, and the ground inside the blocks (yards, parking, empty
    lots) a light grey: which open ground is public and which is held within a block.
    """
    known, unknown = (_shown(found, area) for found in buildings(around))
    polys = _clip_all([b["outline"] for b in known + unknown], area)
    covered = unary_union([Polygon(poly[0], poly[1:]).buffer(0) for poly in polys]) if polys else None
    faces = [_polygon(face["ring"]).buffer(0) for face in around.get("areas") or []
             if face["kind"] in ("road", "sidewalk", "water") and len(face["ring"]) >= 3]
    public = unary_union(faces).intersection(area.shape) if faces else None
    if public is not None and covered is not None:
        public = public.difference(covered)
    held = area.shape
    for part in (covered, public):
        if part is not None:
            held = held.difference(part)
    total = area.shape.area
    layers = [_fill(_rings_of(held), YARD, name="held"), _fill(polys, INK, name="buildings")]
    legend = [_key(INK, "건물", f"{len(known) + len(unknown):,}동 · {_built_share(polys, area):.1f}%"),
              _key("#ffffff", "길·광장 (모두가 다니는 빈 땅)", f"{(public.area if public is not None else 0) / total * 100:.1f}%",
                   outline=INK),
              _key(YARD, "가구 안 빈 땅 (마당·주차·빈터)", f"{held.area / total * 100:.1f}%")]
    footer = ["흰 땅은 수치지형도의 도로·인도·수계 면 · 지도에 도로로 그려지지 않은 광장·공원은 회색으로 보일 수 있습니다"]
    return layers, legend, footer, []


def _heights(around, plan, area, _opts):
    known, unknown = (_shown(found, area) for found in buildings(around))
    layers, streets = _ground(around, area)
    total = len(known) + len(unknown)
    legend = []
    for lo, hi, color, label in HEIGHT_BANDS:
        band = [b for b in known if lo <= b["height"] < hi]
        sure = _clip_all([b["outline"] for b in band if not b["estimate"]], area)
        guessed = _clip_all([b["outline"] for b in band if b["estimate"]], area)
        if guessed:
            layers.append(_fill(guessed, color, opacity=0.55, name=f"{label} (추정)"))
        if sure:
            layers.append(_fill(sure, color, name=label))
        legend.append(_key(color, label, _share(len(band), total)))
    if unknown:
        layers.append(_fill(_clip_all([b["outline"] for b in unknown], area), HATCH, name="높이 미확인"))
        legend.append(_key(HATCH, "높이 미확인", _share(len(unknown), total)))
    guessed = sum(1 for b in known if b["estimate"])
    footer = [f"높이 확인 {len(known) - guessed:,}동 · 층수×층고 추정 {guessed:,}동(옅은 색)"
              + (f" · 가장 높은 건물 {max(b['height'] for b in known):.1f} m" if known else ""),
              "높이: 건축물대장 → GIS건물통합정보 → 층수×용도별 층고"]
    return layers, legend + streets, footer, []


def _uses(around, plan, area, _opts):
    known, unknown = (_shown(found, area) for found in buildings(around))
    layers, streets = _ground(around, area)
    total = len(known) + len(unknown)
    groups: dict[str, tuple[str, list]] = {}
    for b in known:
        label, color = use_group(b["use"])
        groups.setdefault(label, (color, []))[1].append(b)
    for b in unknown:
        groups.setdefault(USE_UNKNOWN[0], (USE_UNKNOWN[1], []))[1].append(b)
    legend = []
    for label, color in [(label, color) for label, _w, color in USE_GROUPS] + [USE_OTHER, USE_UNKNOWN]:
        if label in groups:
            layers.append(_fill(_clip_all([b["outline"] for b in groups[label][1]], area), color, name=label))
            legend.append(_key(color, label, _share(len(groups[label][1]), total)))
    return layers, legend + streets, ["용도: 건축물대장 주용도를 다섯 묶음으로 (이름에 든 낱말로 나눔)"], []


def _streets(around, plan, area, _opts):
    known, unknown = (_shown(found, area) for found in buildings(around))
    layers, legend = [], []
    for kind, color, word in (("sidewalk", WALKWAY, "인도"), ("road", ROAD, "차도"), ("water", WATER, "수계")):
        polys = _clip_all([face["ring"] for face in around.get("areas") or [] if face["kind"] == kind], area)
        if polys:
            layers.append(_fill(polys, color, name=word))
            legend.append(_key(color, word))
    paint: dict[str, list] = {}
    for line in (around.get("road_marks") or {}).get("lines") or []:
        for piece in line.get("pieces") or []:
            paint.setdefault(line.get("color") or "white", []).extend(_clip_line(piece, area))
    for name, word in (("yellow", "중앙선"), ("white", "차선·정지선"), ("blue", "자전거")):
        if paint.get(name):
            layers.append(_line(paint[name], PAINT[name], 0.9, name=word))
            legend.append(_key(PAINT[name], word, mark="line", outline="#9a9a9a" if name == "white" else None))
    layers.append(_fill(_clip_all([b["outline"] for b in known + unknown], area), "#ffffff", stroke=OUTLINE, width=0.6,
                        name="buildings"))
    legend.append(_key("#ffffff", "건물", outline=OUTLINE))
    return layers, legend, ["차도·인도: 수치지형도 1:5,000 · 노면 표시: 정밀도로지도"], []


def _water_trees(around, plan, area, _opts):
    known, unknown = (_shown(found, area) for found in buildings(around))
    layers, legend = [], []
    water = _clip_all([face["ring"] for face in around.get("areas") or [] if face["kind"] == "water"], area)
    if water:
        layers.append(_fill(water, "#6ea9d9", name="water"))
        legend.append(_key("#6ea9d9", "하천·호소", "수치지형도"))
    layers.append(_fill(_clip_all([b["outline"] for b in known + unknown], area), GHOST, name="buildings"))
    trees = around.get("trees") or {}
    crown = float(trees.get("crown") or 5.0) / 2
    circle = [(crown * math.cos(a), crown * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)]
    crowns = []
    for x, y, *_z in (trees.get("points") or [])[:MAX_TREES]:
        if area.inside.contains(Point(x, y)):  # a crown on the edge is cut with the rest
            crowns += _clip([[x + dx, y + dy] for dx, dy in circle], area)
    if crowns:
        layers.append(_fill(crowns, TREE, opacity=0.9, stroke="#ffffff", width=0.6, name="trees"))
    legend.append(_key(TREE, "가로수 (규칙 배치, 표현용)", f"{len(crowns):,}그루", mark="dot"))
    legend.append(_key(GHOST, "건물"))
    footer = ["나무는 실제 위치가 아닙니다: " + str(trees.get("rule") or "인도 규칙 배치"),
              "녹지·공원 면은 아직 없습니다 (토지피복지도 이용 조건 확인 뒤)"]
    return layers, legend, footer, []


def _slope_cells(terrain: dict, area: Region) -> list[tuple[int, list]]:
    """The ground's cells by slope band: [(band, polygons of the merged cells)]."""
    n, step, start = int(terrain["n"]), float(terrain["step"]), float(terrain["min"])
    z = np.asarray(terrain["z"], dtype=float).reshape(n, n)
    gy, gx = np.gradient(z, step)
    slope = np.hypot(gx, gy) * 100
    classes = terrain.get("classes") or ""
    edges = [lo for lo, _hi, _c, _l in SLOPE_BANDS[1:]]
    band = np.digitize(slope, edges)
    out = []
    for k in range(len(SLOPE_BANDS)):
        rects = []
        for i in range(n):
            y = start + i * step
            if y + step / 2 < area.box[1] or y - step / 2 > area.box[3]:
                continue
            j = 0
            while j < n:
                if band[i, j] != k or (classes and classes[i * n + j] == context3d.OUTSIDE):
                    j += 1
                    continue
                j0 = j
                while j < n and band[i, j] == k and not (classes and classes[i * n + j] == context3d.OUTSIDE):
                    j += 1
                rects.append(shapely_box(start + j0 * step - step / 2, y - step / 2, start + (j - 1) * step + step / 2, y + step / 2))
        if rects:
            out.append((k, _rings_of(unary_union(rects).intersection(area.shape))))
    return out


def _terrain(around, plan, area, _opts):
    terrain = around.get("terrain")
    cells = dict(_slope_cells(terrain, area))
    layers = [_fill(cells[k], SLOPE_BANDS[k][2], name=SLOPE_BANDS[k][3]) for k in sorted(cells)]
    known, unknown = (_shown(found, area) for found in buildings(around))
    layers.append(_fill(_clip_all([b["outline"] for b in known + unknown], area), "#ffffff", opacity=0.55,
                        stroke=INK, width=0.4, stroke_opacity=0.4, name="buildings"))
    runs = {False: [], True: []}
    words = []
    for c in around.get("contours") or []:
        for run in _clip_line(c["points"], area):
            runs[bool(c.get("index"))].append(run)
            if c.get("index") and len(words) < 40 and len(run) > 4:
                words.append(_label(run[len(run) // 2], f"{c['elev']:g}", 12, color=CONTOUR_WORD, weight=500))
    layers += [_line(runs[False], CONTOUR, 0.9, name="contours"), _line(runs[True], CONTOUR_INDEX, 1.8, name="index contours"), *words]
    z = np.asarray(terrain["z"], dtype=float)
    elev = around.get("ground_elev")
    footer = []
    if elev is not None:
        lot = _clip_all(_lot(plan), area)
        if lot:
            top = max(p[1] for p in lot[0][0])
            middle = sum(p[0] for p in lot[0][0]) / len(lot[0][0])
            layers.append(_label([middle, top], f"대지 {elev:.1f} m", 14, color=LOT, weight=700))
        footer.append(f"대지 가운데 표고 {elev:.1f} m · 범위 안 {elev + z.min():.1f}~{elev + z.max():.1f} m")
    footer.append("경사: 등고선·표고점(1:5,000)으로 만든 지면의 4 m 격자 · 등고선 5 m, 굵은 선 25 m")
    legend = [_key(color, label) for _lo, _hi, color, label in SLOPE_BANDS]
    if runs[False] or runs[True]:
        legend.append(_key(CONTOUR_INDEX, "등고선 5 m · 계곡선 25 m", mark="line"))
    return layers, legend, footer, []


def _shadow_layer(known: list[dict], alt: float, az: float, area: Region):
    shapes = [_shadow(b["outline"], b["height"], alt, az) for b in known if not b["on_site"]]
    return unary_union(shapes).intersection(area.shape) if shapes else None


def _shade_hours(shades: list) -> list[tuple[int, object]]:
    """[(hours, ground)]: the shaded ground split by how many of the hours' shadows lie on it."""
    pieces: list[tuple[int, object]] = []
    covered = None
    for shade in shades:
        nxt = [(1, shade if covered is None else shade.difference(covered))]
        for count, ground in pieces:
            nxt += [(count + 1, ground.intersection(shade)), (count, ground.difference(shade))]
        covered = shade if covered is None else covered.union(shade)
        merged: dict[int, list] = {}
        for count, ground in nxt:
            if not ground.is_empty and ground.area > 1e-6:
                merged.setdefault(count, []).append(ground)
        pieces = [(count, unary_union(grounds)) for count, grounds in sorted(merged.items())]
    return pieces


def _shadow_kind(around, plan, area, opts):
    """
    One hour: its shadow in one tone over the streets. All of 동지 9~15시: how many hours each
    piece of ground lies in shade, in three bands on white ground, and how much of the site each holds.
    """
    known, unknown = buildings(around)
    origin = around.get("origin") or plan.get("origin") or {}
    lon, lat = float(origin.get("lon", 127.0)), float(origin.get("lat", 37.5))
    day = winter_solstice(int(opts.get("year") or dt.date.today().year))
    hour = opts.get("hour")
    hours = [hour] if hour in SHADOW_HOURS else list(SHADOW_HOURS)
    lot_shape = unary_union([Polygon(r).buffer(0) for r in _lot(plan) if len(r) >= 3]) if _lot(plan) else None
    lot_area = lot_shape.area if lot_shape is not None else 0.0
    one = len(hours) == 1
    layers, streets = _ground(around, area) if one else ([], [])
    lines, shades, suns = [], [], []
    for h in hours:
        alt, az = sun_position(dt.datetime(day.year, day.month, day.day, h, tzinfo=KST), lon, lat)
        if alt <= 1:
            continue
        shade = _shadow_layer(known, alt, az, area)
        share = ""
        if shade is not None and not shade.is_empty:
            shades.append(shade)
            if lot_area > 0:
                share = f" · 대지 그늘 {lot_shape.intersection(shade).area / lot_area * 100:.0f}%"
        lines.append(f"{h}시 고도 {alt:.1f}° 방위 {az:.0f}° · 그림자 길이 높이의 {1 / math.tan(math.radians(alt)):.1f}배{share}")
        suns.append((h, az))
    legend = []
    if one:
        if shades:
            layers.append(_fill(_rings_of(shades[0]), SHADE, opacity=0.4, name=f"{hours[0]}시"))
        legend.append(_key(SHADE, "그늘"))
    else:
        counted = _shade_hours(shades)
        for low, high, color, label in SHADE_BANDS:
            ground = unary_union([g for count, g in counted if low <= count <= high])
            if not ground.is_empty:
                layers.append(_fill(_rings_of(ground), color, name=label))
            note = f"대지 {lot_shape.intersection(ground).area / lot_area * 100:.0f}%" if lot_area > 0 else ""
            legend.append(_key(color, label, note))
    shown = _shown(known, area, on_site=True)
    layers.append(_fill(_clip_all([b["outline"] for b in shown if not b["on_site"]], area), "#ffffff", stroke=OUTLINE,
                        width=0.6, name="buildings"))
    on_site = _clip_all([b["outline"] for b in shown if b["on_site"]], area)
    if on_site:
        layers.append(_fill(on_site, "#ffffff", stroke=OUTLINE, width=0.8, dashed=True, name="old buildings on the site"))
    blind = _clip_all([b["outline"] for b in _shown(unknown, area)], area)
    if blind:
        layers.append(_fill(blind, "#ffffff", stroke=UNKNOWN, width=1.0, dashed=True, name="no height"))
    layers += _sun_marks(suns, area)
    when = f"{day.isoformat()} {hours[0]}시" if one else f"{day.isoformat()} 9~15시, 한 시간마다 그림자를 겹쳐 그늘인 시간을 셈"
    footer = [f"동지 {when} · 땅은 평평하다고 보고 계산", *lines]
    notes = []
    if unknown:
        notes.append(f"높이를 모르는 건물 {len(unknown)}동은 그림자를 그리지 않았습니다.")
    if any(b["on_site"] for b in known):
        notes.append("대지 안의 기존 건물은 그림자를 그리지 않았습니다 (점선).")
    legend.append(_key("#ffffff", "건물", outline=OUTLINE))
    if blind:
        legend.append(_key(UNKNOWN, "높이 미확인: 그림자 없음", mark="line"))
    if suns:
        legend.append(_key(SUN, "해 위치 (시각)", mark="dot"))
    return layers, legend + streets, footer, notes


def _sun_marks(suns: list[tuple[int, float]], area: Region) -> list[dict]:
    """
    A yellow dot with its hour where the sun stands, for each hour: on a circle just inside the
    range (the largest one a box holds, so the dots keep off its corners and the scale bar).
    """
    x0, y0, x1, y1 = area.box
    per_px = (x1 - x0) / 1000  # m a px on the sheet
    reach = min(x1 - x0, y1 - y0) / 2 - 20 * per_px
    out = []
    for h, az in suns:
        at = (math.sin(math.radians(az)) * reach, math.cos(math.radians(az)) * reach)
        dot = Point(at).buffer(11 * per_px, quad_segs=8)
        out.append(_fill(_rings_of(dot), SUN, name=f"해 {h}시"))
        out.append(_label((at[0], at[1] - 4.5 * per_px), str(h), 12, color="#ffffff", weight=700, halo=False))
    return out


def _sun_path(around, plan, _area, opts):
    origin = around.get("origin") or plan.get("origin") or {}
    lon, lat = float(origin.get("lon", 127.0)), float(origin.get("lat", 37.5))
    year = int(opts.get("year") or dt.date.today().year)
    radius = SUN_RADIUS

    def at(alt, az):
        r = (90 - alt) / 90 * radius
        return [r * math.sin(math.radians(az)), r * math.cos(math.radians(az))]

    circle = np.linspace(0, 2 * math.pi, 145)
    rings = [[[(90 - alt) / 90 * radius * math.cos(a), (90 - alt) / 90 * radius * math.sin(a)] for a in circle] for alt in (0, 30, 60)]
    layers = [_line(rings, FRAME, 1.0, name="altitudes"), _line([[[0, 0], at(0, az)] for az in (0, 90, 180, 270)], FRAME, 1.0)]
    layers += [_label([2, (90 - alt) / 90 * radius - 4], f"{alt}°", 12, color=MUTED, anchor="start") for alt in (0, 30, 60)]
    layers += [_label(at(-10, az), word, 16, weight=700) for word, az in (("N", 0), ("E", 90), ("S", 180), ("W", 270))]
    hour_points: dict[int, list] = {}
    footer, legend = [], []
    for word, month, day, color in SUN_DAYS:
        if month == 12:
            day = winter_solstice(year).day
        start = dt.datetime(year, month, day, 4, tzinfo=KST)
        track = [sun_position(start + dt.timedelta(minutes=m), lon, lat) for m in range(0, 17 * 60 + 1, 10)]
        run = [at(alt, az) for alt, az in track if alt > 0]
        layers.append(_line([run], color, 3.0, name=word))
        top = max(alt for alt, _az in track)
        legend.append(_key(color, f"{word} {month}/{day}", f"남중 고도 {top:.1f}°", mark="line"))
        dots = []
        for h in range(5, 20):
            alt, az = sun_position(dt.datetime(year, month, day, h, tzinfo=KST), lon, lat)
            if alt > 0:
                x, y = at(alt, az)
                hour_points.setdefault(h, []).append([x, y])
                dots.append([[x + 1.4 * math.cos(a), y + 1.4 * math.sin(a)] for a in circle[:-1:12]])
        layers.append(_fill([[d] for d in dots], color, stroke="#ffffff", width=1.0))
    layers.append(_line([pts for pts in hour_points.values() if len(pts) > 1], MUTED, 0.8, dashed=True, name="hours"))
    layers += [_label([pts[0][0], pts[0][1] + 4], str(h), 12, color=MUTED) for h, pts in hour_points.items()]
    footer.append(f"위도 {lat:.2f}° 경도 {lon:.2f}° · 시각은 한국 표준시 · 태양 위치 공식(±0.1°)")
    return layers, legend, footer, []


def _distance(around, plan, area, _opts):
    known, unknown = (_shown(found, area) for found in buildings(around))
    layers, _streets = _ground(around, area)
    layers.append(_fill(_clip_all([b["outline"] for b in known + unknown], area), GHOST, name="buildings"))
    box = area.box
    half = max(box[2], box[3], -box[0], -box[1])
    step = 25.0 if half <= 100 else 50.0 if half <= 200 else 100.0
    circle = np.linspace(0, 2 * math.pi, 145)
    runs, words = [], []
    r = step
    while r <= half * math.sqrt(2) + 1e-6:
        runs += _clip_line([[r * math.cos(a), r * math.sin(a)] for a in circle], area)
        tx, ty = r * math.cos(math.radians(-40)), r * math.sin(math.radians(-40))
        if area.inside.contains(Point(tx, ty)):
            seconds = round(r / WALK * 60 / 15) * 15
            walk = f"{seconds}초" if seconds < 60 else f"{seconds // 60}분" + (f" {seconds % 60}초" if seconds % 60 else "")
            words.append(_label([tx, ty], f"{r:g} m · {walk}", 13, color=RINGS, weight=500))
        r += step
    layers += [_line(runs, RINGS, 1.4, dashed=True, name="rings"), *words]
    legend = [_key(RINGS, f"{step:g} m 간격", f"걷기 {WALK:g} m/분", mark="line"), _key(GHOST, "건물")]
    return layers, legend, ["대지 가운데에서 직선거리 · 길을 따라간 보행권이 아닙니다"], []


DRAW = {
    "figure_ground": _figure_ground, "figure_nolli": _figure_nolli, "heights": _heights, "uses": _uses, "streets": _streets,
    "water_trees": _water_trees, "terrain": _terrain, "shadow": _shadow_kind, "sun_path": _sun_path,
    "distance": _distance,
}


def _area_words(around: dict, area: Region) -> str:
    """"지름 300 m 원" / "300 m 정사각" / "300×150 m 직사각": the ground a range draws."""
    side = round(area.box[2] - area.box[0])
    shape = around.get("shape") or context3d.DEFAULT_SHAPE
    if shape == "circle":
        return f"지름 {side} m 원"
    tall = round(area.box[3] - area.box[1])
    return f"{side} m 정사각" if side == tall else f"{side}×{tall} m 직사각"


def ranges(around: dict, kind: str, plan: dict | None = None) -> dict:
    """{range: {"side": m across, "words": the ground it draws}} for a kind at this site; none for the sun path."""
    if kind == "sun_path":
        return {}
    out = {}
    base = fit(around, kind, plan)
    for scope in RANGES:
        hx, hy = context3d.half_sides(reach(kind, scope, base), context3d.range_key(
            around.get("shape") or context3d.DEFAULT_SHAPE, around.get("orient") or context3d.DEFAULT_ORIENT))
        area = Region(Point(0.0, 0.0).buffer(hx, quad_segs=32)) if around.get("shape") == "circle" else \
            Region(shapely_box(-hx, -hy, hx, hy))
        out[scope] = {"side": round(area.box[2] - area.box[0]), "words": _area_words(around, area)}
    return out


RANGE_WORDS = {"small": "좁게", "default": "기본", "large": "넓게"}


def drawing(kind: str, mats: dict, scope: str = "default", *, hour: int | None = None, year: int | None = None) -> dict:
    """
    One diagram of the site's surroundings (`mats` from `materials`), for site_sheet.to_svg:
        {"kind", "title", "number", "subtitle", "range", "shape": circle|box|none, "frame": [x0, y0, x1, y1],
         "layers": [...], "legend": [{color, label, note, mark, outline}], "footer": [line], "sources", "notes"}
    Layers are painted in order: {"type": "fill", "polygons", "color" (or HATCH), "opacity"?,
    "stroke"?, "width"?, "dashed"?}, {"type": "line", "lines", "color", "width", "dashed"?} and
    {"type": "text", "at", "text", "px", "color", "weight", "anchor"}; coordinates are metres
    (x east, y north), widths and letters are px on the 1000 px sheet. `hour` picks one hour of
    the shadow (9~15); none layers them all. Raises ValueError for an unknown kind, range or hour,
    or a kind that cannot be drawn here (its reason).
    """
    if kind not in KINDS:
        raise ValueError("kind must be one of " + ", ".join(KINDS))
    if hour is not None and hour not in SHADOW_HOURS:
        raise ValueError("hour must be 9~15")
    around, plan = mats["around"], mats["plan"]
    state = next(a for a in available(around) if a["kind"] == kind)
    if not state["ready"]:
        raise ValueError(state["reason"])
    area = region(around, kind, scope, plan)
    layers, legend, footer, notes = DRAW[kind](around, plan, area, {"hour": hour, "year": year})
    if kind == "shadow":
        footer.append(f"기본 범위: 동지 9~15시에 대지에 그림자가 닿는 건물을 모두 담는 크기 ({fit(around, kind, plan):g} m, "
                      f"{SHADOW_FIT[0]:g}~{SHADOW_FIT[1]:g} m 안에서)")
    pack = (around.get("building_source") or {}).get("name") or ""
    if kind == "sun_path":
        shape, frame_box, subtitle = "none", [-SUN_RADIUS * 1.15, -SUN_RADIUS * 1.15, SUN_RADIUS * 1.15, SUN_RADIUS * 1.15], \
            "하지·춘추분·동지의 해 길, 한 시간마다 점"
    else:
        site = _site(plan, area)
        layers += site
        if site:
            legend.append(_key("#f8dcd6", "대지", outline=LOT))
        shape = "circle" if (around.get("shape") or context3d.DEFAULT_SHAPE) == "circle" else "box"
        frame_box = [_r(v) for v in area.box]
        subtitle = f"{RANGE_WORDS[scope]} · {_area_words(around, area)}" + (f" · 건물: {pack}" if pack else "")
    return {"kind": kind, "title": KINDS[kind], "number": f"{list(KINDS).index(kind) + 1:02d}", "subtitle": subtitle,
            "range": scope, "shape": shape, "frame": frame_box, "layers": [layer for layer in layers if layer.get("polygons", True)
                                                                           and layer.get("lines", True)],
            "legend": legend, "footer": footer, "sources": _sources(around) if kind != "sun_path" else "",
            "notes": notes}


# ---------------------------------------------------------------------------
# What the designer picked for each (kept with the surroundings' range)
# ---------------------------------------------------------------------------


def choices(project_dir: Path) -> dict:
    """{kind: {"range", "hour"}} for every kind: the saved choice, else the kind's own range and all hours."""
    saved = context_range.read(project_dir).get(CHOICES)
    saved = saved if isinstance(saved, dict) else {}
    out = {}
    for kind in KINDS:
        got = saved.get(kind) if isinstance(saved.get(kind), dict) else {}
        hour = got.get("hour")
        out[kind] = {"range": got.get("range") if got.get("range") in RANGES else "default",
                     "hour": hour if isinstance(hour, int) and hour in SHADOW_HOURS else None}
    return out


def save_choice(project_dir: Path, kind: str, scope: str, hour: int | None = None) -> dict:
    """Keep a diagram's range (and the shadow's hour). Raises ValueError for unknown values."""
    if kind not in KINDS:
        raise ValueError("kind must be one of " + ", ".join(KINDS))
    if scope not in RANGES:
        raise ValueError("range must be small, default or large")
    if hour is not None and (isinstance(hour, bool) or hour not in SHADOW_HOURS):
        raise ValueError("hour must be 9~15")
    data = context_range.read(project_dir)
    saved = data.get(CHOICES) if isinstance(data.get(CHOICES), dict) else {}
    saved[kind] = {"range": scope, "hour": hour if kind == "shadow" else None}
    data[CHOICES] = saved
    context_range.write(project_dir, data)
    return choices(project_dir)[kind]
