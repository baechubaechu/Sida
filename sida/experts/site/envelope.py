"""The legal envelope of a site (법규 볼륨) and reference schemes that fill it (2026-11-17 지훈:
"일조사선·용적률·건폐율·대지안의공지 등 모두 고려한 최대 볼륨").

What it applies, each by rule from the government's data and the statute or ordinance as written:

- 정북 일조 (건축법 제61조①, in force 2026-11-12; 시행령 제86조① was struck out): in a
  전용·일반주거지역 each part of a building stands back from the 정북 인접 대지경계선 by the distances
  the 건축 조례 sets within the law's (ordinance.sunlight_rule; Seoul 제35조①: 1.5 m up to 10 m,
  5 m up to 17 m, then half its height, the law's least). When the ordinance is not read, or reads
  as less than the law asks, the law's distances (data/site_rules.yaml) are used and the line
  says "확인 필요".
  The distance is measured due north from each point to where the ray leaves the lot. A parcel
  to the north whose 지목 is a road, railway, river or park (시행령 제86조⑥1) is crossed and the
  far side used. Where the parcel met to the north lies in a zone that is not 전용·일반주거
  (시행령 제86조②1), the point has no 정북 limit.
- 건폐율 and 용적률: the site's figures as the site card has them (site_facts.limits: the
  ordinance's where it was read by rule, else the statutory caps).
- 건축선, 대지 안의 공지 and 공동주택 채광 (setbacks.py, data/envelope_rules.yaml): by the roads and
  parcels around the lot and the use the designer picks on the card.
- A height the designer entered from a 고도지구's notice (site_envelope.json): the notice's height
  is not in the government's data, so it is entered, not read.

What it does not apply yet: the exceptions of 시행령 제86조②2·3 (지구단위계획구역 등의 20 m 도로,
건축협정구역); the 정북 limit is kept there, the stricter way.

The 연속지적 parcels around the site come from VWorld and are used for this answer only, not kept
(VWorld 이용약관 제19조, as context3d). The zones of the parcels met to the north (토지이용계획)
are cached in memory for a while.

Geometry is in the table's metres (x east, y north, board.site_plan) and the blocks' frame (u, v):
the envelope is worked out on a u, v grid so the schemes' blocks line up with the drafting table's.
"""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import numpy as np
from shapely import box as boxes
from shapely import contains_xy, union_all
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from sida import board
from sida.experts.site import landapi, setbacks, site_facts, site_rules
from sida.storage import atomic_write_text

MAX_CELLS = 40_000  # grid cells over the lot; the cell grows on a big lot
MIN_STEP = 0.5  # m
MAX_FLOORS = 200
MAX_LEVELS = 40  # floors drawn as the envelope's slabs
MARGIN = 40.0  # m around the lot in which the parcels to the north are looked up
MAX_ZONE_LOOKUPS = 20
GRID_CELLS = 12000  # the most cells the screen gets for checking blocks
MIN_SIDE = 4.0  # m: a step of a scheme narrower than this is not kept
TOWER_SHARES = (0.45, 0.55, 0.65, 0.75, 0.85)  # the tower scheme's footprint, as a part of the coverage limit
RESIDENTIAL_FLOOR = 3.0  # m, the floor height assumed for a 주거지역 scheme (the designer changes it)
ZONE_TTL = 3600.0  # s a parcel's zone is kept in memory

_zone_cache: dict[str, tuple[float, str | None]] = {}
_zone_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def allowed_height(d: float, steps: list, half_above: float) -> float:
    """The height a part may reach at due-north distance `d` (m) from the line: the highest step
    whose distance `d` meets, or, past the last step, twice `d` (it stands half its height away)."""
    allowed = 0.0
    for distance, height in steps:
        if d >= distance:
            allowed = max(allowed, float(height))
    if 2 * d > half_above:
        allowed = max(allowed, 2 * d)
    return allowed


def residential(zone: str) -> bool:
    return zone in site_rules.load_rules()["north_sunlight"]["zones"]


