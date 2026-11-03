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
    assert terrain_pack.query(west, south, east, north, folder=pack / "none") == {"contours": [], "spots": [], "areas": [], "sources": []}
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
    assert out["counts"] == {"ledger": 1, "vworld": 1, "estimate": 3, "unknown": 1, "inner": 1}
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
