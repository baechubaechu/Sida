"""Diagrams drawn by rule from a Rhino snapshot (docs/rhino-api.md, "다이어그램").

A diagram here is a drawing instruction: a list of plain items in metres, in the frame of the
snapshot (origin the middle of the site, x east, y north, z up). Sida decides what is drawn and
where; whoever draws it only follows. The Rhino plugin turns the items into real geometry on a
"Sida 다이어그램" layer, and diagram_svg.py draws the same items as an SVG for the screen and for
files. Nothing is estimated: areas are the ones Rhino measured, the ratios and limits are the
ones the figures already hold, and what cannot be drawn is said in `notes`.

    {"kind", "title", "view": "axo" | "flat", "bounds": [x0, y0, z0, x1, y1, z1],
     "items": [...], "notes": [str]}

Items (every coordinate in metres):
    {"type": "slab", "rings": [[[x, y], ...], ...], "z", "height", "color", "tag"}
        a floor plate or a mass: the rings (even-odd, a ring inside another is a hole) from z up
    {"type": "fill", "rings": [...], "z", "color", "light": bool}      a flat region
    {"type": "line", "points": [[x, y, z], ...], "closed", "bold", "dashed", "color"}
    {"type": "text", "at": [x, y, z], "text", "size", "anchor": start|middle|end,
     "upright": bool, "role": "" | title | legend | caption, "swatch": "#rrggbb" | None}
        `size` is the letter height. `upright` text stands on the x-z plane (read from the
        south) beside an axonometric; the rest lies on the ground. Items with a `role` are the
        drawing's words (title, legend, figures): a flat drawing shows them where they lie, an
        axonometric picture lays them out on its own page instead (a legend line carries its
        colour as `swatch`).

The kinds: program (the masses floor by floor in the colours of their meanings), floors (the
same plates pulled apart, each level with its height and area), stack (floor area by level as
bars), site (the lot, the footprints and the buildings around, to scale with north and a scale
bar) and limits (coverage and FAR against the site's limits).
"""

from __future__ import annotations

import math
from pathlib import Path

from shapely.geometry import Polygon
from shapely.geometry import box as shapely_box

from sida import board
from sida.experts.rhino import snapshot as snap

KINDS: dict[str, dict] = {
    "program": {"title": "프로그램 매스", "view": "axo"},
    "floors": {"title": "층별 분해", "view": "axo"},
    "stack": {"title": "층별 면적", "view": "flat"},
    "site": {"title": "대지 배치도", "view": "flat"},
    "limits": {"title": "법정 수치 비교", "view": "flat"},
}
INK = "#20262d"
SOFT = "#d5d9de"  # the buildings around, a gauge's track
PLAIN = "#36536b"  # a bar that has no meaning to colour it
OVER = "#c0392b"  # the part beyond a limit
EXPLODE = 2.2  # how far apart the floor plates are pulled: this many times their real spacing
PLATE = 0.12  # a pulled-apart plate's thickness, as a part of its storey
SITE_REACH = 40.0  # metres of surroundings drawn around the lot in the site plan
GAUGE_RUN = 1.25  # a gauge's track runs to this many times its limit (the panel's gauge does the same)
MAX_SITE_BUILDINGS = 400

NOT_READY = {
    "no_bodies": "건물 의미를 준 레이어에 잴 수 있는 입체가 없습니다.",
    "no_floors": "층고를 정한 레이어가 없어 층별 면적이 없습니다.",
    "no_site": "대지를 조회하지 않았고 건물 바닥도 없어 그릴 것이 없습니다.",
}


def text_width(text: str, size: float) -> float:
    """About how wide a text is at this letter height (Hangul is a full square, Latin about half)."""
    return sum(1.0 if ord(ch) > 0x2E7F else 0.56 for ch in text) * size


def _m2(value: float) -> str:
    return f"{value:,.1f}㎡"


