"""board_export.py — the drawing table as a DXF (CAD) or 3dm (Rhino) file."""

from __future__ import annotations

import io
import math
from types import SimpleNamespace

import ezdxf
import pytest
import rhino3dm

from sida import board, board_export


def _rect(lon, lat, dlon, dlat):
    return [[lon, lat], [lon + dlon, lat], [lon + dlon, lat + dlat], [lon, lat + dlat], [lon, lat]]


PARCEL = {"pnu": "1", "address": "금정동 689",
          "shape": {"type": "Polygon", "coordinates": [_rect(127.0, 37.0, 0.0004, 0.0002)]}}
HOOKS = [("site", SimpleNamespace(board_site=lambda path: {"area_m2": 800.0, "lines": [], "parcels": [PARCEL]}))]
NO_SITE: list = []


def _table(path):
    board.add_paper(path, {"kind": "mass", "id": "mass-a", "title": "안 A", "blocks": [
        {"u": 0, "v": 0, "w": 20, "d": 10, "floors": 5},
        {"u": 20, "v": 0, "w": 10, "d": 10, "floors": 2, "a": 90},
    ]})
    board.add_paper(path, {"kind": "mass", "id": "mass-b", "title": "안 B: 탑상형", "floor_height": 3,
                           "blocks": [{"w": 12, "d": 12, "floors": 10}]})
    board.add_paper(path, {"kind": "tracing", "id": "trace-1", "title": "동선",
                           "strokes": [[[0, 0], [5, 5], [10, 0]], [[1, 1]]]})
    board.add_paper(path, {"kind": "tracing", "id": "trace-empty", "strokes": []})
    board.add_paper(path, {"kind": "note", "text": "남측 마당"})
    board.propose_paper(path, {"kind": "mass", "blocks": [{"w": 5, "d": 5, "floors": 1}]})  # AI section: left out


def test_the_scene_holds_the_site_each_scheme_on_the_table_and_the_tracing_lines(tmp_path):
    _table(tmp_path)
    scene = board_export.export_scene(tmp_path, active="mass-b", hooks=HOOKS)
    names = [layer["name"] for layer in scene["layers"]]
    assert names == ["대지 경계", "매스 - 안 A", "매스 - 안 B 탑상형", "트레이싱 - 동선", "기준점"]
    site, a, b, trace, origin = scene["layers"]

    assert len(site["curves"]) == 1 and site["curves"][0]["closed"] and site["labels"][0]["text"] == "금정동 689"
    width = max(x for x, _y, _z in site["curves"][0]["points"]) - min(x for x, _y, _z in site["curves"][0]["points"])
    assert width == pytest.approx(35.6, abs=0.2)  # metres, as the screen draws the site

    assert (a["visible"], b["visible"]) == (False, True)  # only the scheme shown on the table is on
    assert [s["height"] for s in a["solids"]] == [21.0, 8.4] and b["solids"][0]["height"] == 30.0
    assert [label["text"] for label in a["labels"]] == ["5F", "2F"]
    assert trace["parent"] == "트레이싱" and len(trace["curves"]) == 1  # a one-point stroke is no line
    assert not any(c["closed"] for c in trace["curves"])
    assert scene["origin"] == {"lon": pytest.approx(127.0002), "lat": pytest.approx(37.0001)}
    assert "N" in origin["labels"][0]["text"] and origin["labels"][0]["at"] == [0.0, 0.0, 0.0]

    assert all(layer["visible"] for layer in board_export.export_scene(tmp_path, hooks=HOOKS)["layers"])


def test_blocks_stand_in_the_site_frame_and_turn_about_their_middle():
    frame = {"x": 10.0, "y": 5.0, "angle": math.pi / 2}  # the site's long side runs north
    corners = board_export.block_outline(frame, {"u": 4, "v": 0, "w": 6, "d": 2, "floors": 1})
    assert corners == [[11.0, 6.0], [11.0, 12.0], [9.0, 12.0], [9.0, 6.0]]
    turned = board_export.block_outline(None, {"u": 0, "v": 0, "w": 6, "d": 2, "floors": 1, "a": 90})
    assert [[round(x, 6) + 0.0, round(y, 6) + 0.0] for x, y in turned] == [[1, -3], [1, 3], [-1, 3], [-1, -3]]


