"""A diagram's drawing instruction (diagrams.py) as an SVG picture, for the screen and for files.

A flat drawing is shown from above, to scale, with its words where the drawing has them. An
axonometric one is seen from the south-west and from above (the usual isometric: east to the
lower right, north to the upper right), its plates painted from the far one to the near one,
and its words (title, legend, figures) set on the page around it instead of lying on the ground.
The picture only follows the items: nothing is added that the drawing does not hold.
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

from sida.experts.rhino import snapshot as snap
from sida.experts.rhino.diagrams import text_width

WIDTH = 960.0  # px; the picture scales (viewBox)
MARGIN = 28.0
MAX_AXO_HEIGHT = 900.0
INK = "#20262d"
FONT = "Pretendard, 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif"
COS30, SIN30 = math.cos(math.radians(30)), 0.5
ANCHOR_SHIFT = {"start": 0.0, "middle": 0.5, "end": 1.0}
TITLE_PX, WORD_PX = 20.0, 14.0


def _shade(color: str, factor: float) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(v * factor))) for v in (r, g, b)))


def _path(rings, at) -> str:
    return " ".join("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in (at(p) for p in ring)) + " Z" for ring in rings)


def _line_svg(item: dict, at) -> str:
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (at(p) for p in item["points"]))
    tag = "polygon" if item["closed"] else "polyline"
    dash = ' stroke-dasharray="7 4"' if item["dashed"] else ""
    return (f'<{tag} points="{points}" fill="none" stroke="{item["color"]}" stroke-width="{2.2 if item["bold"] else 1.0}" '
            f'stroke-linejoin="round" stroke-linecap="round"{dash} data-type="line"/>')


def _text_svg(x: float, y: float, text: str, px: float, anchor: str = "start", weight: int = 400) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{px:.1f}" font-weight="{weight}" text-anchor="{anchor}" fill="{INK}" '
            f'font-family="{FONT}" data-type="text">{escape(text)}</text>')


def _page(width: float, height: float, kind: str, body: list[str]) -> bytes:
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.1f} {height:.1f}" '
            f'data-kind="{escape(kind)}">')
    return "\n".join([head, f'<rect width="{width:.1f}" height="{height:.1f}" fill="#ffffff"/>', *body, "</svg>"]).encode("utf-8")


# ---------------------------------------------------------------------------
# Flat: from above, to scale
# ---------------------------------------------------------------------------


def _flat(drawing: dict) -> bytes:
    items = drawing["items"]
    x0, y0, _z0, x1, y1, _z1 = drawing["bounds"]
    for item in items:  # a text reaches beyond its anchor
        if item["type"] != "text":
            continue
        wide = text_width(item["text"], item["size"])
        left = item["at"][0] - wide * ANCHOR_SHIFT[item["anchor"]]
        x0, x1 = min(x0, left), max(x1, left + wide)
        y1 = max(y1, item["at"][1] + item["size"] * 1.2)
        y0 = min(y0, item["at"][1] - item["size"] * 0.3)
    k = (WIDTH - 2 * MARGIN) / max(x1 - x0, 1e-6)
    height = (y1 - y0) * k + 2 * MARGIN

    def at(p):
        return MARGIN + (p[0] - x0) * k, MARGIN + (y1 - p[1]) * k

    body = []
    for item in items:
        if item["type"] == "fill":
            opacity = ' fill-opacity="0.5"' if item.get("light") else ""
            body.append(f'<path d="{_path(item["rings"], at)}" fill="{item["color"]}" fill-rule="evenodd"{opacity} data-type="fill"/>')
    for item in items:
        if item["type"] == "line":
            body.append(_line_svg(item, at))
    for item in items:
        if item["type"] == "text":
            x, y = at(item["at"])
            body.append(_text_svg(x, y, item["text"], item["size"] * k, item["anchor"], 600 if item["role"] == "title" else 400))
    return _page(WIDTH, height, drawing["kind"], body)


# ---------------------------------------------------------------------------
# Axonometric: from the south-west and above
# ---------------------------------------------------------------------------


def _iso(p) -> tuple[float, float]:
    """Model metres to the picture's own metres: east to the lower right, north to the upper right, up is up (y grows down)."""
    x, y, z = p
    return (x - y) * COS30, -((x + y) * SIN30 + z)


