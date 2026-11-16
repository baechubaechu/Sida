"""The deck as files: each slide set on a 16:9 page, then written as PowerPoint, as PDF, or as a bundle.

`pages` sets every slide (slides.deck) on a page of 960 x 540 pt, y down, as plain elements;
`to_pptx` and `to_pdf` draw those same pages, so the two files agree. In PowerPoint everything
stays editable: a slide's title is its title, sentences are text boxes with real bullets, the
figures are a table, and a diagram is one group of shapes (the page rhino/diagram_svg.layout
sets, the same one the SVG is written from). A capture is the PNG Rhino made.

Nothing here writes a sentence or computes a number: the words are the editor's, the pictures
and figures are Sida's. The look is plain on purpose (white page, ink, one hairline), so a
designer's own template can take over in PowerPoint.
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
import struct
import zipfile
from pathlib import Path

from sida.experts.presentation import slides as deck_slides
from sida.experts.rhino import diagram_svg, diagrams
from sida.experts.rhino import snapshot as snap
from sida.experts.rhino.diagrams import text_width

PAGE_W, PAGE_H = 960.0, 540.0  # pt: 13.333 x 7.5 in
SIDE = 54.0
TITLE_BOX = (SIDE, 34.0, PAGE_W - 2 * SIDE, 50.0)  # a content slide's title, sitting on the hairline
RULE_Y = 92.0
BODY_TOP, BODY_BOTTOM = 112.0, 482.0
FOOT_Y = 506.0
INK, MUTED, HAIR = "#20262d", "#616b77", "#dee2e6"
FONT = "Malgun Gothic"
TITLE_SIZE, TITLE_LEAST = 26.0, 18.0
COVER_SIZE, COVER_LEAST = 40.0, 28.0
TEXT_SIZE, TEXT_LEAST = 20.0, 11.0
SIDE_TEXT_SIZE = 16.0
PITCH = 1.35  # a line's height, in letter heights (about what PowerPoint gives Malgun Gothic)
FORMATS = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "zip": "application/zip",
}
WORD_SIZE, WORD_PITCH = 10.0, 16.0  # a diagram's legend and figure lines on a slide
MAX_DIAGRAM_SCALE = 1.5  # a small diagram is not blown up to fill the slide,
MAX_DIAGRAM_LETTER = 16.0  # nor until its letters outgrow the slide's own
MAX_FACES = 6000  # shapes of one diagram in PowerPoint; beyond it the walls of each mass are left out


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def _lines(text: str, size: float, width: float) -> int:
    """About how many lines a text takes (words break early, so a little more than its width says)."""
    return max(1, math.ceil(text_width(text, size) * 1.08 / max(width, 1.0)))


def _fit_size(texts: list[str], width: float, height: float, start: float, least: float, *, bullets: bool = False) -> float:
    """The largest letter height from `start` down to `least` at which the texts fit the box."""
    size = start
    while size > least:
        inner = width - (size * 1.1 if bullets else 0.0)
        tall = sum(_lines(text, size, inner) for text in texts) * size * PITCH + (len(texts) - 1) * size * 0.5 * bullets
        if tall <= height:
            break
        size -= 1.0
    return size


def _text(x, y, w, h, paras, size, *, color=INK, bold=False, bullets=False, align="left", anchor="top", wrap=True) -> dict:
    return {"type": "text", "x": x, "y": y, "w": w, "h": h, "paras": list(paras), "size": size, "color": color, "bold": bold,
            "bullets": bullets, "align": align, "anchor": anchor, "wrap": wrap}


def png_size(path: Path) -> tuple[int, int] | None:
    """A PNG's width and height from its header (None when it is not one)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != snap.PNG or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return (width, height) if width and height else None


def _inside(box, width: float, height: float) -> tuple[float, float, float, float]:
    """A width x height picture as large as the box lets it be, centred in it: (x, y, w, h)."""
    x, y, w, h = box
    k = min(w / width, h / height)
    return x + (w - width * k) / 2, y + (h - height * k) / 2, width * k, height * k


def _extent(page: dict) -> tuple[float, float, float, float]:
    """What a diagram's page really covers (its margins are for a file of its own): (x0, y0, x1, y1) in its pixels."""
    xs: list[float] = []
    ys: list[float] = []
    for shape in page["shapes"]:
        if shape["type"] == "text":
            wide = text_width(shape["text"], shape["px"])
            left = shape["x"] - wide * diagram_svg.ANCHOR_SHIFT[shape["anchor"]]
            xs += [left, left + wide]
            ys += [shape["y"] - shape["px"], shape["y"] + shape["px"] * 0.3]
            continue
        for x, y in (shape["points"] if shape["type"] == "line" else [point for ring in shape["rings"] for point in ring]):
            xs.append(x)
            ys.append(y)
    if not xs:
        return 0.0, 0.0, page["width"], page["height"]
    return min(xs), min(ys), max(max(xs), min(xs) + 1.0), max(max(ys), min(ys) + 1.0)