def test_without_site_facts_the_schemes_still_go_out_around_the_origin(tmp_path):
    _table(tmp_path)
    scene = board_export.export_scene(tmp_path, hooks=NO_SITE)
    assert scene["origin"] is None
    assert [layer["name"] for layer in scene["layers"]] == ["매스 - 안 A", "매스 - 안 B 탑상형", "트레이싱 - 동선"]
    assert scene["layers"][1]["solids"][0]["outline"] == [[-6.0, -6.0], [6.0, -6.0], [6.0, 6.0], [-6.0, 6.0]]


def test_other_domains_add_their_own_layers_and_names_stay_unique(tmp_path):
    board.add_paper(tmp_path, {"kind": "mass", "id": "m1", "title": "안", "blocks": [{"w": 1, "d": 1, "floors": 1}]})
    board.add_paper(tmp_path, {"kind": "mass", "id": "m2", "title": "안", "blocks": [{"w": 1, "d": 1, "floors": 1}]})
    context = SimpleNamespace(board_export_layers=lambda path: [{
        "name": "주변 건물", "color": (150, 150, 150),
        "solids": [{"outline": [[30, 0], [40, 0], [40, 10], [30, 10]], "base": 0.0, "height": 9.0}],
    }])
    scene = board_export.export_scene(tmp_path, hooks=[("context", context)])
    assert [layer["name"] for layer in scene["layers"]] == ["매스 - 안", "매스 - 안 2", "주변 건물"]
    assert scene["layers"][2]["curves"] == [] and scene["layers"][2]["visible"] is True


def test_unknown_schemes_and_formats_are_refused(tmp_path):
    _table(tmp_path)
    with pytest.raises(ValueError, match="not a massing scheme"):
        board_export.export_scene(tmp_path, active="trace-1", hooks=NO_SITE)
    with pytest.raises(ValueError, match="format must be"):
        board_export.export_board(tmp_path, "pdf", hooks=NO_SITE)
    assert board_export.layer_name('a/b:c"d::e', "x") == "a b c d e"
    assert board_export.layer_name("///", "fallback") == "fallback"


def test_the_dxf_opens_with_layers_meshes_and_polylines_in_metres(tmp_path):
    _table(tmp_path)
    data = board_export.export_board(tmp_path, "dxf", active="mass-a", hooks=HOOKS)
    doc = ezdxf.read(io.StringIO(data.decode("utf-8")))
    assert doc.units == 6 and not doc.audit().has_errors
    layers = {layer.dxf.name: layer for layer in doc.layers}
    assert layers["매스 - 안 B 탑상형"].is_off() and layers["매스 - 안 A"].is_on()
    assert layers["대지 경계"].dxf.linetype == "DASHED"
    msp = doc.modelspace()
    meshes = msp.query('MESH[layer=="매스 - 안 A"]')
    assert len(meshes) == 2
    first = list(meshes)[0]
    assert len(first.vertices) == 8 and len(first.faces) == 6
    assert max(v[2] for v in first.vertices) == pytest.approx(21.0)
    site = msp.query('LWPOLYLINE[layer=="대지 경계"]')
    assert len(site) == 1 and site[0].closed
    assert len(msp.query('LWPOLYLINE[layer=="트레이싱 - 동선"]')) == 1
    assert {t.dxf.text for t in msp.query("TEXT")} >= {"금정동 689", "5F", "2F", "10F"}


def test_the_3dm_opens_with_sublayers_and_closed_masses_in_metres(tmp_path):
    _table(tmp_path)
    path = tmp_path / "out.3dm"
    path.write_bytes(board_export.export_board(tmp_path, "3dm", active="mass-a", hooks=HOOKS))
    model = rhino3dm.File3dm.Read(str(path))
    assert model.Settings.ModelUnitSystem == rhino3dm.UnitSystem.Meters
    layers = {layer.FullPath: layer for layer in model.Layers}
    assert set(layers) == {"대지 경계", "매스", "매스::안 A", "매스::안 B 탑상형", "트레이싱", "트레이싱::동선", "기준점"}
    assert layers["매스::안 A"].Visible and not layers["매스::안 B 탑상형"].Visible

    def on(name):
        index = layers[name].Index
        return [o.Geometry for o in model.Objects if o.Attributes.LayerIndex == index]

    masses = [g for g in on("매스::안 B 탑상형") if isinstance(g, rhino3dm.Extrusion)]
    assert len(masses) == 1 and masses[0].IsSolid
    box = masses[0].GetBoundingBox()
    assert (box.Min.Z, box.Max.Z) == (pytest.approx(0), pytest.approx(30.0))
    assert box.Max.X - box.Min.X == pytest.approx(12.0)
    assert [type(g).__name__ for g in on("대지 경계")] == ["PolylineCurve", "TextDot"]
    assert [type(g).__name__ for g in on("트레이싱::동선")] == ["PolylineCurve"]