def _solids(slab: dict) -> list[dict]:
    """A slab as solid pieces to paint: {z, top, depth, faces: [(path in picture metres, colour)]}, each piece's walls before its lid."""
    from shapely.geometry.polygon import orient

    shape = snap._shape(slab["rings"])
    if shape is None or shape.is_empty:
        return []
    z, top = slab["z"], slab["z"] + slab["height"]
    out = []
    for part in getattr(shape, "geoms", [shape]):
        if part.geom_type != "Polygon" or part.is_empty:
            continue
        part = orient(part, 1.0)  # outside counter-clockwise, holes clockwise: (dy, -dx) points away from the body
        loops = [list(part.exterior.coords)[:-1], *(list(hole.coords)[:-1] for hole in part.interiors)]
        cx, cy = part.representative_point().coords[0]
        walls = []
        for loop in loops:
            for (ax, ay), (bx, by) in zip(loop, loop[1:] + loop[:1], strict=True):
                dx, dy = bx - ax, by - ay
                length = math.hypot(dx, dy)
                if length < 1e-9 or dx - dy <= 0:  # faces away from the south-west
                    continue
                light = 0.68 + 0.14 * max(0.0, -dy / length)  # the west side a little lighter than the south side
                quad = [_iso((ax, ay, z)), _iso((bx, by, z)), _iso((bx, by, top)), _iso((ax, ay, top))]
                walls.append(((ax + bx) / 2 + (ay + by) / 2, "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in quad) + " Z",
                              _shade(slab["color"], light)))
        walls.sort(key=lambda wall: -wall[0])  # the far walls first (the far side of a courtyard shows through it)
        lid = " ".join("M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in (_iso((px, py, top)) for px, py in loop)) + " Z" for loop in loops)
        out.append({"z": z, "top": top, "depth": cx + cy, "faces": [*((path, color) for _d, path, color in walls), (lid, slab["color"])]})
    return out


def _far_first(solids: list[dict]) -> list[dict]:
    """
    The order to paint upright solids in, seen from above and the south-west. One that lies wholly
    below another is painted first (it can never hide the one above); two that share a height
    stand side by side, and the one farther to the north-east is painted first. Where that has
    no order (a ring of three), the lowest goes first.
    """
    count = len(solids)
    if count > 400:  # too many to compare each with each: by height, then by distance
        return sorted(solids, key=lambda s: (s["z"], -s["depth"]))
    after: list[set[int]] = [set() for _ in range(count)]  # after[i]: those painted after i
    waits = [0] * count
    for i in range(count):
        for j in range(i + 1, count):
            a, b = solids[i], solids[j]
            if a["top"] <= b["z"] + 1e-6:
                first, then = i, j
            elif b["top"] <= a["z"] + 1e-6:
                first, then = j, i
            else:
                first, then = (i, j) if a["depth"] >= b["depth"] else (j, i)
            after[first].add(then)
            waits[then] += 1
    left = set(range(count))
    order = []
    while left:
        free = [i for i in left if waits[i] == 0]
        pick = min(free) if free else min(left, key=lambda i: (solids[i]["z"], -solids[i]["depth"]))
        left.discard(pick)
        order.append(solids[pick])
        for j in after[pick]:
            if j in left:
                waits[j] -= 1
    return order


def _axo(drawing: dict) -> bytes:
    items = drawing["items"]
    slabs = [i for i in items if i["type"] == "slab"]
    lines = [i for i in items if i["type"] == "line"]
    labels = [i for i in items if i["type"] == "text" and not i["role"]]
    title = next((i["text"] for i in items if i["type"] == "text" and i["role"] == "title"), drawing["title"])
    legend = [i for i in items if i["type"] == "text" and i["role"] == "legend"]
    caption = [i["text"] for i in items if i["type"] == "text" and i["role"] == "caption"]

    # the picture's extent in its own metres
    xs, ys = [], []
    for slab in slabs:
        for ring in slab["rings"]:
            for px, py in ring:
                for z in (slab["z"], slab["z"] + slab["height"]):
                    sx, sy = _iso((px, py, z))
                    xs.append(sx)
                    ys.append(sy)
    for line in lines:
        for point in line["points"]:
            sx, sy = _iso(point)
            xs.append(sx)
            ys.append(sy)
    for label in labels:
        sx, sy = _iso(label["at"])
        wide = text_width(label["text"], label["size"])
        left = sx - wide * ANCHOR_SHIFT[label["anchor"]]
        xs += [left, left + wide]
        ys += [sy, sy - label["size"] * 1.2]
    if not xs:
        xs, ys = [0.0, 1.0], [0.0, 1.0]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    k = min((WIDTH - 2 * MARGIN) / max(x1 - x0, 1e-6), MAX_AXO_HEIGHT / max(y1 - y0, 1e-6))
    top = MARGIN + TITLE_PX * 1.8
    left = MARGIN + ((WIDTH - 2 * MARGIN) - (x1 - x0) * k) / 2  # centred when the height decides the scale

    def at(p):
        sx, sy = _iso(p)
        return left + (sx - x0) * k, top + (sy - y0) * k

    body = [_text_svg(MARGIN, MARGIN + TITLE_PX, title, TITLE_PX, weight=600)]
    body += [_line_svg(line, at) for line in lines]
    solids = _far_first([solid for slab in slabs for solid in _solids(slab)])
    move = f"translate({left - x0 * k:.2f} {top - y0 * k:.2f}) scale({k:.5f})"
    body.append(f'<g transform="{move}" stroke="{INK}" stroke-width="{0.7 / k:.4f}" stroke-linejoin="round" fill-rule="evenodd">')
    body += [f'<path d="{path}" fill="{color}" data-type="face"/>' for solid in solids for path, color in solid["faces"]]
    body.append("</g>")
    for label in labels:
        x, y = at(label["at"])
        body.append(_text_svg(x, y, label["text"], max(label["size"] * k, 9.0), label["anchor"]))
    y = top + (y1 - y0) * k + MARGIN
    for row in legend:
        body.append(f'<rect x="{MARGIN:.1f}" y="{y:.1f}" width="{WORD_PX:.1f}" height="{WORD_PX:.1f}" fill="{row["swatch"] or INK}" data-type="swatch"/>')
        body.append(_text_svg(MARGIN + WORD_PX * 1.6, y + WORD_PX * 0.85, row["text"], WORD_PX))
        y += WORD_PX * 1.7
    for text in caption:
        body.append(_text_svg(MARGIN, y + WORD_PX * 0.85, text, WORD_PX))
        y += WORD_PX * 1.7
    return _page(WIDTH, y + MARGIN - WORD_PX * 0.7, drawing["kind"], body)


def to_svg(drawing: dict) -> bytes:
    """The drawing as an SVG file (UTF-8)."""
    return _axo(drawing) if drawing["view"] == "axo" else _flat(drawing)