def _empty(box, figure: dict) -> dict:
    x, y, w, h = box
    return {"type": "empty", "x": x, "y": y, "w": w, "h": h, "paras": [figure["title"], figure["why"] or "만들 수 없습니다."]}


def _figure(figure: dict, box, mats: dict, project_path: Path, drawn: dict) -> list[dict]:
    """The elements that fill a figure's box: the diagram with its words, the capture, the table, or an empty place that says why."""
    if not figure["ready"] or mats["snapshot"] is None:
        return [_empty(box, figure)]
    x, y, w, h = box
    if figure["kind"] == "diagram":
        kind = figure["key"].split(":", 1)[1]
        if kind not in drawn:
            ctx = diagrams.context(project_path) if kind == "site" else mats["context"]  # only the site plan draws the buildings around
            drawing = diagrams.drawing(kind, mats["snapshot"], ctx)
            # The drawing alone: the slide has a title of its own, and sets the legend at a size that reads on a slide.
            drawn[kind] = (diagram_svg.layout(drawing, words=False), diagram_svg.words(drawing))
        page, said = drawn[kind]
        rows: list[list[tuple[str, str, float]]] = []  # the legend, as many entries on a line as the box holds
        run = w + 1.0
        for color, text in said["legend"]:
            wide = WORD_SIZE * 1.5 + text_width(text, WORD_SIZE) * 1.1 + 18.0
            if run + wide > w:
                rows.append([])
                run = 0.0
            rows[-1].append((color, text, run))
            run += wide
        words_tall = (len(rows) + len(said["caption"])) * WORD_PITCH
        gap = 10.0 if words_tall else 0.0
        room = max(h - words_tall - gap, h * 0.4)
        x0, y0, x1, y1 = _extent(page)
        letters = max((shape["px"] for shape in page["shapes"] if shape["type"] == "text"), default=0.0)
        k = min(w / (x1 - x0), room / (y1 - y0), MAX_DIAGRAM_SCALE, MAX_DIAGRAM_LETTER / letters if letters else MAX_DIAGRAM_SCALE)
        left = x + (w - (x1 - x0) * k) / 2
        top = y + max(h - (y1 - y0) * k - gap - words_tall, 0.0) / 2  # the drawing and its words, together in the middle
        elements = [{"type": "diagram", "x": left - x0 * k, "y": top - y0 * k, "scale": k, "page": page}]
        widest = max([row[-1][2] + WORD_SIZE * 1.5 + text_width(row[-1][1], WORD_SIZE) * 1.1 for row in rows]
                     + [text_width(text, WORD_SIZE) * 1.1 for text in said["caption"]] + [0.0])
        left = max(x, min(left, x + w - widest))  # under the drawing's left edge, as far as the words fit
        line = top + (y1 - y0) * k + gap
        for row in rows:
            for color, text, at in row:
                elements.append({"type": "swatch", "x": left + at, "y": line + (WORD_PITCH - WORD_SIZE) / 2, "size": WORD_SIZE, "color": color})
                elements.append(_text(left + at + WORD_SIZE * 1.5, line, text_width(text, WORD_SIZE) * 1.3 + 8.0, WORD_PITCH, [text],
                                      WORD_SIZE, wrap=False))
            line += WORD_PITCH
        for text in said["caption"]:
            elements.append(_text(left, line, max(x + w - left, 1.0), WORD_PITCH, [text], WORD_SIZE, color=MUTED, wrap=False))
            line += WORD_PITCH
        return elements
    if figure["kind"] == "view":
        try:
            file = snap.view_file(project_path, mats["snapshot"]["id"], mats["items"][figure["key"]]["file"])
        except (snap.SnapshotNotFound, ValueError, KeyError):
            file = None
        size = png_size(file) if file is not None else None
        if size is None:
            return [_empty(box, {**figure, "why": "캡처 파일을 읽을 수 없습니다."})]
        px, py, pw, ph = _inside(box, *size)
        return [{"type": "picture", "x": px, "y": py, "w": pw, "h": ph, "path": str(file)}]
    rows = deck_slides.figure_rows(mats["figures"], mats["limits"])
    row_h = min(36.0, h / len(rows))
    wide = min(w, 560.0)
    return [{"type": "table", "x": x + (w - wide) / 2 if w > wide + 200 else x, "y": y, "w": wide, "row_h": row_h,
             "size": max(9.0, min(18.0, row_h * 0.5)), "rows": rows}]


