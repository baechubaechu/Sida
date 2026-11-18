"""A site analysis diagram (site_diagrams.drawing) set on a sheet, as SVG.

One layout for every kind, so a set of them reads as one series: a 1000 px wide sheet with the
title, the range and the sheet's number on top, the map cut to its range (a circle or a box, as
wide as the sheet, with a thin frame), north and a scale bar on the map's corners, the legend in
columns under the map (each entry with its figure in grey) and the footer lines and sources last.
Fills of one kind are one path (their union, by the nonzero rule), what is not known is a 45°
hatch, and words on the map carry a white halo. Coordinates come in metres (x east, y north) and
are scaled so the map fills the sheet's width; line widths and letters are pixels on the sheet.
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from sida.experts.site import site_diagrams
from sida.experts.site.site_diagrams import HATCH, INK

WIDTH = 1000.0
TOP = 96.0  # px: the title block above the map
PAD = 32.0
FRAME = "#bdb8ad"
GREY, FAINT = "#77756f", "#9a978f"
NOTE = "#8a877f"
FONT = "'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif"
ROW = 32.0
COLUMNS = 3
BARS = (10, 20, 25, 40, 50, 100, 200, 250, 500)  # m a scale bar may span


def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


def _path(rings, at) -> str:
    return "".join("M" + "L".join(f"{_f(x)} {_f(y)}" for x, y in (at(p) for p in ring)) + "Z" for ring in rings)


def _swatch(entry: dict, x: float, y: float) -> str:
    color, mark = entry["color"], entry.get("mark") or "fill"
    if mark == "line":
        return f'<line x1="{_f(x)}" y1="{_f(y + 9)}" x2="{_f(x + 22)}" y2="{_f(y + 9)}" stroke="{color}" stroke-width="4" stroke-linecap="round"/>'
    if mark == "dot":
        return f'<circle cx="{_f(x + 10)}" cy="{_f(y + 9)}" r="6" fill="{color}"/>'
    fill = "url(#hatch)" if color == HATCH else color
    stroke = f' stroke="{entry["outline"]}"' if entry.get("outline") else ""
    return f'<rect x="{_f(x)}" y="{_f(y)}" width="20" height="18" rx="2" fill="{fill}"{stroke}/>'


def _scale(k: float) -> float:
    """The bar's length in m: the one nearest 160 px on the sheet."""
    return min(BARS, key=lambda m: abs(m * k - 160))


