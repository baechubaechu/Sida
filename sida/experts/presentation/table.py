"""The drafting table as slide material: what a deck can show without Rhino.

A designer who only works on the table still has things worth a slide: the massing scheme
(its figures and the diagrams drawn from it), the section drawings and the photos on the table
(a site photo, a sketch, a scene kept from the eye-level view). slides.materials lists them
beside the Rhino ones; deck.py sets them on a slide.

The scheme is read as a model of the same shape as a Rhino snapshot (`scheme_model`), so the
figures and the diagrams come from the very same rules (experts/rhino/snapshot.py figures,
diagrams.py) and agree with the table's own figures (board.blocks_areas): blocks that overlap
are one building, the shared part counted once on the ground and on each floor. For that the
scheme is cut into bands of storeys, each band the ground its blocks cover together. A scheme
has no uses, so the diagram by use (program) is not drawn from it, and the others are drawn in
one plain colour without a legend. Nothing is estimated here.
"""

from __future__ import annotations

from pathlib import Path

from sida import board, board_export, board_section
from sida.experts.rhino import diagrams
from sida.experts.rhino import snapshot as snap

LAYER = "매스"
MEANING = "other"  # every built meaning counts the same in the figures; the diagrams lose its colour and legend (plain)
NO_USES = "제도판 매스안에는 용도가 없어 그릴 수 없습니다. 라이노에서 레이어에 용도를 주면 그려집니다."
PICTURES = ("png", "jpg")  # what both PowerPoint and the PDF take as they are
NOT_A_PICTURE = "PNG·JPG 사진만 슬라이드에 넣을 수 있습니다."
PAGE_WIDTH = 960.0  # px a section's page is set at (like a diagram's, experts/rhino/diagram_svg.py)
LETTER_PX = 12.0  # a section's labels on that page, whatever its paper scale


def schemes(saved: dict) -> list[dict]:
    """The massing schemes on the table that have blocks, in the table's order."""
    return [p for p in saved["papers"] if p.get("kind") == "mass" and p.get("blocks")]


def pick_scheme(saved: dict, scheme_id: str | None = None) -> dict | None:
    """The scheme a deck shows: the one asked for, else the first on the table. Raises ValueError for one that is not there."""
    found = schemes(saved)
    if scheme_id:
        scheme = next((p for p in found if p["id"] == scheme_id), None)
        if scheme is None:
            raise ValueError(f"not a massing scheme on the table: {scheme_id}")
        return scheme
    return found[0] if found else None


def _rings(shape) -> list[list[list[float]]]:
    """A shapely shape as rings read by the even-odd rule (a ring inside another is a hole)."""
    rings = []
    for piece in getattr(shape, "geoms", [shape]):
        if piece.is_empty or piece.geom_type != "Polygon":
            continue
        for ring in (piece.exterior, *piece.interiors):
            rings.append([[round(x, 3), round(y, 3)] for x, y in list(ring.coords)[:-1]])
    return rings


