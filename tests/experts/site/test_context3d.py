"""The site's surroundings in 3D (context3d) and terrain packs (terrain_pack), on made-up data."""

from __future__ import annotations

import math

import numpy as np
import pytest

from sida import board
from sida.experts.site import context3d, landapi, terrain_pack

LON0, LAT0 = 127.0, 37.5
K = math.pi / 180
EAST = board.EARTH_RADIUS * K * math.cos(LAT0 * K)
NORTH = board.EARTH_RADIUS * K


def lonlat(x: float, y: float) -> list[float]:
    """The point x m east and y m north of (LON0, LAT0), in the table's own projection."""
    return [LON0 + x / EAST, LAT0 + y / NORTH]


def square(cx: float, cy: float, half: float, clockwise: bool = False) -> list[list[float]]:
    pts = [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]
    if clockwise:
        pts = pts[::-1]
    ring = [lonlat(x, y) for x, y in pts]
    return ring + [ring[0]]


def feature(ring, **props) -> dict:
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": props}


@pytest.fixture(autouse=True)
def coarse_ground(monkeypatch):
    """Solve the ground on a 4 m grid instead of 2 m: four times fewer cells, same checks.
    The solver itself is checked at 2 m in test_ground_keeps_fixed_heights_and_is_smooth_between_them."""
    monkeypatch.setattr(context3d, "SOLVE_STEP", 4.0)


@pytest.fixture
def pack(tmp_path):
    """A pack where the ground rises 10 m from y = -150 (10 m) to y = 150 (20 m), plus a spot height."""
    conn = terrain_pack.create(tmp_path / f"test{terrain_pack.SUFFIX}", {"name": "test", "source": "made up", "source_date": "2026-10-01"})
    for y, elev in ((-150, 10.0), (-50, 13.0), (50, 17.0), (150, 20.0)):
        terrain_pack.add_contour(conn, elev, [lonlat(x, y) for x in range(-300, 301, 20)])
    terrain_pack.add_spot(conn, *lonlat(0, 0), 15.0)
    terrain_pack.add_contour(conn, 99.0, [lonlat(5000, 5000), lonlat(5100, 5000)])  # far away
    terrain_pack.add_area(conn, "water", square(-150, -150, 20)[:-1])
    terrain_pack.add_area(conn, "sidewalk", square(30, 30, 2)[:-1])  # inside the road parcel below
    conn.commit()
    conn.close()
    return tmp_path


def test_pack_query_returns_only_what_touches_the_box(pack):
    west, south = lonlat(-200, -200)
    east, north = lonlat(200, 200)
    found = terrain_pack.query(west, south, east, north, folder=pack)
    assert sorted(c["elev"] for c in found["contours"]) == [10.0, 13.0, 17.0, 20.0]
    assert found["spots"] == [pytest.approx([*lonlat(0, 0), 15.0])]
    assert found["sources"][0]["source_date"] == "2026-10-01"
    assert [a["kind"] for a in found["areas"]] == ["water", "sidewalk"]
    assert terrain_pack.query(west, south, east, north, folder=pack / "none") == {
        "contours": [], "spots": [], "areas": [], "buildings": [], "map_buildings": [], "sources": []}
    with pytest.raises(ValueError):
        terrain_pack.add_area(None, "lake", [])


def test_ground_keeps_fixed_heights_and_is_smooth_between_them():
    # two lines 100 m apart, 10 m and 20 m: halfway is 15 m, and nothing outside the range appears
    fixed = [(x, y, z) for y, z in ((-50, 10.0), (50, 20.0)) for x in np.arange(-100, 101, 1.0)]
    grid = context3d.solve_ground(fixed, 100, 2.0)
    assert context3d.sample(grid, 100, 2.0, [0.0], [0.0])[0] == pytest.approx(15.0, abs=0.2)
    assert context3d.sample(grid, 100, 2.0, [30.0], [-50.0])[0] == pytest.approx(10.0, abs=0.01)
    middle = context3d.sample(grid, 100, 2.0, np.zeros(11), np.linspace(-50, 50, 11))
    assert np.all(np.diff(middle) > 0)  # rises steadily: no terraces between the lines
    assert context3d.solve_ground([], 100, 2.0) is None
    flat = context3d.solve_ground([(0, 0, 7.0), (10, 0, 7.0)], 20, 2.0)
    assert np.allclose(flat, 7.0)


def plan_for_site() -> dict:
    """A 20 m square site at the middle, as board.site_plan makes it."""
    return board.site_plan([{"pnu": "1111010100100010000", "address": "가", "area_m2": 400.0,
                             "shape": {"type": "Polygon", "coordinates": [square(0, 0, 10)]}}])


