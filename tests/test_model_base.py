"""Model bases for laser cutting: slicing the ground, labelling pieces, laying them on sheets."""

import csv
import itertools

import ezdxf
import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from sida.model_base import strokefont
from sida.model_base.nesting import DoesNotFit, nest
from sida.model_base.output import (
    assembly_svg,
    cut_passes,
    label_strokes,
    piece_rows,
    sheet_dxf,
    sheet_svg,
)
from sida.model_base.pieces import (
    MIN_LABEL_ROOM,
    Piece,
    contour_interval,
    module_grid,
    slice_terrain,
)
from sida.model_base.plan import cut_plan
from sida.model_base.terrain import Terrain, example_terrain


@pytest.fixture(scope="module")
def ground():
    return example_terrain(3, width_m=120, depth_m=90, cell_m=3, relief_m=10)


@pytest.fixture(scope="module")
def model(ground):
    return slice_terrain(ground, scale=500, thickness_mm=3)


@pytest.fixture(scope="module")
def halves(ground):
    return slice_terrain(ground, scale=500, thickness_mm=3, room=(150, 190))  # 240 × 180 mm model, small sheet


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


def test_a_model_that_fits_the_sheet_is_not_cut(model):
    assert len(model.modules) == 1
    assert len([p for p in model.pieces if p.layer == 0]) == 1  # one base plate
    assert model.pieces[0].id == "00A"


def test_a_model_bigger_than_the_sheet_is_halved_then_quartered():
    assert module_grid((480, 360), 590, 390) == (1, 1)
    assert module_grid((480, 360), 390, 290) == (2, 1)  # cut across the long side
    assert module_grid((360, 480), 390, 290) == (1, 2)
    assert module_grid((480, 360), 290, 190) == (2, 2)
    assert module_grid((480, 360), 200, 390) == (3, 1)  # turned, 160 × 360 fits a 200 × 390 room
    with pytest.raises(ValueError):
        module_grid((10000, 10000), 10, 10)


def test_every_layer_comes_apart_at_the_same_straight_line(halves):
    assert len(halves.modules) == 2
    west, east = halves.modules
    seam = west.intersection(east)  # one line through the whole model
    assert seam.length == pytest.approx(180)
    for k, layer in enumerate(halves.layers):
        pieces = [p for p in halves.pieces if p.layer == k]
        assert unary_union([p.shape for p in pieces]).area == pytest.approx(layer.area, rel=1e-6)
        for p in pieces:  # no piece crosses the seam
            assert halves.modules[p.module - 1].buffer(1e-6).contains(p.shape)


def test_pieces_are_named_by_module_layer_and_part(halves):
    ids = [p.id for p in halves.pieces]
    assert len(ids) == len(set(ids))
    assert {"1-00A", "2-00A"} <= set(ids)
    assert all(p.id.startswith(f"{p.module}-{p.layer:02d}") for p in halves.pieces)


def test_ids_are_engraved_where_the_next_layer_will_cover_them(model):
    for p in model.pieces:
        assert p.shape.distance(Point(p.label_at)) < 0.5
        if p.label_room >= MIN_LABEL_ROOM and p.label_hidden:
            assert model.layers[p.layer + 1].buffer(0.1).contains(Point(p.label_at))
    assert all(p.level_m == pytest.approx(model.base_m + 2 * model.interval_m) for p in model.pieces if p.layer == 2)


def test_pieces_carry_the_next_layer_line_and_the_site_boundary_but_not_the_seam(model, halves):
    base = model.pieces[0]
    assert any(ln.distance(model.layers[1].boundary) < 0.01 for ln in base.engrave)
    site_lines = [ln for p in model.pieces for ln in p.engrave if ln.distance(model.site_mm.boundary) < 0.01 and ln.length > 1]
    assert site_lines
    seam = halves.modules[0].intersection(halves.modules[1]).buffer(0.1)
    edge = box(0, 0, *halves.size_mm).boundary.buffer(0.1)
    for p in halves.pieces:
        for ln in p.engrave:  # neither the seam nor the model's own edge is a line to engrave
            assert ln.difference(seam).difference(edge).length > 0 or ln.length < 0.5


def test_hollow_layers_keep_their_rim_and_save_material(ground, model):
    hollow = slice_terrain(ground, scale=500, thickness_mm=3, hollow_rim_mm=6)
    assert sum(p.area for p in hollow.pieces) < sum(p.area for p in model.pieces) * 0.8
    for k in range(1, len(hollow.layers) - 1):
        rim = hollow.layers[k].difference(hollow.layers[k + 1].buffer(-6))
        material = unary_union([p.shape for p in hollow.pieces if p.layer == k])
        assert rim.difference(material).area < 1.0  # everything that shows or bears is still cut


def _placed(layout):
    return [(p, p.place(p.piece.shape)) for p in layout.placements]


def test_layout_keeps_pieces_apart_and_on_the_sheet(halves):
    layout = nest(halves.pieces, 160, 200, gap=2, margin=5, res=1.5, rotations=4)
    assert len(layout.placements) == len(halves.pieces)
    sheet = box(5 - 1e-6, 5 - 1e-6, 155 + 1e-6, 195 + 1e-6)
    placed = _placed(layout)
    for p, shape in placed:
        assert sheet.contains(shape), p.piece.id
    for (a, sa), (b, sb) in itertools.combinations(placed, 2):
        if a.sheet == b.sheet:
            assert sa.distance(sb) >= 2 - 1e-6, (a.piece.id, b.piece.id)