def sunlight_rule(facts: dict) -> dict:
    """
    The 정북 rule for the site: {"applies", "zone", "steps", "half_above", "status", "source",
    "quote", "detail"}. "applies" is None when the site has several zones (not worked out).
    """
    rules = site_rules.load_rules()["north_sunlight"]
    zones = [z["zone"] for z in facts["summary"]["zoning"]]
    out = {"applies": None, "zone": ", ".join(zones), "steps": rules["steps"], "half_above": float(rules["half_above"]),
           "status": "check", "source": rules["law"], "quote": "", "detail": ""}
    if len(zones) != 1:
        out["detail"] = "용도지역이 여러 개라 법규 볼륨을 계산하지 않음"
        return out
    if not residential(zones[0]):
        out.update(applies=False, status="none", detail=f"{zones[0]}은 전용·일반주거지역이 아님")
        return out
    out["applies"] = True
    found = facts.get("building_ordinance") or {}
    if found.get("rule") and not within_law(found["rule"], rules):
        found = {**found, "rule": None, "error": "below_law"}
    if found.get("rule"):
        out.update(steps=found["rule"]["steps"], half_above=float(found["rule"]["half_above"]), status="read",
                   source=f"{found['name']} {found['label']}", quote=_first_paragraph(found["text"]),
                   detail=f"정북 인접 대지경계선에서 {_steps_text(found['rule']['steps'], found['rule']['half_above'])}")
        return out
    why = {"not_found": "건축 조례를 찾지 못함", "no_article": "건축 조례에 정북 일조 조문이 없음", None: "조례 거리를 규칙으로 읽지 못함",
           "below_law": "조례 거리가 법(제61조①)의 범위보다 짧게 읽혀 쓰지 않음"}
    reason = why.get(found.get("error"), "건축 조례를 조회하지 못함") if found else "건축 조례를 조회하지 않음"
    out.update(quote=" ".join(rules["text"].split()),
               detail=f"{reason}. 법의 최소 거리({_steps_text(rules['steps'], rules['half_above'])})로 계산함, 조례 원문 확인")
    return out


def _steps_text(steps: list, half_above: float) -> str:
    """'10m 이하 1.5m, 17m 이하 5m, 17m 넘는 부분은 높이의 1/2'."""
    parts = [f"{h:g}m 이하 {d:g}m" for d, h in steps]
    return ", ".join([*parts, f"{float(half_above):g}m 넘는 부분은 높이의 1/2"])


def within_law(rule: dict, law: dict) -> bool:
    """Whether an ordinance's distances ask at least what the law's do (건축법 제61조①: the
    ordinance sets them "다음 각 호의 구분에 따른 범위에서"): at no distance may a part stand taller
    than the law lets it. Checked at every step's distance and between them."""
    marks = {0.0, 200.0}
    for steps in (rule["steps"], law["steps"]):
        marks.update(float(d) for d, _h in steps)
    marks.update({float(rule["half_above"]) / 2, float(law["half_above"]) / 2})
    points = sorted({m + e for m in marks for e in (-0.01, 0.0, 0.01) if m + e >= 0})
    return all(allowed_height(d, rule["steps"], float(rule["half_above"]))
               <= allowed_height(d, law["steps"], float(law["half_above"])) + 1e-9 for d in points)


def _first_paragraph(text: str) -> str:
    return " ".join((text or "").split("②", 1)[0].split())


def ratios(facts: dict) -> dict:
    """The coverage and floor-area ratios the schemes fill (%), and where each comes from."""
    lim = site_facts.limits(facts)
    if len(lim) != 1:
        return {"bcr": None, "far": None, "bcr_from": "", "far_from": ""}
    z = lim[0]
    return {
        "bcr": z["ordinance_bcr"] or z["bcr_max"], "far": z["ordinance_far"] or z["far_max"],
        "bcr_from": "조례" if z["ordinance_bcr"] else "법정", "far_from": "조례" if z["ordinance_far"] else "법정",
    }


# ---------------------------------------------------------------------------
# The parcels around the site
# ---------------------------------------------------------------------------


def mark_of(jibun: str) -> str:
    """The 지목 letter at the end of a 연속지적 label ("689-14 장" → "장"), or ''."""
    parts = (jibun or "").split()
    last = parts[-1] if len(parts) > 1 else ""
    return last if len(last) == 1 and "가" <= last <= "힣" else ""


def _lonlat_to_local(origin: dict):
    k = math.pi / 180
    east = board.EARTH_RADIUS * k * math.cos(origin["lat"] * k)
    north = board.EARTH_RADIUS * k
    return (lambda lon, lat: ((lon - origin["lon"]) * east, (lat - origin["lat"]) * north)), east, north