def _level(z: float) -> str:
    return f"{z:+,.1f}m"


# ---------------------------------------------------------------------------
# What the drawings are made from
# ---------------------------------------------------------------------------


def context(project_path: Path, hooks=None, *, around: bool = True) -> dict:
    """
    What the diagrams need besides the snapshot, from the project as it stands: the site's
    area, the lot's rings in the snapshot's frame, the limits, and the buildings around that a
    file may hold (the site domain's `board_surroundings`; none when they cannot be had).
    `around=False` leaves the buildings out: only the site plan draws them, and building the
    surroundings for the first time takes a while.
    """
    from sida.experts import domain_hooks

    summary = board.site_summary(project_path, hooks) or {}
    plan = board.site_plan(summary.get("parcels") or [])
    buildings: list[dict] = []
    for _domain, module in (domain_hooks() if hooks is None else hooks) if around else []:
        give = getattr(module, "board_surroundings", None)
        if give is None:
            continue
        try:
            got = give(Path(project_path))
        except Exception:  # the surroundings are an extra: a diagram is drawn without them
            got = None
        if got:
            buildings = [b for b in got.get("buildings") or [] if not b.get("on_site")]
            break
    return {
        "site_area": summary.get("area_m2"),
        "lot": [ring for parcel in (plan or {}).get("parcels", []) for ring in parcel["rings"]],
        "limits": snap.limits(project_path),
        "buildings": buildings,
    }


def bodies(snapshot: dict) -> tuple[list[dict], int]:
    """
    The built objects as the diagrams draw them, and how many could not be drawn (no footprint
    or no height). Each: {code, color, rings, base, top, levels: [{z, area, rings, height}]}.
    The levels are the floors that count (snapshot.counted_floors), each with its own outline
    when the plugin sent one, else the footprint; an object on a layer without a floor height
    has no levels and is drawn as one mass.
    """
    meaning = snap.meaning_of(snapshot)
    floor_heights = {layer["path"]: layer["floor_height"] for layer in snapshot["layers"]}
    out, left_out = [], 0
    for item in snapshot["objects"]:
        code = meaning.get(item["layer"], "")
        if code not in snap.BUILT:
            continue
        base = item["base"] if item["base"] is not None else (item["floors"][0]["z"] if item["floors"] else None)
        if not item["footprint"] or item["height"] is None or base is None:
            left_out += 1
            continue
        top = round(base + item["height"], 3)
        counted = snap.counted_floors(item, floor_heights.get(item["layer"]))
        levels = []
        for i, floor in enumerate(counted):
            above = counted[i + 1]["z"] if i + 1 < len(counted) else top
            levels.append({"z": floor["z"], "area": floor["area"], "rings": floor.get("outline") or item["footprint"],
                           "height": round(max(above - floor["z"], 0.1), 3)})
        out.append({"code": code, "color": snap.MEANINGS[code]["color"], "rings": item["footprint"], "base": round(base, 3),
                    "top": top, "levels": levels})
    return out, left_out


def available(snapshot: dict, ctx: dict) -> list[dict]:
    """Every kind with whether this snapshot can be drawn that way: [{kind, title, view, ready, reason}]."""
    drawn, _left = bodies(snapshot)
    has_levels = any(body["levels"] for body in drawn)
    why = {
        "program": "" if drawn else "no_bodies",
        "floors": "" if has_levels else ("no_floors" if drawn else "no_bodies"),
        "stack": "" if has_levels else ("no_floors" if drawn else "no_bodies"),
        "site": "" if drawn or ctx["lot"] else "no_site",
        "limits": "",
    }
    return [{"kind": kind, "title": about["title"], "view": about["view"], "ready": not why[kind],
             "reason": NOT_READY.get(why[kind], "")} for kind, about in KINDS.items()]


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def _slab(rings, z: float, height: float, color: str, tag: str = "") -> dict:
    return {"type": "slab", "rings": rings, "z": round(z, 3), "height": round(height, 3), "color": color, "tag": tag}


