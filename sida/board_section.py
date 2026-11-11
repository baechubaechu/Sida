"""A section (단면) through the drawing table, and its drawing as SVG, PDF or DXF.

Independent of HTTP and of the screen. A section paper (board.py, kind "section") holds a line
across the site in the table's metres (x east, y north, the site's middle at 0, 0), the side it
looks toward (`flip`), how far beyond the cut the drawing shows (`depth`) and the scale it is
printed at. `cut` turns the line and what stands on the table into the section, by the same rules
the screen uses (webui/app/section-model.js sectionCut):

- The line runs from its first point (A) to its second (A′); `s` is the distance along it. It
  looks to its right (from A toward A′), or to its left when flipped. Drawn as the viewer sees it,
  the right of the drawing is the viewer's right, so a section looking to the right of its line
  reads from A′ on the left to A on the right.
- The ground is the surroundings' height grid read every PROFILE_STEP metres along the line (and
  at its end); off the grid it is left out, so the profile may come in runs.
- A solid (a block of the scheme, a building around) whose footprint the line crosses is cut where
  the line runs inside it. One the line misses but that stands wholly on the looked-at side, no
  further than `depth`, is seen beyond the cut, over the stretch of the line it stands in front of.
- Heights are the table's: a block stands on the lowest ground under it (board_export.mass_base)
  and rises its floors × the floor height; a building runs from the bottom of its foundation to
  its roof. 0 is the ground at the site's middle.

`section_drawing` lays the section out for a file: the cut ground and solids filled, what is seen
beyond as lines with the hidden parts taken away (nearer solids and the ground hide them), floor
lines on the cut blocks, heights, the A and A′ marks and a scale bar. The SVG and PDF are at the
paper's scale in millimetres; the DXF is 1:1 in metres (x along the section from its left end,
y the height), with text sized to read at the paper's scale when plotted.

The section takes the scheme shown in 3D (`active`, else the first on the table). Buildings come
from the site domain's `board_surroundings` hook: only what a file may hold (map files, not
VWorld), and not the building standing on the site now, which the scheme takes the place of.
"""

from __future__ import annotations

import io
import math
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

from sida import board, board_export

PROFILE_STEP = 1.0  # metres between ground heights read along the line
MIN_SPAN = 0.05  # a cut or a view narrower than this (m) is left out
FORMATS = ("svg", "pdf", "dxf")
MEDIA_TYPES = {"svg": "image/svg+xml", "pdf": "application/pdf", "dxf": "application/dxf"}
MARGIN_MM = 12.0
TEXT_MM = 2.5  # the height of the drawing's labels on paper
TITLE_MM = 3.5
BELOW_M = 6.0  # how far the ground's cut goes below the lowest ground on the line
PT_PER_MM = 72 / 25.4
INK = (32, 38, 45)
GROUND = (138, 146, 155)
NEAR = (93, 102, 112)
BEYOND = (120, 128, 136)
# DXF layers: name, ACI colour, true colour
DXF_LAYERS = {
    "ground": ("단면-지형", 8, GROUND), "mass": ("단면-매스", 7, INK), "floors": ("단면-층선", 9, (200, 200, 200)),
    "building": ("단면-주변", 8, NEAR), "beyond": ("단면-뒤쪽", 9, BEYOND), "notes": ("단면-표기", 7, INK),
}


# ---------------------------------------------------------------------------
# The cut
# ---------------------------------------------------------------------------


def line_frame(line, flip: bool = False) -> dict:
    """Length, direction `d`, the looked-toward side `n` (unit vectors) and whether the drawing
    reads from A′ to A (`mirror`)."""
    (x0, y0), (x1, y1) = line
    length = math.hypot(x1 - x0, y1 - y0)
    if length <= 0:
        raise ValueError("a section line needs two different points")
    d = ((x1 - x0) / length, (y1 - y0) / length)
    n = (d[1], -d[0])  # right of the line, walking from A to A′
    if flip:
        n = (-n[0], -n[1])
    right = (n[1], -n[0])  # the viewer's right, facing n
    return {"length": length, "d": d, "n": n, "mirror": d[0] * right[0] + d[1] * right[1] < 0}


def ground_height(ground: dict | None, x: float, y: float) -> float | None:
    """The ground's height at (x, y) (board_export surface form); None off it (or outside a round range)."""
    if not ground:
        return None
    clip = ground.get("clip_radius")
    if clip is not None and math.hypot(x, y) > clip + 1e-9:
        return None
    return board_export.ground_at(ground, x, y)


