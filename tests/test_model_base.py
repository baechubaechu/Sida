"""Model bases for laser cutting: slicing the ground, labelling pieces, laying them on sheets."""

import csv
import itertools
import math

import ezdxf
import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
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
from sida.model_base.terrain import Terrain, example_terrain, terrain_from_grid


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
    assert 'stroke="#0000FF"' in svg and 'stroke="#FF0000"' in svg and "#00A000" not in svg  # engrave blue, cut red
    assert 'stroke="#123456"' in sheet_svg(layout, 0, colors={"outer": "#123456"})
    sheet_dxf(layout, 0, tmp_path / "s.dxf")
    doc = ezdxf.readfile(tmp_path / "s.dxf")
    assert doc.dxfversion == "AC1027" and doc.header["$INSUNITS"] == 4  # AutoCAD 2013, millimetres
    entities = list(doc.modelspace())
    assert {e.dxf.layer for e in entities} == {"CUT", "ENGRAVE", "SHEET"}
    cut, engrave, sheet = (doc.layers.get(n) for n in ("CUT", "ENGRAVE", "SHEET"))
    assert (cut.color, cut.rgb, engrave.color, engrave.rgb) == (1, (255, 0, 0), 5, (0, 0, 255))
    assert cut.dxf.lineweight == 0 and engrave.dxf.lineweight == 0 and sheet.dxf.plot == 0
    layers = [e.dxf.layer for e in entities if e.dxf.layer != "SHEET"]
    assert layers == sorted(layers, key=lambda n: n != "ENGRAVE")  # engrave first, then the cuts
    outline = next(e for e in entities if e.dxf.layer == "SHEET" and e.closed)
    assert [tuple(p[:2]) for p in outline.get_points()] == [(0, 0), (160, 0), (160, 200), (0, 200)]  # from the lower-left
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


def _table_ground(half=100.0, step=2.0):
    """A ground grid shaped as the drawing table's: square, ±half around the site's middle, z = 0 there."""
    axis = -half + step * np.arange(int(round(2 * half / step)) + 1)
    x, y = np.meshgrid(axis, axis)
    return 0.06 * x + 4.0 * np.exp(-((x - 30) ** 2 + (y + 20) ** 2) / 800.0) - 4.0 * np.exp(-(30**2 + 20**2) / 800.0)


def test_table_ground_is_cut_around_the_site_with_heights_above_sea_level():
    grid = _table_ground()
    site = [(-15, -10), (15, -10), (15, 10), (-15, 10)]
    road = [(-200, 30), (200, 30), (200, 42), (-200, 42)]
    t = terrain_from_grid(grid, 100.0, 2.0, width_m=120, depth_m=80, base_elev=37.5, site=site,
                          areas=[("road", road), ("parcel", site)], name="무교동 45")
    assert t.xs[0] == 0 and t.xs[-1] == pytest.approx(120) and t.ys[-1] == pytest.approx(80)
    assert t.z.shape == (len(t.ys), len(t.xs))
    middle = t.z[np.argmin(np.abs(t.ys - 40)), np.argmin(np.abs(t.xs - 60))]
    assert middle == pytest.approx(37.5)  # the grid's middle is the site's middle, at its height above sea level
    assert np.allclose(t.z, grid[30:71, 20:81] + 37.5)  # rows y = -40…40, columns x = -60…60 of the grid
    assert t.site.bounds == pytest.approx((45, 30, 75, 50))
    assert [kind for kind, _ in t.areas] == ["road"]  # kinds the model does not engrave are left out
    assert t.areas[0][1].bounds == pytest.approx((0, 70, 120, 80))  # clipped to the model's edge
    with pytest.raises(ValueError):
        terrain_from_grid(grid, 100.0, 2.0, width_m=240, depth_m=80)
    with pytest.raises(ValueError):
        terrain_from_grid(None, 100.0, 2.0, width_m=120, depth_m=80)