def _fill(rings, color: str, *, z: float = 0.0, light: bool = False, role: str = "") -> dict:
    return {"type": "fill", "rings": rings, "z": round(z, 3), "color": color, "light": light, "role": role}


def _line(points, *, closed: bool = False, bold: bool = False, dashed: bool = False, color: str = INK) -> dict:
    return {"type": "line", "points": [[round(c, 3) for c in (*p, 0.0)[:3]] for p in points], "closed": closed, "bold": bold,
            "dashed": dashed, "color": color}


def _text(at, text: str, size: float, *, anchor: str = "start", upright: bool = False, role: str = "", swatch: str | None = None) -> dict:
    return {"type": "text", "at": [round(c, 3) for c in (*at, 0.0)[:3]], "text": text, "size": round(size, 3), "anchor": anchor,
            "upright": upright, "role": role, "swatch": swatch}


def _box(x0: float, y0: float, x1: float, y1: float) -> list[list[list[float]]]:
    return [[[round(x0, 3), round(y0, 3)], [round(x1, 3), round(y0, 3)], [round(x1, 3), round(y1, 3)], [round(x0, 3), round(y1, 3)]]]


def _extent(items: list[dict]) -> list[float]:
    """The box around the items: [x0, y0, z0, x1, y1, z1] (a text counts as its anchor)."""
    xs, ys, zs = [], [], []
    for item in items:
        if item["type"] in ("slab", "fill"):
            for ring in item["rings"]:
                xs += [p[0] for p in ring]
                ys += [p[1] for p in ring]
            zs += [item["z"], item["z"] + item.get("height", 0.0)]
        elif item["type"] == "line":
            xs += [p[0] for p in item["points"]]
            ys += [p[1] for p in item["points"]]
            zs += [p[2] for p in item["points"]]
        else:
            xs.append(item["at"][0])
            ys.append(item["at"][1])
            zs.append(item["at"][2])
    if not xs:
        return [0.0] * 6
    return [round(v, 3) for v in (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))]


def _words(items: list[dict], title: str, legend: list[tuple[str, str]], caption: list[str], size: float) -> None:
    """
    The drawing's words, laid on the ground south of what is drawn: the title, a legend line
    per colour and the figure lines. An axonometric picture lays them out itself (`role`).
    """
    x0, y0, z0, _x1, _y1, _z1 = _extent(items)
    step = size * 1.7
    y = y0 - size * 3
    items.append(_text([x0, y, z0], title, size * 1.4, role="title"))
    y -= step * 1.2
    for color, text in legend:
        items.append(_fill(_box(x0, y, x0 + size, y + size), color, z=z0, role="legend"))
        items.append(_text([x0 + size * 1.6, y, z0], text, size, role="legend", swatch=color))
        y -= step
    for text in caption:
        items.append(_text([x0, y, z0], text, size, role="caption"))
        y -= step


def _finish(kind: str, items: list[dict], notes: list[str]) -> dict:
    return {"kind": kind, "title": KINDS[kind]["title"], "view": KINDS[kind]["view"], "bounds": _extent(items), "items": items,
            "notes": notes}


def _letter(span: float) -> float:
    """A letter height that reads beside a drawing this wide (metres)."""
    return round(min(max(span / 40, 0.8), 6.0), 2)


def _span(drawn: list[dict], lot) -> float:
    xs = [p[0] for body in drawn for ring in body["rings"] for p in ring] + [p[0] for ring in lot for p in ring]
    ys = [p[1] for body in drawn for ring in body["rings"] for p in ring] + [p[1] for ring in lot for p in ring]
    return max(max(xs) - min(xs), max(ys) - min(ys), 10.0) if xs else 10.0


