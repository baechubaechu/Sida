"""The paint on the roads around the site, as shapes the table and the files can draw.

From the 국토지리정보원 정밀도로지도 (공공누리 제1유형) lane lines (B2 노면선표시) and road marks
(B3 노면표시) a terrain pack keeps (terrain_pack.py). Independent of HTTP and the screen; points
are in the table's frame (metres, x east, y north).

- A lane line's Type is three digits: its colour (1 yellow, 2 white, 3 blue), single (1) or
  double (2), and solid (1), dashed (2) or, for a double line, dashed on the left (3) or on the
  right (4) of the way it was drawn. Its Kind says what it is; only the stop line (530) is
  drawn wider. Dashes are the city lane dash, DASH m painted and GAP m apart.
- A road mark in the file is only the rectangle it covers. An arrow (Type 1, Kind as numbered in
  도로교통법 시행규칙 별표 6: 537x 진행방향, 538x, 539x) is drawn as the arrow its Kind names, laid in
  that rectangle and pointing the way the lane link it names runs; with no link the way is not
  known, and only the rectangle is drawn. A pedestrian crossing (5321) is drawn as stripes that
  run with the traffic. Any other mark is drawn as its rectangle's outline.

Nothing is made up: a line or mark the file does not have is not drawn.
"""

from __future__ import annotations

import math

import numpy as np

LINE_WIDTH = 0.15  # m, a lane line
STOP_WIDTH = 0.45  # m, a stop line (Kind 530)
STOP_LINE = "530"
DASH, GAP = 3.0, 5.0  # m, a dashed lane line in town
DOUBLE_APART = 0.3  # m between the middles of the two lines of a double line
COLORS = {"1": "yellow", "2": "white", "3": "blue"}
ARROWS = {"5371": "직진", "5372": "좌회전", "5373": "우회전", "5381": "직진·좌회전", "5382": "직진·우회전",
          "5391": "좌회전·우회전"}
CROSSINGS = {"5321": "횡단보도"}
STRIPE, STRIPE_GAP = 0.45, 0.5  # m, a crossing's stripes and the gaps between them
HEAD = 1.5  # m, an arrow head's length
SHAFT = 0.18  # m, an arrow shaft's width
LIFT = 0.03  # m the paint is drawn above the ground, so it is not hidden in it


def line_style(type_: str, kind: str) -> dict:
    """{"color", "width", "lines": [(offset m to the left, dashed)]} for a lane line's codes."""
    t = (str(type_) + "   ")[:3]
    color = COLORS.get(t[0], "white")
    width = STOP_WIDTH if str(kind) == STOP_LINE else LINE_WIDTH
    if t[1] == "2":
        half = DOUBLE_APART / 2
        left, right = {"1": (False, False), "2": (True, True), "3": (True, False), "4": (False, True)}.get(t[2], (False, False))
        return {"color": color, "width": width, "lines": [(half, left), (-half, right)]}
    return {"color": color, "width": width, "lines": [(0.0, t[2] == "2")]}


def offset(points, distance: float) -> list[tuple[float, float]]:
    """The line moved `distance` m to its left (negative: right), corners mitred."""
    p = np.asarray(points, dtype=float)
    if distance == 0 or len(p) < 2:
        return [tuple(q) for q in p]
    seg = np.diff(p, axis=0)
    length = np.hypot(seg[:, 0], seg[:, 1])
    keep = length > 1e-9
    if not keep.any():
        return [tuple(q) for q in p]
    normal = np.zeros_like(seg)
    normal[keep] = np.column_stack([-seg[keep, 1], seg[keep, 0]]) / length[keep, None]
    out = []
    for i in range(len(p)):
        a = normal[i - 1] if i > 0 else normal[0]
        b = normal[i] if i < len(seg) else normal[-1]
        n = a + b
        size = np.hypot(*n)
        n = a if size < 1e-9 else n / size
        cos = max(0.5, float(np.dot(n, b if i < len(seg) else a)))  # mitre, at most twice as long
        out.append((p[i, 0] + n[0] * distance / cos, p[i, 1] + n[1] * distance / cos))
    return out


