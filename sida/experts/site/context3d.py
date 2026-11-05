"""The site's surroundings in 3D for the drawing table: ground, nearby buildings, parcels.

Independent of HTTP and the screen. Everything is in the table's frame (board.site_plan):
metres from the site's middle, x east, y north, z up with the ground at the site's middle at
z = 0, so the site, the schemes and the surroundings line up without moving anything.

- Ground: the 국토지리정보원 1:5,000 contour lines and spot heights of a terrain pack
  (terrain_pack.py, CC BY) as fixed heights; between them the surface is the smoothest one
  through them (Laplace's equation on a 2 m grid), so flat ground has no terraces.
- Buildings: VWorld 건축물정보 (LT_C_BLDGINFO) outlines. Height, best first: the 건축물대장
  표제부 height (datago.buildings, matched by parcel and 동 name or footprint area), the
  건축물정보 height, then registered floors × a storey height by use — that last one is an
  estimate and says so. A building with neither height nor floors stays an outline at ground
  level ("unknown"), never a made-up box. A small record inside a bigger building is left out.
- Parcels: VWorld 연속지적 outlines; road parcels (지목 도) are marked.
- Where neither the 건축물대장 nor GIS건물통합정보 has a height or floors, VWorld's 도로명주소
  건물 (gro_flo_co) or 건축물정보 (grnd_flr) floors under the building's middle are asked for, in
  one box query per layer and only then ("api_estimate"; kept in memory for the answer, never
  written down); failing that, a 1:5,000 수치지형도 building over the same spot (its middle inside, or more than half the outline shared) gives
  its 층수, again × the storey height and marked as an estimate ("map_estimate").
- What the ground is, point by point on the screen's grid: road, sidewalk, water or the rest
  ("site"), from the pack's areas (1:5,000 수치지형도 polygons) and the road parcels.
- A building stands at the middle height of the ground along its outline, and its foundation
  goes down to the lowest point there, so on a slope no side floats; its line on the ground
  follows the terrain.

VWorld replies are used for drawing only and are not stored (이용약관 제19조); a short
in-memory cache keeps one site from being fetched twice in a row.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from sida.board import EARTH_RADIUS
from sida.experts.site import datago, landapi, terrain_pack

DEFAULT_RADIUS = 200.0  # m around the site's middle
MAX_RADIUS = 500.0
SOLVE_STEP = 2.0  # m, the grid the ground is computed on
VIEW_STEP = 4.0  # m, the grid the screen gets
MARGIN = 60.0  # m read beyond the radius so the edge of the ground is not guessed
INDEX_EVERY = 25.0  # m: index (계곡선) contours on a 5 m interval
DRAPE_GAP = 2.0  # m between the points of a building's line on the ground
# Storey heights for an estimate from the number of floors (m), by the 건축물대장 main use.
STOREY = (
    (("주택", "아파트", "다세대", "연립", "다가구", "기숙사"), 2.9),
    (("업무", "근린", "판매", "숙박", "문화", "의료", "교육", "운동", "위락"), 3.8),
)
STOREY_OTHER = 3.3
CACHE_SECONDS = 600
LEDGER_WORKERS = 4  # 건축물대장 lookups at once (more drops more replies on data.go.kr)
LEDGER_RETRY = ("network", "bad_response")  # failures worth one more try, after LEDGER_WAIT s
LEDGER_WAIT = 0.6

_cache: dict[tuple, tuple[float, dict]] = {}


# ---------------------------------------------------------------------------
# The table's frame
# ---------------------------------------------------------------------------


class Frame:
    """lon/lat ↔ metres around `origin` exactly as board.site_plan does it."""

    def __init__(self, origin: dict):
        self.lon0, self.lat0 = float(origin["lon"]), float(origin["lat"])
        k = math.pi / 180
        self.east = EARTH_RADIUS * k * math.cos(self.lat0 * k)
        self.north = EARTH_RADIUS * k

    def local(self, points) -> np.ndarray:
        p = np.asarray(points, dtype=float).reshape(-1, 2)
        return np.column_stack([(p[:, 0] - self.lon0) * self.east, (p[:, 1] - self.lat0) * self.north])

    def box(self, half: float) -> tuple[float, float, float, float]:
        """west, south, east, north (degrees) of the square `half` m around the origin."""
        dx, dy = half / self.east, half / self.north
        return self.lon0 - dx, self.lat0 - dy, self.lon0 + dx, self.lat0 + dy


# ---------------------------------------------------------------------------
# Ground
# ---------------------------------------------------------------------------


def solve_ground(fixed: list[tuple[float, float, float]], half: float, step: float) -> np.ndarray | None:
    """
    Heights on a (n × n) grid from -half to +half (rows south to north, columns west to east)
    that keep every fixed (x, y, z) and are smooth in between (Laplace's equation, solved by
    red-black over-relaxation from a coarse grid up). None without a fixed point.
    """
    if not fixed:
        return None
    n = int(round(2 * half / step)) + 1
    total = np.zeros((n, n))
    count = np.zeros((n, n))
    for x, y, z in fixed:
        j, i = int(round((x + half) / step)), int(round((y + half) / step))
        if 0 <= i < n and 0 <= j < n:
            total[i, j] += z
            count[i, j] += 1
    known = count > 0
    if not known.any():
        return None
    values = np.where(known, total / np.maximum(count, 1), 0.0)
    if np.ptp(values[known]) == 0:
        return np.full((n, n), float(values[known][0]))
    grid = _coarse_start(values, known, n)
    return _relax(grid, values, known)


def _coarse_start(values: np.ndarray, known: np.ndarray, n: int) -> np.ndarray:
    """A first guess: the mean of the known cells in blocks of 8, spread and smoothed."""
    b = 8
    m = (n + b - 1) // b
    pad = m * b - n
    v = np.pad(np.where(known, values, 0.0), ((0, pad), (0, pad)))
    k = np.pad(known.astype(float), ((0, pad), (0, pad)))
    sums = v.reshape(m, b, m, b).sum(axis=(1, 3))
    cnts = k.reshape(m, b, m, b).sum(axis=(1, 3))
    coarse_known = cnts > 0
    coarse = _relax(
        np.where(coarse_known, sums / np.maximum(cnts, 1), values[known].mean()),
        np.where(coarse_known, sums / np.maximum(cnts, 1), 0.0),
        coarse_known,
    )
    guess = np.kron(coarse, np.ones((b, b)))[:n, :n]
    return np.where(known, values, guess)


def _relax(grid: np.ndarray, values: np.ndarray, known: np.ndarray, *, tol: float = 1e-3, limit: int = 4000) -> np.ndarray:
    """Red-black successive over-relaxation of Laplace's equation, known cells held."""
    g = np.where(known, values, grid).astype(float)
    n = g.shape[0]
    omega = 2 / (1 + math.sin(math.pi / max(n, 2)))
    ii, jj = np.indices(g.shape)
    colors = [((ii + jj) % 2 == c) & ~known for c in (0, 1)]
    for _ in range(limit):
        biggest = 0.0
        for free in colors:
            p = np.pad(g, 1, mode="edge")
            avg = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]) / 4
            change = omega * (avg - g)
            g[free] += change[free]
            if free.any():
                biggest = max(biggest, float(np.abs(change[free]).max()))
        if biggest < tol:
            break
    return g