def _left_out(left: int) -> list[str]:
    return [f"잴 수 없는 개체 {left}개는 그리지 않았습니다 (닫히지 않았거나 바닥 단면이 없음)."] if left else []


def _legend(fig: dict, *, drawn_only: bool = False) -> list[tuple[str, str]]:
    """A line per meaning with its floor area and share; `drawn_only` leaves out those without floor area (nothing of them is drawn)."""
    total = fig["floor_area_m2"]
    rows = []
    for part in fig["by_meaning"]:
        if drawn_only and not part["floor_area_m2"] > 0:
            continue
        share = f" · {part['floor_area_m2'] / total * 100:.0f}%" if total > 0 else ""
        rows.append((snap.MEANINGS[part["meaning"]]["color"], f"{part['word']} {_m2(part['floor_area_m2'])}{share}"))
    return rows


# ---------------------------------------------------------------------------
# The kinds
# ---------------------------------------------------------------------------


def _program(snapshot: dict, fig: dict, ctx: dict) -> dict:
    drawn, left = bodies(snapshot)
    ground = min((body["base"] for body in drawn), default=0.0)
    items = [_line([[*p, ground] for p in ring], closed=True, bold=True) for ring in ctx["lot"]]
    whole = 0
    for body in drawn:
        if body["levels"]:
            items += [_slab(level["rings"], level["z"], level["height"], body["color"], body["code"]) for level in body["levels"]]
        else:
            whole += 1
            items.append(_slab(body["rings"], body["base"], body["top"] - body["base"], body["color"], body["code"]))
    notes = _left_out(left)
    if whole:
        notes.append(f"층고를 정하지 않은 레이어의 개체 {whole}개는 층 없이 한 덩어리로 그렸습니다.")
    _words(items, KINDS["program"]["title"], _legend(fig), snap.figure_lines(fig)[:3], _letter(_span(drawn, ctx["lot"])))
    return _finish("program", items, notes)


def _by_level(drawn: list[dict]) -> list[dict]:
    """The floors of every body, gathered by height: [{z, area, parts: {code: area}}], lowest first."""
    levels: dict[float, dict] = {}
    for body in drawn:
        for floor in body["levels"]:
            at = levels.setdefault(round(floor["z"], 2), {"z": round(floor["z"], 2), "area": 0.0, "parts": {}})
            at["area"] += floor["area"]
            at["parts"][body["code"]] = at["parts"].get(body["code"], 0.0) + floor["area"]
    return [levels[z] for z in sorted(levels)]


def _floors(snapshot: dict, fig: dict, ctx: dict) -> dict:
    drawn, left = bodies(snapshot)
    storeyed = [body for body in drawn if body["levels"]]
    ground = min((body["base"] for body in storeyed), default=0.0)
    span = _span(storeyed, ctx["lot"])
    size = _letter(span)

    def lifted(z: float) -> float:
        return ground + (z - ground) * EXPLODE

    items = [_line([[*p, ground] for p in ring], closed=True, bold=True) for ring in ctx["lot"]]
    for body in storeyed:
        for level in body["levels"]:
            items.append(_slab(level["rings"], lifted(level["z"]), max(level["height"] * PLATE, 0.2), body["color"], body["code"]))
    x0, y0, _z0, x1, _y1, _z1 = _extent([i for i in items if i["type"] == "slab"])
    levels = _by_level(storeyed)
    # The labels stand in columns east of the plates, at the front. Bodies with different storeys
    # give levels close together: a label that would sit on the one below goes to the next column.
    said = [(level, f"{_level(level['z'])}  {_m2(level['area'])}") for level in levels]
    wide = max((text_width(text, size) for _level_, text in said), default=0.0) + size * 1.5
    column = x1 + size * 2
    aside = wide / (2 * math.cos(math.radians(30)))  # a step south-east: straight to the right in the axonometric picture
    tops: list[float] = []  # the highest label so far in each column
    for level, text in said:
        z = lifted(level["z"])
        at = next((k for k, last in enumerate(tops) if z - last >= size * 1.5), len(tops))
        if at == len(tops):
            if at >= 3:  # three columns are enough to read; a fourth would only move the crowding
                at = min(range(len(tops)), key=lambda k: tops[k])
            else:
                tops.append(z)
        tops[at] = z
        items.append(_text([column + at * aside, y0 - at * aside, z], text, size, upright=True))
    if levels:
        items.append(_line([[column - size * 0.8, y0, lifted(levels[0]["z"])], [column - size * 0.8, y0, lifted(levels[-1]["z"]) + size]],
                           dashed=True))
    notes = _left_out(left)
    if len(drawn) > len(storeyed):
        notes.append(f"층고를 정하지 않은 레이어의 개체 {len(drawn) - len(storeyed)}개는 층이 없어 빠졌습니다.")
    _words(items, KINDS["floors"]["title"], _legend(fig, drawn_only=True), [f"연면적 {_m2(fig['floor_area_m2'])}"], size)
    return _finish("floors", items, notes)