def _inside(x: float, y: float, ring) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, list(ring[1:]) + list(ring[:1]), strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def spans(p0, d, length: float, ring) -> list[tuple[float, float]]:
    """Where the line p0 + s·d (0 ≤ s ≤ length) runs inside the polygon `ring`: [(a, b)]."""
    cuts = {0.0, length}
    for (x1, y1), (x2, y2) in zip(ring, list(ring[1:]) + list(ring[:1]), strict=True):
        ex, ey = x2 - x1, y2 - y1
        den = d[0] * ey - d[1] * ex
        if abs(den) < 1e-12:
            continue
        wx, wy = x1 - p0[0], y1 - p0[1]
        s = (wx * ey - wy * ex) / den
        t = (wx * d[1] - wy * d[0]) / den
        if -1e-9 <= t <= 1 + 1e-9 and 0 < s < length:
            cuts.add(s)
    marks = sorted(cuts)
    out: list[list[float]] = []
    for a, b in zip(marks, marks[1:], strict=False):
        if b - a < 1e-9:
            continue
        m = (a + b) / 2
        if _inside(p0[0] + d[0] * m, p0[1] + d[1] * m, ring):
            if out and abs(out[-1][1] - a) < 1e-9:
                out[-1][1] = b
            else:
                out.append([a, b])
    return [(a, b) for a, b in out]


def profile(line, ground: dict | None, length: float, d) -> list[list[list[float]]]:
    """The ground along the line as runs of [s, z] (a gap where the ground is not known)."""
    if not ground:
        return []
    p0 = line[0]
    steps = max(1, math.ceil(length / PROFILE_STEP - 1e-9))
    runs: list[list[list[float]]] = []
    run: list[list[float]] = []
    for k in range(steps + 1):
        s = min(length, k * PROFILE_STEP)
        z = ground_height(ground, p0[0] + d[0] * s, p0[1] + d[1] * s)
        if z is None:
            if run:
                runs.append(run)
            run = []
            continue
        run.append([round(s, 3), round(z, 3)])
    if run:
        runs.append(run)
    return [r for r in runs if len(r) >= 2]


def cut(line, solids: list[dict], ground: dict | None, *, flip: bool = False, depth: float = board.DEFAULT_SECTION_DEPTH) -> dict:
    """
    The section along `line`: {length, mirror, profile, cut, beyond}. `solids` are
    {outline, base, top, kind ("mass" or "building"), ...}; each cut or seen one comes back with
    its stretch of the line [a, b] (metres from A) and its other fields. `beyond` is far first.
    """
    f = line_frame(line, flip)
    length, d, n = f["length"], f["d"], f["n"]
    p0 = line[0]
    out_cut, out_beyond = [], []
    for solid in solids:
        ring = solid["outline"]
        pieces = [(a, b) for a, b in spans(p0, d, length, ring) if b - a > MIN_SPAN]
        if pieces:
            out_cut += [{**solid, "a": round(a, 3), "b": round(b, 3)} for a, b in pieces]
            continue
        dist = [(x - p0[0]) * n[0] + (y - p0[1]) * n[1] for x, y in ring]
        if min(dist) < 0 or min(dist) > depth:
            continue
        along = [(x - p0[0]) * d[0] + (y - p0[1]) * d[1] for x, y in ring]
        a, b = max(0.0, min(along)), min(length, max(along))
        if b - a > MIN_SPAN:
            out_beyond.append({**solid, "a": round(a, 3), "b": round(b, 3), "dist": round(min(dist), 3)})
    out_beyond.sort(key=lambda x: -x["dist"])
    return {"length": round(length, 3), "mirror": f["mirror"], "profile": profile(line, ground, length, d),
            "cut": out_cut, "beyond": out_beyond}


def summary(result: dict) -> dict:
    """What a section shows in numbers: the ground's low and high on the line, the cut blocks'
    tops and the tallest cut building."""
    zs = [z for run in result["profile"] for _, z in run]
    masses = [c for c in result["cut"] if c["kind"] == "mass"]
    buildings = [c for c in result["cut"] if c["kind"] == "building"]
    tall = max(buildings, key=lambda c: c["top"] - c.get("ground", c["base"]), default=None)
    return {
        "length_m": result["length"],
        "ground_low": round(min(zs), 2) if zs else None,
        "ground_high": round(max(zs), 2) if zs else None,
        "mass_tops": [round(c["top"], 2) for c in masses],
        "buildings_cut": len(buildings),
        "tallest_building_top": round(tall["top"], 2) if tall else None,
    }