def sample(grid: np.ndarray, half: float, step: float, x, y) -> np.ndarray:
    """Bilinear heights of the grid at local points (clamped to its edge)."""
    n = grid.shape[0]
    fx = np.clip((np.asarray(x, dtype=float) + half) / step, 0, n - 1)
    fy = np.clip((np.asarray(y, dtype=float) + half) / step, 0, n - 1)
    j0 = np.minimum(np.floor(fx).astype(int), n - 2)
    i0 = np.minimum(np.floor(fy).astype(int), n - 2)
    tx, ty = fx - j0, fy - i0
    return (grid[i0, j0] * (1 - tx) * (1 - ty) + grid[i0, j0 + 1] * tx * (1 - ty)
            + grid[i0 + 1, j0] * (1 - tx) * ty + grid[i0 + 1, j0 + 1] * tx * ty)


def _densify(line: np.ndarray, gap: float) -> np.ndarray:
    out = [line[:1]]
    for a, b in zip(line[:-1], line[1:], strict=True):
        k = max(1, int(math.ceil(np.hypot(*(b - a)) / gap)))
        t = np.linspace(0, 1, k + 1)[1:, None]
        out.append(a + (b - a) * t)
    return np.vstack(out)


def ground(frame: Frame, radius: float, *, folder: Path | None = None) -> dict:
    """
    The ground around the site from the terrain packs: {"grid" (SOLVE_STEP, relative to the
    site's middle), "half", "step", "ground_elev" (m above sea level at the middle), "contours",
    "sources", "areas" [(kind, local ring)]}. {"grid": None, ...} when no pack covers the site.
    """
    half = radius + MARGIN
    found = terrain_pack.query(*frame.box(half), folder=folder)
    fixed: list[tuple[float, float, float]] = []
    lines = []
    for c in found["contours"]:
        pts = frame.local(c["points"])
        lines.append((c["elev"], pts))
        for x, y in _densify(pts, SOLVE_STEP / 2):
            fixed.append((x, y, c["elev"]))
    if found["spots"]:
        spots = np.asarray(found["spots"], dtype=float)
        for (x, y), z in zip(frame.local(spots[:, :2]), spots[:, 2], strict=True):
            fixed.append((x, y, z))
    areas = [(a["kind"], frame.local(a["ring"])) for a in found["areas"]]
    grid = solve_ground(fixed, half, SOLVE_STEP)
    if grid is None:
        return {"grid": None, "half": half, "step": SOLVE_STEP, "ground_elev": None, "contours": [],
                "sources": found["sources"], "areas": areas, "buildings": found["buildings"],
                "map_buildings": found["map_buildings"]}
    elev0 = float(sample(grid, half, SOLVE_STEP, [0.0], [0.0])[0])
    contours = []
    for elev, pts in lines:
        for run in clip_line(pts, radius):
            contours.append({
                "elev": round(elev, 2), "z": round(elev - elev0, 3),
                "index": abs(elev / INDEX_EVERY - round(elev / INDEX_EVERY)) < 1e-6,
                "points": [[round(float(x), 2), round(float(y), 2)] for x, y in run],
            })
    return {
        "grid": grid - elev0, "half": half, "step": SOLVE_STEP, "ground_elev": round(elev0, 2),
        "contours": contours, "sources": found["sources"], "areas": areas, "buildings": found["buildings"],
        "map_buildings": found["map_buildings"],
    }