def test_road_edges_are_engraved_where_they_show_and_shaded_on_the_assembly_map():
    road = [(-200, 30), (200, 30), (200, 42), (-200, 42)]
    walk = [(-200, 26), (200, 26), (200, 30), (-200, 30)]
    t = terrain_from_grid(_table_ground(), 100.0, 2.0, width_m=120, depth_m=100, base_elev=20,
                          site=[(-15, -10), (15, -10), (15, 10), (-15, 10)],
                          areas=[("road", road), ("sidewalk", walk)])
    plan = slice_terrain(t, scale=500, thickness_mm=3)
    mm = 1000 / 500
    edges = [LineString([(0, y * mm), (120 * mm, y * mm)]) for y in (50 + 26, 50 + 30, 50 + 42)]
    scored = unary_union([ln for p in plan.pieces for ln in p.engrave])
    for edge in edges:  # each edge is scored once along its whole length across the layers
        assert scored.intersection(edge.buffer(0.05)).length == pytest.approx(edge.length, rel=0.03)
    for p in plan.pieces:
        above = plan.layers[p.layer + 1] if p.layer + 1 < len(plan.layers) else Polygon()
        for ln in p.engrave:
            if any(ln.distance(e) < 0.01 for e in edges):  # never under the next layer
                assert ln.difference(above.buffer(-0.2)).length == pytest.approx(ln.length, abs=0.05)
    layout = nest(plan.pieces, 400, 300, res=2, rotations=4)
    svg = assembly_svg(plan, layout)
    assert "#8a8f96" in svg and "도로·인도 경계" in svg


def test_stepped_ground_has_a_slab_per_interval_topped_at_its_contour():
    from sida.model_base.terraces import terrace_view, terraces

    grid = _table_ground()
    site = [(-15, -10), (15, -10), (15, 10), (-15, 10)]
    t = terrain_from_grid(grid, 100.0, 2.0, width_m=160, depth_m=120, base_elev=37.2, site=site)
    steps = terraces(t, 1.5)
    low = float(t.z.min())
    assert steps[0].level_m % 1.5 == pytest.approx(0) and low - 1.5 < steps[0].level_m <= low  # round heights
    assert steps[0].shape.area == pytest.approx(160 * 120)
    assert steps[0].shape.bounds == pytest.approx((-80, -60, 80, 60))  # on the table, around the site's middle
    for lower, upper in itertools.pairwise(steps):
        assert upper.level_m - lower.level_m == pytest.approx(1.5)
        assert upper.bottom == pytest.approx(lower.top)  # each slab stands on the one below
        assert lower.shape.buffer(0.01).contains(upper.shape)
    for s in steps:
        assert s.top == pytest.approx(s.level_m - 37.2)
    # The site's middle (table z = 0) is on the highest step at or below it.
    under = [s for s in steps if s.shape.contains(Point(0, 0))]
    assert -1.5 < under[-1].top <= 0
    view = terrace_view(t, 1.5)
    assert view["base_elev"] == pytest.approx(steps[0].level_m) and view["datum"] == pytest.approx(37.2)
    assert len(view["steps"]) == len(steps)
    first = view["steps"][0]["polygons"][0]
    assert Polygon(first["outline"]).exterior.is_ccw and first["outline"][0] != first["outline"][-1]
    twice = terrace_view(t, 3.0)
    assert len(twice["steps"]) < len(view["steps"])  # a coarser interval, fewer steps
    with pytest.raises(ValueError):
        terraces(t, 0)


def _square(cx, cy, w, d):
    return [[cx - w / 2, cy - d / 2], [cx + w / 2, cy - d / 2], [cx + w / 2, cy + d / 2], [cx - w / 2, cy + d / 2]]


def test_surrounding_buildings_keep_only_heights_that_may_be_written_down():
    from sida.model_base.buildings import buildings_from_context

    around = {
        "buildings": [
            {"outline": _square(40, -20, 12, 10), "base": 1.0, "ground": 1.5, "height": 12.0, "height_source": "ledger"},
            {"outline": _square(-40, 20, 10, 10), "base": -2.0, "ground": -1.8, "height": 9.0, "height_source": "estimate"},
            {"outline": _square(0, 0, 10, 10), "base": 0.0, "ground": 0.0, "height": 30.0, "height_source": "ledger", "on_site": True},
            {"outline": _square(60, 30, 8, 8), "base": 0.0, "ground": 0.0, "height": 11.4, "height_source": "api_estimate"},
            {"outline": _square(60, 10, 8, 8), "base": 0.0, "ground": 0.0, "height": 11.4, "height_source": "api_estimate",
             "offline": {"height": 7.6, "source": "map_estimate"}},
        ],
        "unknown_buildings": [{"outline": _square(-60, -30, 9, 9), "base": -3.0}],
    }
    got = buildings_from_context(around)
    assert len(got) == 5  # the one on the site is left out
    measured, estimated, api_only, offline, unknown = got
    assert measured.top_z == pytest.approx(13.5) and not measured.estimated
    assert estimated.estimated and estimated.top_z == pytest.approx(7.2)
    assert api_only.top_z is None  # VWorld's API floors are for the screen only
    assert offline.top_z == pytest.approx(7.6) and offline.estimated
    assert unknown.top_z is None and unknown.base_z == -3.0
    assert len(buildings_from_context(around, include_site=True)) == 6


