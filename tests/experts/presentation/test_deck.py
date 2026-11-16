"""The deck as files: the same pages as an editable PowerPoint file, as PDF, and as a bundle."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from sida.experts.presentation import deck, slides
from sida.experts.rhino import diagram_svg, diagrams
from tests.experts.presentation.test_slides import (  # noqa: F401  (project is a fixture)
    document,
    masses_only,
    project,
    send,
    tiny_png,
)
from tests.experts.rhino.test_diagrams import ctx, studio

LISTED = [
    {"layout": "title", "title": "무교동 45 복합시설", "subtitle": "저층은 도시에 연다"},
    {"layout": "text", "title": "문제", "bullets": ["좁은 골목", "높은 용적률"], "notes": "30초 안에."},
    {"title": "프로그램", "figure": "diagram:program", "bullets": ["저층 상업", "서쪽 타워는 업무"], "caption": "Sida가 규칙으로 그림"},
    {"title": "수치", "figure": "figures"},
    {"title": "투시", "figure": "view:persp"},
    {"title": "야경", "figure": "view:night"},
]


@pytest.fixture(autouse=True)
def no_font_of_this_machine(monkeypatch):
    """The PDF is written the same on every machine: with the font a reader supplies, none embedded."""
    monkeypatch.setattr(deck, "font_files", lambda: [])


def made(project_dir, listed=LISTED):  # noqa: F811
    mats = slides.materials(project_dir)
    the_deck = slides.deck(project_dir, document(listed), mats)
    return the_deck, mats, deck.pages(the_deck, mats, project_dir)


def of(page: dict, kind: str) -> list[dict]:
    return [element for element in page["elements"] if element["type"] == kind]


def inside_the_slide(element: dict) -> bool:
    return (0 <= element["x"] and element["x"] + element.get("w", 0) <= deck.PAGE_W + 0.01
            and 0 <= element["y"] and element["y"] + element.get("h", 0) <= deck.PAGE_H + 0.01)


def test_every_slide_is_set_on_a_page_with_its_title_its_words_and_what_fills_its_figure(project):  # noqa: F811
    send(project)
    the_deck, _mats, pages = made(project)
    assert [page["number"] for page in pages] == [1, 2, 3, 4, 5, 6] and [page["title"] for page in pages] == [s["title"] for s in the_deck["slides"]]
    assert all(inside_the_slide(e) for page in pages for e in page["elements"] if e["type"] not in ("rule", "diagram"))

    cover, problem, program, figures, view, missing = pages
    assert of(cover, "title")[0]["size"] == deck.COVER_SIZE and of(cover, "text")[0]["paras"] == ["저층은 도시에 연다"]
    assert len(of(cover, "text")) == 1  # the cover carries no project name and page number below
    assert of(problem, "text")[0]["paras"] == ["좁은 골목", "높은 용적률"] and of(problem, "text")[0]["bullets"] is True
    assert [e["paras"] for e in of(problem, "text")[-2:]] == [["무교동 45"], ["2"]] and problem["notes"] == "30초 안에."

    (drawn,) = of(program, "diagram")
    assert drawn["page"]["kind"] == "program" and 0 < drawn["scale"] <= deck.MAX_DIAGRAM_SCALE
    assert not any(shape["type"] == "text" and shape["weight"] >= 600 for shape in drawn["page"]["shapes"])  # the slide has the title
    legend = [e["paras"][0] for e in of(program, "text") if e["size"] == deck.WORD_SIZE and e["color"] == deck.INK]
    assert legend[0].startswith("상업 2,880.0㎡") and len(of(program, "swatch")) == len(legend)  # the legend at a size that reads
    beside = next(e for e in of(program, "text") if e["bullets"])
    assert beside["paras"] == ["저층 상업", "서쪽 타워는 업무"] and beside["x"] > deck.PAGE_W / 2
    assert any(e["paras"] == ["Sida가 규칙으로 그림"] for e in of(program, "text"))

    (table,) = of(figures, "table")
    assert table["rows"] == slides.figure_rows(*(slides.materials(project)[k] for k in ("figures", "limits")))
    (picture,) = of(view, "picture")
    assert Path(picture["path"]).name == "persp.png" and picture["w"] / picture["h"] == pytest.approx(16 / 9)  # the capture's own shape
    assert of(missing, "empty")[0]["paras"] == ["view:night", "이 이름의 그림이 없습니다."]


def test_long_words_are_set_smaller_until_they_fit_and_never_below_the_least(project):  # noqa: F811
    lines = ["대지는 일반상업지역이며 조례 용적률이 적용되고 북쪽 골목은 폭이 좁아 저층부의 개방이 필요하다" * 2] * 8
    _deck, _mats, (page,) = made(project, [{"layout": "text", "title": "가" * 100, "bullets": lines}])
    assert deck.TITLE_LEAST <= of(page, "title")[0]["size"] < deck.TITLE_SIZE
    assert deck.TEXT_LEAST <= of(page, "text")[0]["size"] < deck.TEXT_SIZE
    short = made(project, [{"layout": "text", "title": "문제", "bullets": ["좁은 골목"]}])[2][0]
    assert of(short, "title")[0]["size"] == deck.TITLE_SIZE and of(short, "text")[0]["size"] == deck.TEXT_SIZE


def test_the_powerpoint_file_keeps_every_part_editable(project):  # noqa: F811
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    from pptx.util import Pt

    send(project)
    the_deck, _mats, pages = made(project)
    opened = Presentation(io.BytesIO(deck.to_pptx(pages, the_deck["title"])))
    assert (opened.slide_width, opened.slide_height) == (Pt(960), Pt(540)) and opened.core_properties.title == "무교동 45"
    cover, problem, program, figures, view, missing = opened.slides
    assert [slide.shapes.title.text_frame.text for slide in opened.slides] == [s["title"] for s in the_deck["slides"]]
    run = problem.shapes.title.text_frame.paragraphs[0].runs[0]
    assert run.font.name == deck.FONT and run.font.bold and 'a:ea typeface="Malgun Gothic"' in problem.shapes.title._element.xml

    bullets = next(s for s in problem.shapes if s.has_text_frame and s.text_frame.text.startswith("좁은 골목"))
    assert [p.text for p in bullets.text_frame.paragraphs] == ["좁은 골목", "높은 용적률"] and bullets._element.xml.count("a:buChar") == 2
    assert problem.notes_slide.notes_text_frame.text == "30초 안에." and not cover.has_notes_slide

    (group,) = [s for s in program.shapes if s.shape_type == MSO_SHAPE_TYPE.GROUP]
    assert group.name == "Sida diagram (program)" and len(group.shapes) > 5 and group.width > 0 and group.height > 0
    xml = group._element.xml
    assert "p:style" not in xml and "a:custGeom" in xml  # shapes drawn as they are, nothing taken from the theme
    lids = [s for s in group.shapes if s._element.xml.count("<a:moveTo>") >= 2 and s._element.xml.count("<a:path ") == 1]
    assert lids  # the podium's lid with its courtyard cut out of it: one path of two rings

    table = next(s for s in figures.shapes if s.has_table).table
    assert [(row.cells[0].text, row.cells[1].text) for row in table.rows] == [tuple(r) for r in of(pages[3], "table")[0]["rows"]]
    (picture,) = [s for s in view.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert picture.image.content_type == "image/png" and picture.width / picture.height == pytest.approx(16 / 9, rel=1e-3)
    assert any(s.has_text_frame and "이 이름의 그림이 없습니다." in s.text_frame.text for s in missing.shapes)


def test_faces_painted_one_after_another_in_one_colour_become_one_powerpoint_shape():
    face = {"type": "poly", "rings": [[(0, 0), (1, 0), (1, 1)]], "fill": "#aa0000", "opacity": 1.0, "stroke": "#000000", "width": 0.7, "tag": "face"}
    other = {**face, "fill": "#00aa00"}
    flat = {**face, "tag": "fill", "stroke": None}
    line = {"type": "line", "points": [(0, 0), (1, 1)], "closed": False, "stroke": "#000000", "width": 1.0, "dashed": False, "tag": "line"}
    joined = deck._faces([face, face, other, face, line, face, flat, flat])
    assert [(s["type"], len(s.get("paths", []))) for s in joined] == [("poly", 2), ("poly", 1), ("poly", 1), ("line", 0), ("poly", 1),
                                                                    ("poly", 1), ("poly", 1)]


def test_the_pdf_has_one_page_a_slide_and_korean_letters_from_a_font_a_reader_has(project):  # noqa: F811
    send(project)
    the_deck, _mats, pages = made(project)
    data = deck.to_pdf(pages, the_deck["title"])
    assert data.startswith(b"%PDF-") and len(re.findall(rb"/Type\s*/Page\b", data)) == len(pages)
    assert b"HYGothic-Medium" in data and b"/MediaBox [ 0 0 960 540 ]" in data
    assert deck.pdf_fonts() == ("HYGothic-Medium", "HYGothic-Medium")


def test_words_break_at_spaces_and_a_word_longer_than_a_line_is_cut():
    def measure(text):
        return len(text) * 10.0

    assert deck.wrap("저층은 도시에 열고 고층은 나눈다", 80.0, measure) == ["저층은 도시에", "열고 고층은", "나눈다"]
    assert deck.wrap("abcdefghijkl mn", 50.0, measure) == ["abcde", "fghij", "kl mn"]
    assert deck.wrap("", 50.0, measure) == [""]


def test_the_bundle_holds_both_files_every_diagram_every_capture_and_the_figures(project):  # noqa: F811
    send(project)
    the_deck, mats, pages = made(project)
    with zipfile.ZipFile(io.BytesIO(deck.bundle(project, the_deck, mats, pages))) as archive:
        names = archive.namelist()
        assert names[:2] == ["무교동 45 발표자료.pptx", "무교동 45 발표자료.pdf"]
        assert {n for n in names if n.startswith("다이어그램/")} == {f"다이어그램/{about['title']}.svg" for about in diagrams.KINDS.values()}
        assert {n for n in names if n.startswith("라이노 뷰/")} == {"라이노 뷰/plan.png", "라이노 뷰/persp.png", "라이노 뷰/plan-2.png"}
        assert archive.read("다이어그램/프로그램 매스.svg") == diagram_svg.to_svg(diagrams.drawing("program", mats["snapshot"], ctx()))
        table = archive.read("수치.csv").decode("utf-8-sig").splitlines()
        assert table[0] == "항목,값" and '연면적,"6,080.0㎡"' in table and "상업,\"2,880.0㎡\"" in table


def test_a_file_is_made_of_the_project_as_it_stands_even_before_rhino_or_the_editor(project):  # noqa: F811
    data, name = deck.make(project, None, "pptx")
    assert name == "무교동 45 발표자료.pptx" and data.startswith(b"PK")
    data, name = deck.make(project, None, "pdf")
    assert name == "무교동 45 발표자료.pdf" and len(re.findall(rb"/Type\s*/Page\b", data)) == 1
    send(project, **masses_only())
    data, name = deck.make(project, document(LISTED), "zip")
    assert name == "무교동 45 발표자료.zip" and "다이어그램/층별 분해.svg" not in zipfile.ZipFile(io.BytesIO(data)).namelist()
    with pytest.raises(ValueError, match="format must be one of pptx, pdf, zip"):
        deck.make(project, None, "key")
    assert deck.file_stem('a/b:c*?"<>|  d. ') == "a b c d 발표자료" and deck.file_stem("") == "발표자료"
    assert studio()["rhino"]["file"] == "studio.3dm"
