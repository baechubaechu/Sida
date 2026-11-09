"""The road paint of the 정밀도로지도 drawn as shapes (road_marks), on made-up marks."""

from __future__ import annotations

import numpy as np
import pytest

from sida.experts.site import road_marks


def rect(cx, cy, length, width, along=(1.0, 0.0)):
    """A closed rectangle `length` m along `along` and `width` m across, around (cx, cy)."""
    a = np.asarray(along, dtype=float) / np.hypot(*along)
    c = np.array([-a[1], a[0]])
    pts = [np.array([cx, cy]) + a * u + c * v for u, v in
           ((-length / 2, -width / 2), (length / 2, -width / 2), (length / 2, width / 2), (-length / 2, width / 2))]
    ring = [list(map(float, p)) for p in pts]
    return ring + [ring[0]]


def points_of(shapes):
    return np.asarray([p for s in shapes for p in s], dtype=float)


def test_a_lane_lines_codes_give_its_colour_dashes_and_width():
    assert road_marks.line_style("111", "515") == {"color": "yellow", "width": 0.15, "lines": [(0.0, False)]}
    assert road_marks.line_style("212", "503") == {"color": "white", "width": 0.15, "lines": [(0.0, True)]}
    assert road_marks.line_style("211", "530")["width"] == road_marks.STOP_WIDTH  # a stop line
    assert road_marks.line_style("311", "504")["color"] == "blue"
    double = road_marks.line_style("123", "501")  # yellow double, dashed on the left
    assert double["lines"] == [(0.15, True), (-0.15, False)]


def test_a_dashed_line_is_painted_three_metres_in_eight_from_its_start():
    pieces = road_marks.dashes([(0, 0), (10, 0), (20, 0)])
    assert [(p[0][0], p[-1][0]) for p in pieces] == [(0, 3), (8, 11), (16, 19)]
    assert len(pieces[1]) == 3  # the corner at x = 10 stays in the piece that crosses it


def test_a_line_moved_to_its_left_keeps_its_corners_square():
    moved = road_marks.offset([(0, 0), (10, 0), (10, 10)], 1.0)
    assert moved[0] == pytest.approx((0, 1)) and moved[1] == pytest.approx((9, 1)) and moved[2] == pytest.approx((9, 10))
    pieces = road_marks.strokes([(0, 0), (10, 0)], "121", "501")  # a double line: two, either side
    assert sorted(round(p[0][1], 2) for _c, _w, p in pieces) == [-0.15, 0.15]


def test_an_arrow_points_the_way_its_link_runs():
    ring = rect(0, 0, 5, 0.7)
    east = road_marks.mark_shapes("1", "5371", ring, ahead=(1.0, 0.0))
    west = road_marks.mark_shapes("1", "5371", ring, ahead=(-1.0, 0.0))
    assert east["name"] == "직진" and east["outline"] is None
    tip_e = max(east["shapes"][-1], key=lambda p: p[0])
    tip_w = min(west["shapes"][-1], key=lambda p: p[0])
    assert tip_e[0] == pytest.approx(2.5) and tip_w[0] == pytest.approx(-2.5)  # the head at the far end
    pts = points_of(east["shapes"])
    assert np.abs(pts[:, 1]).max() <= 0.35 + 1e-9  # inside the rectangle the file gives


def test_a_left_turn_arrow_turns_left_of_the_way_it_points():
    north = road_marks.mark_shapes("1", "5372", rect(0, 0, 5, 1.1, along=(0, 1)), ahead=(0.0, 1.0))
    pts = points_of(north["shapes"])
    head = np.asarray(north["shapes"][-1])
    assert head[:, 0].min() == pytest.approx(pts[:, 0].min())  # its head is the westmost point (left)
    shaft = np.asarray(north["shapes"][0])
    assert shaft[:, 0].mean() > 0 and shaft[:, 1].min() == pytest.approx(-2.5)  # the shaft runs up the east side
    right = road_marks.mark_shapes("1", "5373", rect(0, 0, 5, 1.1, along=(0, 1)), ahead=(0.0, 1.0))
    assert np.asarray(right["shapes"][-1])[:, 0].max() == pytest.approx(points_of(right["shapes"])[:, 0].max())


def test_every_arrow_kind_is_drawn_inside_its_rectangle():
    ring = rect(3, 4, 5, 1.1, along=(1, 1))
    for kind in road_marks.ARROWS:
        drawn = road_marks.mark_shapes("1", kind, ring, ahead=(4, 5))
        assert drawn["shapes"] and drawn["outline"] is None
        local = points_of(drawn["shapes"]) - [3, 4]
        along, across = local @ np.array([1, 1]) / 2 ** 0.5, local @ np.array([-1, 1]) / 2 ** 0.5
        assert np.abs(along).max() <= 2.5 + 1e-6 and np.abs(across).max() <= 0.55 + 1e-6


def test_without_a_link_an_arrow_is_only_its_outline_and_an_unknown_mark_too():
    ring = rect(0, 0, 5, 0.7)
    drawn = road_marks.mark_shapes("1", "5371", ring, ahead=None)
    assert drawn["shapes"] == [] and len(drawn["outline"]) == 5  # the way is not known: no arrow made up
    other = road_marks.mark_shapes("5", "534", ring, ahead=(1, 0))
    assert other["shapes"] == [] and other["name"] == "노면표시"


def test_a_crossing_is_stripes_that_run_with_the_traffic():
    ring = rect(0, 0, 4, 10)  # 4 m along the traffic (east), 10 m across the road
    drawn = road_marks.mark_shapes("5", "5321", ring, ahead=(1.0, 0.0))
    assert drawn["name"] == "횡단보도" and len(drawn["shapes"]) == 10
    for stripe in drawn["shapes"]:
        s = np.asarray(stripe)
        assert np.ptp(s[:, 0]) == pytest.approx(4) and np.ptp(s[:, 1]) == pytest.approx(road_marks.STRIPE)
    no_link = road_marks.mark_shapes("5", "5321", ring, ahead=None)  # along the short side
    assert np.ptp(np.asarray(no_link["shapes"][0])[:, 0]) == pytest.approx(4)


def test_the_paint_is_laid_on_the_ground_and_grouped_by_colour():
    def z_at(x, y):
        return np.asarray(x, dtype=float) * 0.1  # a slope up to the east

    lines = [{"type": "111", "kind": "515", "points": [(0, 0), (10, 0)]},
             {"type": "112", "kind": "515", "points": [(0, 5), (20, 5)]},
             {"type": "212", "kind": "503", "points": [(0, 9), (9, 9)]}]
    marks = [{"type": "1", "kind": "5371", "ring": rect(5, 2, 5, 0.7), "ahead": (6, 2)}]
    out = road_marks.drawing(lines, marks, z_at, gap=2.0)
    by_colour = {(g["color"], g["width"]): g["pieces"] for g in out["lines"]}
    assert set(by_colour) == {("yellow", 0.15), ("white", 0.15)}
    assert len(by_colour[("yellow", 0.15)]) == 1 + 3  # the solid line and three dashes
    solid = np.asarray(by_colour[("yellow", 0.15)][0])
    assert np.diff(solid[:, 0]).max() <= 2.0 + 1e-9  # a point every 2 m so it follows the ground
    assert solid[:, 2] == pytest.approx(solid[:, 0] * 0.1 + road_marks.LIFT, abs=0.01)
    (arrow,) = out["marks"]
    assert arrow["kind"] == "5371" and arrow["outline"] is None
    assert all(p[2] == pytest.approx(p[0] * 0.1 + road_marks.LIFT, abs=0.01) for s in arrow["shapes"] for p in s)