def fake_vworld_layers(monkeypatch):
    """Buildings, 도로명주소 건물 and parcels around the site, served for any box."""
    layers = {
        "LT_C_BLDGINFO": [
            feature(square(0, 0, 8), bld_nm="대지 안 건물", height="0", grnd_flr="2"),
            feature(square(60, 0, 10, clockwise=True), bld_nm="대장 높이", height="9", grnd_flr="3"),
            feature(square(60, 0, 2), bld_nm="", height="0", grnd_flr="0"),  # inside the one above
            feature(square(-60, 0, 10), bld_nm="브이월드 높이", height="12.5", grnd_flr="4"),
            feature(square(0, 60, 10), bld_nm="층수만", height="0", grnd_flr="5"),
            feature(square(0, -60, 10), bld_nm="", height="0", grnd_flr="0"),
            feature(square(150, 150, 10), bld_nm="도로명 층수", height="0", grnd_flr="0"),
        ],
        "LT_C_SPBD": [feature(square(150, 150, 11), gro_flo_co="6")],
        "LP_PA_CBND_BUBUN": [
            feature(square(0, 0, 10), pnu="1111010100100010000", jibun="1 대"),
            feature(square(60, 0, 15), pnu="1111010100100020000", jibun="2 대"),
            feature(square(-60, 0, 15), pnu="1111010100100030000", jibun="3 대"),
            feature(square(0, 60, 15), pnu="1111010100100040000", jibun="4 대"),
            feature(square(30, 30, 5), pnu="1111010100100050000", jibun="5 도"),
        ],
    }
    calls = []

    def http_get(url, params):
        calls.append(params)
        assert params["geomFilter"].startswith("BOX(")
        found = layers[params["data"]]
        return {"response": {"status": "OK" if found else "NOT_FOUND", "page": {"total": "1"},
                             "result": {"featureCollection": {"features": found}}}}

    monkeypatch.setattr(landapi, "_http_get", http_get)
    monkeypatch.setattr(landapi, "vworld_credentials", lambda: ("key", "domain"))
    return calls


def ledger(pnu: str) -> list[dict]:
    rows = {
        "1111010100100020000": [{"dong": "", "purpose": "업무시설", "building_area_m2": 400.0,
                                 "floors_above": 3, "height_m": 11.2}],
        "1111010100100040000": [{"dong": "", "purpose": "공동주택", "building_area_m2": 400.0,
                                 "floors_above": 5, "height_m": None}],
    }
    return rows.get(pnu, [])