def to_svg(drawing: dict) -> bytes:
    """The drawing as an SVG file (UTF-8)."""
    x0, y0, x1, y1 = drawing["frame"]
    k = WIDTH / max(x1 - x0, 1e-6)
    map_h = (y1 - y0) * k
    bottom = TOP + map_h

    def at(p):
        return (p[0] - x0) * k, TOP + (y1 - p[1]) * k

    cx, cy, r = WIDTH / 2, TOP + map_h / 2, WIDTH / 2
    shape = drawing.get("shape")
    if shape == "circle":
        clip = f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}"/>'
        frame = f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r - 0.6)}" fill="none" stroke="{FRAME}" stroke-width="1.2"/>'
    else:
        clip = f'<rect x="0" y="{_f(TOP)}" width="{_f(WIDTH)}" height="{_f(map_h)}"/>'
        frame = (f'<rect x="0.6" y="{_f(TOP + 0.6)}" width="{_f(WIDTH - 1.2)}" height="{_f(map_h - 1.2)}" fill="none" '
                 f'stroke="{FRAME}" stroke-width="1.2"/>') if shape == "box" else ""

    body = []
    for layer in drawing["layers"]:
        if layer["type"] == "fill":
            fill = "url(#hatch)" if layer["color"] == HATCH else layer["color"]
            extra = f' fill-opacity="{layer["opacity"]:g}"' if layer.get("opacity") is not None else ""
            if layer.get("stroke"):
                extra += f' stroke="{layer["stroke"]}" stroke-width="{layer["width"]:g}" stroke-linejoin="round"'
                if layer.get("stroke_opacity") is not None:
                    extra += f' stroke-opacity="{layer["stroke_opacity"]:g}"'
                if layer.get("dashed"):
                    extra += ' stroke-dasharray="5 3"'
            d = "".join(_path(poly, at) for poly in layer["polygons"])
            body.append(f'<path d="{d}" fill="{fill}" fill-rule="nonzero"{extra}/>')
        elif layer["type"] == "line":
            dash = ' stroke-dasharray="6 4"' if layer.get("dashed") else ""
            alpha = f' stroke-opacity="{layer["opacity"]:g}"' if layer.get("opacity") is not None else ""
            d = "".join("M" + "L".join(f"{_f(x)} {_f(y)}" for x, y in (at(p) for p in run)) for run in layer["lines"])
            body.append(f'<path d="{d}" fill="none" stroke="{layer["color"]}" stroke-width="{layer["width"]:g}" '
                        f'stroke-linecap="round" stroke-linejoin="round"{dash}{alpha}/>')
        else:
            x, y = at(layer["at"])
            halo = ' stroke="#fff" stroke-width="3.5" stroke-linejoin="round" paint-order="stroke"' if layer.get("halo", True) else ""
            body.append(f'<text x="{_f(x)}" y="{_f(y)}" font-size="{layer["px"]:g}" font-weight="{layer["weight"]}" '
                        f'fill="{layer["color"]}" text-anchor="{layer["anchor"]}"{halo}>{escape(layer["text"])}</text>')

    out = [
        f'<rect width="{_f(WIDTH)}" height="HEIGHT" fill="#ffffff"/>',
        f'<text x="{_f(PAD)}" y="56" font-size="30" font-weight="700" fill="{INK}" letter-spacing="-0.5">{escape(drawing["title"])}</text>',
        f'<text x="{_f(PAD)}" y="82" font-size="14" fill="{GREY}">{escape(drawing.get("subtitle") or "")}</text>',
        f'<text x="{_f(WIDTH - PAD)}" y="56" font-size="30" font-weight="300" fill="#b9b5ab" text-anchor="end">{escape(drawing.get("number") or "")}</text>',
        f'<g clip-path="url(#map)">{"".join(body)}</g>',
        frame,
    ]
    if shape in ("circle", "box"):
        bar = _scale(k)
        cell = bar * k / 4
        bx, by = PAD, bottom - 36
        out.append(f'<g><rect x="{_f(bx - 10)}" y="{_f(by - 26)}" width="{_f(cell * 4 + 60)}" height="44" fill="#fff" opacity="0.85"/>'
                   + "".join(f'<rect x="{_f(bx + i * cell)}" y="{_f(by)}" width="{_f(cell)}" height="6" fill="{INK if i % 2 == 0 else "#fff"}" '
                             f'stroke="{INK}" stroke-width="1"/>' for i in range(4))
                   + f'<text x="{_f(bx)}" y="{_f(by - 8)}" font-size="13" fill="{INK}">0</text>'
                   f'<text x="{_f(bx + cell * 4)}" y="{_f(by - 8)}" font-size="13" fill="{INK}" text-anchor="middle">{bar:g}m</text></g>')
        out.append(f'<g transform="translate({_f(WIDTH - 52)},{_f(TOP + 44)})"><circle r="22" fill="#fff" opacity="0.85"/>'
                   f'<path d="M0 -16 L8 10 L0 5 L-8 10 Z" fill="{INK}"/>'
                   f'<text y="-24" font-size="13" font-weight="700" text-anchor="middle" fill="{INK}">N</text></g>')

    y = bottom + 34
    legend = drawing.get("legend") or []
    step = (WIDTH - 2 * PAD) / COLUMNS
    for i, entry in enumerate(legend):
        x = PAD + (i % COLUMNS) * step
        row = y + (i // COLUMNS) * ROW
        note = f'<tspan fill="{NOTE}" font-size="13">  {escape(entry["note"])}</tspan>' if entry.get("note") else ""
        out.append(_swatch(entry, x, row) + f'<text x="{_f(x + 30)}" y="{_f(row + 14)}" font-size="15" fill="{INK}" '
                   f'xml:space="preserve">{escape(entry["label"])}{note}</text>')
    y += ((len(legend) + COLUMNS - 1) // COLUMNS) * ROW + 12
    lines = list(drawing.get("footer") or [])
    for text in lines:
        out.append(f'<text x="{_f(PAD)}" y="{_f(y)}" font-size="12" fill="{FAINT}">{escape(text)}</text>')
        y += 18
    if drawing.get("sources"):
        out.append(f'<text x="{_f(WIDTH - PAD)}" y="{_f(y)}" font-size="12" fill="{FAINT}" text-anchor="end">'
                   f'자료: {escape(drawing["sources"])}</text>')
        y += 18
    height = y + 6
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(WIDTH)}" height="{_f(height)}" viewBox="0 0 {_f(WIDTH)} {_f(height)}" '
            f'font-family="{escape(FONT)}" data-kind="{escape(drawing["kind"])}">'
            f'<defs><clipPath id="map">{clip}</clipPath>'
            '<pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            '<rect width="7" height="7" fill="#efede8"/><line x1="0" y1="0" x2="0" y2="7" stroke="#c4c0b6" stroke-width="2"/></pattern></defs>')
    svg = head + "\n".join(out).replace('height="HEIGHT"', f'height="{_f(height)}"') + "</svg>"
    return svg.encode("utf-8")


def label(kind: str, mats: dict, choice: dict) -> str:
    """
    The words that name a diagram as chosen, as the screen names it (board-model siteDiagramLabel):
    "그림자 · 동지 12시 (좁게 300m)", "태양 궤적".
    """
    title = site_diagrams.KINDS[kind]
    if kind == "sun_path":
        return title
    scope = choice.get("range") if choice.get("range") in site_diagrams.RANGES else "default"
    side = site_diagrams.ranges(mats["around"], kind, mats.get("plan"))[scope]["side"]
    hour = ""
    if kind == "shadow":
        hour = f" {choice['hour']}시" if isinstance(choice.get("hour"), int) else " 9~15시"
    return f"{title}{hour} ({site_diagrams.RANGE_WORDS[scope]} {side}m)"


def bundle(mats: dict, choices: dict, *, year: int | None = None) -> tuple[bytes, list[str]]:
    """
    Every diagram that can be drawn here, each at its kept range (and the shadow at its hour), as
    SVG files in one zip, numbered as the sheets are: (zip bytes, the names in it). The kinds
    that cannot be drawn here are left out.
    """
    buffer = io.BytesIO()
    names = []
    ready = {a["kind"] for a in site_diagrams.available(mats["around"]) if a["ready"]}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for number, kind in enumerate(site_diagrams.KINDS, start=1):
            if kind not in ready:
                continue
            choice = choices.get(kind) or {}
            drawing = site_diagrams.drawing(kind, mats, choice.get("range") or "default", hour=choice.get("hour"), year=year)
            name = f"{number:02d} {label(kind, mats, choice)}.svg"
            archive.writestr(name, to_svg(drawing))
            names.append(name)
    return buffer.getvalue(), names