def _stack(snapshot: dict, fig: dict, ctx: dict) -> dict:
    drawn, left = bodies(snapshot)
    levels = _by_level(drawn)
    row, bar, run, size = 3.0, 2.2, 40.0, 1.4  # a chart has no scale of its own: metres that read beside a building
    widest = max((level["area"] for level in levels), default=0.0)
    items: list[dict] = []
    for i, level in enumerate(levels):
        y = i * row
        x = 0.0
        for code in snap.BUILT:
            area = level["parts"].get(code)
            if not area:
                continue
            width = area / widest * run if widest > 0 else 0.0
            items.append(_fill(_box(x, y, x + width, y + bar), snap.MEANINGS[code]["color"]))
            x += width
        items.append(_text([-size, y + (bar - size) / 2], _level(level["z"]), size, anchor="end"))
        items.append(_text([x + size, y + (bar - size) / 2], _m2(level["area"]), size))
    items.append(_line([[0.0, -row * 0.3], [0.0, len(levels) * row]]))
    notes = _left_out(left)
    storeyless = sum(1 for body in drawn if not body["levels"])
    if storeyless:
        notes.append(f"층고를 정하지 않은 레이어의 개체 {storeyless}개는 층별 면적이 없어 빠졌습니다.")
    _words(items, KINDS["stack"]["title"], _legend(fig, drawn_only=True), [f"연면적 {_m2(fig['floor_area_m2'])}"], size)
    return _finish("stack", items, notes)


def _scale_bar(width: float) -> float:
    return next((m for m in (1, 2, 5, 10, 20, 50, 100, 200, 500) if m >= width / 6), 1000)


def _within(outline: list, x0: float, y0: float, x1: float, y1: float) -> list[list[list[float]]]:
    """
    A building's outline as far as it lies in the plan's frame: itself when all of it does, cut
    at the frame when it reaches over, nothing when it stands outside. (A plan is cut at its
    frame; a building left whole would hang out of it, and one left out would leave a hole.)
    """
    ring = [[round(p[0], 3), round(p[1], 3)] for p in outline]
    if all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in ring):
        return [ring]
    if max(x for x, _ in ring) <= x0 or min(x for x, _ in ring) >= x1 or max(y for _, y in ring) <= y0 or min(y for _, y in ring) >= y1:
        return []
    shape = Polygon(ring)
    if not shape.is_valid:
        shape = shape.buffer(0)
    cut = shape.intersection(shapely_box(x0, y0, x1, y1))
    parts = [cut] if cut.geom_type == "Polygon" else [g for g in getattr(cut, "geoms", []) if g.geom_type == "Polygon"]
    return [[[round(x, 3), round(y, 3)] for x, y in part.exterior.coords[:-1]] for part in parts if part.area > 0.01]