def dashes(points, on: float = DASH, off: float = GAP) -> list[list[tuple[float, float]]]:
    """The painted pieces of a dashed line: `on` m painted, `off` m left, from its start."""
    pts = [tuple(map(float, q)) for q in points]
    out: list[list[tuple[float, float]]] = []
    if len(pts) < 2:
        return out
    painting, left, run = True, on, [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        seg = math.hypot(x1 - x0, y1 - y0)
        done = 0.0
        while seg - done > 1e-9:
            step = min(seg - done, left)
            done += step
            left -= step
            at = (x0 + (x1 - x0) * done / seg, y0 + (y1 - y0) * done / seg)
            if painting:
                run.append(at)
            if left <= 1e-9:
                if painting and len(run) >= 2:
                    out.append(run)
                painting = not painting
                left = on if painting else off
                run = [at]
    if painting and len(run) >= 2:
        out.append(run)
    return [r for r in out if math.hypot(r[-1][0] - r[0][0], r[-1][1] - r[0][1]) > 0.01 or len(r) > 2]


def strokes(points, type_: str, kind: str) -> list[tuple[str, float, list[tuple[float, float]]]]:
    """(colour, width m, the middle of one painted piece) for everything a lane line paints."""
    style = line_style(type_, kind)
    out = []
    for distance, dashed in style["lines"]:
        line = offset(points, distance)
        for piece in dashes(line) if dashed else [line]:
            out.append((style["color"], style["width"], piece))
    return out


def _axes(ring, ahead):
    """The mark's rectangle as (middle, along, across, length, width): `along` its long side, pointing
    toward `ahead` when given; `across` to the left of it."""
    p = np.asarray(ring, dtype=float)
    if len(p) > 3 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    mid = p.mean(axis=0)
    q = p - mid
    sxx, syy, sxy = float((q[:, 0] ** 2).sum()), float((q[:, 1] ** 2).sum()), float((q[:, 0] * q[:, 1]).sum())
    angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
    along = np.array([math.cos(angle), math.sin(angle)])
    if ahead is not None and np.dot(along, np.asarray(ahead, dtype=float) - mid) < 0:
        along = -along
    across = np.array([-along[1], along[0]])
    u, v = q @ along, q @ across
    lo, wl = float(u.min()), float(v.min())
    return mid + along * (lo + float(u.max())) / 2 + across * (wl + float(v.max())) / 2, along, across, float(u.max() - lo), float(v.max() - wl)


def arrow(kind: str, length: float, width: float) -> list[list[tuple[float, float]]] | None:
    """The arrow `kind` names (ARROWS) as convex pieces in its own frame: (across, along) m from
    the middle of its rectangle, along pointing the way it shows, across to the left. None for a
    Kind that is not an arrow."""
    if kind not in ARROWS:
        return None
    s, half = SHAFT / 2, min(width / 2, 0.6)
    tail, tip = -length / 2, length / 2
    head = min(HEAD, length / 2)
    pieces: list[list[tuple[float, float]]] = []

    def bar(u0, u1, v0, v1):
        pieces.append([(min(u0, u1), v0), (max(u0, u1), v0), (max(u0, u1), v1), (min(u0, u1), v1)])

    def up(u, base, wide):
        pieces.append([(u - wide, base), (u + wide, base), (u, tip)])

    def turn(u, v, way):  # a bar from the shaft at u to the side `way` (+1 left, -1 right) and its head
        end = way * (width / 2) - way * 0.55
        bar(u, end, v - s, v + s)
        pieces.append([(end, v - 0.32), (end, v + 0.32), (end + way * 0.55, v)])

    if kind == "5371":
        bar(-s, s, tail, tip - head)
        up(0.0, tip - head, half)
    elif kind in ("5372", "5373"):
        way = 1 if kind == "5372" else -1
        u, v = -way * (width / 2 - 0.2), tip - 0.5
        bar(u - s, u + s, tail, v + s)
        turn(u, v, way)
    elif kind in ("5381", "5382"):
        way = 1 if kind == "5381" else -1
        u = -way * (width / 2 - 0.32)
        bar(u - s, u + s, tail, tip - head)
        up(u, tip - head, 0.3)
        turn(u, tip - head - 0.9, way)
    else:  # 5391
        v = tip - 0.5
        bar(-s, s, tail, v + s)
        turn(0.0, v, 1)
        turn(0.0, v, -1)
    return pieces


def mark_shapes(type_: str, kind: str, ring, ahead) -> dict:
    """{"name", "shapes": convex pieces to fill, "outline": a ring to draw as a line or None} for a
    road mark (see the module's notes); points in the table's frame."""
    kind = str(kind)
    mid, along, across, length, width = _axes(ring, ahead)

    def place(pieces, a=along, c=across):
        return [[(float(mid[0] + c[0] * u + a[0] * v), float(mid[1] + c[1] * u + a[1] * v)) for u, v in piece] for piece in pieces]

    outline = [tuple(map(float, q)) for q in np.asarray(ring, dtype=float)]
    if str(type_) == "1" and kind in ARROWS and ahead is not None:
        return {"name": ARROWS[kind], "shapes": place(arrow(kind, length, width)), "outline": None}
    if kind in CROSSINGS:
        # stripes run with the traffic: the way the link runs when known, else along the short side
        a = across
        if ahead is not None:
            to = np.asarray(ahead, dtype=float) - mid
            if np.hypot(*to) > 1e-9:
                a = to / np.hypot(*to)
        c = np.array([-a[1], a[0]])
        q = np.asarray(outline, dtype=float) - mid
        ta, tc = q @ a, q @ c
        stripes = []
        b = float(tc.min()) + 0.2
        while b + STRIPE <= float(tc.max()) - 0.1:
            stripes.append([(b, float(ta.min())), (b + STRIPE, float(ta.min())), (b + STRIPE, float(ta.max())), (b, float(ta.max()))])
            b += STRIPE + STRIPE_GAP
        return {"name": CROSSINGS[kind], "shapes": place(stripes, a, c), "outline": None}
    return {"name": ARROWS.get(kind, CROSSINGS.get(kind, "노면표시")), "shapes": [], "outline": outline}


def _densify(points, gap: float) -> np.ndarray:
    p = np.asarray(points, dtype=float)
    out = [p[0]]
    for a, b in zip(p[:-1], p[1:], strict=True):
        k = max(1, math.ceil(math.hypot(*(b - a)) / gap))
        out += [a + (b - a) * (i / k) for i in range(1, k + 1)]
    return np.asarray(out)


def drawing(lines: list[dict], marks: list[dict], z_at, *, gap: float = 2.0) -> dict:
    """
    The road paint laid on the ground: {"lines": [{"color", "width", "pieces": [[[x, y, z]]]}]
    (one entry per colour and width), "marks": [{"kind", "name", "shapes": [[[x, y, z]]],
    "outline": [[x, y, z]] or None}]}. `lines` and `marks` are the pack's records with their
    points already in the table's frame; `z_at(xs, ys)` is the ground's height there. Lines are
    given a point every `gap` m so they follow the ground; everything sits LIFT m above it.
    """
    def lay(points, dense=True):
        p = _densify(points, gap) if dense and len(points) >= 2 else np.asarray(points, dtype=float)
        zs = np.asarray(z_at(p[:, 0], p[:, 1]), dtype=float) + LIFT
        return [[round(float(x), 2), round(float(y), 2), round(float(z), 2)] for (x, y), z in zip(p, zs, strict=True)]

    groups: dict[tuple[str, float], list] = {}
    for line in lines:
        for color, width, piece in strokes(line["points"], line["type"], line["kind"]):
            groups.setdefault((color, width), []).append(lay(piece))
    out_marks = []
    for m in marks:
        drawn = mark_shapes(m["type"], m["kind"], m["ring"], m.get("ahead"))
        out_marks.append({"kind": str(m["kind"]), "name": drawn["name"],
                          "shapes": [lay(s, dense=False) for s in drawn["shapes"]],
                          "outline": lay(drawn["outline"]) if drawn["outline"] else None})
    return {"lines": [{"color": c, "width": w, "pieces": p} for (c, w), p in groups.items()], "marks": out_marks}