def neighbours(plan: dict, own: set[str], *, http_get=None) -> list[dict]:
    """The 연속지적 parcels around the lot (not the lot's own): [{"pnu", "mark", "rings"}] in the
    table's metres. Raises LandApiError."""
    to_local, east, north = _lonlat_to_local(plan["origin"])
    b, o = plan["bounds"], plan["origin"]
    west, south = o["lon"] + (b["min_x"] - MARGIN) / east, o["lat"] + (b["min_y"] - MARGIN) / north
    east_lon, north_lat = o["lon"] + (b["max_x"] + MARGIN) / east, o["lat"] + (b["max_y"] + MARGIN) / north
    out = []
    for f in landapi.features_in_box("LP_PA_CBND_BUBUN", west, south, east_lon, north_lat, http_get=http_get):
        props = f.get("properties") or {}
        pnu = str(props.get("pnu") or "")
        if not pnu or pnu in own:
            continue
        rings = [[list(to_local(lon, lat)) for lon, lat in ring] for ring in board._outer_rings(f["shape"])]
        if rings:
            out.append({"pnu": pnu, "mark": mark_of(str(props.get("jibun") or "")), "rings": rings})
    return out


def zone_of(pnu: str, *, http_get=None) -> str | None:
    """The 용도지역 a parcel lies in (토지이용계획), or None when not known. Cached for a while."""
    now = time.monotonic()
    with _zone_lock:
        hit = _zone_cache.get(pnu)
        if hit and now - hit[0] < ZONE_TTL:
            return hit[1]
    try:
        uses = landapi.land_use(pnu, http_get=http_get)
    except landapi.LandApiError:
        return None
    zones = site_facts.load_limits()["zones"]
    found = next((u["name"] for u in uses if u["name"] in zones and u.get("relation") != "접함"), None)
    with _zone_lock:
        _zone_cache[pnu] = (now, found)
    return found


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


class _North:
    """Where a ray due north from a point leaves the lot, and what it meets there, by column."""

    def __init__(self, lot, parcels: list[dict], across: dict, column: float):
        self.lot = lot
        self.parcels = [(unary_union([Polygon(r) for r in p["rings"] if len(r) >= 3]).buffer(0), p) for p in parcels]
        self.parcels = [(shape, p) for shape, p in self.parcels if not shape.is_empty]
        self.tree = STRtree([shape for shape, _ in self.parcels]) if self.parcels else None
        self.across = across
        self.column = column
        self.top = lot.bounds[3] + MARGIN * 4
        self.low = lot.bounds[1] - 1
        self.cache: dict[int, list] = {}

    def _spans(self, shape, x: float) -> list[tuple[float, float]]:
        cut = LineString([(x, self.low - MARGIN * 4), (x, self.top)]).intersection(shape)
        parts = getattr(cut, "geoms", [cut])
        return sorted((min(p.coords[0][1], p.coords[-1][1]), max(p.coords[0][1], p.coords[-1][1]))
                      for p in parts if not p.is_empty and p.geom_type == "LineString")

    def _met(self, x: float, y: float):
        if self.tree is None:
            return None
        for i in self.tree.query(Point(x, y)):
            shape, p = self.parcels[int(i)]
            if shape.covers(Point(x, y)):
                return shape, p
        return None

    def spans(self, x: float) -> list:
        """[(bottom, exit y, crossed marks, parcel met beyond or None)] for the lot's spans at x."""
        key = round(x / self.column)
        if key in self.cache:
            return self.cache[key]
        xc = key * self.column
        out = []
        for low, high in self._spans(self.lot, xc):
            y, crossed, met = high, [], None
            for _hop in range(3):
                hit = self._met(xc, y + 0.05)
                if hit is None:
                    break
                shape, p = hit
                if p["mark"] in self.across:
                    crossed.append(self.across[p["mark"]])
                    far = [hi for lo, hi in self._spans(shape, xc) if lo <= y + 0.05 <= hi]
                    if not far:
                        break
                    y = far[0]
                    continue
                met = p
                break
            out.append((low, y, tuple(crossed), met))
        self.cache[key] = out
        return out


def frame_grid(lot, frame: dict, step: float | None = None):
    """The u, v grid over the lot: (u0, v0, step, nu, nv, x, y) with cell-centre table points."""
    a = frame["angle"]
    local = translate(lot, -frame["x"], -frame["y"])
    uv = rotate(local, -a, origin=(0, 0), use_radians=True)
    u0, v0, u1, v1 = uv.bounds
    if step is None:
        step = max(MIN_STEP, math.sqrt((u1 - u0) * (v1 - v0) / MAX_CELLS))
    nu, nv = max(1, math.ceil((u1 - u0) / step)), max(1, math.ceil((v1 - v0) / step))
    us = u0 + (np.arange(nu) + 0.5) * step
    vs = v0 + (np.arange(nv) + 0.5) * step
    uu, vv = np.meshgrid(us, vs)
    x = frame["x"] + uu * math.cos(a) - vv * math.sin(a)
    y = frame["y"] + uu * math.sin(a) + vv * math.cos(a)
    return u0, v0, step, nu, nv, x, y


