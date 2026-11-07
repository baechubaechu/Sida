"""
Files for the laser and for the person putting the model together.

- `sheet_svg` / `sheet_dxf` / `sheets_pdf`: the sheets for the laser, in mm at true size, in
  the usual laser convention: engraving blue, cuts red, hairlines. The cuts come inner first
  (holes, and the outline of a piece that sits in a hole, innermost first), then the outer
  outlines, so nothing drops out before it is cut; the SVG keeps them as the groups engrave,
  inner and outer, the order the laser runs them. The DXF (AutoCAD 2013, mm, origin at the
  sheet's lower-left corner) has the layers CUT (red), ENGRAVE (blue) and SHEET (the sheet's
  outline and number, not printed), so every AutoCAD opens it as plain lines. The PDF has one
  page per sheet as vector paths, so Illustrator opens it as editable paths (and can save it as
  .ai). Each piece has its id (its layer) and a north arrow engraved in single-line strokes, so
  a cut piece says which layer it is and which way it faces.
- `guide_svg`: the same sheet for people, pieces filled by height and ids written large.
- `assembly_svg`: the finished model from above, every piece in its place with its id, the
  site outlined, roads, pavements and water shaded, buildings with their sheet counts, a north
  arrow and a scale bar.
- `piece_rows`: one row per piece (id, layer, height, sheet) for a list.
- `files` / `zip_files`: all of the above by file name, ready to save or send.
"""

from __future__ import annotations

import csv
import io
import math
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from shapely.geometry import Polygon

from sida.model_base.nesting import Layout, Placement
from sida.model_base.pieces import ModelPlan, Piece, _polygons
from sida.model_base.strokefont import strokes, text_width

COLORS = {"engrave": "#0000FF", "inner": "#FF0000", "outer": "#FF0000"}  # the laser convention
# DXF layer, ACI colour, true colour; lineweight 0 (hairline). SHEET is not printed.
DXF_LAYERS = {"engrave": ("ENGRAVE", 5, (0, 0, 255)), "cut": ("CUT", 1, (255, 0, 0)), "sheet": ("SHEET", 8, (128, 128, 128))}
FORMATS = ("dxf", "pdf", "svg")  # the laser files a zip can hold
HAIRLINE = 0.1  # mm in the SVG: lasers read the colour, not the width
PDF_HAIRLINE_PT = 0.001  # the thinnest stroke: Illustrator shows it as a hairline
PT_PER_MM = 72 / 25.4
SHEET_LABEL_MM = 2.5  # the sheet number's height, in the margin of a laid-out sheet
LOW, HIGH = (233, 228, 206), (104, 132, 86)  # guide fill from the lowest to the highest layer
AREA_STYLE = {"road": "#8a8f96", "sidewalk": "#b9a98f", "water": "#4f8fc0"}  # assembly map outlines
AREA_NAMES = {"road": "도로", "sidewalk": "인도", "water": "수계"}
BUILDING_FILL, ESTIMATE_FILL = "#c9c9c9", "#e2d3b4"  # measured height, floors × a storey height


def piece_fill(piece: Piece, layers: int) -> str:
    if piece.kind == "building":
        return ESTIMATE_FILL if piece.estimated else BUILDING_FILL
    return layer_fill(piece.layer, layers)


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


def cut_passes(layout: Layout, sheet: int) -> dict:
    """
    The sheet's lines by laser pass: engrave, inner (each closed cut inside another one, the
    deepest first) and outer (the rest). `depth` counts the cut lines around a line; layouts
    nest one deep, so it is 0, 1 (a hole) or 2 (a piece in a hole).
    """
    rings, engrave = [], []
    for p in layout.on_sheet(sheet):
        _, cuts, lines = _piece_geometry(p)
        rings += cuts
        engrave += [line for line in lines if len(line) > 1]
    areas = [Polygon(r) for r in rings]
    depth = []
    for i, poly in enumerate(areas):
        inside = poly.representative_point()
        depth.append(sum(1 for j, other in enumerate(areas) if j != i and other.area > poly.area and other.contains(inside)))
    inner = [r for _, r in sorted(((d, r) for d, r in zip(depth, rings, strict=True) if d > 0), key=lambda t: -t[0])]
    outer = [r for d, r in zip(depth, rings, strict=True) if d == 0]
    return {"engrave": engrave, "inner": inner, "outer": outer, "max_depth": max(depth, default=0)}