def test_a_missing_package_is_a_plain_message_not_a_crash(tmp_path, monkeypatch):
    def missing(scene):
        raise ModuleNotFoundError("No module named 'rhino3dm'", name="rhino3dm")

    monkeypatch.setitem(board_export.WRITERS, "3dm", missing)
    with pytest.raises(ValueError, match="rhino3dm package is not installed"):
        board_export.export_board(tmp_path, "3dm", hooks=NO_SITE)


def test_a_height_grid_goes_out_as_a_nurbs_surface_in_3dm_and_a_mesh_in_dxf(tmp_path):
    # a 4 × 4 grid 10 m apart from (-15, -15), rising 1 m per column eastward
    ground = SimpleNamespace(board_export_layers=lambda path: [{
        "name": "대지 주변 - 지형", "short": "지형", "parent": "대지 주변", "color": (170, 150, 120),
        "surfaces": [{"min_x": -15, "min_y": -15, "step": 10, "nx": 4, "ny": 4, "z": [i % 4 for i in range(16)]}],
    }])
    path = tmp_path / "out.3dm"
    path.write_bytes(board_export.export_board(tmp_path, "3dm", hooks=[("site", ground)]))
    model = rhino3dm.File3dm.Read(str(path))
    layers = {layer.FullPath: layer.Index for layer in model.Layers}
    assert "대지 주변::지형" in layers
    surfaces = [o.Geometry for o in model.Objects if o.Attributes.LayerIndex == layers["대지 주변::지형"]]
    assert len(surfaces) == 1
    nurbs = surfaces[0]
    nurbs = nurbs.ToNurbsSurface() if hasattr(nurbs, "ToNurbsSurface") else nurbs
    u, v = nurbs.Domain(0), nurbs.Domain(1)
    corner = nurbs.PointAt(u.T1, v.T0)
    assert (corner.X, corner.Y, corner.Z) == (pytest.approx(15), pytest.approx(-15), pytest.approx(3))  # through the corner

    doc = ezdxf.read(io.StringIO(board_export.export_board(tmp_path, "dxf", hooks=[("site", ground)]).decode("utf-8")))
    mesh = list(doc.modelspace().query('MESH[layer=="대지 주변 - 지형"]'))
    assert len(mesh) == 1 and len(mesh[0].vertices) == 16 and len(mesh[0].faces) == 9


def test_each_block_of_a_mass_stands_on_the_lowest_ground_under_it(tmp_path):
    # ground falling 1 m per 10 m eastward: z = -x / 10, a 41 × 41 grid 5 m apart over ±100 m
    n, step = 41, 5.0
    ground = {"min_x": -100.0, "min_y": -100.0, "step": step, "nx": n, "ny": n,
              "z": [-(-100.0 + (k % n) * step) / 10 for k in range(n * n)]}
    # a 20 × 10 block east of the middle (x 30..50): lowest ground at its east edge, x = 50 → -5
    east = [[30, -5], [50, -5], [50, 5], [30, 5]]
    assert board_export.mass_base(east, ground) == pytest.approx(-5.0)
    assert board_export.mass_base(east, None) == 0.0  # no ground: on the table
    assert board_export.mass_base([[300, 300], [310, 300], [310, 310]], ground) == 0.0  # off the grid
    assert board_export.mass_base(east, ground, datum=1.5) == 1.5  # one 계획고 for all masses wins
    # a dip in the middle of a footprint counts, not only its edges
    pit = dict(ground, z=[0.0] * (n * n))
    pit["z"][20 * n + 20] = -2.0  # the grid point at (0, 0)
    assert board_export.mass_base([[-6, -6], [6, -6], [6, 6], [-6, 6]], pit) == pytest.approx(-2.0)

    board.add_paper(tmp_path, {"kind": "mass", "id": "mass-a", "title": "안 A", "blocks": [
        {"u": 40, "v": 0, "w": 20, "d": 10, "floors": 5}]})
    hooks = [("site", SimpleNamespace(board_ground=lambda path: ground))]
    scene = board_export.export_scene(tmp_path, hooks=hooks)
    solid = next(layer for layer in scene["layers"] if layer["parent"] == "매스")["solids"][0]
    assert solid["base"] == pytest.approx(-5.0) and solid["height"] == pytest.approx(21.0)
    label = next(layer for layer in scene["layers"] if layer["parent"] == "매스")["labels"][0]
    assert label["at"][2] == pytest.approx(16.0)  # the floor tag on its roof
    saved = next(p for p in board.load_board(tmp_path)["papers"] if p["id"] == "mass-a")["blocks"][0]
    assert "base" not in saved and "z" not in saved  # the saved table is unchanged
    flat = board_export.export_scene(tmp_path, hooks=NO_SITE)
    assert next(layer for layer in flat["layers"] if layer["parent"] == "매스")["solids"][0]["base"] == 0.0