CLASS_CODES = {"site": "g", "road": "r", "sidewalk": "s", "water": "w"}
# A spot of ground that lies in several areas takes the first of these (a stream under a road
# bridge is drawn as the road the designer can walk on, a pavement inside a road area as pavement).
CLASS_ORDER = ("sidewalk", "road", "water")


def inside_many(points: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Which of the (m × 2) points lie inside the ring (even-odd rule), all at once."""
    inside = np.zeros(len(points), dtype=bool)
    lo, hi = ring.min(axis=0), ring.max(axis=0)
    near = np.all((points >= lo) & (points <= hi), axis=1)
    if not near.any():
        return inside
    x, y = points[near, 0][:, None], points[near, 1][:, None]
    xs, ys = ring[:, 0][None, :], ring[:, 1][None, :]
    xj, yj = np.roll(ring[:, 0], 1)[None, :], np.roll(ring[:, 1], 1)[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        at = (xj - xs) * (y - ys) / (yj - ys) + xs
    crossing = ((ys > y) != (yj > y)) & (x < at)
    inside[near] = (np.count_nonzero(crossing, axis=1) % 2).astype(bool)
    return inside


def classify(points: np.ndarray, areas: list[tuple[str, np.ndarray]]) -> str:
    """One letter per point (CLASS_CODES): what the ground is there, 'g' outside every area."""
    codes = np.full(len(points), "g", dtype="<U1")
    taken = np.zeros(len(points), dtype=bool)
    for kind in CLASS_ORDER:
        for k, ring in areas:
            if k == kind and len(ring) >= 3:
                hit = inside_many(points, ring) & ~taken
                codes[hit] = CLASS_CODES[kind]
                taken |= hit
    return "".join(codes)


def view_grid(g: dict, radius: float, areas: list[tuple[str, np.ndarray]] | None = None,
              step: float = VIEW_STEP) -> dict | None:
    """
    The ground as the screen draws it: heights on a `step` grid over ±radius (rows south to
    north) and what the ground is at each point ("classes", CLASS_CODES letters).
    """
    if g["grid"] is None:
        return None
    axis = np.arange(-radius, radius + step / 2, step)
    xx, yy = np.meshgrid(axis, axis)
    z = sample(g["grid"], g["half"], g["step"], xx.ravel(), yy.ravel())
    classes = classify(np.column_stack([xx.ravel(), yy.ravel()]), areas or [])
    return {"min": -radius, "step": step, "n": len(axis), "z": [round(float(v), 2) for v in z], "classes": classes}


# ---------------------------------------------------------------------------
# Buildings and parcels
# ---------------------------------------------------------------------------


def _rings(shape: dict, frame: Frame) -> list[np.ndarray]:
    polys = shape["coordinates"] if shape["type"] == "MultiPolygon" else [shape["coordinates"]]
    out = []
    for poly in polys:
        if poly and len(poly[0]) >= 4:
            ring = frame.local(poly[0])
            if np.allclose(ring[0], ring[-1]):
                ring = ring[:-1]
            out.append(ring)
    return out


def _area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) / 2


def _inside(pt, ring: np.ndarray) -> bool:
    x, y = pt
    xs, ys = ring[:, 0], ring[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    cross = (ys > y) != (yj > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        at = (xj - xs) * (y - ys) / (yj - ys) + xs
    return bool(np.count_nonzero(cross & (x < at)) % 2)


def storey_height(use: str) -> float:
    for words, h in STOREY:
        if any(w in (use or "") for w in words):
            return h
    return STOREY_OTHER


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


AREA_MATCH = (0.7, 1.3)  # outline area / 건축면적 for a 대장 동 to take an outline
AREA_NAMED = (0.5, 2.0)  # the same, when the outline also carries the 동's name (or is the only pair)


def _usable(row: dict) -> bool:
    return (row.get("height_m") or 0) > 0 or (row.get("floors_above") or 0) > 0


def _named(row: dict, props: dict) -> bool:
    dong, name = str(row.get("dong") or "").strip(), str(row.get("name") or "").strip()
    return bool((dong and dong == str(props.get("dong_nm") or "").strip())
                or (name and name == str(props.get("bld_nm") or "").strip()))


def assign_ledger(rows: list[dict], outlines: list[tuple[int, float, dict]]
                  ) -> tuple[dict[int, tuple[dict, float | None]], list[dict]]:
    """
    One parcel's 건축물대장 표제부 동 put on its building outlines one to one: each 동, the largest
    first, takes the outline whose area is closest to its 건축면적 within ±30% (within half to
    double when the outline carries the 동's name, or when the parcel has one 동 and one outline).
    `outlines` are (key, area m², properties). Returns ({key: (row, area ratio)}, the 동 left
    without an outline). An outline left over gets no 대장 row: never the parcel's tallest record.
    """
    usable = sorted((r for r in rows if _usable(r)), key=lambda r: -(r.get("building_area_m2") or 0))
    free = {key: (area, props) for key, area, props in outlines}
    single = len(usable) == 1 and len(outlines) == 1
    taken: dict[int, tuple[dict, float | None]] = {}
    left: list[dict] = []
    for row in usable:
        arch = row.get("building_area_m2") or 0
        if arch > 0:
            near = []
            for key, (area, props) in free.items():
                lo, hi = AREA_NAMED if (single or _named(row, props)) else AREA_MATCH
                if lo <= area / arch <= hi:
                    near.append(key)
            named = [k for k in near if _named(row, free[k][1])]
            pick = min(named or near, key=lambda k: abs(free[k][0] / arch - 1), default=None)
        else:  # no 건축면적: only by name, or when it is the parcel's only pair
            named = [k for k in free if _named(row, free[k][1])]
            pick = max(named, key=lambda k: free[k][0]) if named else (next(iter(free)) if single and free else None)
        if pick is None:
            left.append(row)
            continue
        taken[pick] = (row, round(free[pick][0] / arch, 2) if arch > 0 else None)
        del free[pick]
    return taken, left


ESTIMATES = ("estimate", "api_estimate", "map_estimate")  # height sources that are floors × a storey height
NEAR_PARCEL = 60.0  # m from a parcel's file outline, where no parcel shape is known (export)
OVERLAP = 0.5  # share of a building's outline a 1:5,000 building must cover to lend its floors


def overlap_share(a: np.ndarray, b: np.ndarray, gap: float = 0.5) -> float:
    """About how much of ring `a`'s area ring `b` covers (points `gap` m apart over `a`'s box)."""
    lo, hi = a.min(axis=0), a.max(axis=0)
    xs = np.arange(lo[0] + gap / 2, hi[0], gap)
    ys = np.arange(lo[1] + gap / 2, hi[1], gap)
    if not len(xs) or not len(ys):
        return 0.0
    pts = np.column_stack([g.ravel() for g in np.meshgrid(xs, ys)])
    in_a = inside_many(pts, a)
    if not in_a.any():
        return 0.0
    return float((in_a & inside_many(pts, b)).sum() / in_a.sum())


def map_floors(ring: np.ndarray, mapped: list[tuple[np.ndarray, float, str]]) -> tuple[float, str] | None:
    """(floors, use) of the 1:5,000 building over this outline, or None."""
    middle = ring.mean(axis=0)
    for other, floors, use in mapped:
        if _inside(middle, other) or _inside(other.mean(axis=0), ring) or overlap_share(ring, other) > OVERLAP:
            return floors, use
    return None


def _pack_features(buildings: list[dict]) -> list[dict]:
    """Pack buildings (terrain_pack.BUILDING_FIELDS) in the shape VWorld's 건축물정보 features have."""
    return [
        {"properties": {"bld_nm": b.get("name", ""), "dong_nm": b.get("dong", ""), "height": b.get("height"),
                        "grnd_flr": b.get("floors"), "pnu": b.get("pnu", ""), "use": b.get("use", "")},
         "shape": {"type": "Polygon", "coordinates": [b["ring"]]}}
        for b in buildings
    ]


def surroundings(
    frame: Frame, radius: float, ground_at: Callable, *, site_rings: list[np.ndarray] | None = None,
    http_get=None, ledger: Callable[[str], list[dict]] | None = None, packed: list[dict] | None = None,
    mapped: list[dict] | None = None, for_export: bool = False,
) -> dict:
    """
    Buildings (with their height and where it came from) and parcels around the site. The
    buildings come from the packs (`packed`, GIS건물통합정보) where there are some, else from
    VWorld's 건축물정보 and 도로명주소 건물 layers.
    """
    box = frame.box(radius)
    notes: list[str] = []
    if packed or for_export:
        bldg, spbd, file_source = _pack_features(packed or []), [], "file"
    else:
        bldg, file_source = landapi.features_in_box("LT_C_BLDGINFO", *box, http_get=http_get), "vworld"
        try:
            spbd = landapi.features_in_box("LT_C_SPBD", *box, http_get=http_get)
        except landapi.LandApiError as exc:
            spbd, notes = [], [*notes, f"spbd:{exc.kind}"]
    parcels = [] if for_export else landapi.features_in_box("LP_PA_CBND_BUBUN", *box, http_get=http_get)

    api_floors: list | None = None  # VWorld floors, fetched once the first file building lacks them

    def vworld_floors(middle) -> int:
        """Floors VWorld knows for the building under this point (0 when none)."""
        nonlocal api_floors
        if api_floors is None:
            api_floors = []
            for layer, field in (("LT_C_SPBD", "gro_flo_co"), ("LT_C_BLDGINFO", "grnd_flr")):
                try:
                    found = landapi.features_in_box(layer, *box, http_get=http_get)
                except landapi.LandApiError as exc:
                    notes.append(f"{layer}:{exc.kind}")
                    continue
                api_floors += [(_rings(f["shape"], frame), _number(f["properties"].get(field))) for f in found]
        return int(next((fl for rings, fl in api_floors if fl > 0 and any(_inside(middle, r) for r in rings)), 0))

    lots = [(_rings(p["shape"], frame), str(p["properties"].get("pnu") or ""), str(p["properties"].get("jibun") or ""))
            for p in parcels]
    floors_spbd = [(_rings(f["shape"], frame), _number(f["properties"].get("gro_flo_co"))) for f in spbd]
    found = []
    for f in bldg:
        for ring in _rings(f["shape"], frame):
            middle = ring.mean(axis=0)
            if np.abs(middle).max() <= radius:
                found.append((ring, f["properties"], abs(_area(ring)), middle))
    inner = set()
    for i, (_ring, _p, area, middle) in enumerate(found):
        for j, (ring_j, _pj, area_j, _mj) in enumerate(found):
            if i != j and area_j > area and _inside(middle, ring_j):
                inner.add(i)
                break

    def pnu_at(pt) -> str | None:
        return next((pnu for rings, pnu, _j in lots if any(_inside(pt, r) for r in rings)), None)

    pnus = {i: str(found[i][1].get("pnu") or "") or pnu_at(found[i][3]) for i in range(len(found)) if i not in inner}
    records: dict[str, list[dict]] = {}
    wanted = sorted({p for p in pnus.values() if p})
    if wanted:
        look = ledger or datago.buildings

        def one(pnu):
            for again in (False, True):
                try:
                    return pnu, look(pnu)
                except landapi.LandApiError as exc:
                    if again or exc.kind not in LEDGER_RETRY:
                        return pnu, exc.kind
                    time.sleep(LEDGER_WAIT)

        with ThreadPoolExecutor(max_workers=LEDGER_WORKERS) as pool:
            for pnu, rows in pool.map(one, wanted):
                if isinstance(rows, str):
                    notes.append(f"ledger:{rows}")
                    records[pnu] = []
                else:
                    records[pnu] = rows

    buildings, unknown, left_out = [], [], []
    counts = {"ledger": 0, "vworld": 0, "file": 0, "estimate": 0, "api_estimate": 0, "map_estimate": 0,
              "unknown": 0, "inner": len(inner)}
    map_rings = [(r, float(m["floors"]), m.get("use", "")) for m in mapped or [] for r in _rings(
        {"type": "Polygon", "coordinates": [m["ring"]]}, frame)]

    # Each parcel's 대장 동 on its outlines, one to one; a 동 without an outline in the file takes
    # one from the 1:5,000 map (a downloaded file: it can be exported), else from VWorld (screen only).
    matched: dict[int, tuple[dict, float | None]] = {}
    extra: list[dict] = []  # outlines found for 동 the file lacks: {ring, row, ratio, source, pnu}
    used_maps: set[int] = set()
    vworld_rings: list | None = None
    for pnu in wanted:
        keys = [i for i, p in pnus.items() if p == pnu]
        taken, left = assign_ledger(records.get(pnu, []), [(i, found[i][2], found[i][1]) for i in keys])
        matched.update(taken)
        near = [found[i][3] for i in keys]
        parcel = [r for rings, lot_pnu, _j in lots if lot_pnu == pnu for r in rings]

        def here(ring, parcel=parcel, near=near):
            m = ring.mean(axis=0)
            if np.abs(m).max() > radius:  # like the file's outlines: only within the radius
                return False
            if parcel:
                return any(_inside(m, r) for r in parcel)
            return any(np.hypot(*(m - n)) <= NEAR_PARCEL for n in near)

        for row in left:
            arch = row.get("building_area_m2") or 0
            if arch <= 0:
                continue
            fits = [(abs(abs(_area(r)) / arch - 1), k, r) for k, (r, _f, _u) in enumerate(map_rings)
                    if k not in used_maps and AREA_MATCH[0] <= abs(_area(r)) / arch <= AREA_MATCH[1] and here(r)]
            source = "map"
            if not fits and not for_export:
                if vworld_rings is None:
                    vworld_rings = []
                    for layer in ("LT_C_SPBD", "LT_C_BLDGINFO"):
                        try:
                            vworld_rings += [r for f in landapi.features_in_box(layer, *box, http_get=http_get)
                                             for r in _rings(f["shape"], frame)]
                        except landapi.LandApiError as exc:
                            notes.append(f"{layer}:{exc.kind}")
                fits = [(abs(abs(_area(r)) / arch - 1), -1, r) for r in vworld_rings
                        if AREA_MATCH[0] <= abs(_area(r)) / arch <= AREA_MATCH[1] and here(r)]
                source = "vworld"
            if fits:
                _d, k, ring = min(fits, key=lambda f: f[0])
                if k >= 0:
                    used_maps.add(k)
                extra.append({"ring": ring, "row": row, "ratio": round(abs(_area(ring)) / arch, 2),
                              "source": source, "pnu": pnu})
    # File outlines that lie mostly inside an outline found above are pieces of that building.
    covered = {i for i in pnus if i not in matched
               and any(overlap_share(found[i][0], e["ring"]) > OVERLAP for e in extra)}
    # A leftover file record carrying the name of a 대장 동 placed on another outline repeats that
    # building: its own height and floors are not used again.
    placed = {str(r.get("name") or "").strip() for r, _ratio in matched.values()} | {
        str(e["row"].get("name") or "").strip() for e in extra}
    placed.discard("")
    repeats = {i for i in pnus if i not in matched and str(found[i][1].get("bld_nm") or "").strip() in placed}

    first_extra = len(found)
    for e in extra:  # stood up like the file's buildings, on the outline found for them
        ring = e["ring"]
        found.append((ring, {"bld_nm": e["row"].get("name") or "", "dong_nm": e["row"].get("dong") or "",
                             "use": e["row"].get("purpose") or ""}, abs(_area(ring)), ring.mean(axis=0)))
        matched[len(found) - 1] = (e["row"], e["ratio"])
        pnus[len(found) - 1] = e["pnu"]
    outline_from = {first_extra + n: e["source"] for n, e in enumerate(extra)}

    for i, (ring, props, _size, middle) in enumerate(found):
        ccw = ring if _area(ring) > 0 else ring[::-1]
        edge = _densify(np.vstack([ccw, ccw[:1]]), DRAPE_GAP)
        under = ground_at(edge[:, 0], edge[:, 1])
        # A building stands at the middle height of the ground along its outline; on a slope its
        # foundation reaches down to the lowest point, so no side hangs in the air.
        level, base = float(np.median(under)), float(np.min(under))
        outline = [[round(float(x), 2), round(float(y), 2)] for x, y in ccw]
        touch = [[round(float(x), 2), round(float(y), 2), round(float(z) + 0.02, 2)] for (x, y), z in zip(edge, under, strict=True)]
        name = str(props.get("bld_nm") or "").strip()
        if i in inner or i in covered:
            left_out.append({"outline": outline, "base": round(base, 2), "name": name})
            continue
        row, ratio = matched.get(i, (None, None))
        if i in repeats:
            props = {**props, "height": None, "grnd_flr": None}
        use = (row or {}).get("purpose", "") or str(props.get("use") or "")
        floors = (row or {}).get("floors_above") or int(_number(props.get("grnd_flr"))) or int(
            next((fl for rings, fl in floors_spbd if fl > 0 and any(_inside(middle, r) for r in rings)), 0)
        )
        match = {"source": outline_from.get(i, file_source), "dong": str(row.get("dong") or row.get("name") or ""),
                 "ratio": ratio} if row else None
        if row and (row.get("height_m") or 0) > 0:
            height, source = float(row["height_m"]), "ledger"
        elif _number(props.get("height")) > 0:
            height, source = _number(props.get("height")), file_source
        elif floors:
            height, source = floors * storey_height(use), "estimate"
        elif packed and not for_export and i not in repeats and (asked := vworld_floors(middle)):
            floors = asked
            height, source = floors * storey_height(use), "api_estimate"
            # What the file export uses instead: VWorld's floors stay on the screen (제19조)
            lent = map_floors(ring, map_rings)
            offline = {"height": round(lent[0] * storey_height(use or lent[1]), 2), "source": "map_estimate",
                       "floors": int(lent[0])} if lent else None
        elif (lent := map_floors(ring, map_rings)) is not None:
            floors = int(lent[0])
            use = use or lent[1]
            height, source = floors * storey_height(use), "map_estimate"
        else:
            counts["unknown"] += 1
            unknown.append({"outline": outline, "base": round(base, 2), "ground_line": touch, "name": name})
            continue
        counts[source] += 1
        if source != "api_estimate":
            offline = None
        buildings.append({
            "outline": outline, "base": round(base, 2), "ground": round(level, 2),
            "foundation": round(level - base, 2), "top": round(level + height, 2), "ground_line": touch,
            "height": round(height, 2), "height_source": source,
            **({"offline": offline} if source == "api_estimate" else {}),
            "floors": floors or None, "use": use, "name": name,
            "on_site": bool(site_rings) and any(_inside(middle, r) for r in site_rings),
            "match": match,  # the 대장 동 on this outline, where the outline came from, area ratio
            **({"display_only": True} if outline_from.get(i) == "vworld" else {}),
        })
    lots_out = []
    for rings, _pnu, jibun in lots:
        for ring in rings:
            if np.abs(ring.mean(axis=0)).max() <= radius + 30:
                lots_out.append({"ring": [[round(float(x), 2), round(float(y), 2)] for x, y in ring],
                                 "road": jibun.strip().endswith("도"), "label": jibun.strip()})
    return {"buildings": buildings, "unknown_buildings": unknown, "left_out": left_out,
            "parcels": lots_out, "counts": counts, "notes": notes}


# ---------------------------------------------------------------------------
# All of it
# ---------------------------------------------------------------------------


AREA_LAYERS = {"road": ("도로", (150, 150, 150)), "sidewalk": ("인도", (190, 180, 160)), "water": ("수계", (90, 160, 200))}
EXPORT_GROUP = "대지 주변"


def clip_line(points, lim: float) -> list[np.ndarray]:
    """The parts of a polyline inside the square |x|, |y| <= lim (Liang–Barsky per segment), each
    part a run of points with the cut points on the square's edge."""
    pts = np.asarray(points, dtype=float)
    parts: list[list] = []
    run: list = []
    for a, b in zip(pts[:-1], pts[1:], strict=True):
        d = b - a
        if d[0] == 0 and d[1] == 0:
            continue
        t0, t1 = 0.0, 1.0
        for p, q in ((-d[0], a[0] + lim), (d[0], lim - a[0]), (-d[1], a[1] + lim), (d[1], lim - a[1])):
            if p == 0:
                if q < 0:
                    t0, t1 = 1.0, 0.0
            elif p < 0:
                t0 = max(t0, q / p)
            else:
                t1 = min(t1, q / p)
        if t0 >= t1:
            if run:
                parts.append(run)
                run = []
            continue
        start, end = a + d * t0, a + d * t1
        if not run or t0 > 0:
            if run:
                parts.append(run)
            run = [start]
        run.append(end)
        if t1 < 1:
            parts.append(run)
            run = []
    if run:
        parts.append(run)
    return [np.asarray(r) for r in parts if len(r) >= 2]


def export_layers(around: dict) -> list[dict]:
    """
    The surroundings as board_export layers (same frame as the table): the ground as a height
    grid, its road / sidewalk / water outlines laid on it, the contour lines (index ones apart)
    and the buildings as solids from their foundation, split by where the height came from.
    Only what comes from map files is written (packs, CC BY): VWorld replies are for the screen
    only (이용약관 제19조), so parcels, and buildings drawn from VWorld, stay out.
    """
    def layer(short, color, **parts):
        return {"name": f"{EXPORT_GROUP} - {short}", "short": short, "parent": EXPORT_GROUP, "color": color,
                "curves": [], "solids": [], "surfaces": [], "labels": [], **parts}

    out = []
    t = around.get("terrain")
    if t:
        out.append(layer("지형", (170, 150, 120), surfaces=[
            {"min_x": t["min"], "min_y": t["min"], "step": t["step"], "nx": t["n"], "ny": t["n"], "z": t["z"]}]))
    if t and around.get("areas"):
        grid = np.asarray(t["z"], dtype=float).reshape(t["n"], t["n"])
        half = -t["min"]
        for kind, (short, color) in AREA_LAYERS.items():
            curves = []
            for a in around["areas"]:
                if a["kind"] != kind:
                    continue
                # cut to the ground's square, so no line hangs past the edge of the surface
                for ring in clip_line(_densify(np.vstack([a["ring"], a["ring"][:1]]), DRAPE_GAP), half):
                    zs = sample(grid, half, t["step"], ring[:, 0], ring[:, 1]) + 0.03
                    curves.append({"points": [[round(float(x), 2), round(float(y), 2), round(float(z), 2)] for (x, y), z in zip(ring, zs, strict=True)],
                                   "closed": False})
            if curves:
                out.append(layer(f"지형 - {short}", color, curves=curves))
    for index, short, color in ((False, "등고선", (180, 160, 120)), (True, "등고선 - 계곡선", (120, 100, 70))):
        curves = [{"points": [[x, y, c["z"]] for x, y in c["points"]], "closed": False}
                  for c in around.get("contours") or [] if bool(c["index"]) == index]
        if curves:
            out.append(layer(short, color, curves=curves))
    if around.get("building_source", {}).get("pack"):
        groups = {"측정 높이": [], "추정 높이": []}
        unknown = [{"points": b["ground_line"], "closed": False} for b in around.get("unknown_buildings") or [] if b.get("ground_line")]
        for b in around.get("buildings") or []:
            if b.get("display_only"):  # an outline from VWorld: for the screen only (이용약관 제19조)
                continue
            height, source = b["height"], b["height_source"]
            if source == "api_estimate":  # VWorld's floors are for the screen only: fall back without them
                if not b.get("offline"):
                    unknown.append({"points": b["ground_line"], "closed": False})
                    continue
                height, source = b["offline"]["height"], b["offline"]["source"]
            key = "추정 높이" if source in ESTIMATES else "측정 높이"
            groups[key].append({"outline": b["outline"], "base": b["base"], "height": round(b["ground"] + height - b["base"], 2)})
        for short, solids in groups.items():
            if solids:
                out.append(layer(f"건물 - {short}", (200, 200, 200) if short == "측정 높이" else (220, 200, 160), solids=solids))
        if unknown:
            out.append(layer("건물 - 높이 미확인(바닥선)", (200, 120, 50), curves=unknown))
    return out


def build(plan: dict, radius: float = DEFAULT_RADIUS, *, folder: Path | None = None, http_get=None,
          ledger=None, use_cache: bool = True, for_export: bool = False) -> dict:
    """
    The surroundings of a site whose table plan is `plan` (board.site_plan): ground, contours,
    buildings and parcels within `radius` m of its middle, in the table's frame. Raises
    ValueError for a plan without an origin or a radius out of range.
    """
    origin = (plan or {}).get("origin")
    if not origin:
        raise ValueError("the site has no boundary to stand on")
    radius = float(radius)
    if not 50 <= radius <= MAX_RADIUS:
        raise ValueError(f"radius must be 50–{MAX_RADIUS:g} m")
    site_rings = [np.asarray(r, dtype=float) for p in plan.get("parcels") or [] for r in p.get("rings") or []]
    rings = tuple(r.tobytes() for r in site_rings)
    key = (origin["lon"], origin["lat"], radius, str(folder), for_export, rings)
    # An export takes what the screen has just drawn for the same site and radius: the ground,
    # contours and pack buildings are the same, so the 건축물대장 is not asked again.
    # export_layers leaves its VWorld-only values (parcels, VWorld buildings, api_estimate) out.
    tried = [key, (*key[:4], False, rings)] if for_export else [key]
    for k in tried:
        hit = _cache.get(k)
        if use_cache and hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    started = time.perf_counter()
    frame = Frame(origin)
    g = ground(frame, radius, folder=folder)
    if g["grid"] is None:
        def ground_at(x, y):
            return np.zeros(np.shape(x))
    else:
        def ground_at(x, y):
            return sample(g["grid"], g["half"], g["step"], x, y)
    packed = [b for b in g["buildings"] if np.abs(frame.local(b["ring"]).mean(axis=0)).max() <= radius]
    around = surroundings(frame, radius, ground_at, site_rings=site_rings, http_get=http_get, ledger=ledger,
                          packed=packed, mapped=g["map_buildings"], for_export=for_export)

    def source(s):
        return {"name": s.get("source", ""), "date": s.get("source_date", ""), "pack": s.get("name", "")}

    terrain_sources = [source(s) for s in g["sources"] if s.get("kind", "contours") in ("contours", "areas")]
    building_packs = [source(s) for s in g["sources"] if s.get("kind") == "buildings"]
    building_source = (building_packs[0] if packed and building_packs
                       else {"name": "브이월드 건축물정보·도로명주소 건물 (실시간, 저장하지 않음)", "date": "", "pack": ""})
    out = {
        "origin": {"lon": origin["lon"], "lat": origin["lat"]},
        "radius": radius,
        "ground_elev": g["ground_elev"],
        "terrain": view_grid(g, radius, g["areas"] + [
            ("road", np.asarray(p["ring"], dtype=float)) for p in around["parcels"] if p["road"]
        ]),
        "terrain_sources": terrain_sources,
        "building_source": building_source,
        "areas": [
            {"kind": kind, "ring": [[round(float(x), 2), round(float(y), 2)] for x, y in ring]}
            for kind, ring in g["areas"] if len(ring) >= 3 and np.abs(ring.mean(axis=0)).max() <= radius
        ],
        "contours": g["contours"],
        **around,
        "seconds": round(time.perf_counter() - started, 1),
    }
    _cache[key] = (time.time(), out)
    return out