def sheet_svg(layout: Layout, sheet: int, colors: dict | None = None) -> str:
    c = {**COLORS, **(colors or {})}
    w, h = layout.sheet_w, layout.sheet_h
    flip = _flip(h)
    passes = cut_passes(layout, sheet)
    style = f'fill="none" stroke-width="{HAIRLINE}"'
    groups = []
    for name, closed in (("engrave", False), ("inner", True), ("outer", True)):  # the order the laser runs them
        paths = "\n".join(f'<path d="{_path(line, flip, closed=closed)}"/>' for line in passes[name])
        groups.append(f'<g id="{name}" {style} stroke="{c[name]}">\n{paths}\n</g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">\n'
            + "\n".join(groups) + "\n</svg>\n")


def parse_formats(value) -> tuple[str, ...]:
    """The laser formats asked for ("dxf,pdf" or a list), in FORMATS order. Raises ValueError for
    an unknown one or none."""
    items = value.split(",") if isinstance(value, str) else list(value or [])
    asked = {str(v).strip().lower() for v in items if str(v).strip()}
    unknown = asked - set(FORMATS)
    if unknown or not asked:
        raise ValueError(f"formats are some of {', '.join(FORMATS)}")
    return tuple(f for f in FORMATS if f in asked)


def sheet_label(layout: Layout, sheet: int) -> list[list[tuple[float, float]]]:
    """The sheet's number ("S3/21") in single-line strokes at its lower-left corner, in the margin."""
    return strokes(f"S{sheet + 1}/{layout.sheets}", 1.5, 1.2, SHEET_LABEL_MM)


def sheet_dxf(layout: Layout, sheet: int, path) -> None:
    """One sheet as DXF (AutoCAD 2013, mm, origin at the sheet's lower-left corner): engraving on
    ENGRAVE, then the cuts on CUT inner first, and the sheet's outline on SHEET. The sheet number
    is engraved in the margin of a laid-out sheet; a sheet cut in place (no margin: its layer
    covers the whole board) has it on SHEET, so the model's top stays unmarked."""
    import ezdxf

    doc = ezdxf.new("R2013", setup=True, units=4)  # 4 = millimetres
    doc.header["$MEASUREMENT"] = 1  # metric
    for name, aci, rgb in DXF_LAYERS.values():
        layer = doc.layers.add(name, color=aci)
        layer.rgb = rgb
        layer.dxf.lineweight = 0  # hairline
    doc.layers.get("SHEET").dxf.plot = 0
    msp = doc.modelspace()
    passes = cut_passes(layout, sheet)
    label_layer = "ENGRAVE" if layout.margin > 0 else "SHEET"
    label = sheet_label(layout, sheet)
    for line in passes["engrave"] + (label if label_layer == "ENGRAVE" else []):
        msp.add_lwpolyline(line, dxfattribs={"layer": "ENGRAVE"})
    for kind in ("inner", "outer"):  # the order the laser runs them
        for line in passes[kind]:
            msp.add_lwpolyline(line, close=True, dxfattribs={"layer": "CUT"})
    w, h = layout.sheet_w, layout.sheet_h
    msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True, dxfattribs={"layer": "SHEET"})
    for line in label if label_layer == "SHEET" else []:
        msp.add_lwpolyline(line, dxfattribs={"layer": "SHEET"})
    doc.saveas(path)


def _pdf_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return " ".join(f"{int(h[i:i + 2], 16) / 255:.3f}" for i in (0, 2, 4))


