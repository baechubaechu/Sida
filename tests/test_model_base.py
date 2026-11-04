"""Model bases for laser cutting: slicing the ground, labelling pieces, laying them on sheets."""

import csv
import itertools

import ezdxf
import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from sida.model_base import strokefont
from sida.model_base.nesting import DoesNotFit, nest
from sida.model_base.output import assembly_svg, label_strokes, piece_rows, sheet_dxf, sheet_svg
from sida.model_base.pieces import (
    MIN_LABEL_ROOM,
    Piece,
    contour_interval,
    slice_terrain,
    split_to_fit,
)
from sida.model_base.plan import cut_plan
from sida.model_base.terrain import Terrain, example_terrain


@pytest.fixture(scope="module")
def ground():
    return example_terrain(3, width_m=120, depth_m=90, cell_m=3, relief_m=10)


@pytest.fixture(scope="module")
def model(ground):
    return slice_terrain(ground, scale=500, thickness_mm=3, hollow_rim_mm=0)


def test_one_sheet_stands_for_thickness_times_scale():
    assert contour_interval(500, 3) == pytest.approx(1.5)
    assert contour_interval(1000, 2) == pytest.approx(2.0)
    with pytest.raises(ValueError):
        contour_interval(500, 0)


def test_example_ground_is_repeatable_and_holds_the_site(ground):
    again = example_terrain(3, width_m=120, depth_m=90, cell_m=3, relief_m=10)
    assert np.array_equal(ground.z, again.z)
    assert ground.z.min() == pytest.approx(0) and ground.z.max() == pytest.approx(10)
    assert ground.extent.contains(ground.site)
    assert not np.array_equal(ground.z, example_terrain(4, width_m=120, depth_m=90, cell_m=3).z)


def test_layers_stack_inside_each_other_from_a_full_base(model):
    w, d = model.size_mm
    assert (w, d) == pytest.approx((240, 180))  # 120 m × 90 m at 1:500
    assert model.layers[0].area == pytest.approx(w * d)
    for lower, upper in itertools.pairwise(model.layers):
        assert upper.difference(lower).area < 1e-3  # each layer sits on the one below
    assert len(model.layers) == pytest.approx(10 / 1.5, abs=1.01)


def test_pieces_are_named_by_layer_and_part_and_labelled_where_they_can_be_read(model):
    ids = [p.id for p in model.pieces]
    assert len(ids) == len(set(ids))
    assert ids[0] == "00A"
    assert all(p.id.startswith(f"{p.layer:02d}") for p in model.pieces)
    for p in model.pieces:
        assert p.shape.contains(Point(p.label_at)) or p.shape.distance(Point(p.label_at)) < 0.5
        if p.label_room >= MIN_LABEL_ROOM and p.label_hidden:
            above = model.layers[p.layer + 1]
            assert above.buffer(0.1).contains(Point(p.label_at))  # under the next layer, out of sight
    assert all(p.level_m == pytest.approx(model.base_m + 2 * model.interval_m) for p in model.pieces if p.layer == 2)


def test_pieces_carry_the_next_layer_line_and_the_site_boundary(model):
    base = model.pieces[0]
    lines = [ln for ln in base.engrave]
    assert lines, "the base shows where layer 1 goes"
    upper_outline = model.layers[1].boundary
    assert any(ln.distance(upper_outline) < 0.01 for ln in lines)
    site_lines = [ln for p in model.pieces for ln in p.engrave if ln.distance(model.site_mm.boundary) < 0.01
                  and ln.length > 1 and ln.hausdorff_distance(model.site_mm.boundary) < model.site_mm.length]
    assert site_lines


def test_hollow_layers_keep_their_rim_and_save_material(ground, model):
    hollow = slice_terrain(ground, scale=500, thickness_mm=3, hollow_rim_mm=6)
    solid_area = sum(p.area for p in model.pieces)
    assert sum(p.area for p in hollow.pieces) < solid_area * 0.8
    for k in range(1, len(hollow.layers) - 1):
        rim = hollow.layers[k].difference(hollow.layers[k + 1].buffer(-6))
        material = unary_union([p.shape for p in hollow.pieces if p.layer == k])
        assert rim.difference(material).area < 1.0  # everything that shows or bears is still cut


def test_a_piece_too_big_for_the_sheet_is_cut_into_tiles_that_add_up():
    big = Piece(id="00A", layer=0, level_m=0, shape=box(0, 0, 500, 300))
    tiles = split_to_fit([big], 200, 150)
    assert [t.id for t in tiles][:2] == ["00A1", "00A2"]
    assert sum(t.area for t in tiles) == pytest.approx(500 * 300)
    assert all(t.shape.bounds[2] - t.shape.bounds[0] <= 200 + 1e-6 for t in tiles)
    assert tiles[0].tile == f"1/{len(tiles)}"


def test_thin_rims_are_cut_into_chunks_but_compact_pieces_are_left_whole():
    ring = Piece(id="02A", layer=2, level_m=0, shape=box(0, 0, 300, 200).difference(box(10, 10, 290, 190)))
    blob = Piece(id="03A", layer=3, level_m=0, shape=Point(0, 0).buffer(60))
    out = split_to_fit([ring, blob], 500, 400, chunk=120)
    assert sum(1 for p in out if p.id.startswith("02A")) > 3
    assert [p.id for p in out if p.id.startswith("03")] == ["03A"]


def _placed(layout):
    return [(p, p.place(p.piece.shape)) for p in layout.placements]