def _site(snapshot: dict, fig: dict, ctx: dict) -> dict:
    drawn, left = bodies(snapshot)
    own = [ring for body in drawn for ring in body["rings"]] + list(ctx["lot"])
    xs = [p[0] for ring in own for p in ring]
    ys = [p[1] for ring in own for p in ring]
    x0, y0, x1, y1 = min(xs) - SITE_REACH, min(ys) - SITE_REACH, max(xs) + SITE_REACH, max(ys) + SITE_REACH
    size = _letter(max(x1 - x0, y1 - y0))
    items: list[dict] = []
    near = 0
    for building in ctx["buildings"]:
        outline = building.get("outline") or []
        if len(outline) < 3 or near >= MAX_SITE_BUILDINGS:
            continue
        rings = _within(outline, x0, y0, x1, y1)
        if not rings:
            continue
        near += 1
        for ring in rings:
            items.append(_fill([ring], SOFT, light=bool(building.get("estimate"))))
            items.append(_line(ring, closed=True, color="#8a929b"))
    for body in drawn:
        items.append(_fill(body["rings"], INK))
    for ring in ctx["lot"]:
        items.append(_line(ring, closed=True, bold=True, dashed=True))
    items.append(_line([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], closed=True))
    # north, up the page: the frame of the snapshot has y to the north
    nx, ny, arrow = x1 - size * 2.5, y1 - size * 7, size * 4
    items.append(_line([[nx, ny], [nx, ny + arrow]], bold=True))
    items.append(_line([[nx - size * 0.8, ny + arrow - size * 1.4], [nx, ny + arrow], [nx + size * 0.8, ny + arrow - size * 1.4]], bold=True))
    items.append(_text([nx, ny + arrow + size * 0.5], "N", size * 1.2, anchor="middle"))
    bar = _scale_bar(x1 - x0)
    bx, by = x0 + size * 2, y0 + size * 2
    items.append(_line([[bx, by], [bx + bar, by]], bold=True))
    for x in (bx, bx + bar / 2, bx + bar):
        items.append(_line([[x, by - size * 0.4], [x, by + size * 0.4]]))
    items.append(_text([bx + bar + size, by - size * 0.4], f"{bar:g}m", size))
    notes = _left_out(left)
    if not ctx["lot"]:
        notes.append("대지를 조회하지 않아 대지 경계가 없습니다.")
    if not near:
        notes.append("파일에 담을 수 있는 주변 건물 자료가 없어 주변은 비어 있습니다.")
    caption = [f"대지면적 {_m2(fig['site_area_m2'])}" if fig["site_area_m2"] else "대지면적 미확인", f"건축면적 {_m2(fig['footprint_m2'])}"]
    _words(items, KINDS["site"]["title"], [], caption, size)
    return _finish("site", items, notes)


def gauge(value: float | None, zones: list[dict], ordinance_key: str, legal_key: str) -> dict:
    """
    A ratio against its limit: {value, limit, source}. The limit is the ordinance's value when it
    was read by rule, else the legal ceiling, and only when the site lies in one zone: across
    zones the limit would be a weighted figure nobody has computed, so there is none.
    """
    out = {"value": value, "limit": None, "source": ""}
    if len(zones) != 1:
        return out
    zone = zones[0]
    read = zone.get(ordinance_key)
    limit = read if read is not None else zone.get(legal_key)
    if limit is None or not limit > 0:
        return out
    return {"value": value, "limit": limit, "source": "조례" if read is not None else "법정 상한"}


def limit_lines(zones: list[dict]) -> list[str]:
    """The zones' limits as lines, as the site facts have them (nothing merged across zones)."""
    lines = []
    for zone in zones:
        legal = ", ".join(x for x in (f"건폐율 {zone['bcr_max']:g}% 이하" if zone.get("bcr_max") is not None else "",
                                       f"용적률 {zone['far_max']:g}% 이하" if zone.get("far_max") is not None else "") if x)
        read = ", ".join(x for x in (f"건폐율 {zone['ordinance_bcr']:g}%" if zone.get("ordinance_bcr") is not None else "",
                                      f"용적률 {zone['ordinance_far']:g}%" if zone.get("ordinance_far") is not None else "") if x)
        lines.append(f"{zone['zone']}: 법정 {legal or '미확인'}" + (f" (조례 {read})" if read else ""))
    return lines