def test_buildings_stand_on_their_step_as_stacked_sheets_in_a_cut_out():
    from sida.model_base.buildings import Building
    from sida.model_base.terraces import terrace_view

    t = terrain_from_grid(_table_ground(), 100.0, 2.0, width_m=160, depth_m=120, base_elev=20)
    # On the side of the hill at (30, -20): the lowest ground along the outline is its seat.
    on_hill = Polygon(_square(20, -20, 14, 10))
    xs = np.linspace(13, 27, 15)
    rim = [float(t.z[np.argmin(np.abs(t.ys - (y + 60))), np.argmin(np.abs(t.xs - (x + 80)))]) - 20
           for x in xs for y in (-25, -15)]
    hill = Building(outline=on_hill, base_z=min(rim), top_z=max(rim) + 9.0)
    unknown = Building(outline=Polygon(_square(-50, 30, 10, 10)), base_z=0.0)
    plan = slice_terrain(t, scale=500, thickness_mm=3, buildings=[hill, unknown])
    (b,) = plan.buildings
    assert b.id == "B01" and b.layer == int(np.floor((min(rim) + 20 - plan.base_m) / 1.5 + 1e-9))
    stack = [p for p in plan.pieces if p.kind == "building"]
    assert [p.id for p in stack] == [f"B01.{i}" for i in range(1, b.sheets + 1)]
    assert b.sheets == round((max(rim) + 9.0 + 20 - (plan.base_m + b.layer * 1.5)) / 1.5)
    assert [p.label_hidden for p in stack] == [True] * (b.sheets - 1) + [False]  # only the roof shows its id
    fp = b.footprint
    for k in range(b.layer + 1, len(plan.layers)):  # the layers above the seat make room for it
        assert plan.layers[k].intersection(fp).area < 0.5
    assert plan.layers[b.layer + 1].area > 0  # the hill itself is still there
    seat = [p for p in plan.pieces if p.kind == "ground" and p.layer == b.layer]
    scored = unary_union([ln for p in seat for ln in p.engrave])
    assert scored.intersection(fp.boundary.buffer(0.05)).length == pytest.approx(fp.length, rel=0.03)
    (dashed,) = plan.footprints_mm  # a building without a height is only scored on the ground
    all_scored = unary_union([ln for p in plan.pieces for ln in p.engrave])
    assert all_scored.intersection(dashed.boundary.buffer(0.05)).length == pytest.approx(dashed.length, rel=0.03)
    layout = nest(plan.pieces, 400, 300, res=2, rotations=4)
    assert sum(1 for p in layout.placements if p.piece.kind == "building") == b.sheets
    assert f"B01×{b.sheets}" in assembly_svg(plan, layout)
    rows = piece_rows(layout)
    assert {r["kind"] for r in rows} == {"ground", "building"}

    view = terrace_view(t, 1.5, buildings=[hill, unknown])
    (stand,) = view["buildings"]
    assert stand["bottom"] == pytest.approx(plan.base_m + b.layer * 1.5 - 20)
    assert stand["top"] - stand["bottom"] == pytest.approx(b.sheets * 1.5) and stand["sheets"] == b.sheets


