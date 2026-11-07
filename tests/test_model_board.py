"""A model board laid on the ground (sida/model_base/board.py), and the nesting that lays its buildings out."""

import hashlib

import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box

from sida.model_base import board
from sida.model_base.buildings import Building
from sida.model_base.nesting import nest
from sida.model_base.pieces import Piece, slice_terrain
from sida.model_base.terrain import example_terrain, terrain_in_frame


def digest(layout) -> str:
    rows = "\n".join(f"{p.piece.id}:{p.sheet}:{p.angle:g}:{p.dx:.3f}:{p.dy:.3f}" for p in layout.placements)
    return hashlib.sha256(rows.encode()).hexdigest()[:16]


def stacks() -> list[Piece]:
    """30 building outlines, many of them stacked several sheets high (pieces of the same shape)."""
    out = []
    for i in range(30):
        w, h = 6 + (i * 7) % 17, 5 + (i * 5) % 11
        shape = Polygon([(0, 0), (w, 0), (w, h), (w * 0.4, h)])
        for k in range(1 + i % 5 * 2):
            out.append(Piece(id=f"B{i:02d}.{k + 1}", layer=1, level_m=0.0, shape=shape, kind="building"))
    return out


def test_boards_lie_landscape_or_portrait_and_custom_sides_are_checked():
    assert board.board_size("W600x900") == (900.0, 600.0)
    assert board.board_size("A1", "portrait") == (594.0, 841.0)
    assert board.board_size(board.CUSTOM, "landscape", (400, 700)) == (700.0, 400.0)
    for bad in (("A9", "landscape", None), ("A1", "diagonal", None), (board.CUSTOM, "landscape", (50, 700)),
                (board.CUSTOM, "landscape", None)):
        with pytest.raises(ValueError):
            board.board_size(*bad)
    assert board.frame_size((900, 600), 500) == (450.0, 300.0)  # 900 mm at 1:500 is 450 m
    with pytest.raises(ValueError):
        board.check_scale(500.5)
    with pytest.raises(ValueError):
        board.check_thickness(0.1)


def test_a_frame_past_the_range_says_by_how_much():
    square = box(-300, -200, 300, 200)
    assert board.check_frame((0, 0), (540, 360), square).bounds == (-270, -180, 270, 180)
    with pytest.raises(board.FrameOutside) as caught:
        board.check_frame((50, 0), (540, 360), square)  # the east edge at 320 m
    assert caught.value.overflow_m == pytest.approx(20)
    circle = Point(0, 0).buffer(300, quad_segs=64)
    with pytest.raises(board.FrameOutside) as caught:
        board.check_frame((0, 0), (540, 360), circle)  # the corners lie 324 m from the middle
    assert caught.value.overflow_m == pytest.approx(24, abs=1)  # the circle is a polygon
    assert board.overflow(board.frame_box((0, 0), (400, 300)), circle) == 0  # corners 250 m out


def test_fit_takes_the_scale_that_fills_the_range_and_holds_the_site():
    site = box(-10, -10, 10, 10)
    wide = box(-300, -200, 300, 200)  # the large rectangle range
    assert board.fit((900, 600), wide, site) == {"scale": 600, "center": [0.0, 0.0], "frame_m": [540.0, 360.0]}
    assert board.fit((841, 594), wide, site)["scale"] == 600  # A1: 504.6 × 356.4 m
    assert board.fit((900, 600), Point(0, 0).buffer(300, quad_segs=64), site)["scale"] == 500  # corners within 300 m
    off = box(150, -10, 170, 10)  # a site off the middle: the frame moves to hold it
    got = board.fit((900, 600), box(-200, -200, 200, 200), off)
    frame = board.frame_box(got["center"], got["frame_m"])
    assert frame.contains(off) and board.overflow(frame, box(-200, -200, 200, 200)) <= 0.01
    with pytest.raises(board.NoFit):
        board.fit((900, 600), box(-50, -50, 50, 50), box(-60, -60, 60, 60))  # the site is bigger than the range