def test_build_places_ground_buildings_and_parcels_in_the_table_frame(pack, monkeypatch):
    fake_vworld_layers(monkeypatch)
    out = context3d.build(plan_for_site(), 200, folder=pack, ledger=ledger, use_cache=False)

    assert out["ground_elev"] == pytest.approx(15.0, abs=0.3)  # the spot height under the middle
    terrain = out["terrain"]
    assert terrain["min"] == -200 and terrain["step"] == context3d.VIEW_STEP
    assert len(terrain["z"]) == terrain["n"] ** 2
    middle = terrain["z"][(terrain["n"] // 2) * terrain["n"] + terrain["n"] // 2]
    assert middle == pytest.approx(0.0, abs=0.05)  # z is measured from the ground at the middle
    assert {c["elev"] for c in out["contours"]} == {10.0, 13.0, 17.0, 20.0}
    assert {c["elev"]: c["index"] for c in out["contours"]}[10.0] is False
    assert out["terrain_sources"][0]["date"] == "2026-10-01"

    by_name = {b["name"]: b for b in out["buildings"]}
    assert by_name["대장 높이"]["height"] == 11.2 and by_name["대장 높이"]["height_source"] == "ledger"
    assert by_name["브이월드 높이"]["height"] == 12.5 and by_name["브이월드 높이"]["height_source"] == "vworld"
    assert by_name["층수만"]["height"] == pytest.approx(5 * 2.9)  # 공동주택 storeys
    assert by_name["층수만"]["height_source"] == "estimate"
    assert by_name["도로명 층수"]["height"] == pytest.approx(6 * context3d.STOREY_OTHER)
    assert by_name["대지 안 건물"]["on_site"] is True and by_name["층수만"]["on_site"] is False
    north = by_name["층수만"]
    south = out["unknown_buildings"][0]
    assert north["ground"] > 0 > south["base"]  # standing on the rising ground, not on z = 0
    # on the slope the foundation reaches the downhill side; the height is counted from the middle
    assert north["foundation"] > 0.2 and north["base"] == pytest.approx(north["ground"] - north["foundation"], abs=0.02)
    assert north["top"] == pytest.approx(north["ground"] + north["height"], abs=0.02)
    line = np.array(north["ground_line"])
    assert line[:, 2].max() - line[:, 2].min() > 0.4  # the line on the ground follows the slope
    assert np.hypot(*np.diff(line[:, :2], axis=0).T).max() <= context3d.DRAPE_GAP + 1e-6
    assert len(out["unknown_buildings"]) == 1 and len(out["left_out"]) == 1
    assert out["counts"] == {"ledger": 1, "vworld": 1, "file": 0, "estimate": 3, "api_estimate": 0, "map_estimate": 0,
                             "unknown": 1, "inner": 1}
    outline = np.array(by_name["대장 높이"]["outline"])
    assert context3d._area(outline) > 0  # counter-clockwise even when VWorld gave it clockwise
    assert outline[:, 0].mean() == pytest.approx(60, abs=0.1)

    roads = [p for p in out["parcels"] if p["road"]]
    assert [p["label"] for p in roads] == ["5 도"]

    def ground_at(x, y):
        n, step = terrain["n"], terrain["step"]
        return terrain["classes"][round((y + 200) / step) * n + round((x + 200) / step)]

    assert len(terrain["classes"]) == terrain["n"] ** 2
    assert ground_at(28, 28) == "s"  # sidewalk area wins inside the road parcel
    assert ground_at(33, 33) == "r"  # the rest of the road parcel
    assert ground_at(-150, -150) == "w" and ground_at(-100, 100) == "g"


def test_classify_takes_sidewalk_over_road_over_water():
    ring = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    small = np.array([[2, 2], [4, 2], [4, 4], [2, 4]], dtype=float)
    pts = np.array([[3, 3], [8, 8], [20, 20]], dtype=float)
    assert context3d.classify(pts, [("water", ring), ("road", ring), ("sidewalk", small)]) == "srg"
    assert context3d.classify(pts, []) == "ggg"


def test_build_without_a_pack_keeps_buildings_on_flat_ground_and_reports_ledger_failures(tmp_path, monkeypatch):
    fake_vworld_layers(monkeypatch)

    def broken(pnu):
        raise landapi.LandApiError("no_key", "DATA_GO_KR_API_KEY")

    out = context3d.build(plan_for_site(), 200, folder=tmp_path, ledger=broken, use_cache=False)
    assert out["terrain"] is None and out["ground_elev"] is None and out["contours"] == []
    assert all(b["base"] == 0 for b in out["buildings"])
    assert "ledger:no_key" in out["notes"]
    assert out["counts"]["ledger"] == 0  # without the 건축물대장, heights come from VWorld or floors


def test_build_refuses_a_site_without_a_boundary_and_a_bad_radius(pack):
    with pytest.raises(ValueError):
        context3d.build({"parcels": []}, 200, folder=pack)
    with pytest.raises(ValueError):
        context3d.build(plan_for_site(), 10, folder=pack)


def test_build_reuses_a_recent_result(pack, monkeypatch):
    calls = fake_vworld_layers(monkeypatch)
    context3d._cache.clear()
    first = context3d.build(plan_for_site(), 200, folder=pack, ledger=ledger)
    n = len(calls)
    assert context3d.build(plan_for_site(), 200, folder=pack, ledger=ledger) is first
    assert len(calls) == n
    context3d._cache.clear()


def test_storey_height_by_use():
    assert context3d.storey_height("공동주택") == 2.9
    assert context3d.storey_height("제2종근린생활시설") == 3.8
    assert context3d.storey_height("공장") == context3d.STOREY_OTHER
    assert context3d.storey_height("") == context3d.STOREY_OTHER


def test_build_takes_buildings_from_a_pack_before_vworld(pack, monkeypatch):
    calls = fake_vworld_layers(monkeypatch)
    conn = terrain_pack.create(pack / f"b{terrain_pack.SUFFIX}", {
        "name": "b", "kind": "buildings", "source": "GIS건물통합정보", "source_date": "2026-03-06"})
    terrain_pack.add_building(conn, square(60, 0, 10)[:-1], {"pnu": "1111010100100020000", "height": 7.5, "floors": 2,
                                                              "use": "업무시설", "name": "파일 건물", "date": "2026-03-06"})
    terrain_pack.add_building(conn, square(-60, 0, 10)[:-1], {"pnu": "1111010100100090000", "floors": 4, "use": "공동주택"})
    terrain_pack.add_building(conn, square(600, 600, 10)[:-1], {"name": "범위 밖"})
    conn.commit()
    conn.close()

    out = context3d.build(plan_for_site(), 200, folder=pack, ledger=ledger, use_cache=False)
    layers = [c["data"] for c in calls]
    assert "LT_C_BLDGINFO" not in layers and "LT_C_SPBD" not in layers  # the pack has the buildings
    assert "LP_PA_CBND_BUBUN" in layers  # parcels still come from VWorld, for drawing only
    by_name = {b["name"]: b for b in out["buildings"]}
    assert by_name["파일 건물"]["height"] == 11.2  # the 건축물대장 height (matched by the file's PNU) comes first
    assert [b["height"] for b in out["buildings"] if b["name"] == ""] == [pytest.approx(4 * 2.9)]
    assert out["counts"]["ledger"] == 1 and out["counts"]["estimate"] == 1 and out["counts"]["vworld"] == 0
    assert out["building_source"] == {"name": "GIS건물통합정보", "date": "2026-03-06", "pack": "b"}
    assert [s["pack"] for s in out["terrain_sources"]] == ["test"]

    no_ledger = context3d.build(plan_for_site(), 200, folder=pack, ledger=lambda pnu: [], use_cache=False)
    filed = {b["name"]: b for b in no_ledger["buildings"]}["파일 건물"]
    assert filed["height"] == 7.5 and filed["height_source"] == "file"


def test_a_building_with_no_height_or_floors_takes_them_from_the_1_5000_map(pack, monkeypatch):
    fake_vworld_layers(monkeypatch)
    conn = terrain_pack.create(pack / f"m{terrain_pack.SUFFIX}", {"name": "m", "kind": "areas", "source": "1:5,000"})
    terrain_pack.add_map_building(conn, square(1, -59, 9)[:-1], 3, "제1종근린생활시설")  # over the unknown one
    terrain_pack.add_map_building(conn, square(150, -150, 5)[:-1], 9, "")  # over nothing
    terrain_pack.add_map_building(conn, square(0, 0, 1)[:-1], 0, "")  # no floors: not kept
    conn.commit()
    conn.close()

    out = context3d.build(plan_for_site(), 200, folder=pack, ledger=ledger, use_cache=False)
    lent = [b for b in out["buildings"] if b["height_source"] == "map_estimate"]
    assert len(lent) == 1 and lent[0]["floors"] == 3 and lent[0]["height"] == pytest.approx(3 * 3.8)
    assert out["counts"]["map_estimate"] == 1 and out["counts"]["unknown"] == 0
    assert out["unknown_buildings"] == []


def test_overlap_share_and_map_floors():
    a = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    half = np.array([[5, -5], [20, -5], [20, 20], [5, 20]], dtype=float)
    far = np.array([[50, 50], [60, 50], [60, 60], [50, 60]], dtype=float)
    assert context3d.overlap_share(a, half) == pytest.approx(0.5, abs=0.06)
    assert context3d.overlap_share(a, far) == 0
    assert context3d.map_floors(a, [(far, 5.0, ""), (half, 2.0, "업무시설")]) == (2.0, "업무시설")  # its middle is inside
    assert context3d.map_floors(a, [(far, 5.0, "")]) is None


def test_export_layers_hold_the_ground_contours_and_file_buildings_only(pack, monkeypatch):
    fake_vworld_layers(monkeypatch)
    out = context3d.build(plan_for_site(), 200, folder=pack, ledger=ledger, use_cache=False)
    names = [layer["short"] for layer in context3d.export_layers(out)]
    assert names == ["지형", "지형 - 인도", "지형 - 수계", "등고선"]  # buildings came from VWorld: not written
    ground = context3d.export_layers(out)[0]["surfaces"][0]
    assert ground["nx"] == ground["ny"] == out["terrain"]["n"] and ground["min_x"] == -200
    water = context3d.export_layers(out)[2]["curves"][0]["points"]
    assert all(len(p) == 3 for p in water) and water[0][2] < 0  # laid on the ground, which is low to the south

    conn = terrain_pack.create(pack / f"b{terrain_pack.SUFFIX}", {"name": "b", "kind": "buildings", "source": "GIS건물통합정보"})
    terrain_pack.add_building(conn, square(60, 0, 10)[:-1], {"pnu": "1111010100100020000"})
    terrain_pack.add_building(conn, square(0, 60, 10)[:-1], {"floors": 3, "use": "공장"})
    terrain_pack.add_building(conn, square(0, -60, 10)[:-1], {})  # VWorld has no floors there either
    conn.commit()
    conn.close()
    layers = {layer["short"]: layer for layer in context3d.export_layers(
        context3d.build(plan_for_site(), 200, folder=pack, ledger=ledger, use_cache=False))}
    assert {"건물 - 측정 높이", "건물 - 추정 높이", "건물 - 높이 미확인(바닥선)"} <= set(layers)
    measured = layers["건물 - 측정 높이"]["solids"][0]
    assert measured["height"] > 11.2  # the 건축물대장 height plus the foundation on the slope
    assert all(layer["parent"] == context3d.EXPORT_GROUP for layer in layers.values())


def test_the_export_hook_gives_nothing_without_a_site(tmp_path):
    from sida.experts.site import hooks

    assert hooks.board_export_layers(tmp_path) == []


def test_a_file_building_without_height_or_floors_asks_vworld_once_per_layer(tmp_path, monkeypatch):
    """VWorld replies around one building, recorded and then moved to a made-up spot with made-up names
    (tests/fixtures/landapi/context_*_sample*): no real place is in the repository."""
    import json
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "landapi"
    building = json.loads((fixtures / "context_pack_building_sample.json").read_text(encoding="utf-8"))
    replies = {layer: json.loads((fixtures / f"context_{layer}_sample_box.json").read_text(encoding="utf-8"))
               for layer in ("LT_C_SPBD", "LT_C_BLDGINFO")}
    calls = []

    def http_get(url, params):
        calls.append(params["data"])
        return replies.get(params["data"], {"response": {"status": "NOT_FOUND"}})

    monkeypatch.setattr(landapi, "_http_get", http_get)
    monkeypatch.setattr(landapi, "vworld_credentials", lambda: ("key", "domain"))
    conn = terrain_pack.create(tmp_path / f"b{terrain_pack.SUFFIX}", {"name": "b", "kind": "buildings", "source": "GIS건물통합정보"})
    terrain_pack.add_building(conn, building["ring"], {"pnu": "1114010100100330001", "use": "제2종근린생활시설"})
    conn.commit()
    conn.close()

    plan = {"origin": building["origin"], "parcels": []}
    out = context3d.build(plan, 200, folder=tmp_path, ledger=lambda pnu: [], use_cache=False)
    (b,) = out["buildings"]
    assert b["height_source"] == "api_estimate" and b["floors"] == building["floors"] == 7
    assert b["height"] == pytest.approx(7 * 3.8)  # 근린생활시설 storeys
    assert out["counts"]["api_estimate"] == 1 and out["counts"]["unknown"] == 0
    assert sorted(calls) == ["LP_PA_CBND_BUBUN", "LT_C_BLDGINFO", "LT_C_SPBD"]  # one box query each
    assert not any(p.name != f"b{terrain_pack.SUFFIX}" for p in tmp_path.iterdir())  # nothing written down


def test_vworld_floors_stay_out_of_the_export(tmp_path, monkeypatch):
    """The building that got VWorld's floors on the screen goes out as a ground line (no map floors here)."""
    test_a_file_building_without_height_or_floors_asks_vworld_once_per_layer(tmp_path, monkeypatch)
    import json
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "landapi"
    origin = json.loads((fixtures / "context_pack_building_sample.json").read_text(encoding="utf-8"))["origin"]
    out = context3d.build({"origin": origin, "parcels": []}, 200, folder=tmp_path, ledger=lambda pnu: [], use_cache=False)
    assert out["buildings"][0]["offline"] is None
    layers = {layer["short"]: layer for layer in context3d.export_layers(out)}
    assert "건물 - 추정 높이" not in layers and len(layers["건물 - 높이 미확인(바닥선)"]["curves"]) == 1

    # with a 1:5,000 building over it, the export uses those floors instead
    conn = terrain_pack.create(tmp_path / f"m{terrain_pack.SUFFIX}", {"name": "m", "kind": "areas", "source": "1:5,000"})
    terrain_pack.add_map_building(conn, json.loads((fixtures / "context_pack_building_sample.json").read_text(encoding="utf-8"))["ring"], 6, "")
    conn.commit()
    conn.close()
    out = context3d.build({"origin": origin, "parcels": []}, 200, folder=tmp_path, ledger=lambda pnu: [], use_cache=False)
    b = out["buildings"][0]
    assert b["height_source"] == "api_estimate" and b["offline"] == {"height": pytest.approx(6 * 3.8), "source": "map_estimate", "floors": 6}
    solid = {layer["short"]: layer for layer in context3d.export_layers(out)}["건물 - 추정 높이"]["solids"][0]
    assert solid["height"] == pytest.approx(b["ground"] + 6 * 3.8 - b["base"], abs=0.02)


def test_a_ledger_lookup_that_drops_is_tried_once_more_before_falling_back(tmp_path, monkeypatch):
    fake_vworld_layers(monkeypatch)
    monkeypatch.setattr(context3d, "LEDGER_WAIT", 0)
    tries: dict[str, int] = {}

    def flaky(pnu):  # every parcel drops once, then answers
        tries[pnu] = tries.get(pnu, 0) + 1
        if tries[pnu] == 1:
            raise landapi.LandApiError("network", "timed out")
        return ledger(pnu)

    out = context3d.build(plan_for_site(), 200, folder=tmp_path, ledger=flaky, use_cache=False)
    assert tries and set(tries.values()) == {2}
    assert not [n for n in out["notes"] if n.startswith("ledger:")]

    def down(pnu):  # still down on the second try: the old fallback, said once per parcel
        tries[pnu] = tries.get(pnu, 0) + 1
        raise landapi.LandApiError("network", "timed out")

    tries.clear()
    out = context3d.build(plan_for_site(), 200, folder=tmp_path, ledger=down, use_cache=False)
    assert set(tries.values()) == {2} and out["counts"]["ledger"] == 0
    assert out["notes"].count("ledger:network") == len(tries)

    def no_key(pnu):  # a missing key is not worth a second try
        tries[pnu] = tries.get(pnu, 0) + 1
        raise landapi.LandApiError("no_key", "DATA_GO_KR_API_KEY")

    tries.clear()
    context3d.build(plan_for_site(), 200, folder=tmp_path, ledger=no_key, use_cache=False)
    assert set(tries.values()) == {1}


def test_lines_are_cut_to_the_ground_square():
    parts = context3d.clip_line([[-250, 0], [0, 0], [250, 0]], 200)
    assert [p.tolist() for p in parts] == [[[-200, 0], [0, 0], [200, 0]]]
    # out, in, out and in again: two parts, each ending on the edge
    parts = context3d.clip_line([[0, 0], [0, 300], [10, 300], [10, 0]], 200)
    assert [p.tolist() for p in parts] == [[[0, 0], [0, 200]], [[10, 200], [10, 0]]]
    assert context3d.clip_line([[300, 300], [400, 300]], 200) == []
    assert context3d.clip_line([[100, 300], [300, 100]], 200) == []  # touches one corner only


def test_export_keeps_local_ground_and_crossing_contour_without_vworld(tmp_path, monkeypatch):
    from sida.experts.site import hooks

    conn = terrain_pack.create(tmp_path / "local.terrain.sqlite", {"kind": "contours"})
    terrain_pack.add_contour(conn, 25, [lonlat(-300, 0), lonlat(300, 0)])
    conn.commit()
    conn.close()
    monkeypatch.setattr(terrain_pack, "TERRAIN_DIR", tmp_path)
    monkeypatch.setattr(hooks.site_facts, "load_facts", lambda path: {"site": "test"})
    monkeypatch.setattr(hooks.site_facts, "board_summary", lambda facts: {"parcels": []})
    plan = plan_for_site()
    monkeypatch.setattr("sida.board.site_plan", lambda parcels: plan)

    def offline(*args, **kwargs):
        raise AssertionError("export must not request VWorld screen layers")

    monkeypatch.setattr(landapi, "features_in_box", offline)
    assert hooks.board_ground(tmp_path)["nx"] == 101
    layers = {item["short"]: item for item in hooks.board_export_layers(tmp_path)}
    assert layers["지형"]["surfaces"]
    assert layers["등고선 - 계곡선"]["curves"][0]["points"] == [[-200, 0, 0], [200, 0, 0]]


def test_exported_ground_lines_stay_on_the_ground(pack, monkeypatch):
    fake_vworld_layers(monkeypatch)
    conn = terrain_pack.create(pack / f"r{terrain_pack.SUFFIX}", {"name": "r", "kind": "areas", "source": "1:5,000"})
    plan = plan_for_site()
    # a road strip running far past the east edge of the 200 m square
    terrain_pack.add_area(conn, "road", [lonlat(x, y) for x, y in ((100, -5), (270, -5), (270, 5), (100, 5))])
    conn.commit()
    conn.close()
    out = context3d.build(plan, 200, folder=pack, ledger=ledger, use_cache=False)
    road = next(layer for layer in context3d.export_layers(out) if layer["short"] == "지형 - 도로")
    points = [p for c in road["curves"] for p in c["points"]]
    assert max(abs(x) for x, _, _ in points) <= 200.01 and max(abs(y) for _, y, _ in points) <= 200.01


def test_the_ground_hook_gives_the_terrain_grid_or_nothing(tmp_path, pack, monkeypatch):
    from sida.experts.site import hooks

    assert hooks.board_ground(tmp_path) is None  # no site
    fake_vworld_layers(monkeypatch)
    out = context3d.build(plan_for_site(), 200, folder=pack, ledger=ledger, use_cache=False)
    monkeypatch.setattr(hooks.site_facts, "load_facts", lambda path: {"x": 1})
    monkeypatch.setattr(hooks.site_facts, "board_summary", lambda facts: {"parcels": [{}]})
    plan = plan_for_site()
    monkeypatch.setattr("sida.board.site_plan", lambda parcels: plan)
    monkeypatch.setattr(context3d, "build", lambda plan, **kwargs: out)
    ground = hooks.board_ground(tmp_path)
    assert ground["nx"] == out["terrain"]["n"] and ground["min_x"] == out["terrain"]["min"] and ground["z"] == out["terrain"]["z"]
    monkeypatch.setattr(context3d, "build", lambda plan, **kwargs: {**out, "terrain": None})
    assert hooks.board_ground(tmp_path) is None  # no terrain pack over the site


def test_an_export_after_the_screen_reuses_its_result_without_asking_the_ledger_again(pack, monkeypatch):
    fake_vworld_layers(monkeypatch)
    conn = terrain_pack.create(pack / f"b{terrain_pack.SUFFIX}", {"name": "b", "kind": "buildings", "source": "GIS건물통합정보"})
    terrain_pack.add_building(conn, square(60, 0, 10)[:-1], {"pnu": "1111010100100020000"})
    terrain_pack.add_building(conn, square(150, 150, 10)[:-1], {})  # floors from VWorld only (screen)
    conn.commit()
    conn.close()
    asked: list[str] = []

    def counting(pnu):
        asked.append(pnu)
        return ledger(pnu)

    context3d._cache.clear()
    screen = context3d.build(plan_for_site(), 200, folder=pack, ledger=counting)
    n = len(asked)
    assert n and any(b["height_source"] == "api_estimate" for b in screen["buildings"])
    export = context3d.build(plan_for_site(), 200, folder=pack, ledger=counting, for_export=True)
    assert len(asked) == n  # no 건축물대장 call for the export
    layers = {layer["short"]: layer for layer in context3d.export_layers(export)}
    solids = [s for k in ("건물 - 측정 높이", "건물 - 추정 높이") for s in layers.get(k, {}).get("solids", [])]
    assert len(solids) == 1  # the VWorld-floors building is left out of the file (no map floors either)
    assert "건물 - 높이 미확인(바닥선)" in layers
    context3d._cache.clear()
    context3d.build(plan_for_site(), 200, folder=pack, ledger=counting, for_export=True)
    assert len(asked) > n  # without a screen result the export asks for itself
    context3d._cache.clear()


def _matching_case(pack, monkeypatch):
    """
    The two cases found in 중구, with made-up coordinates (1:5,000 map coordinates do not go
    into the repository): like 서울시청, a parcel whose 신관 (대장 13층·53.5m·건축면적 2,500㎡
    here) is missing from the building file, which has a 1,600㎡ outline and a small piece of it,
    while the 1:5,000 map has the 신관's outline; like 센터플레이스, a parcel whose file has only a
    324㎡ outline carrying the tower's name and height (대장 23층·97.6m·1,677㎡) while the map has
    the 1,681㎡ outline; and a parcel whose 동 is only in VWorld (screen only).
    """
    hall, tower, only, far = ("1111010100100110000", "1111010100100120000", "1111010100100130000",
                              "1111010100100140000")
    conn = terrain_pack.create(pack / f"b{terrain_pack.SUFFIX}", {"name": "b", "kind": "buildings", "source": "GIS건물통합정보"})
    terrain_pack.add_building(conn, square(-75, -20, 20)[:-1], {"pnu": hall, "height": 35.8, "floors": 6, "use": "업무시설"})
    terrain_pack.add_building(conn, square(-45, 20, 5)[:-1], {"pnu": hall})  # a piece inside the 신관
    terrain_pack.add_building(conn, square(75, 10, 9)[:-1], {"pnu": tower, "height": 97.6, "floors": 23, "name": "센터플레이스"})
    terrain_pack.add_building(conn, square(25, 140, 3)[:-1], {"pnu": only})  # a shed
    terrain_pack.add_building(conn, square(0, -185, 3)[:-1], {"pnu": far})  # a shed on a parcel reaching out
    conn.commit()
    conn.close()
    conn = terrain_pack.create(pack / f"m{terrain_pack.SUFFIX}", {"name": "m", "kind": "areas", "source": "1:5,000"})
    terrain_pack.add_map_building(conn, square(-50, 15, 25)[:-1], 11, "업무시설")  # the 신관
    terrain_pack.add_map_building(conn, square(50, -5, 20.5)[:-1], 23, "근린생활시설")  # the tower
    terrain_pack.add_map_building(conn, square(0, -230, 15)[:-1], 4, "")  # past the radius
    conn.commit()
    conn.close()
    layers = {
        "LT_C_SPBD": [feature(square(0, 120, 15), buld_nm="별관", gro_flo_co="5")],
        "LT_C_BLDGINFO": [],
        "LP_PA_CBND_BUBUN": [feature(square(-60, 0, 45), pnu=hall, jibun="31 대"),
                             feature(square(60, 0, 40), pnu=tower, jibun="155 대"),
                             feature(square(5, 125, 30), pnu=only, jibun="7 대"),
                             feature(square(0, -215, 35), pnu=far, jibun="9 대")],
    }

    def http_get(url, params):
        found = layers[params["data"]]
        return {"response": {"status": "OK" if found else "NOT_FOUND", "page": {"total": "1"},
                             "result": {"featureCollection": {"features": found}}}}

    monkeypatch.setattr(landapi, "_http_get", http_get)
    monkeypatch.setattr(landapi, "vworld_credentials", lambda: ("key", "domain"))
    rows = {
        hall: [{"dong": "신관", "name": "서울특별시 청사", "purpose": "업무시설", "building_area_m2": 2500.0,
                "floors_above": 13, "height_m": 53.5},
               {"dong": "", "name": "", "purpose": "업무시설", "building_area_m2": 0.0, "floors_above": 7, "height_m": 0.0}],
        tower: [{"dong": "", "name": "센터플레이스", "purpose": "업무시설", "building_area_m2": 1677.0,
                 "floors_above": 23, "height_m": 97.6}],
        only: [{"dong": "별관", "name": "", "purpose": "업무시설", "building_area_m2": 900.0, "floors_above": 5, "height_m": 20.0}],
        far: [{"dong": "", "name": "", "purpose": "", "building_area_m2": 900.0, "floors_above": 4, "height_m": 15.0}],
    }
    return lambda pnu: rows.get(pnu, [])


def test_each_ledger_dong_takes_the_outline_closest_to_its_building_area(pack, monkeypatch):
    look = _matching_case(pack, monkeypatch)
    out = context3d.build(plan_for_site(), 200, folder=pack, ledger=look, use_cache=False)
    by_height = {b["height"]: b for b in out["buildings"]}
    new = by_height[53.5]  # 서울시청 신관: on the 1:5,000 map's outline, 13층
    assert new["floors"] == 13 and new["match"] == {"source": "map", "dong": "신관", "ratio": 1.0}
    assert abs(context3d._area(np.asarray(new["outline"]))) == pytest.approx(2500, rel=0.01)
    assert by_height[35.8]["height_source"] == "file" and by_height[35.8]["match"] is None  # 1,600㎡: not the 신관
    assert any(abs(context3d._area(np.asarray(b["outline"]))) == pytest.approx(100, rel=0.05) for b in out["left_out"])

    tower = by_height[97.6]  # 센터플레이스: 23층 on the ~1,681㎡ outline, not the small one
    assert tower["floors"] == 23 and tower["match"]["source"] == "map" and tower["match"]["ratio"] == 1.0
    assert abs(context3d._area(np.asarray(tower["outline"]))) == pytest.approx(1681, rel=0.01)
    assert sorted(b["name"] for b in out["unknown_buildings"]) == ["", "", "센터플레이스"]  # two sheds; the small one repeats the tower
    assert sum(b["height"] == 97.6 for b in out["buildings"]) == 1

    assert 15.0 not in by_height  # its only outline lies past the radius: not drawn
    assert all(np.abs(np.asarray(b["outline"]).mean(axis=0)).max() <= 200 for b in out["buildings"])
    annex = by_height[20.0]  # only VWorld has its outline: drawn, but never written to a file
    assert annex["display_only"] and annex["match"]["source"] == "vworld"
    solids = [s["height"] for layer in context3d.export_layers(out) for s in layer.get("solids", [])]
    assert not any(abs(h - 20.0 - (annex["ground"] - annex["base"])) < 0.01 for h in solids)
    assert len(solids) == len([b for b in out["buildings"] if not b.get("display_only") and b["height_source"] != "api_estimate"]) + sum(
        1 for b in out["buildings"] if b["height_source"] == "api_estimate" and b.get("offline"))


def test_the_export_finds_the_map_outlines_and_leaves_the_vworld_one_out(pack, monkeypatch):
    look = _matching_case(pack, monkeypatch)
    out = context3d.build(plan_for_site(), 200, folder=pack, ledger=look, use_cache=False, for_export=True)
    heights = sorted(b["height"] for b in out["buildings"] if b["height_source"] == "ledger")
    assert 53.5 in heights and 97.6 in heights and 20.0 not in heights  # no VWorld outline without the screen


def test_assign_ledger_is_one_to_one_and_never_gives_a_leftover_the_tallest_record():
    rows = [{"dong": "A", "building_area_m2": 1000.0, "floors_above": 20, "height_m": 80.0},
            {"dong": "B", "building_area_m2": 300.0, "floors_above": 3, "height_m": 12.0}]
    taken, left = context3d.assign_ledger(rows, [(1, 980.0, {}), (2, 310.0, {}), (3, 760.0, {})])
    assert taken[1][0]["dong"] == "A" and taken[2][0]["dong"] == "B" and 3 not in taken and left == []
    taken, left = context3d.assign_ledger(rows[:1], [(1, 320.0, {})])  # one 동, one outline, 3 times apart
    assert taken == {} and left == rows[:1]
    taken, _left = context3d.assign_ledger(rows[:1], [(1, 600.0, {"dong_nm": "A"})])  # named: half to double
    assert taken[1][1] == 0.6