def _limits(snapshot: dict, fig: dict, ctx: dict) -> dict:
    row, bar, run, size = 7.0, 2.0, 40.0, 1.4
    zones = ctx["limits"]
    rows = (("건폐율", gauge(fig["coverage_pct"], zones, "ordinance_bcr", "bcr_max")),
            ("용적률", gauge(fig["far_pct"], zones, "ordinance_far", "far_max")))
    items: list[dict] = []
    for i, (label, g) in enumerate(rows):
        y = -i * row
        said = "미확인" if g["value"] is None else f"{g['value']:,.1f}%"
        items.append(_text([0.0, y + bar + size * 0.6], f"{label} {said}", size * 1.2))
        if g["limit"] is None:
            continue
        mark = run / GAUGE_RUN  # where the limit stands on the track
        items.append(_fill(_box(0.0, y, run, y + bar), SOFT))
        if g["value"] is not None:
            part = min(g["value"] / g["limit"], GAUGE_RUN)
            items.append(_fill(_box(0.0, y, min(part, 1.0) * mark, y + bar), PLAIN))
            if part > 1.0:
                items.append(_fill(_box(mark, y, part * mark, y + bar), OVER))
        items.append(_line([[mark, y - bar * 0.25], [mark, y + bar * 1.25]], bold=True))
        over = " 초과" if g["value"] is not None and g["value"] > g["limit"] else ""
        items.append(_text([mark, y - bar * 0.25 - size * 1.3], f"{g['source']} {g['limit']:g}%{over}", size, anchor="middle"))
    notes = []
    if not zones:
        notes.append("대지를 조회하지 않아 한도가 없습니다.")
    elif len(zones) > 1:
        notes.append("용도지역이 여러 개라 한도 막대는 그리지 않았습니다. 지역별 한도는 아래 줄에 있습니다.")
    caption = [
        f"대지면적 {_m2(fig['site_area_m2'])}" if fig["site_area_m2"] else "대지면적 미확인",
        f"건축면적 {_m2(fig['footprint_m2'])} · 연면적 {_m2(fig['floor_area_m2'])}",
        *([f"최고 높이 {fig['height_m']:,.1f}m"] if fig["height_m"] is not None else []),
        *limit_lines(zones),
    ]
    _words(items, KINDS["limits"]["title"], [], caption, size)
    return _finish("limits", items, notes)


MAKERS = {"program": _program, "floors": _floors, "stack": _stack, "site": _site, "limits": _limits}


def drawing(kind: str, snapshot: dict, ctx: dict) -> dict:
    """One diagram of a (checked) snapshot. Raises ValueError for an unknown kind or one this snapshot cannot be drawn as."""
    if kind not in KINDS:
        raise ValueError("kind must be one of " + ", ".join(KINDS))
    state = next(a for a in available(snapshot, ctx) if a["kind"] == kind)
    if not state["ready"]:
        raise ValueError(state["reason"])
    return MAKERS[kind](snapshot, snap.figures(snapshot, ctx["site_area"]), ctx)


def of_snapshot(project_path: Path, snapshot_id: str, kind: str | None = None):
    """
    A saved snapshot's diagrams: with a kind its drawing, without the list of kinds and whether
    each can be drawn. Raises SnapshotNotFound, ValueError.
    """
    saved = snap.load_snapshot(project_path, snapshot_id)
    ctx = context(project_path, around=kind == "site")
    return available(saved, ctx) if kind is None else drawing(kind, saved, ctx)