# ---------------------------------------------------------------------------
# From the project
# ---------------------------------------------------------------------------


def _surroundings(project_path: Path, hooks) -> dict | None:
    for _domain, module in hooks:
        give = getattr(module, "board_surroundings", None)
        if give is None:
            continue
        got = give(Path(project_path))
        if got:
            return got
    return None


def section_of(project_path: Path, paper_id: str, *, active: str | None = None, hooks=None) -> dict:
    """
    The section paper `paper_id` cut through the table: {paper, scheme (its name or ""), result}.
    Raises board.PaperNotFound for no such paper and ValueError when it is not a section or
    `active` is not a scheme on the table.
    """
    from sida.experts import domain_hooks

    hooks = domain_hooks() if hooks is None else hooks
    saved = board.load_board(project_path)
    paper = next((p for p in saved["papers"] if p["id"] == paper_id), None)
    if paper is None:
        raise board.PaperNotFound(paper_id)
    if paper.get("kind") != "section":
        raise ValueError(f"not a section: {paper_id}")
    masses = [p for p in saved["papers"] if p.get("kind") == "mass"]
    if active and not any(p["id"] == active for p in masses):
        raise ValueError(f"not a massing scheme on the table: {active}")
    scheme = next((p for p in masses if p["id"] == active), None) if active else (masses[0] if masses else None)
    around = _surroundings(project_path, hooks) or {}
    ground = around.get("ground")
    summary_ = board.site_summary(project_path, hooks)
    plan = board.site_plan((summary_ or {}).get("parcels") or [])
    frame = (plan or {}).get("frame")
    solids = []
    if scheme:
        storey = float(scheme.get("floor_height") or board.DEFAULT_FLOOR_HEIGHT)
        for i, block in enumerate(scheme.get("blocks") or []):
            outline = board_export.block_outline(frame, block)
            base = board_export.mass_base(outline, ground)
            solids.append({"kind": "mass", "outline": outline, "base": base, "top": round(base + block["floors"] * storey, 3),
                           "floors": int(block["floors"]), "storey": storey, "name": f"{i + 1}동"})
    for b in around.get("buildings") or []:
        if b.get("on_site"):  # the building standing on the site now: the scheme takes its place
            continue
        solids.append({"kind": "building", "outline": b["outline"], "base": b["base"], "top": round(b["base"] + b["height"], 3),
                       "estimate": bool(b.get("estimate"))})
    result = cut(paper["line"], solids, ground, flip=bool(paper.get("flip")), depth=float(paper.get("depth", board.DEFAULT_SECTION_DEPTH)))
    return {"paper": paper, "scheme": board.paper_name(scheme) if scheme else "", "result": result,
            "ground_known": ground is not None}


# ---------------------------------------------------------------------------
# The drawing
# ---------------------------------------------------------------------------