def pages(deck: dict, mats: dict, project_path: Path) -> list[dict]:
    """
    Every slide of the deck set on its page: [{number, layout, title, notes, elements}]. Elements,
    in pt with y down:
        {"type": "title", x, y, w, h, text, size}                  the slide's title (bottom of its box)
        {"type": "text", x, y, w, h, paras, size, color, bold, bullets, align, anchor, wrap}
        {"type": "rule", x1, y1, x2, y2, color, width}
        {"type": "picture", x, y, w, h, path}                      a PNG, already fitted
        {"type": "diagram", x, y, scale, page}                     a page of diagram_svg.layout, without its words
        {"type": "swatch", x, y, size, color}                      a legend's square of colour
        {"type": "table", x, y, w, row_h, size, rows}              (label, value) rows
        {"type": "empty", x, y, w, h, paras}                       a figure that cannot be made, and why
    """
    path = Path(project_path)
    wide = PAGE_W - 2 * SIDE
    drawn: dict[str, tuple[dict, dict]] = {}
    out = []
    for number, slide in enumerate(deck["slides"], start=1):
        elements: list[dict] = []
        if slide["layout"] == "title":
            size = _fit_size([slide["title"]], wide, 100.0, COVER_SIZE, COVER_LEAST)
            elements.append({"type": "title", "x": SIDE, "y": 176.0, "w": wide, "h": 104.0, "text": slide["title"], "size": size})
            elements.append({"type": "rule", "x1": SIDE, "y1": 292.0, "x2": SIDE + 48.0, "y2": 292.0, "color": INK, "width": 2.0})
            under = [text for text in (slide["subtitle"], *slide["bullets"]) if text]
            if under:
                elements.append(_text(SIDE, 306.0, wide, 150.0, under, _fit_size(under, wide, 150.0, 18.0, TEXT_LEAST), color=MUTED))
        else:
            x, y, w, h = TITLE_BOX
            size = _fit_size([slide["title"]], w, h, TITLE_SIZE, TITLE_LEAST)
            elements.append({"type": "title", "x": x, "y": y, "w": w, "h": h, "text": slide["title"], "size": size})
            elements.append({"type": "rule", "x1": SIDE, "y1": RULE_Y, "x2": PAGE_W - SIDE, "y2": RULE_Y, "color": HAIR, "width": 0.75})
            bottom = BODY_BOTTOM
            if slide["caption"]:
                bottom -= 26.0
            tall = bottom - BODY_TOP
            if slide["figure"] is not None:
                beside = slide["bullets"]
                box = (SIDE, BODY_TOP, 540.0 if beside else wide, tall)
                elements += _figure(slide["figure"], box, mats, path, drawn)
                if beside:
                    left = SIDE + 540.0 + 28.0
                    room = PAGE_W - SIDE - left
                    elements.append(_text(left, BODY_TOP, room, tall, beside,
                                          _fit_size(beside, room, tall, SIDE_TEXT_SIZE, TEXT_LEAST, bullets=True), bullets=True))
                if slide["caption"]:
                    elements.append(_text(SIDE, bottom + 8.0, wide, 18.0, [slide["caption"]], 11.0, color=MUTED))
            else:
                lines = [text for text in (slide["subtitle"], *slide["bullets"]) if text]
                room = wide - 120.0  # a shorter line reads better than one across the whole slide
                if lines:
                    elements.append(_text(SIDE, BODY_TOP, room, tall, lines, _fit_size(lines, room, tall, TEXT_SIZE, TEXT_LEAST, bullets=True),
                                          bullets=True))
                if slide["caption"]:
                    elements.append(_text(SIDE, bottom + 8.0, wide, 18.0, [slide["caption"]], 11.0, color=MUTED))
            elements.append(_text(SIDE, FOOT_Y, wide - 60.0, 14.0, [deck["title"]], 9.0, color=MUTED))
            elements.append(_text(PAGE_W - SIDE - 60.0, FOOT_Y, 60.0, 14.0, [str(number)], 9.0, color=MUTED, align="right"))
        out.append({"number": number, "layout": slide["layout"], "title": slide["title"], "notes": slide["notes"], "elements": elements})
    return out