def test_the_ground_under_a_frame_runs_edge_to_edge():
    n, step, half = 51, 4.0, 100.0
    axis = -half + step * np.arange(n)
    grid = np.tile(axis * 0.1, (n, 1))  # rising 0.1 m per m eastward
    t = terrain_in_frame(grid, half, step, center=(10, 5), width_m=57, depth_m=33, base_elev=20.0,
                         site=box(0, 0, 10, 10), areas=[("road", box(-100, -100, 100, 0))])
    assert (t.xs[0], t.xs[-1], t.ys[-1]) == (0.0, 57.0, 33.0) and t.origin == (-18.5, -11.5)
    assert t.z[0, 0] == pytest.approx(20 - 1.85) and t.z[0, -1] == pytest.approx(20 + 3.85)  # interpolated
    assert t.site.bounds == (18.5, 11.5, 28.5, 21.5) and t.areas[0][1].bounds == (0, 0, 57, 11.5)
    with pytest.raises(ValueError):
        terrain_in_frame(grid, half, step, center=(90, 0), width_m=57, depth_m=33)


def test_each_layer_is_cut_where_it_lies_on_a_board_size_sheet():
    terrain = example_terrain(2, width_m=120, depth_m=80)
    tall = Building(outline=box(50, 30, 62, 40), base_z=float(terrain.z.min()), top_z=float(terrain.z.max()) + 12.0)
    made = board.cut(terrain, scale=500, thickness_mm=3.0, board_mm=(240, 160), buildings=[tall])
    layers = len(made.model.layers)
    assert made.in_place and made.model.size_mm == pytest.approx((240, 160))
    ground = [p for p in made.layout.placements if p.piece.kind == "ground"]
    assert ground and all(p.sheet == p.piece.layer and (p.dx, p.dy, p.angle) == (0, 0, 0) for p in ground)
    sheet = box(0, 0, 240, 160).buffer(0.01)
    assert all(sheet.contains(p.place(p.piece.shape)) for p in made.layout.placements)  # all on the board
    houses = [p for p in made.layout.placements if p.piece.kind == "building"]
    assert houses and min(p.sheet for p in houses) == layers  # the buildings on sheets of their own
    s = made.summary()
    assert s["layers"] == layers and s["sheets"] == made.layout.sheets and s["in_place"]
    assert s["total_height_mm"] == pytest.approx((max(p.layer for p in made.model.pieces) + 1) * 3.0)
    saved = board.cut(terrain, scale=500, thickness_mm=3.0, board_mm=(240, 160), buildings=[tall], save_material=True)
    assert saved.layout.sheets < made.layout.sheets  # the upper layers laid out together
    assert [p.sheet for p in saved.layout.placements if p.piece.layer == 0] == [0]
    small_bed = board.cut(terrain, scale=500, thickness_mm=3.0, board_mm=(240, 160), bed_mm=(150, 110))
    assert not small_bed.in_place and len(small_bed.model.modules) > 1


def test_nesting_lays_pieces_out_as_before_only_faster(monkeypatch):
    # the same layout the nesting gave before it skipped sheets (recorded on these inputs)
    model = slice_terrain(example_terrain(3), scale=1000, thickness_mm=2, room=(140, 90), hollow_rim_mm=3)
    terrain_layout = nest(model.pieces, 160, 110, res=1.0, rotations=4)
    assert (digest(terrain_layout), terrain_layout.sheets) == ("0638e39f553f9417", 25)
    calls = []
    real = np.fft.irfft2
    monkeypatch.setattr(np.fft, "irfft2", lambda *a, **k: calls.append(1) or real(*a, **k))
    stacked = nest(stacks(), 100, 70, res=1.0, rotations=4)
    assert (digest(stacked), stacked.sheets, len(stacked.placements)) == ("7271feca43eb7d8e", 9, 150)
    assert len(calls) < 1000  # trying every sheet afresh took 3172