def _cover(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _minus(a: float, b: float, covers: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[a, b] less the covered stretches."""
    out, at = [], a
    for c0, c1 in covers:
        if c1 <= at or c0 >= b:
            continue
        if c0 > at:
            out.append((at, c0))
        at = max(at, c1)
    if at < b:
        out.append((at, b))
    return [(x, y) for x, y in out if y - x > 1e-6]


def _ground_z(runs, s: float) -> float | None:
    """The ground's height at `s` on runs of [s, z] (sorted by s); None in a gap."""
    for run in runs:
        if run[0][0] - 1e-9 <= s <= run[-1][0] + 1e-9:
            for (s0, z0), (s1, z1) in zip(run, run[1:], strict=False):
                if s0 - 1e-9 <= s <= s1 + 1e-9:
                    return z0 if s1 == s0 else z0 + (z1 - z0) * (s - s0) / (s1 - s0)
    return None


def _seen(segment, horizontal: bool, nearer, runs) -> list[list[list[float]]]:
    """The parts of an edge of a solid seen beyond the cut that nothing nearer hides: `nearer` are
    boxes (x0, x1, z0, z1) in front of it, and the cut ground hides what is under its line."""
    (x0, y0), (x1, y1) = segment
    if horizontal:
        covers = _cover([(max(x0, bx0), min(x1, bx1)) for bx0, bx1, bz0, bz1 in nearer
                         if bz0 < y0 < bz1 and bx0 < x1 and bx1 > x0])
        return [[[p, y0], [q, y0]] for p, q in _minus(x0, x1, covers)
                if (g := _ground_z(runs, (p + q) / 2)) is None or y0 > g]
    covers = _cover([(max(y0, bz0), min(y1, bz1)) for bx0, bx1, bz0, bz1 in nearer
                     if bx0 < x0 < bx1 and bz0 < y1 and bz1 > y0])
    g = _ground_z(runs, x0)
    start = max(y0, g) if g is not None else y0
    return [[[x0, p], [x0, q]] for p, q in _minus(start, y1, covers)]


def section_drawing(found: dict) -> dict:
    """
    The section laid out in its own metres: x along the drawing from its left end, y the height
    (0 = the ground at the site's middle). {width, low, high, scale, fills: [{part, points}],
    lines: [{part, points, dashed}], texts: [{at, text, plain, size, anchor}]} — `plain` is the
    same text in Latin letters for the PDF, whose fonts have no Hangul.
    """
    paper, result = found["paper"], found["result"]
    length, mirror = result["length"], result["mirror"]
    scale = int(paper.get("scale") or board.DEFAULT_SECTION_SCALE)
    name = paper.get("title") or "A"
    u = (lambda s: length - s) if mirror else (lambda s: s)  # noqa: E731
    runs = [[[u(s), z] for s, z in run] for run in result["profile"]]
    runs = [sorted(r) for r in runs]
    zs = [z for r in runs for _, z in r]
    tops = [c["top"] for c in result["cut"] + result["beyond"]]
    bases = [c["base"] for c in result["cut"]]
    low = min([0.0, *zs, *bases]) - BELOW_M
    high = max([0.0, *zs, *tops]) + 4.0
    fills, lines, texts = [], [], []
    m_per_mm = scale / 1000

    def text(at, words, plain=None, size=TEXT_MM, anchor="start"):
        texts.append({"at": [round(at[0], 3), round(at[1], 3)], "text": words, "plain": plain if plain is not None else words,
                      "size": size, "anchor": anchor})

    def box(c):
        a, b = sorted((u(c["a"]), u(c["b"])))
        return a, b

    # what hides lines seen beyond: the cut solids, nearer solids beyond, and the ground
    solid_boxes = [(*box(c), c["base"], c["top"]) for c in result["cut"]]
    beyond = result["beyond"]  # far first
    for k, c in enumerate(beyond):
        a, b = box(c)
        nearer = solid_boxes + [(*box(x), x["base"], x["top"]) for x in beyond[k + 1:]]
        for seg, horizontal in (([[a, c["top"]], [b, c["top"]]], True), ([[a, c["base"]], [a, c["top"]]], False),
                                ([[b, c["base"]], [b, c["top"]]], False)):
            for piece in _seen(seg, horizontal, nearer, runs):
                lines.append({"part": "beyond", "points": piece, "dashed": bool(c.get("estimate"))})
    for r in runs:
        fills.append({"part": "ground", "points": [[r[0][0], low], *r, [r[-1][0], low]]})
        lines.append({"part": "ground", "points": r, "dashed": False, "weight": 2})
    for c in result["cut"]:
        a, b = box(c)
        rect = [[a, c["base"]], [b, c["base"]], [b, c["top"]], [a, c["top"]]]
        if c["kind"] == "mass":
            fills.append({"part": "mass", "points": rect})
            for f in range(1, int(c.get("floors") or 0)):
                z = c["base"] + f * c["storey"]
                lines.append({"part": "floors", "points": [[a, z], [b, z]], "dashed": False})
        else:
            fills.append({"part": "building", "points": rect, "light": bool(c.get("estimate"))})
            if c.get("estimate"):
                lines.append({"part": "building", "points": [*rect, rect[0]], "dashed": True})
                text([(a + b) / 2, c["top"] + 1.2 * m_per_mm], "추정", "est.", TEXT_MM * 0.8, "middle")
    # ±0, the masses' heights, A and A′, the scale bar and the title
    lines.append({"part": "notes", "points": [[-3 * m_per_mm, 0.0], [length + 3 * m_per_mm, 0.0]], "dashed": True})
    text([-4 * m_per_mm, -0.8 * m_per_mm], "±0", "+-0", TEXT_MM, "end")
    for c in [x for x in result["cut"] if x["kind"] == "mass"]:
        _a, b = box(c)
        x = b + 3 * m_per_mm
        height = c["top"] - c["base"]
        lines.append({"part": "notes", "points": [[x, c["base"]], [x, c["top"]]], "dashed": False})
        for z in (c["base"], c["top"]):
            lines.append({"part": "notes", "points": [[x - m_per_mm, z - m_per_mm], [x + m_per_mm, z + m_per_mm]], "dashed": False})
        text([x + 1.5 * m_per_mm, (c["base"] + c["top"]) / 2], f"{height:.1f}m {c['floors']}층", f"{height:.1f}m {c['floors']}F")
        text([x + 1.5 * m_per_mm, c["top"] + 0.6 * m_per_mm], f"{c['top']:+.2f}", f"{c['top']:+.2f}")
    ends = (f"{name}′", f"{name}'"), (name, name)
    left, right = (ends[0], ends[1]) if mirror else (ends[1], ends[0])
    under = low - 5 * m_per_mm
    text([0.0, under], left[0], left[1], TITLE_MM, "middle")
    text([length, under], right[0], right[1], TITLE_MM, "middle")
    bar = next(m for m in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000) if m / m_per_mm >= 20) if m_per_mm else 10
    bx = length / 2 - bar / 2
    lines.append({"part": "notes", "points": [[bx, under], [bx + bar, under]], "dashed": False, "weight": 2})
    for x in (bx, bx + bar / 2, bx + bar):
        lines.append({"part": "notes", "points": [[x, under - m_per_mm], [x, under + m_per_mm]], "dashed": False})
    text([bx + bar + 2 * m_per_mm, under - 0.8 * m_per_mm], f"{bar:g}m", f"{bar:g}m")
    title = f"단면 {name}–{name}′ · 1:{scale}" + (f" · {found['scheme']}" if found.get("scheme") else "")
    text([0.0, high + 3 * m_per_mm], title, f"SECTION {name}-{name}'  1:{scale}", TITLE_MM)
    if not found.get("ground_known"):
        text([0.0, high + 0.5 * m_per_mm], "지형 미확인: 주변 3D를 만들면 지형과 주변 건물이 들어갑니다", "Ground unknown", TEXT_MM)
    return {"width": length, "low": low, "high": high + 3 * m_per_mm + TITLE_MM * m_per_mm, "scale": scale,
            "fills": fills, "lines": lines, "texts": texts}


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

FILL_RGB = {"ground": GROUND, "mass": INK, "building": NEAR}
LINE_RGB = {"ground": INK, "floors": (255, 255, 255), "building": INK, "beyond": BEYOND, "notes": INK}


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _paper(drawing: dict):
    """mm on the page: (x, y) of a point, the page's width and height (y down for SVG)."""
    k = 1000 / drawing["scale"]
    left = MARGIN_MM + 6
    width = drawing["width"] * k + left + MARGIN_MM + 30
    height = (drawing["high"] - drawing["low"]) * k + 2 * MARGIN_MM + 8

    def at(x, y):
        return left + x * k, MARGIN_MM + (drawing["high"] - y) * k

    return at, width, height


def to_svg(drawing: dict) -> bytes:
    at, w, h = _paper(drawing)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}mm" height="{h:.1f}mm" viewBox="0 0 {w:.2f} {h:.2f}">',
           f'<rect width="{w:.2f}" height="{h:.2f}" fill="#ffffff"/>']

    def pts(points):
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in (at(*p) for p in points))

    for f in drawing["fills"]:
        rgb = FILL_RGB[f["part"]]
        opacity = ' fill-opacity="0.45"' if f.get("light") else ""
        out.append(f'<polygon points="{pts(f["points"])}" fill="{_hex(rgb)}"{opacity} data-part="{f["part"]}"/>')
    for line in drawing["lines"]:
        width = 0.35 if line.get("weight") == 2 else 0.13
        dash = ' stroke-dasharray="1.2 0.8"' if line.get("dashed") else ""
        out.append(f'<polyline points="{pts(line["points"])}" fill="none" stroke="{_hex(LINE_RGB[line["part"]])}" '
                   f'stroke-width="{width}"{dash} data-part="{line["part"]}"/>')
    for t in drawing["texts"]:
        x, y = at(*t["at"])
        anchor = {"start": "start", "middle": "middle", "end": "end"}[t["anchor"]]
        out.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{t["size"]:.2f}" text-anchor="{anchor}" fill="{_hex(INK)}" '
                   f'font-family="Malgun Gothic, Apple SD Gothic Neo, sans-serif">{escape(t["text"])}</text>')
    out.append("</svg>")
    return "\n".join(out).encode("utf-8")