def _faces(shapes: list[dict]) -> list[dict]:
    """
    A diagram's shapes with the sides of each solid joined where PowerPoint can take them as one
    shape: faces painted one after another in the same colour become one shape of several
    separately filled paths ({..., "paths": [rings, ...]}), which keeps a tower of many plates
    light to edit. Past MAX_FACES shapes the drawing is too heavy to be useful as shapes at all.
    """
    out: list[dict] = []
    for shape in shapes:
        if shape["type"] != "poly":
            out.append(shape)
            continue
        last = out[-1] if out else None
        same = last is not None and last["type"] == "poly" and shape["tag"] == "face" and last["tag"] == "face" and all(
            last[key] == shape[key] for key in ("fill", "opacity", "stroke", "width"))
        if same:
            last["paths"].append(shape["rings"])
        else:
            out.append({**shape, "paths": [shape["rings"]]})
    return out


# ---------------------------------------------------------------------------
# PowerPoint
# ---------------------------------------------------------------------------


def to_pptx(made: list[dict], title: str) -> bytes:
    """The pages as a PowerPoint file, every part of it editable."""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.dml import MSO_LINE
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Pt

    align = {"left": PP_ALIGN.LEFT, "right": PP_ALIGN.RIGHT, "center": PP_ALIGN.CENTER}
    anchors = {"top": MSO_ANCHOR.TOP, "bottom": MSO_ANCHOR.BOTTOM, "middle": MSO_ANCHOR.MIDDLE}

    def rgb(color: str):
        return RGBColor.from_string(color.lstrip("#").upper())

    def style(run, size: float, color: str, bold: bool = False) -> None:
        font = run.font
        font.name, font.size, font.bold = FONT, Pt(size), bold
        font.color.rgb = rgb(color)
        properties = run._r.get_or_add_rPr()
        latin = properties.find(qn("a:latin"))
        latin.addnext(properties.makeelement(qn("a:ea"), {"typeface": FONT}))  # the font for Hangul, not only for Latin letters

    def frame(text_frame, *, wrap: bool = True, anchor: str = "top") -> None:
        text_frame.word_wrap = wrap
        text_frame.auto_size = MSO_AUTO_SIZE.NONE
        text_frame.margin_left = text_frame.margin_right = text_frame.margin_top = text_frame.margin_bottom = 0
        text_frame.vertical_anchor = anchors[anchor]

    def write(text_frame, paras, size, color, *, bold=False, bullets=False, where="left") -> None:
        for index, text in enumerate(paras):
            para = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
            para.alignment = align[where]
            if bullets:
                para.space_after = Pt(size * 0.5)
                properties = para._p.get_or_add_pPr()
                properties.set("marL", str(int(Pt(size * 1.1))))
                properties.set("indent", str(-int(Pt(size * 1.1))))
                properties.append(properties.makeelement(qn("a:buFont"), {"typeface": "Arial"}))
                properties.append(properties.makeelement(qn("a:buChar"), {"char": "•"}))
            style(para.add_run(), size, color, bold)
            para.runs[0].text = text

    def outline(shape, color: str | None, width: float, dashed: bool = False) -> None:
        """The shape's line as said, and nothing from the theme (its accent colour, its shadow)."""
        themed = shape._element.find(qn("p:style"))
        if themed is not None:
            shape._element.remove(themed)
        if color is None:
            shape.line.fill.background()
            return
        shape.line.color.rgb = rgb(color)
        shape.line.width = Pt(width)
        if dashed:
            shape.line.dash_style = MSO_LINE.DASH

    def freeform(shapes, paths, *, closed: bool, fill: str | None, opacity: float = 1.0, stroke: str | None = None,
                 width: float = 0.0, dashed: bool = False):
        """One shape of several paths (each filled by itself; a path's rings cut holes), in page pt."""
        points = [point for rings in paths for ring in rings for point in ring]
        x0, y0 = int(Pt(min(x for x, _y in points))), int(Pt(min(y for _x, y in points)))
        x1, y1 = int(Pt(max(x for x, _y in points))), int(Pt(max(y for _x, y in points)))
        builder = shapes.build_freeform(Emu(x0), Emu(y0))
        builder.add_line_segments([(Emu(max(x1, x0 + 1)), Emu(max(y1, y0 + 1)))], close=False)
        shape = builder.convert_to_shape()
        path_list = shape._element.spPr.find(qn("a:custGeom")).find(qn("a:pathLst"))
        for old in list(path_list):
            path_list.remove(old)
        size = {"w": str(max(x1 - x0, 1)), "h": str(max(y1 - y0, 1))}
        for rings in paths:
            path = path_list.makeelement(qn("a:path"), size if fill else {**size, "fill": "none"})
            path_list.append(path)
            for ring in rings:
                for index, (x, y) in enumerate(ring):
                    step = path.makeelement(qn("a:moveTo" if index == 0 else "a:lnTo"), {})
                    step.append(step.makeelement(qn("a:pt"), {"x": str(int(Pt(x)) - x0), "y": str(int(Pt(y)) - y0)}))
                    path.append(step)
                if closed:
                    path.append(path.makeelement(qn("a:close"), {}))
        if fill:
            shape.fill.solid()
            shape.fill.fore_color.rgb = rgb(fill)
            if opacity < 1:
                colour = shape._element.spPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
                colour.append(colour.makeelement(qn("a:alpha"), {"val": str(round(opacity * 100000))}))
        else:
            shape.fill.background()
        outline(shape, stroke, width, dashed)
        return shape

    def diagram(slide, element: dict) -> None:
        k, left, top = element["scale"], element["x"], element["y"]

        def at(point):
            return left + point[0] * k, top + point[1] * k

        drawn = _faces(element["page"]["shapes"])
        if len(drawn) > MAX_FACES:  # far too many plates to edit by hand: the lids alone still read
            drawn = [shape for shape in drawn if shape["type"] != "poly" or shape["tag"] != "face" or len(shape["paths"]) == 1]
        made_shapes = []
        for shape in drawn:
            if shape["type"] == "poly":
                paths = [[[at(p) for p in ring] for ring in rings] for rings in shape["paths"]]
                made_shapes.append(freeform(slide.shapes, paths, closed=True, fill=shape["fill"], opacity=shape["opacity"],
                                            stroke=shape["stroke"], width=shape["width"] * k))
            elif shape["type"] == "line":
                made_shapes.append(freeform(slide.shapes, [[[at(p) for p in shape["points"]]]], closed=shape["closed"], fill=None,
                                            stroke=shape["stroke"], width=max(shape["width"] * k, 0.25), dashed=shape["dashed"]))
            else:
                size = shape["px"] * k
                wide = text_width(shape["text"], size) * 1.25 + size
                x, y = at((shape["x"], shape["y"]))
                x -= wide * diagram_svg.ANCHOR_SHIFT[shape["anchor"]]
                box = slide.shapes.add_textbox(Pt(x), Pt(y - size * 1.08), Pt(wide), Pt(size * PITCH))
                frame(box.text_frame, wrap=False)
                write(box.text_frame, [shape["text"]], size, diagram_svg.INK, bold=shape["weight"] >= 600,
                      where={"start": "left", "middle": "center", "end": "right"}[shape["anchor"]])
                made_shapes.append(box)
        if not made_shapes:
            return
        # Grouped in one go: adding to a group one by one measures the whole group each time.
        group = slide.shapes.add_group_shape()
        group.name = f"Sida diagram ({element['page']['kind']})"
        for shape in made_shapes:
            group._element.append(shape._element)
        group._element.recalculate_extents()

    def table(slide, element: dict) -> None:
        rows = element["rows"]
        made_frame = slide.shapes.add_table(len(rows), 2, Pt(element["x"]), Pt(element["y"]), Pt(element["w"]),
                                            Pt(element["row_h"] * len(rows)))
        made_table = made_frame.table
        made_table.first_row = made_table.horz_banding = False
        made_table._tbl.tblPr.find(qn("a:tableStyleId")).text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # "No Style, No Grid"
        made_table.columns[0].width = Pt(element["w"] * 0.4)
        made_table.columns[1].width = Pt(element["w"] * 0.6)
        for index, (label, value) in enumerate(rows):
            made_table.rows[index].height = Pt(element["row_h"])
            for column, text in enumerate((label, value)):
                cell = made_table.cell(index, column)
                cell.margin_left = cell.margin_right = Pt(4)
                cell.margin_top = cell.margin_bottom = 0
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.text_frame.word_wrap = True
                write(cell.text_frame, [text], element["size"], MUTED if column == 0 else INK, where="left" if column == 0 else "right")
                properties = cell._tc.get_or_add_tcPr()
                under = properties.makeelement(qn("a:lnB"), {"w": str(int(Pt(0.75))), "cap": "flat", "cmpd": "sng", "algn": "ctr"})
                fill = under.makeelement(qn("a:solidFill"), {})
                fill.append(fill.makeelement(qn("a:srgbClr"), {"val": HAIR.lstrip("#").upper()}))
                under.append(fill)
                under.append(under.makeelement(qn("a:prstDash"), {"val": "solid"}))
                properties.append(under)

    deck_file = Presentation()
    deck_file.slide_width, deck_file.slide_height = Pt(PAGE_W), Pt(PAGE_H)
    about = deck_file.core_properties
    about.title, about.author, about.last_modified_by, about.comments = title, "", "", ""
    layout = deck_file.slide_layouts[5]  # "Title Only": a title PowerPoint knows as the slide's title, nothing else
    x, y, w, h = TITLE_BOX
    place = layout.placeholders[0]
    place.left, place.top, place.width, place.height = Pt(x), Pt(y), Pt(w), Pt(h)  # where "Reset" puts a title back
    for page in made:
        slide = deck_file.slides.add_slide(layout)
        for element in page["elements"]:
            kind = element["type"]
            if kind == "title":
                head = slide.shapes.title
                head.left, head.top, head.width, head.height = (Pt(element[key]) for key in ("x", "y", "w", "h"))
                frame(head.text_frame, anchor="bottom")
                write(head.text_frame, [element["text"]], element["size"], INK, bold=True)
            elif kind == "text":
                box = slide.shapes.add_textbox(Pt(element["x"]), Pt(element["y"]), Pt(element["w"]), Pt(element["h"]))
                frame(box.text_frame, wrap=element["wrap"], anchor=element["anchor"])
                write(box.text_frame, element["paras"], element["size"], element["color"], bold=element["bold"],
                      bullets=element["bullets"], where=element["align"])
            elif kind == "swatch":
                box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(element["x"]), Pt(element["y"]), Pt(element["size"]), Pt(element["size"]))
                box.fill.solid()
                box.fill.fore_color.rgb = rgb(element["color"])
                outline(box, None, 0.0)
            elif kind == "rule":
                line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Pt(element["x1"]), Pt(element["y1"]), Pt(element["x2"]), Pt(element["y2"]))
                outline(line, element["color"], element["width"])
            elif kind == "picture":
                slide.shapes.add_picture(element["path"], Pt(element["x"]), Pt(element["y"]), Pt(element["w"]), Pt(element["h"]))
            elif kind == "diagram":
                diagram(slide, element)
            elif kind == "table":
                table(slide, element)
            else:  # an empty place
                box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(element["x"]), Pt(element["y"]), Pt(element["w"]), Pt(element["h"]))
                box.fill.background()
                outline(box, MUTED, 0.75, dashed=True)
                frame(box.text_frame, anchor="middle")
                write(box.text_frame, element["paras"], 12.0, MUTED, where="center")
        if page["notes"]:
            slide.notes_slide.notes_text_frame.text = page["notes"]
    out = io.BytesIO()
    deck_file.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def font_files() -> list[tuple[Path, Path]]:
    """Where a Korean TrueType font may be on this machine, best first: (regular, bold)."""
    windows = Path(os.environ.get("WINDIR") or "C:/Windows") / "Fonts"
    return [
        (windows / "malgun.ttf", windows / "malgunbd.ttf"),
        (Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"), Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf")),
        (Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")),
    ]


