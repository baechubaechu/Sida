"""What the 법규 볼륨 (envelope.py) applies besides 정북일조: 건축선, 대지 안의 공지 and 공동주택 채광,
each by rule from data/envelope_rules.yaml (the statute and ordinance figures copied from the 원문
once, nothing fetched at run time: 2026-11-17 지훈 "할때마다 읽어오는건 안돼").

The lot's outer boundary is looked at in pieces about PIECE long. What lies just beyond each piece
in the 연속지적 map says what kind of edge it is:

- "road": a parcel whose 지목 is 도로. Its width is measured straight across the road parcels from
  the piece's middle (the median along each run of road pieces). A road narrower than 4 m moves
  the 건축선 back to 2 m from its middle (건축법 제46조①, the least road of 법 제2조①11호); at a
  corner of two roads under 8 m meeting at under 120° the corner is cut (시행령 제31조①).
- "open": a park, railway or river (envelope_rules open_space.across_marks): the 인접 대지경계선 of
  대지 안의 공지 is its far side (시행령 제80조의2).
- "neighbour": another parcel; "unknown": nothing found there (taken as a neighbour, the strict
  way).

Then, by the use the designer picked (and its floor area):

- 대지 안의 공지 (법 제58조): the distance from the 건축선 and from the 인접 대지경계선, from the
  시·도 ordinance's table where this file has it, else the least of the statute's range with
  "확인 필요".
- 공동주택 채광 (법 제61조②, 시행령 제86조③1): each part at most `times` its distance to the
  인접 대지경계선, every one taken as faced by a window. Across a road, railway, river or park the
  line is that parcel's middle (제86조⑥). A 다세대주택 is kept `multiplex_free` from the lines
  instead, where the ordinance sets that distance (제86조③ 단서).

Cells kept open get height 0 in the envelope; the 채광 limit caps the height. The area between the
road and a moved 건축선 is left out of the site area the ratios use (시행령 제119조①1 가목).
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import shapely
import yaml
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.strtree import STRtree

from sida.config import ROOT
from sida.experts.site import site_rules

RULES_PATH = ROOT / "data" / "envelope_rules.yaml"
PIECE = 1.0  # m: the lot's edges are looked at in pieces about this long
PROBE = 0.3  # m beyond an edge where the parcel across is looked for
RAY = 60.0  # m: the widest road measured
SIMPLIFY = 0.2  # m: kinks smaller than this in the lot's boundary are smoothed out first
ROAD_MARK = "도"
CORNER_ROAD = 8.0  # m: the 건축선 is cut at a corner of roads narrower than this (시행령 제31조①)
CORNER_ANGLE = 120.0  # degrees
USE_AREA_RANGE = (1.0, 10_000_000.0)  # ㎡: the floor area the designer enters for the use


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def uses() -> list[dict]:
    """The uses the card offers: [{"key", "label"}]."""
    return [{"key": k, "label": v["label"]} for k, v in load_rules()["uses"].items()]


def _region(municipality: str, table: dict) -> str | None:
    return next((name for name in table if (municipality or "").startswith(name)), None)


# ---------------------------------------------------------------------------
# 대지 안의 공지: which row of the table holds
# ---------------------------------------------------------------------------


def _fits(row: dict, group: str, floor_area: float, zone: str) -> bool:
    if group not in row["uses"]:
        return False
    if "area_min" in row and floor_area < row["area_min"]:
        return False
    if "area_max" in row and floor_area >= row["area_max"]:
        return False
    if any(w in zone for w in row.get("zones_not", [])):
        return False
    return not row.get("zones") or any(w in zone for w in row["zones"])


def _distance(row: dict, zone: str) -> float:
    if "m" in row:
        return float(row["m"])
    return float(next(m for word, m in row["by_zone"] if word is None or word in zone))


def open_space(municipality: str, zone: str, use: str, floor_area: float) -> dict:
    """
    The 대지 안의 공지 for a use: {"road": {"m", "text"}, "neighbour": {"m", "text"}, "status",
    "source", "statute"}. "read" when the 시·도 ordinance's table is in the rules file (a use it does
    not name keeps 0), else "check" with the least of the statute's ranges.
    """
    rules = load_rules()["open_space"]
    group = rules_use(use)["group"]
    region = _region(municipality, rules["regions"])
    table = rules["regions"][region] if region else rules["statute"]
    out = {"status": "read" if region else "check", "statute": not region,
           "source": table["source"] if region else rules["law"]}
    for kind in ("building_line", "neighbour"):
        row = next((r for r in table[kind] if _fits(r, group, floor_area, zone)), None)
        key = "road" if kind == "building_line" else "neighbour"
        out[key] = {"m": _distance(row, zone), "text": row["text"]} if row else {"m": 0.0, "text": ""}
    return out


def rules_use(use: str) -> dict:
    return load_rules()["uses"][use]


# ---------------------------------------------------------------------------
# The lot's edges and what lies beyond them
# ---------------------------------------------------------------------------


class _Around:
    """The 연속지적 parcels around the lot, for finding what is at a point."""

    def __init__(self, parcels: list[dict]):
        self.items = []
        for p in parcels:
            shape = unary_union([Polygon(r) for r in p["rings"] if len(r) >= 3]).buffer(0)
            if not shape.is_empty:
                self.items.append((shape, p))
        self.tree = STRtree([s for s, _ in self.items]) if self.items else None
        self._unions: dict[frozenset, object] = {}

    def at(self, x: float, y: float) -> dict | None:
        if self.tree is None:
            return None
        pt = Point(x, y)
        for i in self.tree.query(pt):
            shape, p = self.items[int(i)]
            if shape.covers(pt):
                return p
        return None

    def union_of(self, marks: frozenset):
        if marks not in self._unions:
            self._unions[marks] = unary_union([s for s, p in self.items if p["mark"] in marks])
        return self._unions[marks]


def _kind(p: dict | None, open_marks: dict) -> str:
    if p is None:
        return "unknown"
    if p["mark"] == ROAD_MARK:
        return "road"
    return "open" if p["mark"] in open_marks else "neighbour"


def _width(around: _Around, mid, normal, marks: frozenset) -> float | None:
    """How far straight out from `mid` the parcels with `marks` run (m), or None."""
    shape = around.union_of(marks)
    if shape.is_empty:
        return None
    start = (mid[0] + normal[0] * 0.02, mid[1] + normal[1] * 0.02)
    ray = LineString([start, (start[0] + normal[0] * RAY, start[1] + normal[1] * RAY)])
    cut = ray.intersection(shape)
    for part in getattr(cut, "geoms", [cut]):
        if part.is_empty or part.geom_type != "LineString":
            continue
        a, b = Point(part.coords[0]), Point(part.coords[-1])
        near, far = (a, b) if a.distance(Point(start)) <= b.distance(Point(start)) else (b, a)
        if near.distance(Point(start)) <= 0.3:
            return round(far.distance(Point(start)) + 0.02, 2)
    return None


def edges(lot, parcels: list[dict]) -> dict:
    """
    The lot's outer boundary as runs of one kind: {"runs": [{"kind", "marks", "line", "width",
    "length"}], "corners": [{"at", "angle", "before", "after"}]} (`before`/`after`: run indices
    meeting at a vertex of the lot, the angle inside the lot in degrees).
    """
    rules = load_rules()
    open_marks = rules["open_space"]["across_marks"]
    around = _Around(parcels)
    runs: list[dict] = []
    corners: list[dict] = []
    for poly in getattr(lot, "geoms", [lot]):
        if poly.geom_type != "Polygon":
            continue
        ring = list(orient(poly.simplify(SIMPLIFY), 1.0).exterior.coords)[:-1]
        n = len(ring)
        if n < 3:
            continue
        first_run = len(runs)
        seg_first, seg_last = [], []
        for k in range(n):
            a, b = np.array(ring[k]), np.array(ring[(k + 1) % n])
            length = float(np.hypot(*(b - a)))
            if length < 1e-6:
                seg_first.append(len(runs) - 1)
                seg_last.append(len(runs) - 1)
                continue
            t = (b - a) / length
            normal = (float(t[1]), float(-t[0]))  # outward for a counter-clockwise ring
            count = max(1, math.ceil(length / PIECE))
            for m in range(count):
                pa, pb = a + (b - a) * (m / count), a + (b - a) * ((m + 1) / count)
                mid = (pa + pb) / 2
                p = around.at(float(mid[0] + normal[0] * PROBE), float(mid[1] + normal[1] * PROBE))
                kind = _kind(p, open_marks)
                mark = p["mark"] if p else ""
                same = runs and len(runs) > first_run and runs[-1]["kind"] == kind and m > 0
                if not same:
                    runs.append({"kind": kind, "marks": set(), "pieces": [], "widths": []})
                if m == 0:
                    seg_first.append(len(runs) - 1)
                run = runs[-1]
                run["pieces"].append((tuple(map(float, pa)), tuple(map(float, pb))))
                if mark:
                    run["marks"].add(mark)
                if kind in ("road", "open"):
                    marks = frozenset([ROAD_MARK]) if kind == "road" else frozenset(open_marks)
                    w = _width(around, (float(mid[0]), float(mid[1])), normal, marks)
                    if w is not None:
                        run["widths"].append(w)
            seg_last.append(len(runs) - 1)
        for k in range(n):
            before, after = seg_last[k - 1], seg_first[k]
            if before < first_run or after < first_run or before == after:
                continue
            v = np.array(ring[k])
            p, q = np.array(ring[k - 1]) - v, np.array(ring[(k + 1) % n]) - v
            cross = p[0] * q[1] - p[1] * q[0]
            angle = math.degrees(math.atan2(abs(cross), float(p @ q)))
            if cross > 0:  # turning the other way: a reflex vertex of a counter-clockwise ring
                angle = 360 - angle
            corners.append({"at": (float(v[0]), float(v[1])), "angle": round(angle, 1), "before": before, "after": after,
                            "dirs": (tuple(p / np.hypot(*p)), tuple(q / np.hypot(*q)))})
    for run in runs:
        run["line"] = shapely.multilinestrings([[a, b] for a, b in run.pop("pieces")])
        widths = run.pop("widths")
        run["width"] = round(float(np.median(widths)), 1) if widths else None
        run["length"] = round(run["line"].length, 1)
    return {"runs": runs, "corners": corners}


# ---------------------------------------------------------------------------
# 건축선
# ---------------------------------------------------------------------------


def _corner_cut(rows: list, angle: float, this: float, cross: float) -> float | None:
    for under, c_from, c_under, t_from, t_under, m in rows:
        if angle < under and c_from <= cross < c_under and t_from <= this < t_under:
            return float(m)
    return None


def building_line(lot, found: dict) -> dict:
    """
    The 건축선 the roads make: {"setbacks": {run index: m back from the road edge}, "cuts":
    [{"shape", "m": (along before, along after), "angle", "widths"}], "removed": the lot's part
    between the roads and the 건축선 (a shape)}.
    """
    rules = load_rules()["building_line"]
    least = float(rules["least_road"])
    setbacks = {}
    for n, run in enumerate(found["runs"]):
        if run["kind"] == "road" and run["width"] is not None and run["width"] < least:
            setbacks[n] = round((least - run["width"]) / 2, 2)
    cuts = []
    for c in found["corners"]:
        a, b = found["runs"][c["before"]], found["runs"][c["after"]]
        if a["kind"] != "road" or b["kind"] != "road" or a["width"] is None or b["width"] is None:
            continue
        wa, wb = max(a["width"], least), max(b["width"], least)  # a narrower road counts at its 소요너비
        if wa >= CORNER_ROAD or wb >= CORNER_ROAD or c["angle"] >= CORNER_ANGLE:
            continue
        da, db = _corner_cut(rules["corner"], c["angle"], wa, wb), _corner_cut(rules["corner"], c["angle"], wb, wa)
        if not da or not db:
            continue
        (vx, vy), (pa, pb) = c["at"], c["dirs"]
        tri = Polygon([(vx, vy), (vx + pa[0] * da, vy + pa[1] * da), (vx + pb[0] * db, vy + pb[1] * db)])
        cuts.append({"shape": tri, "m": (da, db), "angle": c["angle"], "widths": (a["width"], b["width"])})
    parts = [found["runs"][n]["line"].buffer(s, cap_style="flat") for n, s in setbacks.items()]
    parts += [c["shape"] for c in cuts]
    removed = lot.intersection(unary_union(parts)) if parts else Polygon()
    return {"setbacks": setbacks, "cuts": cuts, "removed": removed}


# ---------------------------------------------------------------------------
# Everything together, over the envelope's grid
# ---------------------------------------------------------------------------


def _line(id_: str, status: str, title: str, value: str, detail: str = "", quote: str = "", source: str = "") -> dict:
    return {"id": id_, "status": status, "title": title, "value": value, "detail": detail, "quote": quote, "source": source}


def _dist(geom, pts) -> np.ndarray:
    return shapely.distance(geom, pts)


def work_out(lot, x: np.ndarray, y: np.ndarray, inside: np.ndarray, *, zone: str, municipality: str,
             parcels: list[dict] | None, use: str | None, floor_area: float | None, assumed_area: float | None,
             neighbours_error: str = "") -> dict:
    """
    What 건축선, 대지 안의 공지 and 채광 leave on each cell (x, y: cell centres; inside: cells on the
    lot): {"open": bool cells kept free of building, "cap": heights (inf where no limit),
    "removed_m2": the 건축선's cut of the site area, "lines": card lines, "roads": [{"width", "length",
    "setback"}]}.
    """
    rules = load_rules()
    found = edges(lot, parcels or [])
    runs = found["runs"]
    bl = building_line(lot, found)
    pts = shapely.points(x[inside], y[inside])
    free = np.zeros(pts.shape, dtype=bool)
    cap = np.full(pts.shape, np.inf)
    lines = []

    # 건축선
    roads = [{"width": r["width"], "length": r["length"], "setback": bl["setbacks"].get(n, 0.0)}
             for n, r in enumerate(runs) if r["kind"] == "road"]
    for n, s in bl["setbacks"].items():
        free |= _dist(runs[n]["line"], pts) < s
    for c in bl["cuts"]:
        free |= _dist(c["shape"], pts) <= 1e-9
    law = rules["building_line"]["law"]
    if neighbours_error:
        lines.append(_line("building_line", "check", "건축선", "미확인",
                           "연속지적을 받지 못해 도로에 접한 변을 찾지 못함. 도로 너비와 건축선 확인"))
    elif not roads:
        lines.append(_line("building_line", "check", "건축선", "도로 미확인",
                           "대지에 접한 도로 필지(지목 도)를 찾지 못함. 접도와 건축선 확인", "", law))
    else:
        widths = ", ".join(f"{r['width']:g}m" if r["width"] is not None else "폭 미확인" for r in roads)
        parts = [f"접한 도로 너비 {widths}(연속지적 도로 필지 폭)"]
        if bl["setbacks"]:
            parts.append("4m 미만 도로는 도로 중심에서 2m 물러난 선이 건축선(법 제46조①). "
                         + ", ".join(f"{s:g}m 후퇴" for s in bl["setbacks"].values()))
        for c in bl["cuts"]:
            parts.append(f"모퉁이 {c['angle']:g}°(도로 {c['widths'][0]:g}m·{c['widths'][1]:g}m)를 "
                         f"{c['m'][0]:g}m·{c['m'][1]:g}m 자름(시행령 제31조①)")
        if bl["removed"].area > 0.05:
            parts.append(f"건축선과 도로 사이 {bl['removed'].area:,.1f}㎡는 대지면적에서 뺌(시행령 제119조①1)")
        parts.append("막다른 도로, 도로 건너편이 하천·경사지인 경우, 도시계획도로 폭은 따로 확인")
        status = "check" if (bl["setbacks"] or bl["cuts"] or any(r["width"] is None for r in roads)) else "read"
        value = "후퇴·모퉁이 자름" if (bl["setbacks"] or bl["cuts"]) else "대지경계선 그대로"
        lines.append(_line("building_line", status, "건축선", value, "; ".join(parts), "", law))

    # 대지 안의 공지 and 채광 need the use
    os_rules, dl = rules["open_space"], rules["daylight"]
    if not use:
        lines.append(_line("open_space", "check", "대지 안의 공지", "용도 선택 필요",
                           "건물 용도(와 바닥면적)를 고르면 건축선·인접 대지경계선에서 띄울 거리를 반영함", "", os_rules["law"]))
        lines.append(_line("daylight", "check", "공동주택 채광", "용도 선택 필요",
                           "공동주택이면 인접 대지경계선까지 거리의 2배(근린상업·준주거 4배) 이하 높이", "", dl["law"]))
        return {"open": free, "cap": cap, "removed_m2": round(float(bl["removed"].area), 1), "lines": lines, "roads": roads}
    spec = rules_use(use)
    area_for = floor_area if floor_area else (assumed_area or 0.0)
    space = open_space(municipality, zone, use, area_for)
    multiplex = spec["group"] == "multiplex"
    free_region = _region(municipality, dl["multiplex_free"]) if multiplex else None
    keep_nb = space["neighbour"]["m"]
    if free_region:
        keep_nb = max(keep_nb, float(dl["multiplex_free"][free_region]["m"]))
    d_road = space["road"]["m"]
    if d_road > 0:
        for n, r in enumerate(runs):
            if r["kind"] == "road":
                free |= _dist(r["line"], pts) < bl["setbacks"].get(n, 0.0) + d_road
        for c in bl["cuts"]:
            free |= _dist(c["shape"], pts) < d_road
    if keep_nb > 0:
        for r in runs:
            if r["kind"] in ("neighbour", "unknown"):
                free |= _dist(r["line"], pts) < keep_nb
            elif r["kind"] == "open":  # the line is its far side
                left = keep_nb - (r["width"] or 0.0)
                if left > 0:
                    free |= _dist(r["line"], pts) < left
    area_note = (f"바닥면적 {floor_area:,.0f}㎡ 기준" if floor_area
                 else f"바닥면적은 입력이 없어 용적률을 채운 {area_for:,.0f}㎡로 봄" if spec.get("area") else "")
    rows = [f"건축선에서 {d_road:g}m" + (f" ({space['road']['text']})" if space["road"]["text"] else " (해당 행 없음)"),
            f"인접 대지경계선에서 {space['neighbour']['m']:g}m"
            + (f" ({space['neighbour']['text']})" if space["neighbour"]["text"] else " (해당 행 없음)")]
    detail = "; ".join(rows)
    if space["statute"]:
        detail += ". 이 시·도 조례 표가 아직 없어 시행령 별표 2 범위의 최소 거리로 계산함, 조례 확인"
    detail += ". 공원·철도·하천 너머는 그 건너편 경계선에서 잼(시행령 제80조의2)"
    if area_note:
        detail += f". {area_note}"
    status = space["status"]
    if neighbours_error or any(r["kind"] == "unknown" for r in runs):
        status = "check"
        detail += ". 지도에서 너머를 알 수 없는 변은 인접 대지경계선으로 봄(도로면 건축선 거리로 바꿔 확인)"
    lines.append(_line("open_space", status, "대지 안의 공지",
                       f"건축선 {d_road:g}m · 인접 {space['neighbour']['m']:g}m", detail,
                       " ".join(os_rules["text"].split()), space["source"]))

    # 공동주택 채광
    if not spec.get("housing"):
        lines.append(_line("daylight", "none", "공동주택 채광", "해당 없음", f"{spec['label']}은 공동주택이 아님", "", dl["law"]))
    elif any(w in zone for w in dl["zones_not"]):
        lines.append(_line("daylight", "none", "공동주택 채광", "해당 없음", f"{zone}은 적용하지 않는 지역(제86조③)", "", dl["law"]))
    elif free_region:
        m = float(dl["multiplex_free"][free_region]["m"])
        lines.append(_line("daylight", "read", "공동주택 채광", f"인접 경계선에서 {m:g}m",
                           f"다세대주택은 창이 있는 벽을 인접 대지경계선에서 {m:g}m 이상 띄우면 채광 높이 제한을 받지 않음"
                           f"(제86조③ 단서). 이 거리로 띄워 계산함", " ".join(dl["text"].split()),
                           f"{dl['law']}, {dl['multiplex_free'][free_region]['source']}"))
    else:
        times = float(next((t for w, t in dl["times_by_zone"] if w in zone), dl["times"]))
        across = site_rules.load_rules()["across_marks"]
        for r in runs:
            middle = 0.0
            if r["kind"] in ("road", "open") and r["marks"] <= set(across):
                middle = (r["width"] or 0.0) / 2  # 제86조⑥: 공동주택은 그 중심선
            cap = np.minimum(cap, times * (_dist(r["line"], pts) + middle))
        detail = (f"각 부분 높이를 인접 대지경계선까지 거리의 {times:g}배 이하로 함. 창이 어느 쪽에 날지 몰라 모든 경계선을 "
                  "창이 향한 것으로 봄(가장 엄격). 도로·공원·철도·하천 너머는 그 중심선에서 잼(제86조⑥)")
        if multiplex:
            detail += ". 다세대주택 제외 거리(조례)가 이 파일에 없어 적용해 계산함, 조례 확인"
        lines.append(_line("daylight", "check" if multiplex else "read", "공동주택 채광", f"거리의 {times:g}배", detail,
                           " ".join(dl["text"].split()), dl["law"]))
    return {"open": free, "cap": cap, "removed_m2": round(float(bl["removed"].area), 1), "lines": lines, "roads": roads}