def scheme_model(scheme: dict, frame: dict | None) -> dict:
    """
    A massing scheme as a model of a snapshot's shape (experts/rhino/snapshot.py), in the
    table's frame, standing on z = 0: one object for every band of storeys between two block
    heights, its footprint the ground the blocks that reach it cover together and a floor at
    every storey. So a tower drawn through its podium is counted once.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    storey = float(scheme.get("floor_height") or board.DEFAULT_FLOOR_HEIGHT)
    blocks = [(int(b["floors"]), Polygon(board_export.block_outline(frame, b))) for b in scheme.get("blocks") or []]
    objects = []
    below = 0
    for level in sorted({floors for floors, _shape in blocks}):
        shape = unary_union([s for floors, s in blocks if floors >= level])
        rings = _rings(shape)
        if rings:
            area = round(float(shape.area), 3)
            objects.append({
                "id": f"table-{below}-{level}", "sida_id": None, "layer": LAYER, "name": "",
                "volume": round(area * (level - below) * storey, 3), "height": round((level - below) * storey, 3),
                "base": round(below * storey, 3), "footprint": rings,
                "floors": [{"z": round(k * storey, 3), "area": area} for k in range(below, level)],
            })
        below = level
    return {
        "schema": snap.SCHEMA, "rhino": {"version": "", "file": "", "units": "m"},
        "layers": [{"path": LAYER, "meaning": MEANING, "color": diagrams.PLAIN, "floor_height": storey}],
        "objects": objects, "views": [],
    }


def plain(drawing: dict) -> dict:
    """A diagram of a scheme without what only uses give it: one plain colour, no legend."""
    tint = snap.MEANINGS[MEANING]["color"]
    items = [{**item, "color": diagrams.PLAIN} if item.get("color") == tint else item
             for item in drawing["items"] if item.get("role") != "legend"]
    return {**drawing, "items": items}


def frame_of(project_path: Path, hooks=None) -> dict | None:
    """The frame the blocks of a scheme are drawn in (the site plan's), None without a site."""
    summary = board.site_summary(project_path, hooks)
    plan = board.site_plan((summary or {}).get("parcels") or [])
    return (plan or {}).get("frame")


def extras(project_path: Path, saved: dict) -> dict[str, dict]:
    """
    The sections and photos on the table as slide materials, by key: `section:<paper id>` and
    `photo:<paper id>`. A photo that is not a PNG or JPEG (a GIF, a WebP, a PDF page) is listed
    as not ready, with why.
    """
    items: dict[str, dict] = {}
    for paper in saved["papers"]:
        if paper.get("kind") == "section" and paper.get("line"):
            key = f"section:{paper['id']}"
            name = paper.get("title") or "A"
            items[key] = {"key": key, "kind": "section", "title": f"단면 {name}–{name}′", "ready": True, "why": "", "paper": paper["id"]}
    for paper in saved["papers"]:
        if paper.get("kind") != "photo":
            continue
        file = str(paper.get("file") or "")
        if not board.PHOTO_FILE.fullmatch(file) or not (board.photo_dir(project_path) / file).is_file():
            continue
        key = f"photo:{paper['id']}"
        ok = file.rsplit(".", 1)[1] in PICTURES
        items[key] = {"key": key, "kind": "photo", "title": board.paper_name(paper), "ready": ok, "why": "" if ok else NOT_A_PICTURE,
                      "paper": paper["id"], "file": file}
    return items


def section_drawing(project_path: Path, paper_id: str, scheme_id: str | None = None) -> dict:
    """A section on the table as its drawing (board_section.section_drawing). Raises board.PaperNotFound, ValueError."""
    return board_section.section_drawing(board_section.section_of(project_path, paper_id, active=scheme_id))


def section_page(drawing: dict) -> dict:
    """
    A section's drawing set on a page of the shape a diagram's is (diagram_svg.layout: px, y
    down), so a slide draws it as editable shapes. Its own title line is left out: the slide has
    a title, and the scale it names holds on paper, not on a slide (the scale bar still does).
    """
    texts = [t for t in drawing["texts"] if t.get("role") != "title"]
    k = PAGE_WIDTH / max(drawing["width"], 1.0)  # px per metre
    ys = [p[1] for part in (drawing["fills"], drawing["lines"]) for item in part for p in item["points"]] + [t["at"][1] for t in texts]
    high = max(ys, default=0.0)

    def at(p):
        return (round(p[0] * k, 2), round((high - p[1]) * k, 2))

    def color(rgb) -> str:
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    shapes: list[dict] = []
    for fill in drawing["fills"]:
        shapes.append({"type": "poly", "rings": [[at(p) for p in fill["points"]]], "fill": color(board_section.FILL_RGB[fill["part"]]),
                       "opacity": 0.45 if fill.get("light") else 1.0, "stroke": None, "width": 0.0, "tag": "fill"})
    for line in drawing["lines"]:
        shapes.append({"type": "line", "points": [at(p) for p in line["points"]], "closed": False,
                       "stroke": color(board_section.LINE_RGB[line["part"]]), "width": 2.0 if line.get("weight") == 2 else 0.8,
                       "dashed": bool(line.get("dashed")), "tag": "line"})
    for text in texts:
        x, y = at(text["at"])
        shapes.append({"type": "text", "x": x, "y": y, "text": text["text"], "px": round(text["size"] / board_section.TEXT_MM * LETTER_PX, 2), "anchor": text["anchor"],
                       "weight": 400, "tag": "text"})
    xs = [x for shape in shapes for x in ([p[0] for ring in shape["rings"] for p in ring] if shape["type"] == "poly"
                                           else [p[0] for p in shape["points"]] if shape["type"] == "line" else [shape["x"]])]
    low = min(ys, default=0.0)
    return {"kind": "section", "width": round(max(xs, default=PAGE_WIDTH), 2), "height": round((high - low) * k, 2), "shapes": shapes}