def _pdf_text(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def to_pdf(drawing: dict) -> bytes:
    """One page, vector paths at the paper's scale; labels in Helvetica (Latin letters)."""
    at, w, h = _paper(drawing)

    def xy(p):
        x, y = at(*p)
        return f"{x * PT_PER_MM:.2f} {(h - y) * PT_PER_MM:.2f}"

    ops = ["1 J 1 j"]
    for f in drawing["fills"]:
        r, g, b = (v / 255 for v in FILL_RGB[f["part"]])
        if f.get("light"):
            r, g, b = (1 - 0.45 * (1 - v) for v in (r, g, b))
        pts = f["points"]
        ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg " + f"{xy(pts[0])} m " + " ".join(f"{xy(p)} l" for p in pts[1:]) + " h f")
    for line in drawing["lines"]:
        r, g, b = (v / 255 for v in LINE_RGB[line["part"]])
        width = (0.35 if line.get("weight") == 2 else 0.13) * PT_PER_MM
        dash = "[3.4 2.3] 0 d" if line.get("dashed") else "[] 0 d"
        pts = line["points"]
        ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w {dash} {xy(pts[0])} m " + " ".join(f"{xy(p)} l" for p in pts[1:]) + " S")
    r, g, b = (v / 255 for v in INK)
    for t in drawing["texts"]:
        size = t["size"] * PT_PER_MM
        x, y = at(*t["at"])
        shift = {"start": 0, "middle": 0.5, "end": 1}[t["anchor"]] * len(t["plain"]) * size * 0.55
        ops.append(f"BT {r:.3f} {g:.3f} {b:.3f} rg /F1 {size:.2f} Tf {x * PT_PER_MM - shift:.2f} {(h - y) * PT_PER_MM:.2f} Td ("
                   + _pdf_text(t["plain"]).decode("latin-1") + ") Tj ET")
    stream = zlib.compress("\n".join(ops).encode("latin-1"))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w * PT_PER_MM:.2f} {h * PT_PER_MM:.2f}] /Contents 4 0 R "
         "/Resources << /Font << /F1 5 0 R >> >> >>").encode("ascii"),
        f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode("ascii") + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
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