def pdf_fonts() -> tuple[str, str]:
    """
    The names of the regular and the bold font to write Korean with, registered. With a Korean
    font on this machine (Malgun Gothic on Windows) the file embeds the letters it uses, so it
    reads the same anywhere; without one it names Adobe's Korean gothic, which a PDF reader
    supplies itself.
    """
    from reportlab.pdfbase import pdfmetrics

    known = pdfmetrics.getRegisteredFontNames()
    if "SidaSans" in known:
        return "SidaSans", "SidaSans-Bold"
    for regular, bold in font_files():
        if not regular.is_file():
            continue
        from reportlab.pdfbase.ttfonts import TTFError, TTFont

        try:
            pdfmetrics.registerFont(TTFont("SidaSans", str(regular)))
            pdfmetrics.registerFont(TTFont("SidaSans-Bold", str(bold if bold.is_file() else regular)))
            return "SidaSans", "SidaSans-Bold"
        except TTFError:
            continue
    if "HYGothic-Medium" not in known:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
    return "HYGothic-Medium", "HYGothic-Medium"


def wrap(text: str, width: float, measure) -> list[str]:
    """The text broken into lines no wider than `width`, at spaces; a word longer than a line is cut by letter."""
    lines: list[str] = []
    line = ""
    for word in text.split(" "):
        trial = f"{line} {word}" if line else word
        if measure(trial) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        while measure(word) > width and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and measure(word[:cut]) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        line = word
    if line:
        lines.append(line)
    return lines or [""]