def test_a_round_outline_cuts_every_layer_and_module_to_the_circle():
    # a 200 m square of ground rising eastward, modelled as the 90 m circle around its middle
    axis = np.arange(-100, 101, 2.0)
    grid = np.tile(axis / 20.0, (len(axis), 1))
    circle = Point(0, 0).buffer(90, quad_segs=32)
    ring = [[-10, -10], [10, -10], [10, 10], [-10, 10]]
    terrain = terrain_from_grid(grid, 100, 2.0, width_m=180, depth_m=180, base_elev=30.0, boundary=circle,
                                site=ring, areas=[("road", [[-100, -5], [100, -5], [100, 5], [-100, 5]])])
    assert terrain.extent.area == pytest.approx(math.pi * 90 ** 2, rel=0.01)
    square = terrain_from_grid(grid, 100, 2.0, width_m=180, depth_m=180, base_elev=30.0, site=ring)
    assert square.extent.area == pytest.approx(180 * 180) and square.boundary is None  # as before
    (road,) = [shape for kind, shape in terrain.areas if kind == "road"]
    assert road.within(terrain.extent.buffer(0.01))  # the engraved road stops at the circle
    # 1:500, 3 mm: the 180 m circle is 360 mm across; a 200 mm sheet makes it modules
    plan = slice_terrain(terrain, scale=500, thickness_mm=3, room=(200, 200))
    circle_mm = affinity.scale(affinity.translate(terrain.extent, -float(terrain.xs[0]), -float(terrain.ys[0])), 2, 2, origin=(0, 0))
    assert len(plan.modules) > 1
    assert all(p.shape.within(circle_mm.buffer(0.05)) for p in plan.pieces)  # every piece inside the circle
    base = unary_union([p.shape for p in plan.pieces if p.layer == 0])
    assert base.area == pytest.approx(circle_mm.area, rel=0.01)  # the base sheet is the whole round model
    modules = {p.module for p in plan.pieces}
    assert len(modules) == len(plan.modules)  # each module still gets its share, clipped to the circle


def test_the_laser_pdf_has_a_true_size_vector_page_per_sheet(halves):
    import re
    import zlib

    from sida.model_base.output import sheets_pdf

    layout = nest(halves.pieces, 160, 200, res=1.5, rotations=4)
    pdf = sheets_pdf(layout)
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    start = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    rows = pdf[start:].split(b"\n")[3:]  # "xref", "0 n", the free entry, then one row per object
    for k, row in enumerate(rows[:2 + 2 * layout.sheets], start=1):  # each points at its object
        assert pdf[int(row[:10]):].startswith(f"{k} 0 obj".encode())
    boxes = re.findall(rb"/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", pdf)
    assert len(boxes) == layout.sheets
    assert all(float(w) == pytest.approx(160 * 72 / 25.4, abs=0.01) and float(h) == pytest.approx(200 * 72 / 25.4, abs=0.01) for w, h in boxes)
    pages = [zlib.decompress(s).decode("ascii") for s in re.findall(rb"stream\n(.*?)\nendstream", pdf, re.S)]
    assert len(pages) == layout.sheets
    first = pages[0]
    assert "0.000 0.000 1.000 RG" in first and "1.000 0.000 0.000 RG" in first  # engrave blue, cut red
    assert " m " in first and " l " in first and " h S" in first and "Do" not in first  # paths, no pictures
    assert first.index("0.000 0.000 1.000 RG") < first.index("1.000 0.000 0.000 RG")  # the laser's order
    assert re.search(r"\n0\.000353 w\n", first)  # a 0.001 pt hairline in mm units


def test_laser_formats_are_picked_and_unknown_ones_refused(halves):
    from sida.model_base.output import files, parse_formats

    assert parse_formats("svg, dxf") == ("dxf", "svg") and parse_formats(["PDF"]) == ("pdf",)
    for bad in ("dwg", "", [], "dxf,ai"):
        with pytest.raises(ValueError):
            parse_formats(bad)
    layout = nest(halves.pieces, 160, 200, res=1.5, rotations=4)
    named = files(halves, layout, formats=("pdf",))
    assert "sheets.pdf" in named and not any(n.endswith(".dxf") or (n.endswith(".svg") and "guide" not in n and n != "assembly.svg") for n in named)
    assert "sheet-1-guide.svg" in named and "assembly.svg" in named and "pieces.csv" in named  # always there
    assert {"sheet-1.dxf", "sheet-1.svg", "sheets.pdf"} <= set(files(halves, layout))