def heights(lot, frame: dict, rule: dict, parcels: list[dict], zones_of, across: dict, step: float | None = None) -> dict:
    """
    The height allowed on each cell of the u, v grid (m; nan outside the lot, inf with no limit)
    and what the rays met: {"grid": (u0, v0, step, nu, nv), "h", "crossed", "free_cells",
    "unknown_zone", "met_none"}.
    """
    u0, v0, step, nu, nv, x, y = frame_grid(lot, frame, step)
    inside = contains_xy(lot, x, y)
    h = np.full((nv, nu), np.nan)
    info = {"grid": (u0, v0, step, nu, nv), "crossed": set(), "free_cells": 0, "unknown_zone": 0, "met_none": 0}
    if not rule["applies"]:
        h[inside] = np.inf
        info["h"] = h
        return info
    north = _North(lot, parcels, across, step / 2)
    hits = []
    met_pnus: dict[str, None] = {}
    for j, i in zip(*np.nonzero(inside), strict=True):
        px, py = float(x[j, i]), float(y[j, i])
        span = next((s for s in north.spans(px) if s[0] - 1e-6 <= py <= s[1] + 1e-6), None)
        if span is None:  # on the lot's very edge between columns: the nearest span above
            span = next((s for s in north.spans(px) if s[1] >= py), None)
        if span is None:
            continue
        hits.append((j, i, max(span[1] - py, 0.0), span))
        if span[3] is not None:
            met_pnus.setdefault(span[3]["pnu"], None)
    zones = {}
    for n, pnu in enumerate(met_pnus):
        zones[pnu] = zones_of(pnu) if n < MAX_ZONE_LOOKUPS else None
    counted_none, counted_unknown = set(), set()
    for j, i, d, (_low, _top, crossed, met) in hits:
        info["crossed"].update(crossed)
        if met is None:
            counted_none.add((j, i))
        elif zones.get(met["pnu"]) is None:
            counted_unknown.add((j, i))
        elif not residential(zones[met["pnu"]]):  # 시행령 제86조②1: the land to the north is not 주거
            h[j, i] = np.inf
            info["free_cells"] += 1
            continue
        h[j, i] = allowed_height(d, rule["steps"], rule["half_above"])
    info["met_none"], info["unknown_zone"] = len(counted_none), len(counted_unknown)
    info["h"] = h
    return info


def _cells_to_rings(mask: np.ndarray, grid: tuple, frame: dict) -> list[list[list[float]]]:
    u0, v0, step, _nu, _nv = grid
    runs = []  # one box per run of cells along a row
    for j in range(mask.shape[0]):
        edges = np.flatnonzero(np.diff(np.concatenate(([0], mask[j].astype(np.int8), [0]))))
        for a, b in zip(edges[::2], edges[1::2], strict=True):
            runs.append((u0 + a * step, v0 + j * step, u0 + b * step, v0 + (j + 1) * step))
    if not runs:
        return []
    shape = rotate(union_all(boxes(*np.array(runs).T)), frame["angle"], origin=(0, 0), use_radians=True)
    shape = translate(shape, frame["x"], frame["y"]).simplify(step * 0.2)
    out = []
    for g in getattr(shape, "geoms", [shape]):
        if g.geom_type == "Polygon" and g.area >= step * step:
            out.append([[round(px, 2), round(py, 2)] for px, py in list(g.exterior.coords)[:-1]])
    return out


# ---------------------------------------------------------------------------
# Reference schemes
# ---------------------------------------------------------------------------