def to_pdf(made: list[dict], title: str) -> bytes:
    """The pages as a PDF, one slide a page, drawn as vectors (a capture stays the PNG it is)."""
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    regular, bold_font = pdf_fonts()
    out = io.BytesIO()
    page_canvas = canvas.Canvas(out, pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    page_canvas.setTitle(title)
    page_canvas.setAuthor("")
    page_canvas.setCreator("Sida")

    def down(y: float) -> float:
        return PAGE_H - y

    def put(x: float, baseline: float, text: str, font: str, size: float, color: str, where: str = "left") -> None:
        page_canvas.setFont(font, size)
        page_canvas.setFillColor(HexColor(color))
        {"left": page_canvas.drawString, "right": page_canvas.drawRightString, "center": page_canvas.drawCentredString}[where](
            x, down(baseline), text)

    def block(element: dict, paras: list[str], *, font: str, size: float, color: str, bullets: bool = False, where: str = "left",
              anchor: str = "top", gap: float = 0.0) -> None:
        indent = size * 1.1 if bullets else 0.0
        wrapped = [wrap(text, element["w"] - indent, lambda s: stringWidth(s, font, size)) if element.get("wrap", True) else [text]
                   for text in paras]
        tall = sum(len(lines) for lines in wrapped) * size * PITCH + (len(paras) - 1) * gap
        y = element["y"]
        if anchor == "bottom":
            y = element["y"] + element["h"] - tall
        elif anchor == "middle":
            y = element["y"] + (element["h"] - tall) / 2
        edge = {"left": element["x"] + indent, "right": element["x"] + element["w"], "center": element["x"] + element["w"] / 2}[where]
        for lines in wrapped:
            if bullets:  # a dot drawn, not a letter: not every font has the bullet
                page_canvas.setFillColor(HexColor(color))
                page_canvas.circle(element["x"] + size * 0.3, down(y + size * 0.66), size * 0.11, stroke=0, fill=1)
            for line in lines:
                put(edge, y + size, line, font, size, color, where)
                y += size * PITCH
            y += gap

    def stroke(color: str, width: float, dashed: bool = False) -> None:
        page_canvas.setStrokeColor(HexColor(color))
        page_canvas.setLineWidth(width)
        page_canvas.setLineJoin(1)
        page_canvas.setDash([7 * width, 4 * width] if dashed else [])

    def diagram(element: dict) -> None:
        k, left, top = element["scale"], element["x"], element["y"]

        def at(point):
            return left + point[0] * k, down(top + point[1] * k)

        for shape in element["page"]["shapes"]:
            if shape["type"] == "text":
                size = shape["px"] * k
                x, y = at((shape["x"], shape["y"]))
                put(x, down(y), shape["text"], bold_font if shape["weight"] >= 600 else regular, size, diagram_svg.INK,
                    {"start": "left", "middle": "center", "end": "right"}[shape["anchor"]])
                continue
            path = page_canvas.beginPath()
            rings = shape["rings"] if shape["type"] == "poly" else [shape["points"]]
            for ring in rings:
                for index, point in enumerate(ring):
                    (path.moveTo if index == 0 else path.lineTo)(*at(point))
                if shape["type"] == "poly" or shape["closed"]:
                    path.close()
            if shape["type"] == "poly":
                page_canvas.setFillColor(HexColor(shape["fill"]))
                page_canvas.setFillAlpha(shape["opacity"])
                if shape["stroke"]:
                    stroke(shape["stroke"], shape["width"] * k)
                page_canvas.drawPath(path, stroke=1 if shape["stroke"] else 0, fill=1, fillMode=canvas.FILL_EVEN_ODD)
                page_canvas.setFillAlpha(1)
            else:
                stroke(shape["stroke"], max(shape["width"] * k, 0.25), shape["dashed"])
                page_canvas.drawPath(path, stroke=1, fill=0)
        page_canvas.setDash([])

    for page in made:
        for element in page["elements"]:
            kind = element["type"]
            if kind == "title":
                block(element, [element["text"]], font=bold_font, size=element["size"], color=INK, anchor="bottom")
            elif kind == "text":
                block(element, element["paras"], font=bold_font if element["bold"] else regular, size=element["size"], color=element["color"],
                      bullets=element["bullets"], where=element["align"], anchor=element["anchor"],
                      gap=element["size"] * 0.5 if element["bullets"] else 0.0)
            elif kind == "swatch":
                page_canvas.setFillColor(HexColor(element["color"]))
                page_canvas.rect(element["x"], down(element["y"] + element["size"]), element["size"], element["size"], stroke=0, fill=1)
            elif kind == "rule":
                stroke(element["color"], element["width"])
                page_canvas.line(element["x1"], down(element["y1"]), element["x2"], down(element["y2"]))
            elif kind == "picture":
                page_canvas.drawImage(element["path"], element["x"], down(element["y"] + element["h"]), element["w"], element["h"], mask="auto")
            elif kind == "diagram":
                diagram(element)
            elif kind == "table":
                size, row_h = element["size"], element["row_h"]
                for index, (label, value) in enumerate(element["rows"]):
                    baseline = element["y"] + index * row_h + row_h / 2 + size * 0.36
                    put(element["x"] + 4, baseline, label, regular, size, MUTED)
                    put(element["x"] + element["w"] - 4, baseline, value, regular, size, INK, "right")
                    stroke(HAIR, 0.75)
                    under = element["y"] + (index + 1) * row_h
                    page_canvas.line(element["x"], down(under), element["x"] + element["w"], down(under))
            else:  # an empty place
                stroke(MUTED, 0.75, dashed=True)
                page_canvas.rect(element["x"], down(element["y"] + element["h"]), element["w"], element["h"], stroke=1, fill=0)
                page_canvas.setDash([])
                block(element, element["paras"], font=regular, size=12.0, color=MUTED, where="center", anchor="middle")
        page_canvas.showPage()
    page_canvas.save()
    return out.getvalue()


# ---------------------------------------------------------------------------
# The files a designer downloads
# ---------------------------------------------------------------------------


def file_stem(title: str) -> str:
    """A file name from the deck's title: what a file system refuses is taken out."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title or "")
    name = " ".join(name.split()).strip(". ")[:60].strip()
    return f"{name} 발표자료" if name else "발표자료"


def bundle(project_path: Path, deck: dict, mats: dict, made: list[dict]) -> bytes:
    """
    Everything at once, as a zip: the PowerPoint file and the PDF, every diagram that can be drawn
    (SVG), every capture of the snapshot (PNG) and the figures as a table (CSV that Excel opens).
    """
    path = Path(project_path)
    stem = file_stem(deck["title"])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{stem}.pptx", to_pptx(made, deck["title"]))
        archive.writestr(f"{stem}.pdf", to_pdf(made, deck["title"]))
        saved = mats["snapshot"]
        if saved is not None:
            for item in mats["items"].values():
                if not item["ready"]:
                    continue
                if item["kind"] == "diagram":
                    kind = item["key"].split(":", 1)[1]
                    ctx = diagrams.context(path) if kind == "site" else mats["context"]
                    archive.writestr(f"다이어그램/{item['title']}.svg", diagram_svg.to_svg(diagrams.drawing(kind, saved, ctx)))
            for view in saved["views"]:
                try:
                    archive.write(snap.view_file(path, saved["id"], view["file"]), f"라이노 뷰/{view['file']}")
                except (snap.SnapshotNotFound, ValueError, OSError):
                    continue
            if mats["items"][deck_slides.FIGURES_KEY]["ready"]:
                table = io.StringIO()
                writer = csv.writer(table, lineterminator="\r\n")
                writer.writerow(["항목", "값"])
                writer.writerows((label.strip(), value) for label, value in deck_slides.figure_rows(mats["figures"], mats["limits"]))
                archive.writestr("수치.csv", table.getvalue().encode("utf-8-sig"))
    return out.getvalue()


def make(project_path: Path, document: str | None, fmt: str) -> tuple[bytes, str]:
    """
    The deck of the project as it stands, as one file: (bytes, file name). `document` is the
    presentation editor's document (None when it has not run: the deck is then the default one).
    Raises ValueError for an unknown format.
    """
    if fmt not in FORMATS:
        raise ValueError("format must be one of " + ", ".join(FORMATS))
    path = Path(project_path)
    mats = deck_slides.materials(path)
    deck = deck_slides.deck(path, document, mats)
    made = pages(deck, mats, path)
    if fmt == "pptx":
        return to_pptx(made, deck["title"]), f"{file_stem(deck['title'])}.pptx"
    if fmt == "pdf":
        return to_pdf(made, deck["title"]), f"{file_stem(deck['title'])}.pdf"
    return bundle(path, deck, mats, made), f"{file_stem(deck['title'])}.zip"
