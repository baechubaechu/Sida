"""The section through the drawing table (sida/board_section.py)."""

from __future__ import annotations

from types import SimpleNamespace

import ezdxf
import pytest

from sida import board, board_section


def square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def flat(z=0.0, half=50, step=10):
    n = 2 * half // step + 1
    return {"min_x": -half, "min_y": -half, "step": step, "nx": n, "ny": n, "z": [z] * (n * n)}


def test_the_line_looks_to_its_right_and_reads_as_the_viewer_sees_it():
    north = board_section.line_frame([[0, 0], [0, 10]])
    assert north["n"] == pytest.approx((1, 0)) and north["mirror"] is True  # looking east, A (south) on the right
    flipped = board_section.line_frame([[0, 0], [0, 10]], flip=True)
    assert flipped["n"] == pytest.approx((-1, 0)) and flipped["mirror"] is False
    with pytest.raises(ValueError):
        board_section.line_frame([[1, 1], [1, 1]])


def test_spans_find_every_stretch_inside_a_concave_footprint():
    u_shape = [[0, 0], [30, 0], [30, 20], [20, 20], [20, 5], [10, 5], [10, 20], [0, 20]]
    got = board_section.spans((-5, 10), (1, 0), 50, u_shape)
    assert got == [pytest.approx((5, 15)), pytest.approx((25, 35))]
    assert board_section.spans((-5, 2), (1, 0), 50, u_shape) == [pytest.approx((5, 35))]
    assert board_section.spans((-5, 30), (1, 0), 50, u_shape) == []
    assert board_section.spans((-5, 10), (1, 0), 8, u_shape) == [pytest.approx((5, 8))]  # the line ends inside


def test_cut_and_beyond_follow_the_side_and_the_depth():
    solids = [
        {"kind": "mass", "outline": square(-5, -5, 5, 5), "base": 0, "top": 12},
        {"kind": "building", "outline": square(10, 20, 20, 30), "base": 0, "top": 9},  # 20 m beyond, looking north
        {"kind": "building", "outline": square(-20, 80, -10, 90), "base": 0, "top": 30},  # 80 m beyond
        {"kind": "building", "outline": square(0, -30, 10, -20), "base": 0, "top": 30},  # behind the viewer
    ]
    line = [[30, 0], [-30, 0]]  # walking west, it looks to its right: north
    got = board_section.cut(line, solids, None, depth=60)
    assert [(c["kind"], c["a"], c["b"]) for c in got["cut"]] == [("mass", 25, 35)]
    assert [(c["a"], c["b"], c["dist"]) for c in got["beyond"]] == [(10, 20, 20)]
    deep = board_section.cut(line, solids, None, depth=100)
    assert [c["dist"] for c in deep["beyond"]] == [80, 20]  # far first, so nearer ones cover them
    back = board_section.cut(line, solids, None, flip=True, depth=100)
    assert [(c["a"], c["b"]) for c in back["beyond"]] == [(20, 30)]


def test_the_profile_leaves_out_ground_that_is_not_known():
    ground = flat(2.0, half=20, step=5)
    got = board_section.cut([[-30, 0], [30, 0]], [], ground)
    assert len(got["profile"]) == 1
    run = got["profile"][0]
    assert run[0] == [10.0, 2.0] and run[-1] == [50.0, 2.0]
    round_range = {**flat(1.0, half=20, step=5), "clip_radius": 10}
    assert board_section.cut([[-30, 0], [30, 0]], [], round_range)["profile"][0][0] == [20.0, 1.0]
    assert board_section.cut([[-30, 0], [30, 0]], [], None)["profile"] == []


def hooks_with(ground=None, buildings=()):
    return [("site", SimpleNamespace(board_surroundings=lambda path: {"ground": ground, "buildings": list(buildings)}))]


