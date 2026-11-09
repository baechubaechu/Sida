"""What the Conductor (and the experts) are told about the site when they think about massing
(2026-11-09 지훈: "부지 입력하면 정보가 바로 연동되는 거 아닌가?").

Three parts, all from what Sida has saved or draws already:

1. The site facts as the experts get them: area, zoning, the statutory and ordinance coverage and
   floor-area ratios (site_facts.regulatory_lines).
2. The lot in the drawing table's frame, the one massing blocks stand in (board.site_plan): u
   along the largest parcel's longest edge, v across it, metres from that parcel's middle. The
   outline, its extent, the long and short sides and which way u points (a bearing from north),
   so a proposed scheme can be laid inside the lot.
3. When the designer has the surroundings on (site_context.json `shown`), a short summary of them
   (context3d.build, the map-file part only, as the export uses: VWorld replies stay on the
   screen): for each side of the lot the nearest and the tallest buildings with their distance
   from the lot's edge, which sides have road along them, and how the ground falls across the lot.

The geometry functions take plain dicts so they can be tested without a site lookup.
"""

from __future__ import annotations

import logging
import math
import threading
from pathlib import Path

log = logging.getLogger(__name__)
MAX_FACT_LINES = 14
MAX_FACT_CHARS = 300
SKIP_FACT_LINES = ("건축제한 근거 조문", "건축 가능 여부")

SIDES = ("북", "동", "남", "서")  # bearings 0, 90, 180, 270 from north
NEAR = 60.0  # m from the lot's edge: buildings beyond this are left out of the summary
ROAD_NEAR = 12.0  # m: a road area within this of an edge counts as along that side
MAX_OUTLINE_POINTS = 24


def _to_frame(point, frame: dict) -> tuple[float, float]:
    """A table point (x east, y north, m) in the blocks' frame (u, v)."""
    a = frame["angle"]
    dx, dy = point[0] - frame["x"], point[1] - frame["y"]
    return dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)


def _bearing(dx: float, dy: float) -> float:
    """Degrees clockwise from north of a direction (x east, y north)."""
    return math.degrees(math.atan2(dx, dy)) % 360