def max_rect(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """The largest all-True rectangle of cells: (j0, i0, j1, i1), ends exclusive."""
    nv, nu = mask.shape
    run = np.zeros(nu, dtype=int)
    best, found = 0, None
    for j in range(nv):
        run = np.where(mask[j], run + 1, 0)
        stack: list[tuple[int, int]] = []
        for i in range(nu + 1):
            hgt = int(run[i]) if i < nu else 0
            start = i
            while stack and stack[-1][1] >= hgt:
                s, sh = stack.pop()
                if sh * (i - s) > best:
                    best, found = sh * (i - s), (j - sh + 1, s, j + 1, i)
                start = s
            stack.append((start, hgt))
    return found


def _north_side(angle: float) -> tuple[str, int]:
    """Which grid axis runs nearer north and which way: ('v', +1) when north is up the v axis."""
    nu, nv = math.sin(angle), math.cos(angle)  # north (0, 1) in the u, v frame
    return ("v", 1 if nv > 0 else -1) if abs(nv) >= abs(nu) else ("u", 1 if nu > 0 else -1)


def _trim_north(rect, target_cells: int, side) -> tuple:
    """Cut rows from the north side until the rectangle holds at most `target_cells` cells."""
    j0, i0, j1, i1 = rect
    axis, sign = side
    while (j1 - j0) * (i1 - i0) > target_cells and (j1 - j0) > 1 and (i1 - i0) > 1:
        if axis == "v":
            if sign > 0:
                j1 -= 1
            else:
                j0 += 1
        elif sign > 0:
            i1 -= 1
        else:
            i0 += 1
    return (j0, i0, j1, i1)


def _compact(rect, target_cells: int, side) -> tuple:
    """Squarer: the longer side shortened from both ends, the shorter one from the north."""
    j0, i0, j1, i1 = rect
    flip = 0
    while (j1 - j0) * (i1 - i0) > target_cells and (j1 - j0) > 1 and (i1 - i0) > 1:
        if (i1 - i0) > (j1 - j0):
            i0, i1 = (i0 + 1, i1) if flip == 0 else (i0, i1 - 1)
            flip ^= 1
        else:
            j0, i0, j1, i1 = _trim_north((j0, i0, j1, i1), (j1 - j0 - 1) * (i1 - i0), side)
    return (j0, i0, j1, i1)


def scheme(h: np.ndarray, grid: tuple, base, floor_height: float, far_cells: float, side, name: str) -> dict | None:
    """
    A stack of rectangles: floor k is the largest rectangle inside floor k-1 where the envelope
    allows k floors. Floors above the floor-area ratio are left off; the last kept floor is cut
    (from the north) to the area left. Blocks: one per distinct rectangle, as tall as it goes.
    """
    u0, v0, step, _nu, _nv = grid
    min_side = max(1, math.ceil(MIN_SIDE / step))
    tall = np.nan_to_num(h, nan=-1.0, posinf=1e9)
    levels, total = [], 0
    rect = base
    for k in range(1, MAX_FLOORS + 1):
        j0, i0, j1, i1 = rect
        if k > 1:
            sub = tall[j0:j1, i0:i1] >= k * floor_height
            if not sub.all():
                r = max_rect(sub)
                if r is None:
                    break
                rect = (r[0] + j0, r[1] + i0, r[2] + j0, r[3] + i0)
        elif not (tall[j0:j1, i0:i1] >= floor_height).all():
            return None
        j0, i0, j1, i1 = rect
        if (j1 - j0) < min_side or (i1 - i0) < min_side:
            break
        cells = (j1 - j0) * (i1 - i0)
        if total + cells > far_cells:
            room = int(far_cells - total)
            if room >= min_side * min_side:
                cut = _trim_north(rect, room, side)
                if (cut[2] - cut[0]) >= min_side and (cut[3] - cut[1]) >= min_side:
                    levels.append(cut)
                    total += (cut[2] - cut[0]) * (cut[3] - cut[1])
            break
        levels.append(rect)
        total += cells
    if not levels:
        return None
    blocks = []
    for n, r in enumerate(levels):
        if n + 1 < len(levels) and levels[n + 1] == r:
            continue
        j0, i0, j1, i1 = r
        ua, ub, va, vb = u0 + i0 * step, u0 + i1 * step, v0 + j0 * step, v0 + j1 * step
        blocks.append({"u": round((ua + ub) / 2, 2), "v": round((va + vb) / 2, 2), "w": round(ub - ua, 2),
                       "d": round(vb - va, 2), "floors": n + 1})
    cell = step * step
    return {"name": name, "blocks": blocks, "floor_height": floor_height,
            "footprint_m2": round((levels[0][2] - levels[0][0]) * (levels[0][3] - levels[0][1]) * cell, 1),
            "floor_area_m2": round(total * cell, 1), "height_m": round(len(levels) * floor_height, 1)}


def schemes(h: np.ndarray, grid: tuple, frame: dict, floor_height: float, area: float, bcr: float, far: float) -> list[dict]:
    """Two reference schemes: 넓게 낮게 (the coverage filled) and 남쪽 탑형 (a squarer tower on
    the south side). [] when the lot holds no floor."""
    step = grid[2]
    side = _north_side(frame["angle"])
    mask = np.nan_to_num(h, nan=-1.0, posinf=1e9) >= floor_height
    rect = max_rect(mask)
    if rect is None:
        return []
    bcr_cells = int(area * bcr / 100 / (step * step))
    far_cells = area * far / 100 / (step * step)
    out = []
    wide = scheme(h, grid, _trim_north(rect, bcr_cells, side), floor_height, far_cells, side, "넓게 낮게")
    if wide:
        out.append(wide)
    # the tower: the smallest footprint (from TOWER_SHARES of the coverage up) whose floors reach
    # the ratio under the envelope, else the one that holds the most
    best = None
    for share in TOWER_SHARES:
        s = scheme(h, grid, _compact(rect, int(bcr_cells * share), side), floor_height, far_cells, side, "남쪽 탑형")
        if s and (best is None or s["floor_area_m2"] > best["floor_area_m2"] + 1e-6):
            best = s
        if best and best["floor_area_m2"] >= far_cells * step * step * 0.95:
            break
    if best:
        out.append(best)
    return out


# ---------------------------------------------------------------------------
# For the screen
# ---------------------------------------------------------------------------


def _line(id_: str, status: str, title: str, value: str, detail: str = "", quote: str = "", source: str = "") -> dict:
    return {"id": id_, "status": status, "title": title, "value": value, "detail": detail, "quote": quote, "source": source}


def compute(plan: dict, facts: dict, rule: dict, parcels: list[dict] | None, zones_of, *, floor_height: float,
            neighbours_error: str = "", height_cap: float | None = None, use: str | None = None,
            use_area: float | None = None) -> dict:
    """The envelope view of a site (the API's reply) from its plan, facts and the parcels around.
    `height_cap`: the height the designer entered from a 고도지구's notice (m), cutting the envelope;
    `use`, `use_area`: the building's use (envelope_rules uses) and its floor area (㎡), for 대지 안의
    공지 and 채광 (setbacks.py)."""
    rules_data = site_rules.load_rules()
    across = dict(rules_data["across_marks"])
    maybe = dict(rules_data["maybe_across_marks"])
    lot = unary_union([Polygon(r) for p in plan["parcels"] for r in p["rings"] if len(r) >= 3]).buffer(0)
    frame = plan["frame"]
    area = facts["summary"]["total_area_m2"] if facts["summary"].get("area_complete") else None
    ratio = ratios(facts)
    out = {"available": rule["applies"] is not None, "zone": rule["zone"], "floor_height": floor_height,
           "area_m2": area, **ratio, "frame": frame, "grid": None, "levels": [], "max_height_m": None,
           "full_floor_area_m2": None, "schemes": [], "lines": [],
           "height_districts": site_rules.height_districts(facts), "height_limit_m": height_cap,
           "uses": setbacks.uses(), "use": use, "use_area_m2": use_area, "building_line_area_m2": None, "roads": []}
    lines = out["lines"]
    if rule["applies"] is None:
        lines.append(_line("sunlight", "check", "법규 볼륨", "계산 안 함", rule["detail"]))
        return out
    info = heights(lot, frame, rule, parcels or [], zones_of, across)
    h, grid = info["h"], info["grid"]
    u0, v0, step, nu, nv = grid
    # 건축선, 대지 안의 공지, 공동주택 채광 (setbacks.py)
    inside = ~np.isnan(h)
    _u0, _v0, _step, _nu, _nv, x, y = frame_grid(lot, frame, step)
    assumed = area * ratio["far"] / 100 if area and ratio["far"] else None
    more = setbacks.work_out(lot, x, y, inside, zone=rule["zone"], municipality=facts["summary"].get("municipality") or "",
                             parcels=parcels, use=use, floor_area=use_area, assumed_area=assumed,
                             neighbours_error=neighbours_error)
    cell_h = np.minimum(h[inside], more["cap"])
    cell_h[more["open"]] = 0.0
    h[inside] = cell_h
    out["roads"] = more["roads"]
    if more["removed_m2"]:
        out["building_line_area_m2"] = more["removed_m2"]
    if height_cap:
        h = np.minimum(h, float(height_cap))  # nan (outside) stays nan
    finite = h[np.isfinite(h)]
    limited = bool(rule["applies"] or height_cap or more["open"].any() or np.isfinite(more["cap"]).any())
    if limited:
        top = float(finite.max()) if finite.size else 0.0
        out["max_height_m"] = round(top, 1) if finite.size and not np.isinf(h).any() else None
        floors = np.floor(np.nan_to_num(h, nan=0.0, posinf=MAX_FLOORS * floor_height) / floor_height).clip(0, MAX_FLOORS)
        if not np.isinf(h).any():
            out["full_floor_area_m2"] = round(float(floors.sum() * step * step), 1)
        shown = int(min(MAX_LEVELS, (top if finite.size else 0) // floor_height))
        if np.isinf(h).any():  # open above: the ground floor shows where building may stand
            shown = max(shown, 1)
        tall = np.nan_to_num(h, nan=-1.0, posinf=1e9)
        for k in range(1, shown + 1):
            rings = _cells_to_rings(tall >= k * floor_height, grid, frame)
            if not rings:
                break
            out["levels"].append({"z": round(k * floor_height, 2), "rings": rings})
        # the grid for checking blocks on the screen: the calculation's own cells while they are few,
        # else cells pooled to about GRID_CELLS (each keeping the lowest value in it)
        pool = max(1, math.ceil(math.sqrt(nu * nv / GRID_CELLS)))
        rows = []
        for j in range(0, nv, pool):
            row = []
            for i in range(0, nu, pool):
                part = h[j:j + pool, i:i + pool]
                part = part[~np.isnan(part)]
                row.append(None if not part.size else (-1 if np.isinf(part).all() else round(float(part[np.isfinite(part)].min()), 2)))
            rows.append(row)
        out["grid"] = {"u0": round(u0, 3), "v0": round(v0, 3), "step": round(step * pool, 3), "h": rows,
                       "note": "null: outside the lot; -1: no height limit"}
    if area and ratio["bcr"] and ratio["far"]:
        net = area - (out["building_line_area_m2"] or 0.0)  # 시행령 제119조①1: the 건축선's cut is not site area
        out["schemes"] = schemes(h, grid, frame, floor_height, net, ratio["bcr"], ratio["far"])
    # what went into it
    if rule["applies"]:
        lines.append(_line("sunlight", rule["status"], "정북일조", "적용", rule["detail"], rule["quote"], rule["source"]))
        if neighbours_error:
            lines.append(_line("north", "check", "북쪽 이웃 필지", "미확인",
                               "연속지적을 받지 못해 대지경계선에서 바로 잼(도로·공원 건너편, 주거지역 여부를 반영하지 못함)"))
        else:
            parts = []
            if info["crossed"]:
                parts.append(f"북쪽 {', '.join(sorted(info['crossed']))} 건너편 경계선에서 잼(제86조⑥)")
            if info["free_cells"]:
                parts.append("북쪽 이웃이 주거지역이 아닌 부분은 정북일조를 빼고 계산(시행령 제86조②1)")
            if info["unknown_zone"]:
                parts.append("북쪽 이웃 일부는 용도지역을 몰라 적용해 계산함")
            near = sorted({maybe[p["mark"]] for p in parcels or [] if p["mark"] in maybe})
            if near:
                parts.append(f"주변에 {', '.join(near)}이(가) 있음: 건너편 경계선으로 볼지 확인")
            status = "check" if (info["unknown_zone"] or near) else "read"
            lines.append(_line("north", status, "북쪽 이웃 필지", "연속지적·토지이용계획",
                               "; ".join(parts) or "북쪽 이웃은 대지(도로·공원 아님), 대지경계선에서 잼", "",
                               "건축법 제61조① 단서, 시행령 제86조②1·⑥"))
    else:
        lines.append(_line("sunlight", "none", "정북일조", "해당 없음", rule["detail"], "", rule["source"]))
    districts = out["height_districts"]
    if height_cap:
        lines.append(_line("height", "read", "높이 한도", f"{float(height_cap):g}m",
                           f"{', '.join(districts) or '고도지구'}의 고시 높이로 볼륨을 자름", "", "사용자 입력"))
    elif districts:
        lines.append(_line("height", "check", "높이 한도", "입력 필요",
                           f"{', '.join(districts)}: 높이는 지역마다 고시로 정함. 고시에서 최고 높이를 찾아 입력하면 볼륨을 자름"))
    elif not rule["applies"]:
        lines.append(_line("height", "check", "높이", "열려 있음",
                           "높이 한도를 규칙으로 읽지 못해 위가 열려 있음, 용적률로만 층이 정해짐. 고도지구 등 지정 내용 확인"))
    if ratio["bcr"] and ratio["far"]:
        detail = f"건폐율 {ratio['bcr']:g}%({ratio['bcr_from']}), 용적률 {ratio['far']:g}%({ratio['far_from']})"
        lines.append(_line("ratios", "read", "건폐율·용적률", f"{ratio['bcr']:g}% · {ratio['far']:g}%",
                           detail + (" 대지면적 미확인이라 참고 매스는 만들지 않음" if not area else "")))
    lines.extend(more["lines"])
    out["neighbours"] = {"error": neighbours_error, "crossed": sorted(info["crossed"])}
    return out


def floor_height_for(zone: str) -> float:
    return RESIDENTIAL_FLOOR if "주거" in zone else board.DEFAULT_FLOOR_HEIGHT


def envelope_for(project_dir, *, floor_height: float | None = None, http_get=None) -> dict:
    """
    The 법규 볼륨 of the project's site (compute). Looks the 건축 조례 up once per municipality and
    keeps it in the site facts. LookupError without a site or without parcel boundaries.
    """
    from sida.experts.regulation import ordinance  # the law.go.kr client lives with regulation

    facts = site_facts.load_facts(project_dir)
    if not facts or not facts["summary"]["zoning"]:
        raise LookupError("no_site")
    plan = board.site_plan(facts["parcels"])  # only the boundaries count: the same frame as the table's
    if plan is None:
        raise LookupError("no_plan")
    municipality = facts["summary"].get("municipality") or ""
    zones = [z["zone"] for z in facts["summary"]["zoning"]]
    if len(zones) == 1 and residential(zones[0]):
        kept = facts.get("building_ordinance") or {}
        if kept.get("municipality") != municipality or kept.get("error") not in (None, "not_found", "no_article"):
            found = ordinance.sunlight_lookup(municipality, http_get=http_get)
            if found.get("error") in (None, "not_found", "no_article"):  # a network failure is tried again next time
                facts["building_ordinance"] = found
                site_facts.save_facts(project_dir, facts)
            else:
                facts = {**facts, "building_ordinance": found}
    rule = sunlight_rule(facts)
    parcels, error = [], ""
    if rule["applies"] is not None:  # the roads and neighbours count for every rule, not only 정북일조
        try:
            parcels = neighbours(plan, {p["pnu"] for p in facts["parcels"]}, http_get=http_get)
        except landapi.LandApiError as exc:
            error = exc.kind
    zone = zones[0] if zones else ""
    fh = floor_height or floor_height_for(zone)
    settings = load_settings(project_dir)
    return compute(plan, facts, rule, parcels, lambda pnu: zone_of(pnu, http_get=http_get), floor_height=fh,
                   neighbours_error=error, height_cap=settings["height_limit_m"], use=settings["use"],
                   use_area=settings["use_area_m2"])


# ---------------------------------------------------------------------------
# What the designer entered for the envelope, kept per project (site_envelope.json)
# ---------------------------------------------------------------------------

SETTINGS_FILE = "site_envelope.json"
HEIGHT_LIMIT_RANGE = (1.0, 500.0)  # m: a 고도지구's notice height


def load_settings(project_dir) -> dict:
    """{"height_limit_m", "use", "use_area_m2"}: what the designer entered (None for what was not; an
    unreadable or out-of-range value is left out)."""
    try:
        data = json.loads((Path(project_dir) / SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = {"height_limit_m": _number(data.get("height_limit_m"), HEIGHT_LIMIT_RANGE),
           "use": data.get("use") if data.get("use") in setbacks.load_rules()["uses"] else None,
           "use_area_m2": _number(data.get("use_area_m2"), setbacks.USE_AREA_RANGE)}
    return out


def _number(value, bounds: tuple[float, float]) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and bounds[0] <= value <= bounds[1]:
        return float(value)
    return None


def save_settings(project_dir, changes: dict) -> dict:
    """Set what the designer entered: `height_limit_m` (m within HEIGHT_LIMIT_RANGE), `use` (a key of
    envelope_rules uses), `use_area_m2` (㎡ within setbacks.USE_AREA_RANGE); None clears one.
    ValueError (naming the key) for a value out of range. Returns the settings as saved."""
    settings = load_settings(project_dir)
    for key, bounds in (("height_limit_m", HEIGHT_LIMIT_RANGE), ("use_area_m2", setbacks.USE_AREA_RANGE)):
        if key in changes:
            value = changes[key]
            if value is not None:
                value = float(value)
                if not bounds[0] <= value <= bounds[1]:
                    raise ValueError(key)
                value = round(value, 2)
            settings[key] = value
    if "use" in changes:
        if changes["use"] is not None and changes["use"] not in setbacks.load_rules()["uses"]:
            raise ValueError("use")
        settings["use"] = changes["use"]
    atomic_write_text(Path(project_dir) / SETTINGS_FILE, json.dumps(settings, ensure_ascii=False, indent=1) + "\n")
    return settings