def test_a_piece_without_holes_goes_into_a_ring_once_and_no_deeper():
    ring = Piece(id="01A", layer=1, level_m=0, shape=box(0, 0, 180, 180).difference(box(20, 20, 160, 160)))
    small = Piece(id="02A", layer=2, level_m=0, shape=box(0, 0, 100, 100))
    layout = nest([ring, small], 200, 200, gap=2, margin=5, res=1, rotations=1)
    assert layout.sheets == 1
    passes = cut_passes(layout, 0)
    assert passes["max_depth"] == 2 and len(passes["outer"]) == 1
    assert Polygon(passes["inner"][0]).area == pytest.approx(100 * 100, rel=0.01)  # cut before the hole


def test_a_piece_with_holes_never_goes_into_a_hole():
    ring = Piece(id="01A", layer=1, level_m=0, shape=box(0, 0, 180, 180).difference(box(20, 20, 160, 160)))
    inner_ring = Piece(id="02A", layer=2, level_m=0, shape=box(0, 0, 100, 100).difference(box(30, 30, 70, 70)))
    layout = nest([ring, inner_ring], 200, 200, gap=2, margin=5, res=1, rotations=1)
    assert layout.sheets == 2  # it would fit in the hole, but its own hole would need a third cut pass
    assert all(cut_passes(layout, n)["max_depth"] <= 1 for n in range(2))


def test_a_piece_no_sheet_can_hold_is_reported():
    with pytest.raises(DoesNotFit):
        nest([Piece(id="00A", layer=0, level_m=0, shape=box(0, 0, 400, 400))], 300, 300, rotations=2)


def test_engraved_id_and_north_arrow_stay_on_the_piece(halves):
    layout = nest(halves.pieces, 160, 200, res=1.5, rotations=4)
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


def test_laser_files_engrave_then_cut_inside_then_outside(halves, tmp_path):
    layout = nest(halves.pieces, 160, 200, res=1.5, rotations=4)
    svg = sheet_svg(layout, 0)
    assert 'width="160mm"' in svg
    assert svg.index('id="engrave"') < svg.index('id="inner"') < svg.index('id="outer"')  # the order the laser runs
    assert 'stroke="#0000FF"' in svg and 'stroke="#00A000"' in svg
    assert 'stroke="#123456"' in sheet_svg(layout, 0, colors={"outer": "#123456"})
    sheet_dxf(layout, 0, tmp_path / "s.dxf")
    doc = ezdxf.readfile(tmp_path / "s.dxf")
    used = {e.dxf.layer for e in doc.modelspace()}
    assert {"CUT_OUTER", "ENGRAVE"} <= used <= {"CUT_INNER", "CUT_OUTER", "ENGRAVE"}
    assert doc.header["$INSUNITS"] == 4  # millimetres
    plan_svg = assembly_svg(halves, layout)
    assert all(f">{p.piece.id}·{p.sheet + 1}<" in plan_svg for p in layout.placements)
    assert ">1<" in plan_svg and ">2<" in plan_svg  # module numbers on the assembly map
    rows = piece_rows(layout)
    assert {r["sheet"] for r in rows} == set(range(1, layout.sheets + 1))
    assert {r["module"] for r in rows} == {1, 2}


def test_cut_plan_halves_the_model_only_when_the_sheet_is_smaller(ground):
    big = cut_plan(ground, 300, 220, res=2, rotations=4)
    small = cut_plan(ground, 170, 210, res=2, rotations=4)
    assert len(big.model.modules) == 1
    assert len(small.model.modules) == 2
    for plan in (big, small):
        assert len(plan.layout.placements) == len(plan.pieces)
        for n in range(plan.layout.sheets):
            assert cut_passes(plan.layout, n)["max_depth"] <= 2


def test_flat_ground_is_just_the_base_plate():
    # Reproduces a crash: ground whose top is below the first level asked for an empty band.
    xs, ys = np.arange(0, 61, 3.0), np.arange(0, 41, 3.0)
    flat = Terrain(xs=xs, ys=ys, z=np.full((len(ys), len(xs)), 5.0))
    plan = slice_terrain(flat, scale=500, thickness_mm=3)
    assert [p.id for p in plan.pieces] == ["00A"]


def test_script_writes_laser_files_guides_and_an_assembly_map(tmp_path):
    from scripts.model_base_terrain import main

    out = tmp_path / "base"
    assert main(["--sheet", "160x200", "--area", "120x90", "--res", "2", "--rotations", "4", "--out", str(out)]) == 0
    files = {p.name for p in out.iterdir()}
    assert {"assembly.svg", "pieces.csv", "sheet-1.svg", "sheet-1-guide.svg", "sheet-1.dxf"} <= files
    with (out / "pieces.csv").open(encoding="utf-8-sig") as f:
        first = next(csv.DictReader(f))
    assert first["id"] == "1-00A" and first["module"] == "1"


def test_rotated_pieces_keep_their_shape():
    piece = Piece(id="01A", layer=1, level_m=0, shape=Polygon([(0, 0), (60, 0), (60, 10), (10, 40), (0, 40)]))
    layout = nest([piece], 100, 70, res=1, rotations=8)
    placed = layout.placements[0].place(piece.shape)
    assert placed.area == pytest.approx(piece.area)
    assert placed.is_valid