def test_layout_keeps_pieces_apart_and_on_the_sheet(model):
    pieces = split_to_fit(model.pieces, 290, 190)
    layout = nest(pieces, 300, 200, gap=2, margin=5, res=1.5, rotations=4)
    assert len(layout.placements) == len(pieces)
    sheet = box(5 - 1e-6, 5 - 1e-6, 295 + 1e-6, 195 + 1e-6)
    placed = _placed(layout)
    for p, shape in placed:
        assert sheet.contains(shape), p.piece.id
    for (a, sa), (b, sb) in itertools.combinations(placed, 2):
        if a.sheet == b.sheet:
            assert sa.distance(sb) >= 2 - 1e-6, (a.piece.id, b.piece.id)


def test_small_pieces_go_into_the_holes_of_rings():
    ring = Piece(id="01A", layer=1, level_m=0, shape=box(0, 0, 180, 180).difference(box(20, 20, 160, 160)))
    small = Piece(id="02A", layer=2, level_m=0, shape=box(0, 0, 100, 100))
    layout = nest([ring, small], 200, 200, gap=2, margin=5, res=1, rotations=1)
    assert layout.sheets == 1


def test_a_piece_no_sheet_can_hold_is_reported():
    with pytest.raises(DoesNotFit):
        nest([Piece(id="00A", layer=0, level_m=0, shape=box(0, 0, 400, 400))], 300, 300, rotations=2)


def test_engraved_id_and_north_arrow_stay_on_the_piece(model):
    pieces = split_to_fit(model.pieces, 290, 190)
    layout = nest(pieces, 300, 200, res=1.5, rotations=4)
    for p in layout.placements:
        if p.piece.label_room < MIN_LABEL_ROOM:
            continue
        shape = p.place(p.piece.shape).buffer(0.3)
        for line in label_strokes(p.piece, p):
            for xy in line:
                assert shape.contains(Point(xy)), p.piece.id


def test_stroke_font_covers_every_id_character():
    for ch in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-./m":
        assert ch in strokefont.GLYPHS
    assert strokefont.text_width("03B", 6) == pytest.approx(3 * 5.5 - 1.5)
    with pytest.raises(ValueError):
        strokefont.strokes("가", 0, 0, 3)


def test_laser_files_cut_in_red_and_engrave_in_blue(model, tmp_path):
    layout = nest(split_to_fit(model.pieces, 290, 190), 300, 200, res=1.5, rotations=4)
    svg = sheet_svg(layout, 0)
    assert 'width="300mm"' in svg and 'stroke="#FF0000"' in svg and 'stroke="#0000FF"' in svg
    assert svg.count("<path") > len(layout.on_sheet(0))
    assert 'stroke="#00AA00"' in sheet_svg(layout, 0, colors={"engrave": "#00AA00"})
    sheet_dxf(layout, 0, tmp_path / "s.dxf")
    doc = ezdxf.readfile(tmp_path / "s.dxf")
    assert {e.dxf.layer for e in doc.modelspace()} == {"CUT", "ENGRAVE"}
    assert doc.header["$INSUNITS"] == 4  # millimetres
    plan_svg = assembly_svg(model, layout)
    assert all(f">{p.piece.id}·{p.sheet + 1}<" in plan_svg for p in layout.placements)
    rows = piece_rows(layout)
    assert {r["sheet"] for r in rows} == set(range(1, layout.sheets + 1))


def test_cut_plan_takes_the_fewest_sheets_then_the_fewest_pieces(ground):
    whole = cut_plan(ground, 300, 200, res=1.5, rotations=4, chunks=(None,))
    best = cut_plan(ground, 300, 200, res=1.5, rotations=4, chunks=(None, 120.0))
    assert best.layout.sheets <= whole.layout.sheets
    if best.layout.sheets == whole.layout.sheets:
        assert best.chunk is None


def test_flat_ground_is_just_the_base_plate():
    # Reproduces a crash: ground whose top is below the first level asked for an empty band.
    xs, ys = np.arange(0, 61, 3.0), np.arange(0, 41, 3.0)
    flat = Terrain(xs=xs, ys=ys, z=np.full((len(ys), len(xs)), 5.0))
    plan = slice_terrain(flat, scale=500, thickness_mm=3)
    assert [p.id for p in plan.pieces] == ["00A"]


def test_script_writes_laser_files_guides_and_an_assembly_map(tmp_path):
    from scripts.model_base_terrain import main

    out = tmp_path / "base"
    assert main(["--sheet", "300x200", "--area", "100x80", "--res", "2", "--rotations", "4", "--chunk", "0",
                 "--out", str(out)]) == 0
    files = {p.name for p in out.iterdir()}
    assert {"assembly.svg", "pieces.csv", "sheet-1.svg", "sheet-1-guide.svg", "sheet-1.dxf"} <= files
    with (out / "pieces.csv").open(encoding="utf-8-sig") as f:
        assert next(csv.DictReader(f))["id"] == "00A"


def test_rotated_pieces_keep_their_shape():
    piece = Piece(id="01A", layer=1, level_m=0, shape=Polygon([(0, 0), (60, 0), (60, 10), (10, 40), (0, 40)]))
    layout = nest([piece], 100, 70, res=1, rotations=8)
    placed = layout.placements[0].place(piece.shape)
    assert placed.area == pytest.approx(piece.area)
    assert affinity.rotate(placed, 0).is_valid