def test_section_of_cuts_the_scheme_on_its_ground_and_leaves_the_old_building_on_the_site_out(tmp_path):
    board.add_paper(tmp_path, {"kind": "mass", "id": "m1", "title": "안 1", "blocks": [{"u": 0, "v": 0, "w": 20, "d": 10, "floors": 5}]})
    board.add_paper(tmp_path, {"kind": "mass", "id": "m2", "blocks": [{"u": 0, "v": 0, "w": 20, "d": 10, "floors": 2}], "floor_height": 3})
    board.add_paper(tmp_path, {"kind": "section", "id": "s1", "title": "B", "line": [[0, -40], [0, 40]]})
    ground = flat(-1.5)
    old = {"outline": square(-6, -3, 6, 3), "base": -1.5, "height": 20, "on_site": True}
    near = {"outline": square(-5, 20, 5, 30), "base": -2, "height": 15, "estimate": True}
    found = board_section.section_of(tmp_path, "s1", hooks=hooks_with(ground, [old, near]))
    assert found["scheme"] == "안 1" and found["ground_known"] is True
    mass, building = found["result"]["cut"]
    assert (mass["base"], mass["top"], mass["floors"]) == (-1.5, pytest.approx(19.5), 5)
    assert (building["kind"], building["top"], building["estimate"]) == ("building", 13, True)
    other = board_section.section_of(tmp_path, "s1", active="m2", hooks=hooks_with())
    assert other["result"]["cut"][0]["top"] == 6 and other["ground_known"] is False
    with pytest.raises(ValueError):
        board_section.section_of(tmp_path, "m1", hooks=hooks_with())
    with pytest.raises(ValueError):
        board_section.section_of(tmp_path, "s1", active="nope", hooks=hooks_with())
    with pytest.raises(board.PaperNotFound):
        board_section.section_of(tmp_path, "gone", hooks=hooks_with())


def test_the_drawing_hides_what_stands_behind_nearer_buildings_and_under_the_ground():
    solids = [
        {"kind": "building", "outline": square(-10, 5, 10, 15), "base": -3, "top": 10},  # beyond, near
        {"kind": "building", "outline": square(-5, 40, 5, 50), "base": -3, "top": 20},  # beyond, far, taller, behind it
    ]
    result = board_section.cut([[-30, 0], [30, 0]], solids, flat(0.0, half=40, step=10), flip=True)
    assert [c["dist"] for c in result["beyond"]] == [40, 5]
    drawing = board_section.section_drawing({"paper": {"title": "C", "scale": 200}, "result": result, "scheme": "", "ground_known": True})
    far = [line["points"] for line in drawing["lines"] if line["part"] == "beyond"]
    # the far building's walls show only above the near one; the near one's run from the ground, not its foundation
    assert [[25.0, 10], [25.0, 20]] in far and [[35.0, 10], [35.0, 20]] in far
    assert [[25.0, 20], [35.0, 20]] in far  # its roof, whole
    assert [[20.0, 0.0], [20.0, 10.0]] in far  # the near one's wall from the ground
    assert not any(p[1] < 0 for line in far for p in line)
    assert {t["text"] for t in drawing["texts"]} >= {"C", "C′", "±0"}


@pytest.fixture
def drawing():
    solids = [{"kind": "mass", "outline": square(-5, -5, 5, 5), "base": 0, "top": 12, "floors": 3, "storey": 4, "name": "1동"},
              {"kind": "building", "outline": square(10, -5, 20, 5), "base": 0, "top": 6, "estimate": True}]
    result = board_section.cut([[-30, 0], [30, 0]], solids, flat(), flip=True)
    return board_section.section_drawing({"paper": {"title": "A", "scale": 500}, "result": result, "scheme": "안 1", "ground_known": True})


def test_the_drawing_has_floor_lines_heights_and_a_scale_bar(drawing):
    floors = [line["points"] for line in drawing["lines"] if line["part"] == "floors"]
    assert [p[0][1] for p in floors] == [4, 8]
    words = {t["text"] for t in drawing["texts"]}
    assert "12.0m 3층" in words and "+12.00" in words and "추정" in words and "단면 A–A′ · 1:500 · 안 1" in words
    assert {t["plain"] for t in drawing["texts"]} >= {"12.0m 3F", "est.", "SECTION A-A'  1:500"}


def test_the_files_are_an_svg_a_one_page_pdf_and_a_dxf_in_metres(drawing, tmp_path):
    svg = board_section.to_svg(drawing).decode()
    assert svg.startswith("<svg") and 'data-part="mass"' in svg and "추정" in svg
    pdf = board_section.to_pdf(drawing)
    assert pdf.startswith(b"%PDF-1.4") and b"/Count 1" in pdf and pdf.rstrip().endswith(b"%%EOF")
    (tmp_path / "s.dxf").write_bytes(board_section.to_dxf(drawing))
    doc = ezdxf.readfile(tmp_path / "s.dxf")
    assert doc.header["$INSUNITS"] == 6
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"단면-지형", "단면-매스", "단면-층선", "단면-주변", "단면-표기"} <= layers
    with pytest.raises(ValueError):
        board_section.export_section(tmp_path, "x", "png")
