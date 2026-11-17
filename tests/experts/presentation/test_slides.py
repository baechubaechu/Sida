"""The deck as data: the slides the presentation editor listed, and what Sida can put on them."""

from __future__ import annotations

import json

import pytest

from sida.experts import FACTS, ExpertRun
from sida.experts.presentation import hooks, slides
from sida.experts.rhino import diagrams
from sida.experts.rhino import snapshot as snap
from tests.experts.rhino.test_diagrams import ctx, studio


def tiny_png(width: int = 4, height: int = 2) -> bytes:
    """A real (grey) PNG of this size: the files read a capture's size from it."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + b"\x80" * (3 * width) for _ in range(height))
    return snap.PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def document(listed: list[dict], before: str = "# Presentation Editor\n\n## One-line Summary\n- 저층은 연다\n") -> str:
    return f"{before}\n```json\n{json.dumps({'slides': listed}, ensure_ascii=False)}\n```\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project folder with a brief and a site (area, lot, one zone with an ordinance); no Rhino snapshot yet."""
    (tmp_path / "brief.md").write_text("# Brief\n\n## Project Name\n무교동 45\n", encoding="utf-8")
    monkeypatch.setattr(diagrams, "context", lambda path, hooks=None, around=True: ctx())
    return tmp_path


def send(project, **changes) -> dict:
    """The studio model (test_diagrams) sent from Rhino, with a perspective and two plans captured."""
    views = [{"kind": "plan", "file": "plan.png"}, {"kind": "persp", "file": "persp.png"}, {"kind": "plan", "file": "plan-2.png"}]
    return snap.save_snapshot(project, {**studio(), "views": views, **changes}, {v["file"]: tiny_png(16, 9) for v in views})


def masses_only() -> dict:
    """The same model with no floor counted in it: masses can be drawn, floors cannot."""
    return {"objects": [{**item, "floors": []} for item in studio()["objects"]],
            "layers": [{**layer, "floor_height": None} for layer in studio()["layers"]]}


def test_the_slide_list_is_the_last_fenced_json_that_holds_one_and_the_document_is_shown_without_it():
    board = '```json\n{"board": "A1", "scale": 500}\n```\n'
    text = document([{"title": "하나"}], before=f"# Presentation Editor\n\n## Key Outputs\n- 다이어그램\n\n{board}")
    assert slides.read_block(text) == [{"title": "하나"}]
    assert slides.read_block(text + "\n```json\n{not json}\n```\n") == [{"title": "하나"}]  # a broken block after it is passed over
    assert slides.read_block(board) is None and slides.read_block("no block") is None and slides.read_block(None) is None
    assert slides.read_block('```json\n{"slides": "three"}\n```') is None
    shown = slides.without_block(text)
    assert "```" not in shown and shown.startswith("# Presentation Editor") and shown.endswith("- 다이어그램")


def test_listed_slides_are_checked_cut_to_length_and_given_the_layout_their_content_asks_for():
    listed, notes = slides.clean([
        {"title": "  무교동   45  ", "subtitle": "저층은 연다"},                      # no layout, first, no bullets: the title slide
        {"layout": "figure", "title": "문제", "bullets": ["좁은 골목", "", 7, {"x": 1}, ["y"]]},  # says figure but names none: text
        {"layout": "text", "title": "프로그램", "figure": "diagram:program", "caption": "규칙으로 그림", "notes": " 30초 \n"},
        {"layout": "poster", "bullets": [f"{i}번" for i in range(11)]},
        {"caption": "says nothing"}, "not a slide", {"title": "가" * 500, "notes": 3},
    ])
    assert [s["layout"] for s in listed] == ["title", "text", "figure", "text", "text"]
    assert listed[0]["title"] == "무교동 45" and listed[0]["subtitle"] == "저층은 연다"
    assert listed[1]["bullets"] == ["좁은 골목", "7"] and listed[1]["figure"] == ""
    assert listed[2]["figure"] == "diagram:program" and listed[2]["caption"] == "규칙으로 그림" and listed[2]["notes"] == "30초"
    assert len(listed[3]["bullets"]) == slides.MAX_BULLETS and notes == [f"4번 슬라이드의 항목은 {slides.MAX_BULLETS}개까지만 넣었습니다."]
    assert len(listed[4]["title"]) == slides.MAX_TITLE and listed[4]["notes"] == ""

    many, said = slides.clean([{"title": f"{i}"} for i in range(slides.MAX_SLIDES + 3)])
    assert len(many) == slides.MAX_SLIDES and said == [f"슬라이드는 {slides.MAX_SLIDES}장까지만 만듭니다. 나머지 3장은 넣지 않았습니다."]


def test_materials_are_the_newest_snapshots_diagrams_captures_and_figures_each_ready_or_saying_why_not(project):
    empty = slides.materials(project)
    assert empty["snapshot"] is None and empty["figures"] is None and not any(item["ready"] for item in empty["items"].values())
    assert set(empty["items"]) == {"diagram:program", "diagram:floors", "diagram:stack", "diagram:site", "diagram:limits", "figures"}
    assert "라이노에서 Sida로 보내면" in empty["items"]["figures"]["why"] and empty["source"] is None

    saved = send(project)
    mats = slides.materials(project)
    assert mats["snapshot"]["id"] == saved["id"] and mats["figures"]["floor_area_m2"] == 6080.0 and mats["limits"] == ctx()["limits"]
    assert list(mats["items"]) == ["diagram:program", "diagram:floors", "diagram:stack", "diagram:site", "diagram:limits",
                                   "view:persp", "view:plan", "figures"]  # captures in the order a deck shows them
    assert all(item["ready"] for item in mats["items"].values())
    assert mats["items"]["view:plan"] == {"key": "view:plan", "kind": "view", "title": "라이노 평면 뷰", "ready": True, "why": "",
                                          "file": "plan.png"}  # the first plan stands for the kind
    assert mats["items"]["diagram:program"]["title"] == "프로그램 매스"

    send(project, **masses_only())
    flat = slides.materials(project)["items"]
    assert flat["diagram:program"]["ready"] and not flat["diagram:floors"]["ready"]
    assert flat["diagram:floors"]["why"] == diagrams.NOT_READY["no_floors"]


