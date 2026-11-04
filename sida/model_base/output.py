"""
Files for the laser and for the person putting the model together.

- `sheet_svg` / `sheet_dxf`: one sheet for the laser, in mm. Cut lines red, engraved lines
  blue (the colours most laser shops map to cut and score; change them with `colors`). Each
  piece has its id and a north arrow engraved, so a cut piece says which layer it is and which
  way it faces.
- `guide_svg`: the same sheet for people, pieces filled by height and ids written large.
- `assembly_svg`: the finished model from above, every piece in its place with its id, the
  site outlined, a north arrow and a scale bar.
- `piece_rows`: one row per piece (id, layer, height, sheet) for a list.
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

from shapely.geometry import Polygon

from sida.model_base.nesting import Layout, Placement
from sida.model_base.pieces import ModelPlan, Piece, _polygons
from sida.model_base.strokefont import strokes, text_width

CUT = "#FF0000"
ENGRAVE = "#0000FF"
COLORS = {"cut": CUT, "engrave": ENGRAVE}
HAIRLINE = 0.1  # mm: lasers read the colour, not the width
LOW, HIGH = (233, 228, 206), (104, 132, 86)  # guide fill from the lowest to the highest layer


def _rings(poly: Polygon):
    yield list(poly.exterior.coords)
    for r in poly.interiors:
        yield list(r.coords)


def layer_fill(layer: int, layers: int) -> str:
    t = layer / max(1, layers - 1)
    r, g, b = (round(a + (b - a) * t) for a, b in zip(LOW, HIGH, strict=True))
    return f"#{r:02x}{g:02x}{b:02x}"


def label_strokes(piece: Piece, placement: Placement | None = None) -> list[list[tuple[float, float]]]:
    """The id and a north arrow, upright on the sheet, sized to the room around the label spot."""
    cx, cy = placement.place_point(piece.label_at) if placement else piece.label_at
    text = piece.id
    # The id and the arrow beside it must fit inside the free circle around the spot.
    height = 4.0
    while height > 1.2 and math.hypot(text_width(text, height) + height, height) > 1.8 * piece.label_room:
        height -= 0.2
    width = text_width(text, height)
    arrow = height * 0.9
    total = width + arrow * 1.1
    x = cx - total / 2
    y = cy - height / 2
    lines = strokes(text, x, y, height)
    # North arrow: points to the ground's north, which turns with the piece.
    a = math.radians(placement.angle if placement else 0)
    ax, ay = x + width + arrow * 0.75, cy
    tip = (ax - math.sin(a) * arrow / 2, ay + math.cos(a) * arrow / 2)
    tail = (ax + math.sin(a) * arrow / 2, ay - math.cos(a) * arrow / 2)
    left = (tip[0] - math.sin(a + 2.6) * arrow * 0.45, tip[1] + math.cos(a + 2.6) * arrow * 0.45)
    right = (tip[0] - math.sin(a - 2.6) * arrow * 0.45, tip[1] + math.cos(a - 2.6) * arrow * 0.45)
    lines += [[tail, tip], [left, tip, right]]
    return lines


def _flip(h: float):
    return lambda x, y: (round(x, 3), round(h - y, 3))  # SVG y runs down


def _path(points, flip, closed=False) -> str:
    pts = [flip(x, y) for x, y in points]
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    return d + (" Z" if closed else "")


def _piece_geometry(p: Placement):
    shape = p.place(p.piece.shape)
    cuts = [ring for poly in _polygons(shape) for ring in _rings(poly)]
    engrave = [list(p.place(line).coords) for line in p.piece.engrave if not line.is_empty]
    return shape, cuts, engrave + label_strokes(p.piece, p)


def sheet_svg(layout: Layout, sheet: int, colors: dict | None = None) -> str:
    c = {**COLORS, **(colors or {})}
    w, h = layout.sheet_w, layout.sheet_h
    flip = _flip(h)
    cut_paths, engrave_paths = [], []
    for p in layout.on_sheet(sheet):
        _, cuts, engrave = _piece_geometry(p)
        cut_paths += [_path(r, flip, closed=True) for r in cuts]
        engrave_paths += [_path(line, flip) for line in engrave if len(line) > 1]
    style = f'fill="none" stroke-width="{HAIRLINE}"'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">\n'
        f'<g id="engrave" {style} stroke="{c["engrave"]}">\n' + "\n".join(f'<path d="{d}"/>' for d in engrave_paths) + "\n</g>\n"
        f'<g id="cut" {style} stroke="{c["cut"]}">\n' + "\n".join(f'<path d="{d}"/>' for d in cut_paths) + "\n</g>\n</svg>\n"
    )


def sheet_dxf(layout: Layout, sheet: int, path) -> None:
    import ezdxf

    doc = ezdxf.new("R2013", setup=True, units=4)  # 4 = millimetres
    doc.layers.add("CUT", color=1)  # red
    doc.layers.add("ENGRAVE", color=5)  # blue
    msp = doc.modelspace()
    for p in layout.on_sheet(sheet):
        _, cuts, engrave = _piece_geometry(p)
        for ring in cuts:
            msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": "CUT"})
        for line in engrave:
            if len(line) > 1:
                msp.add_lwpolyline(line, dxfattribs={"layer": "ENGRAVE"})
    doc.saveas(path)


def _text(x, y, size, text, anchor="middle", weight="600", fill="#20262d") -> str:
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size:.2f}" text-anchor="{anchor}" font-weight="{weight}" '
            f'fill="{fill}" font-family="IBM Plex Sans KR, Malgun Gothic, sans-serif">{escape(text)}</text>')


def guide_svg(layout: Layout, sheet: int, plan: ModelPlan) -> str:
    w, h = layout.sheet_w, layout.sheet_h
    flip = _flip(h)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h + 16}">',
           f'<rect x="0" y="0" width="{w}" height="{h}" fill="#f6f4ee" stroke="#9aa3ad" stroke-width="0.4"/>']
    for p in layout.on_sheet(sheet):
        shape, cuts, _ = _piece_geometry(p)
        d = " ".join(_path(r, flip, closed=True) for r in cuts)
        out.append(f'<path d="{d}" fill="{layer_fill(p.piece.layer, len(plan.layers))}" fill-rule="evenodd" stroke="#5b4a3a" stroke-width="0.3"/>')
        for line in p.piece.engrave:
            out.append(f'<path d="{_path(list(p.place(line).coords), flip)}" fill="none" stroke="#2b5d8a" stroke-width="0.25" stroke-dasharray="1.2 0.8"/>')
        x, y = flip(*p.place_point(p.piece.label_at))
        size = max(2.5, min(9, p.piece.label_room * 0.7))
        out.append(_text(x, y + size * 0.35, size, p.piece.id))
    total = sum(1 for _ in layout.on_sheet(sheet))
    out.append(_text(2, h + 10, 5, f"판 {sheet + 1}/{layout.sheets} · 조각 {total}개 · {w:g}×{h:g} mm · 색이 진할수록 높은 층 · 점선: 다음 층·대지 경계 새김선", anchor="start", weight="400"))
    out.append("</svg>\n")
    return "\n".join(out)


def assembly_svg(plan: ModelPlan, layout: Layout) -> str:
    """The finished model from above: every piece where it goes, highest on top."""
    w, h = plan.size_mm
    pad = 14
    flip = lambda x, y: (round(x + pad, 3), round(h - y + pad, 3))  # noqa: E731
    sheet_of = {p.piece.id: p.sheet + 1 for p in layout.placements}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 2 * pad}mm" height="{h + 2 * pad + 24}mm" viewBox="0 0 {w + 2 * pad} {h + 2 * pad + 24}">',
           f'<rect width="{w + 2 * pad}" height="{h + 2 * pad + 24}" fill="#ffffff"/>']
    for piece in sorted(plan_pieces(layout), key=lambda q: q.layer):
        d = " ".join(_path(r, flip, closed=True) for poly in _polygons(piece.shape) for r in _rings(poly))
        out.append(f'<path d="{d}" fill="{layer_fill(piece.layer, len(plan.layers))}" fill-rule="evenodd" stroke="#5b4a3a" stroke-width="0.25"/>')
    if plan.site_mm is not None:
        out.append(f'<path d="{_path(list(plan.site_mm.exterior.coords), flip, closed=True)}" fill="none" stroke="#cf3f2e" stroke-width="0.8" stroke-dasharray="3 1.5"/>')
    for piece in plan_pieces(layout):
        x, y = flip(*piece.show_at)
        size = max(3.2, min(7, piece.show_room * 0.8))
        out.append(_text(x, y + size * 0.35, size, f"{piece.id}·{sheet_of[piece.id]}"))
    nx, ny = pad + w - 6, pad + 10
    out.append(f'<path d="M{nx},{ny - 7} L{nx + 3},{ny + 2} L{nx},{ny} L{nx - 3},{ny + 2} Z" fill="#20262d"/>')
    out.append(_text(nx, ny - 9, 4, "N"))
    bar = 20 * 1000 / plan.scale  # 20 m
    out.append(f'<path d="M{pad},{h + pad + 8} h{bar}" stroke="#20262d" stroke-width="0.8"/>')
    out.append(_text(pad + bar / 2, h + pad + 13, 3.5, "20 m", weight="400"))
    out.append(_text(pad, h + pad + 20, 4, f"조립도 1:{plan.scale} · 판 두께 {plan.thickness_mm:g} mm = 등고 {plan.interval_m:g} m · 조각 이름·판 번호 (예: 03B·2 = 3층 B 조각, 2번 판)", anchor="start", weight="400"))
    out.append("</svg>\n")
    return "\n".join(out)


def plan_pieces(layout: Layout) -> list[Piece]:
    return [p.piece for p in layout.placements]


def piece_rows(layout: Layout) -> list[dict]:
    return [
        {"id": p.piece.id, "layer": p.piece.layer, "level_m": p.piece.level_m, "sheet": p.sheet + 1,
         "tile": p.piece.tile, "area_mm2": round(p.piece.area, 1), "label_hidden": p.piece.label_hidden}
        for p in sorted(layout.placements, key=lambda q: (q.piece.layer, q.piece.id))
    ]