def sheets_pdf(layout: Layout, colors: dict | None = None) -> bytes:
    """Every sheet as a page of a vector PDF at true size (mm), in the laser colours with hairline
    strokes: engraving, then the cuts inner first. Illustrator opens the paths as they are."""
    import zlib

    c = {**COLORS, **(colors or {})}
    pages = []
    for n in range(layout.sheets):
        passes = cut_passes(layout, n)
        ops = [f"{PT_PER_MM:.6f} 0 0 {PT_PER_MM:.6f} 0 0 cm", f"{PDF_HAIRLINE_PT / PT_PER_MM:.6f} w", "1 J 1 j"]
        engrave = passes["engrave"] + (sheet_label(layout, n) if layout.margin > 0 else [])
        for kind, lines, closed in (("engrave", engrave, False), ("inner", passes["inner"], True),
                                    ("outer", passes["outer"], True)):
            if not lines:
                continue
            ops.append(f"{_pdf_color(c[kind])} RG")
            for line in lines:
                pts = [(round(x, 3), round(y, 3)) for x, y in line]
                ops.append(f"{pts[0][0]} {pts[0][1]} m " + " ".join(f"{x} {y} l" for x, y in pts[1:]) + (" h S" if closed else " S"))
        pages.append(zlib.compress("\n".join(ops).encode("ascii")))
    w, h = layout.sheet_w * PT_PER_MM, layout.sheet_h * PT_PER_MM
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               ("<< /Type /Pages /Kids [" + " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
                + f"] /Count {len(pages)} >>").encode("ascii")]
    for i, stream in enumerate(pages):
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:.3f} {h:.3f}] /Contents {4 + 2 * i} 0 R "
                       "/Resources << >> >>".encode("ascii"))
        objects.append(f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode("ascii") + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for k, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    out += b"".join(f"{o:010d} 00000 n \n".encode("ascii") for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    return bytes(out)


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
        out.append(f'<path d="{d}" fill="{piece_fill(p.piece, len(plan.layers))}" fill-rule="evenodd" stroke="#5b4a3a" stroke-width="0.3"/>')
        for line in p.piece.engrave:
            out.append(f'<path d="{_path(list(p.place(line).coords), flip)}" fill="none" stroke="#2b5d8a" stroke-width="0.25" stroke-dasharray="1.2 0.8"/>')
        x, y = flip(*p.place_point(p.piece.label_at))
        size = max(2.5, min(9, p.piece.label_room * 0.7))
        out.append(_text(x, y + size * 0.35, size, p.piece.id))
    total = sum(1 for _ in layout.on_sheet(sheet))
    out.append(_text(2, h + 10, 5, f"판 {sheet + 1}/{layout.sheets} · 조각 {total}개 · {w:g}×{h:g} mm · 색이 진할수록 높은 층 · 점선: 새김선(다음 층·대지 경계·도로 등) · 레이저 순서: 새김(파랑) → 안쪽 자르기 → 바깥 자르기(빨강)", anchor="start", weight="400"))
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
    for piece in sorted((q for q in plan_pieces(layout) if q.kind == "ground"), key=lambda q: q.layer):
        d = " ".join(_path(r, flip, closed=True) for poly in _polygons(piece.shape) for r in _rings(poly))
        out.append(f'<path d="{d}" fill="{layer_fill(piece.layer, len(plan.layers))}" fill-rule="evenodd" stroke="#5b4a3a" stroke-width="0.25"/>')
    for fp in plan.footprints_mm:  # height not known: engraved outline only
        out.append(f'<path d="{_path(list(fp.exterior.coords), flip, closed=True)}" fill="none" stroke="#8a6a3a" stroke-width="0.3" stroke-dasharray="1 0.8"/>')
    for b in plan.buildings:
        d = " ".join(_path(r, flip, closed=True) for r in _rings(b.footprint))
        out.append(f'<path d="{d}" fill="{ESTIMATE_FILL if b.estimated else BUILDING_FILL}" fill-rule="evenodd" stroke="#4a4a4a" stroke-width="0.3"/>')
    for kind, shape in plan.areas_mm:
        d = " ".join(_path(r, flip, closed=True) for poly in _polygons(shape) for r in _rings(poly))
        if d:
            out.append(f'<path d="{d}" fill="{AREA_STYLE[kind]}" fill-opacity="0.22" fill-rule="evenodd" '
                       f'stroke="{AREA_STYLE[kind]}" stroke-width="0.35"/>')
    for poly in _polygons(plan.site_mm) if plan.site_mm is not None else []:
        out.append(f'<path d="{_path(list(poly.exterior.coords), flip, closed=True)}" fill="none" stroke="#cf3f2e" stroke-width="0.8" stroke-dasharray="3 1.5"/>')
    if len(plan.modules) > 1:  # where the model comes apart, and which module is which
        for n, module in enumerate(plan.modules, start=1):
            out.append(f'<path d="{_path(list(module.exterior.coords), flip, closed=True)}" fill="none" stroke="#20262d" stroke-width="1.2"/>')
            mx0, _, _, my1 = module.bounds
            x, y = flip(mx0 + 4, my1 - 4)
            out.append(f'<circle cx="{x + 5}" cy="{y + 5}" r="5" fill="#20262d"/>')
            out.append(_text(x + 5, y + 7, 6, str(n), fill="#ffffff"))
    for b in plan.buildings:
        x, y = flip(*b.footprint.representative_point().coords[0])
        out.append(_text(x, y + 1, 2.6, f"{b.id}×{b.sheets}", weight="500"))
    for piece in plan_pieces(layout):
        if piece.kind == "building":
            continue
        x, y = flip(*piece.show_at)
        size = max(3.2, min(7, piece.show_room * 0.8))
        out.append(_text(x, y + size * 0.35, size, f"{piece.id}·{sheet_of[piece.id]}"))
    nx, ny = pad + w - 6, pad + 10
    out.append(f'<path d="M{nx},{ny - 7} L{nx + 3},{ny + 2} L{nx},{ny} L{nx - 3},{ny + 2} Z" fill="#20262d"/>')
    out.append(_text(nx, ny - 9, 4, "N"))
    bar = 20 * 1000 / plan.scale  # 20 m
    out.append(f'<path d="M{pad},{h + pad + 8} h{bar}" stroke="#20262d" stroke-width="0.8"/>')
    out.append(_text(pad + bar / 2, h + pad + 13, 3.5, "20 m", weight="400"))
    example = "1-03B·2 = 1번 모듈 3층 B 조각, 2번 판" if len(plan.modules) > 1 else "03B·2 = 3층 B 조각, 2번 판"
    modules = f" · 모듈 {len(plan.modules)}개(굵은 선에서 나뉨)" if len(plan.modules) > 1 else ""
    kinds = [AREA_NAMES[kind] for kind, _ in plan.areas_mm]
    areas = f" · 새김선: {'·'.join(kinds)} 경계" if kinds else ""
    if plan.buildings:
        areas += " · 건물 B07×5 = 7번 건물 5장 쌓기(회색 측정 높이, 베이지 추정 높이)"
    if plan.footprints_mm:
        areas += " · 점선: 높이 미확인 건물(바닥선만 새김)"
    out.append(_text(pad, h + pad + 20, 4, f"조립도 1:{plan.scale} · 판 두께 {plan.thickness_mm:g} mm = 등고 {plan.interval_m:g} m{modules}{areas} · 조각 이름·판 번호 (예: {example})", anchor="start", weight="400"))
    out.append("</svg>\n")
    return "\n".join(out)


def plan_pieces(layout: Layout) -> list[Piece]:
    return [p.piece for p in layout.placements]


def piece_rows(layout: Layout) -> list[dict]:
    return [
        {"id": p.piece.id, "kind": p.piece.kind, "module": p.piece.module, "layer": p.piece.layer,
         "level_m": p.piece.level_m, "sheet": p.sheet + 1, "area_mm2": round(p.piece.area, 1),
         "label_hidden": p.piece.label_hidden, "estimated": p.piece.estimated}
        for p in sorted(layout.placements, key=lambda q: (q.piece.module, q.piece.layer, q.piece.id))
    ]



def files(plan: ModelPlan, layout: Layout, colors: dict | None = None,
          formats: tuple[str, ...] = FORMATS) -> dict[str, bytes]:
    """Every file of a cutting layout by name: per sheet the laser files in `formats` (DXF, SVG;
    the PDF holds every sheet, sheets.pdf) and the guide, then assembly.svg and pieces.csv
    (UTF-8 with a BOM, so Excel reads the Korean)."""
    out: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as folder:
        for n in range(layout.sheets):
            if "svg" in formats:
                out[f"sheet-{n + 1}.svg"] = sheet_svg(layout, n, colors).encode("utf-8")
            out[f"sheet-{n + 1}-guide.svg"] = guide_svg(layout, n, plan).encode("utf-8")
            if "dxf" in formats:
                path = Path(folder) / f"sheet-{n + 1}.dxf"
                sheet_dxf(layout, n, path)
                out[path.name] = path.read_bytes()
    if "pdf" in formats:
        out["sheets.pdf"] = sheets_pdf(layout, colors)
    out["assembly.svg"] = assembly_svg(plan, layout).encode("utf-8")
    rows = piece_rows(layout)
    text = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(text, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    out["pieces.csv"] = ("\ufeff" + text.getvalue()).encode("utf-8")
    return out


def zip_files(named: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in named.items():
            z.writestr(name, data)
    return buffer.getvalue()