def test_the_figures_table_says_sidas_figures_with_the_limit_a_ratio_is_set_against(project):
    send(project)
    mats = slides.materials(project)
    rows = dict(slides.figure_rows(mats["figures"], mats["limits"]))
    fig = mats["figures"]
    assert rows["대지면적"] == "3,600.0㎡" and rows["연면적"] == f"{fig['floor_area_m2']:,.1f}㎡" == "6,080.0㎡"
    assert rows["  상업"] == "2,880.0㎡" and rows["  업무"] == "3,200.0㎡"  # by meaning, under the total
    assert rows["건폐율"] == f"{fig['coverage_pct']:,.1f}% (조례 60%)" and rows["용적률"] == f"{fig['far_pct']:,.1f}% (조례 800%)"
    assert rows["최고 높이"] == "45.0m"

    unknown = dict(slides.figure_rows(snap.figures(mats["snapshot"], None), []))
    assert unknown["대지면적"] == unknown["건폐율"] == unknown["용적률"] == "미확인"  # no site: nothing is made up
    two_zones = dict(slides.figure_rows(fig, [*mats["limits"], {**mats["limits"][0], "zone": "제3종일반주거지역"}]))
    assert two_zones["건폐율"] == f"{fig['coverage_pct']:,.1f}%"  # across zones no one limit holds


def test_without_a_list_the_deck_is_laid_out_by_rule_from_what_can_be_made(project):
    bare = slides.deck(project, None)
    assert bare["source"] == "default" and bare["title"] == "무교동 45" and bare["snapshot"] is None and bare["notes"] == []
    assert [(s["layout"], s["title"], s["figure"]) for s in bare["slides"]] == [("title", "무교동 45", None)]

    saved = send(project)
    made = slides.deck(project, "# Presentation Editor\n\n(an older document, without a list)\n")
    assert made["source"] == "default" and made["snapshot"] == {"id": saved["id"], "taken_at": saved["taken_at"], "file": "studio.3dm"}
    assert [s["figure"]["key"] if s["figure"] else None for s in made["slides"]] == [
        None, "figures", "diagram:program", "diagram:floors", "diagram:stack", "diagram:site", "diagram:limits", "view:persp", "view:plan"]
    assert all(s["bullets"] == [] and s["caption"] == "" for s in made["slides"])  # no sentence is written by rule
    assert made["slides"][2]["title"] == "프로그램 매스" and made["slides"][2]["layout"] == "figure"

    (project / "brief.md").write_text("# Brief\n", encoding="utf-8")
    assert slides.deck(project, None)["title"] == project.name  # no name in the brief: the folder's


def test_the_editors_list_sets_the_order_and_a_figure_it_cannot_have_keeps_its_place_and_is_said(project):
    send(project, **masses_only())
    made = slides.deck(project, document([
        {"layout": "title", "title": "무교동 45 복합시설", "subtitle": "저층은 연다"},
        {"title": "프로그램", "figure": "diagram:program", "bullets": ["저층 상업"]},
        {"title": "층별", "figure": "diagram:floors"},
        {"title": "야경", "figure": "view:night"},
        {"title": "수치", "figure": "figures"},
    ]))
    assert made["source"] == "editor" and [s["title"] for s in made["slides"]] == ["무교동 45 복합시설", "프로그램", "층별", "야경", "수치"]
    assert made["slides"][1]["figure"] == {"key": "diagram:program", "kind": "diagram", "title": "프로그램 매스", "ready": True, "why": ""}
    assert made["slides"][2]["figure"]["ready"] is False and made["slides"][3]["figure"] == {
        "key": "view:night", "kind": "view", "title": "view:night", "ready": False, "why": "이 이름의 그림이 없습니다."}
    assert made["notes"] == [
        f"3번 슬라이드의 그림(층별 분해)은 비어 있습니다. {diagrams.NOT_READY['no_floors']}",
        "4번 슬라이드의 그림(view:night)은 비어 있습니다. 이 이름의 그림이 없습니다.",
    ]
    assert slides.deck(project, document([{"caption": "nothing to show"}]))["source"] == "default"  # an empty list is no list


def test_the_presentation_editor_is_told_the_keys_it_may_place_and_no_other_expert_is(project):
    def run_for(agent_id: str) -> ExpertRun:
        return ExpertRun(config={}, agent={"id": agent_id}, project_dir=project, project_brief="", project_state=None,
                         previous_outputs="", warn=lambda message: None)

    assert hooks.prompt_blocks(run_for("design_critic")) == []
    (block,) = hooks.prompt_blocks(run_for("presentation_editor"))
    assert block.slot == FACTS and block.text.startswith("## Slide Materials") and "no Rhino snapshot and no massing scheme" in block.text

    send(project, **masses_only())
    (block,) = hooks.prompt_blocks(run_for("presentation_editor"))
    assert "- `diagram:program`: 프로그램 매스\n" in block.text and "- `view:persp`: 라이노 투시 뷰\n" in block.text
    assert f"- `diagram:floors`: 층별 분해 (cannot be made now: {diagrams.NOT_READY['no_floors']})" in block.text
    assert "- 일반상업지역: 법정 건폐율 80% 이하, 용적률 1300% 이하 (조례 건폐율 60%, 용적률 800%)" in block.text
    assert hooks.EDITOR == slides.EDITOR