def to_dxf(drawing: dict) -> bytes:
    """AutoCAD 2013, 1:1 in metres: x along the section, y the height; text sized for the scale."""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    doc = ezdxf.new("R2013", setup=True, units=6)  # 6 = metres
    doc.header["$MEASUREMENT"] = 1
    style = doc.styles.get("Standard")
    style.dxf.font = board_export.TEXT_FONT
    for name, aci, rgb in DXF_LAYERS.values():
        made = doc.layers.add(name, color=aci)
        made.rgb = rgb
    msp = doc.modelspace()
    k = drawing["scale"] / 1000  # metres per paper mm
    for f in drawing["fills"]:
        name, aci, _rgb = DXF_LAYERS[f["part"]]
        hatch = msp.add_hatch(color=aci, dxfattribs={"layer": name})
        hatch.paths.add_polyline_path([tuple(p) for p in f["points"]], is_closed=True)
        if f["part"] == "building":
            msp.add_lwpolyline([tuple(p) for p in f["points"]], close=True, dxfattribs={"layer": name})
    for line in drawing["lines"]:
        attrs = {"layer": DXF_LAYERS[line["part"]][0]}
        if line.get("dashed"):
            attrs["linetype"] = "DASHED"
            attrs["ltscale"] = k
        if line.get("weight") == 2:
            attrs["lineweight"] = 35
        msp.add_lwpolyline([tuple(p) for p in line["points"]], dxfattribs=attrs)
    align = {"start": TextEntityAlignment.LEFT, "middle": TextEntityAlignment.CENTER, "end": TextEntityAlignment.RIGHT}
    for t in drawing["texts"]:
        msp.add_text(t["text"], height=t["size"] * k, dxfattribs={"layer": DXF_LAYERS["notes"][0]}).set_placement(
            tuple(t["at"]), align=align[t["anchor"]])
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


WRITERS = {"svg": to_svg, "pdf": to_pdf, "dxf": to_dxf}


def export_section(project_path: Path, paper_id: str, fmt: str, *, active: str | None = None, hooks=None) -> bytes:
    """The section paper's drawing as a file. Raises ValueError for an unknown format."""
    fmt = (fmt or "").lower()
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}")
    return WRITERS[fmt](section_drawing(section_of(project_path, paper_id, active=active, hooks=hooks)))


def file_name(paper: dict, fmt: str) -> str:
    name = paper.get("title") or "A"
    return f"단면_{name}-{name}.{fmt}"