def _side(bearing: float) -> str:
    return SIDES[int(((bearing + 45) % 360) // 90)]


def _thin(points: list, limit: int) -> list:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    return [points[int(i * step)] for i in range(limit)]


def lot_lines(plan: dict) -> list[str]:
    """Part 2: the lot in the blocks' frame."""
    frame = plan["frame"]
    rings = [ring for p in plan.get("parcels") or [] for ring in p.get("rings") or []]
    if not rings:
        return []
    uv = [[_to_frame(pt, frame) for pt in ring] for ring in rings]
    us = [u for ring in uv for u, _ in ring]
    vs = [v for ring in uv for _, v in ring]
    u_bearing = _bearing(math.cos(frame["angle"]), math.sin(frame["angle"]))
    v_bearing = (u_bearing - 90) % 360
    lines = [
        "Blocks stand in the table's frame: u runs along the lot's long side "
        f"(toward bearing {u_bearing:.0f}° from north, {_side(u_bearing)}쪽), v across it "
        f"(toward bearing {v_bearing:.0f}°, {_side(v_bearing)}쪽), metres from the lot's middle. "
        "A block's (u, v) is its centre, w its length along u, d its depth along v.",
        f"Lot extent: u {min(us):.1f} to {max(us):.1f} m, v {min(vs):.1f} to {max(vs):.1f} m "
        f"(about {max(us) - min(us):.1f} × {max(vs) - min(vs):.1f} m).",
    ]
    for i, ring in enumerate(uv):
        pts = _thin([[round(u, 1), round(v, 1)] for u, v in ring], MAX_OUTLINE_POINTS)
        label = "Lot outline" if len(uv) == 1 else f"Parcel {i + 1} outline"
        lines.append(f"{label} (u, v): " + ", ".join(f"({u:g}, {v:g})" for u, v in pts))
    lines.append("Lay every block of a proposed scheme inside this outline, set back from its edges as the "
                 "rules need; Sida checks coverage and floor-area ratio from the blocks.")
    return lines


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _distance_to_lot(points, rings) -> float:
    """The shortest distance (m) from any of `points` to the lot's edges."""
    best = math.inf
    for ring in rings:
        for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
            for px, py in points:
                best = min(best, _segment_distance(px, py, ax, ay, bx, by))
    return best


def _middle(points) -> tuple[float, float]:
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def _ground_at(terrain: dict, x: float, y: float) -> float | None:
    """The ground height (m, from the site's middle) at a point, between the surroundings' grid points."""
    n, step, low, z = terrain["n"], terrain["step"], terrain["min"], terrain["z"]
    fx, fy = (x - low) / step, (y - low) / step
    if not (0 <= fx <= n - 1 and 0 <= fy <= n - 1) or n < 2:
        return None
    i, j = min(int(fx), n - 2), min(int(fy), n - 2)
    tx, ty = fx - i, fy - j

    def at(a, b):
        return float(z[b * n + a])

    return (at(i, j) * (1 - tx) * (1 - ty) + at(i + 1, j) * tx * (1 - ty)
            + at(i, j + 1) * (1 - tx) * ty + at(i + 1, j + 1) * tx * ty)


def around_lines(plan: dict, around: dict) -> list[str]:
    """Part 3: the surroundings around the lot, side by side."""
    rings = [ring for p in plan.get("parcels") or [] for ring in p.get("rings") or []]
    if not rings:
        return []
    mx, my = _middle([pt for ring in rings for pt in ring])
    per_side: dict[str, list[dict]] = {side: [] for side in SIDES}
    on_site = []
    for b in around.get("buildings") or []:
        outline = b.get("outline") or []
        if len(outline) < 3:
            continue
        # What only VWorld gave (an outline drawn for the screen, a height from its floor count) stays
        # on the screen (이용약관 제19조), as in the export.
        if b.get("display_only") or b.get("height_source") == "api_estimate":
            continue
        if b.get("on_site"):
            on_site.append(b)
            continue
        gap = _distance_to_lot(outline, rings)
        if gap > NEAR:
            continue
        cx, cy = _middle(outline)
        per_side[_side(_bearing(cx - mx, cy - my))].append({**b, "gap": gap})
    lines = [f"Surroundings within {NEAR:.0f} m of the lot (Sida's 3D surroundings, public map data, "
             "heights from the building register where known, else estimated):"]

    def describe(b: dict) -> str:
        floors = f" {b['floors']}층" if b.get("floors") else ""
        guess = " (추정 높이)" if str(b.get("height_source") or "").endswith("estimate") else ""
        name = f" {b['name']}" if b.get("name") else ""
        return f"{b['height']:.0f} m{floors}{guess}, {b['gap']:.0f} m away{name}"

    for side in SIDES:
        found = per_side[side]
        if not found:
            lines.append(f"- {side}쪽: no building within {NEAR:.0f} m")
            continue
        nearest = min(found, key=lambda b: b["gap"])
        tallest = max(found, key=lambda b: b.get("height") or 0)
        text = f"- {side}쪽: {len(found)} building{'s' if len(found) > 1 else ''}; nearest {describe(nearest)}"
        if tallest is not nearest:
            text += f"; tallest {describe(tallest)}"
        lines.append(text)
    if on_site:
        top = max(on_site, key=lambda b: b.get("height") or 0)
        lines.append(f"- On the lot now: {len(on_site)} existing building(s), tallest {top['height']:.0f} m "
                     "(the screen draws them see-through; a new scheme usually replaces them)")
    roads = sorted({_side(_bearing(cx - mx, cy - my))
                    for a in around.get("areas") or [] if a.get("kind") == "road" and len(a.get("ring") or []) >= 3
                    for cx, cy in [_middle(a["ring"])]
                    if _distance_to_lot(a["ring"], rings) <= ROAD_NEAR}, key=SIDES.index)
    if around.get("areas"):
        lines.append("- Road along the lot: " + (", ".join(f"{s}쪽" for s in roads) if roads else "none found in the map data"))
    terrain = around.get("terrain")
    if terrain:
        points = [pt for ring in rings for pt in ring]
        heights = [(h, pt) for pt in points if (h := _ground_at(terrain, pt[0], pt[1])) is not None]
        if heights:
            low = min(heights, key=lambda x: x[0])
            high = max(heights, key=lambda x: x[0])
            drop = high[0] - low[0]
            if drop < 0.5:
                lines.append("- Ground: the lot is about flat")
            else:
                toward = _side(_bearing(low[1][0] - high[1][0], low[1][1] - high[1][1]))
                lines.append(f"- Ground: falls about {drop:.1f} m across the lot, lowest toward {toward}쪽")
    return lines


def _plan_and_facts(project_dir: Path):
    from sida.board import site_plan
    from sida.experts.site import site_facts

    facts = site_facts.load_facts(project_dir)
    if not facts:
        return None, None
    return site_plan(site_facts.board_summary(facts)["parcels"]), facts


def _warm(plan: dict, picked: dict) -> None:
    from sida.experts.site import context3d

    try:
        context3d.build(plan, picked["radius"], shape=picked["shape"], orient=picked["orient"], for_export=True)
    except Exception as exc:  # only a warm-up: the next message tries again
        log.warning("surroundings for the massing brief could not be made: %s", exc)


def surroundings_lines(project_dir: Path, plan: dict | None = None) -> list[str]:
    """Part 3 for this project, only while the designer has the surroundings on. A message never
    waits for them: what the screen (or an export) made in the last minutes is used; when there is
    none, they are made in the background for the next message and left out of this one."""
    from sida.experts.site import context3d, context_range

    if plan is None:
        plan, _facts = _plan_and_facts(project_dir)
    if not plan or not context_range.shown(project_dir):
        return []
    picked = context_range.load(project_dir)
    around = context3d.cached(plan, picked["radius"], shape=picked["shape"], orient=picked["orient"])
    if around is None:
        threading.Thread(target=_warm, args=(plan, picked), daemon=True).start()
        return ["Surroundings: being prepared (Sida's 3D surroundings are on but not made yet); "
                "they come with the next message."]
    return around_lines(plan, around)


def conductor_brief(project_dir: Path) -> str:
    """Parts 1-3 for the Conductor ("" without saved site facts)."""
    from sida.experts.site import site_facts

    plan, facts = _plan_and_facts(project_dir)
    if not facts:
        return ""
    lines = ["SITE (Sida's saved site facts; place massing schemes with these):"]
    # The long lists of article titles stay with the regulation checker; a line is kept short.
    facts_lines = [line for line in site_facts.regulatory_lines(facts) if not line.startswith(SKIP_FACT_LINES)]
    lines += [line if len(line) <= MAX_FACT_CHARS else line[:MAX_FACT_CHARS] + "…" for line in facts_lines[:MAX_FACT_LINES]]
    if plan:
        lines += lot_lines(plan)
        lines += surroundings_lines(project_dir, plan)
    return "\n".join(lines)