def test_a_round_ground_goes_out_as_only_the_cells_inside_the_circle(tmp_path):
    # a 9 × 9 grid 10 m apart over ±40 m, clipped to a 30 m circle
    surface = {"min_x": -40, "min_y": -40, "step": 10, "nx": 9, "ny": 9, "z": [1.0] * 81, "clip_radius": 30.0}
    cells = board_export.grid_cells(surface)
    assert 0 < len(cells) < 64 and len(board_export.grid_cells({**surface, "clip_radius": None})) == 64
    ground = SimpleNamespace(board_export_layers=lambda path: [{
        "name": "대지 주변 - 지형", "short": "지형", "parent": "대지 주변", "color": (170, 150, 120), "surfaces": [surface]}])
    doc = ezdxf.read(io.StringIO(board_export.export_board(tmp_path, "dxf", hooks=[("site", ground)]).decode("utf-8")))
    (mesh,) = doc.modelspace().query('MESH[layer=="대지 주변 - 지형"]')
    assert len(mesh.faces) == len(cells)
    path = tmp_path / "round.3dm"
    path.write_bytes(board_export.export_board(tmp_path, "3dm", hooks=[("site", ground)]))
    model = rhino3dm.File3dm.Read(str(path))
    layers = {layer.FullPath: layer.Index for layer in model.Layers}
    (body,) = [o.Geometry for o in model.Objects if o.Attributes.LayerIndex == layers["대지 주변::지형"]]
    assert isinstance(body, rhino3dm.Mesh) and body.Faces.Count == len(cells)
    box = body.GetBoundingBox()
    assert max(abs(box.Min.X), abs(box.Max.X), abs(box.Min.Y), abs(box.Max.Y)) <= 30.0 + 1e-6
    # a mass still stands on the ground of a round range
    assert board_export.mass_base([[-5, -5], [5, -5], [5, 5], [-5, 5]], surface) == pytest.approx(1.0)


def test_blocks_and_sheets_on_the_designers_own_layers_go_out_on_layers_of_those_names(tmp_path):
    board.set_layers(tmp_path, [*board.default_layers(), {"id": "tower", "name": "타워", "parent": "mass", "color": "#c0504d"}])
    board.add_paper(tmp_path, {"kind": "mass", "id": "m1", "title": "안", "blocks": [
        {"w": 10, "d": 10, "floors": 2}, {"w": 5, "d": 5, "floors": 9, "layer": "tower"}]})
    board.add_paper(tmp_path, {"kind": "mass", "id": "m2", "title": "탑", "layer": "tower", "blocks": [{"w": 4, "d": 4, "floors": 3}]})
    board.add_paper(tmp_path, {"kind": "tracing", "id": "t1", "title": "선", "layer": "tower", "strokes": [[[0, 0], [1, 1]]]})
    scene = board_export.export_scene(tmp_path, hooks=[])
    by_name = {x["name"]: x for x in scene["layers"]}
    assert len(by_name["매스 - 타워"]["solids"]) == 2  # one block of m1 and all of m2
    assert by_name["매스 - 타워"]["color"] == (192, 80, 77)
    assert len(by_name["매스 - 타워"]["curves"]) == 1
    scheme = next(x for x in scene["layers"] if x["name"].endswith("안"))
    assert len(scheme["solids"]) == 1
    assert not any(x["name"].endswith("탑") for x in scene["layers"])  # nothing left on its own layer
