"""site_relay — the ground and the 건축물대장 of one site from the Sida relay, for a PC without packs."""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from sida import relay
from sida.experts.site import context3d, ground_tiles, site_relay, terrain_pack
from tests.experts.site.test_context3d import LAT0, LON0, fake_vworld_layers, lonlat, plan_for_site
from tests.experts.site.test_ground_tiles import make

BASE = "https://relay.test"
SQUARE_M = [[-20, -20], [20, -20], [20, 20], [-20, 20]]


@pytest.fixture(autouse=True)
def small_tiles(monkeypatch):
    """Coarse grids and a short margin, as in test_ground_tiles."""
    monkeypatch.setattr(context3d, "SOLVE_STEP", 4.0)
    monkeypatch.setattr(ground_tiles, "STEP", 8.0)
    monkeypatch.setattr(ground_tiles, "TILE_MARGIN", 80.0)


@pytest.fixture
def heights(tmp_path):
    """A contours pack: the ground rises 10 m from y = -150 to y = 150 (15 m at the middle)."""
    folder = tmp_path / "packs"
    folder.mkdir()
    conn = terrain_pack.create(folder / f"h{terrain_pack.SUFFIX}", {"name": "h", "kind": "contours", "source": "made up"})
    for y, elev in ((-150, 10.0), (-50, 13.0), (50, 17.0), (150, 20.0)):
        terrain_pack.add_contour(conn, elev, [lonlat(x, y) for x in range(-600, 601, 20)])
    terrain_pack.add_spot(conn, *lonlat(0, 0), 15.0)
    conn.commit()
    conn.close()
    return folder


@pytest.fixture
def relay_on(monkeypatch):
    """An access key and a relay that answers from `server["ground"]` / `server["ledger"]`; `asked` lists the calls."""
    monkeypatch.setenv(relay.ENV_NAME, BASE)
    monkeypatch.setenv(relay.TOKEN_ENV, "sida_test_key_123")
    server = {"asked": [], "ledger": {}, "down": False,
              "ground": lambda body: {"format": 1, "radius": body["radius"], "half": body["radius"] + 60, "step": 2.0,
                                      "grid": None, "contours": [], "sources": []}}

    def http_post(url, body):
        server["asked"].append((url.removeprefix(BASE), body))
        assert relay.headers(url) == {"Authorization": "Bearer sida_test_key_123"}
        if server["down"]:
            raise site_relay.SiteRelayError("network", "ConnectionError")
        if url.endswith(site_relay.GROUND_PATH):
            return json.loads(json.dumps(server["ground"](body)))  # as it comes over the wire
        return {"rows": {p: server["ledger"][p] for p in body["pnus"] if p in server["ledger"]}, "month": "2026-09"}

    monkeypatch.setattr(site_relay, "_http_post", http_post)
    return server


def test_the_relay_sends_only_local_metres_and_heights_relative_to_the_site(heights, monkeypatch):
    make(heights)
    asked = []
    query = terrain_pack.query
    monkeypatch.setattr(terrain_pack, "query", lambda *a, **k: asked.append(k) or query(*a, **k))
    shared = context3d.shared_ground(LON0, LAT0, 100, folder=heights)
    assert asked == [{"folder": heights, "heights": False}]  # no contour or road points read: the tiles have the heights
    assert shared["tiles"] and "contours" not in shared and "grid" not in shared  # the PC draws the contours
    text = json.dumps(shared)
    assert "elev" not in text and str(LON0) not in text and str(LAT0) not in text
    grid = context3d._shared_grid(shared, shared["half"])
    middle = grid[grid.shape[0] // 2, grid.shape[1] // 2]
    assert abs(middle) < 0.05  # the ground at the site's middle is 0, not 15 m above the sea
    assert shared["phase"] == pytest.approx(15.0, abs=0.3)  # 15 m modulo 25 m: where the 5 m lines fall, not the height
    for t in shared["tiles"]:  # metres within the range and its margin, not degrees
        assert abs(t["x0"]) <= shared["half"] + t["dx"] + 0.01 and abs(t["y0"]) <= shared["half"] + t["dy"] + 0.01
        assert abs(t["x0"] + (t["nx"] - 1) * t["dx"]) <= shared["half"] + t["dx"] + 0.01


def test_a_pc_without_packs_draws_the_relays_ground_like_the_packs(heights, relay_on, tmp_path, monkeypatch):
    make(heights)
    monkeypatch.setattr(site_relay, "ASK_RADIUS", 100.0)  # the tiles here cover ±150 m
    relay_on["ground"] = lambda body: context3d.shared_ground(body["lon"], body["lat"], body["radius"], folder=heights)
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})
    here = tmp_path / "no_packs"
    remote = context3d.ground(frame, 80, folder=here)
    local = context3d.ground(frame, 80, folder=heights)
    assert remote["relative"] and remote["ground_elev"] == 0 and not local["relative"]
    assert remote["half"] == local["half"] and remote["grid"].shape == local["grid"].shape
    xs, ys = np.meshgrid(np.linspace(-80, 80, 41), np.linspace(-80, 80, 41))
    on_remote = context3d.sample(remote["grid"], remote["half"], remote["step"], xs.ravel(), ys.ravel())
    on_local = context3d.sample(local["grid"], local["half"], local["step"], xs.ravel(), ys.ravel())
    assert np.abs(on_remote - on_local).max() < 0.011  # the same tiles at the seams: only cm rounding apart
    # The contours are drawn on the PC from the joined grid, at whole 5 m above the sea.
    elev0 = local["ground_elev"]
    drawn = context3d.grid_contours(local["grid"] + elev0, local["half"], local["step"], context3d.CONTOUR_EVERY)
    assert {round(c["z"], 1) for c in remote["contours"]} == {round(level - elev0, 1) for level, _ in drawn}
    assert all(abs((c["z"] + elev0) % 5) < 0.05 or abs((c["z"] + elev0) % 5 - 5) < 0.05 for c in remote["contours"])
    assert [b for _url, b in relay_on["asked"]] == [{"lon": LON0, "lat": LAT0, "radius": 100.0}]
    # A smaller range and a lost connection: drawn from what was received, not asked again.
    relay_on["down"] = True
    again = context3d.ground(frame, 50, folder=here)
    assert again["relative"] and len(relay_on["asked"]) == 1 and again["half"] == 50 + context3d.MARGIN
    assert list((here / site_relay.CACHE).iterdir())


def test_the_map_features_come_back_as_they_were_sent(tmp_path):
    folder = tmp_path / "packs"
    folder.mkdir()
    conn = terrain_pack.create(folder / f"f{terrain_pack.SUFFIX}", {"name": "f", "kind": "areas", "source": "made up"})
    square = [lonlat(x, y) for x, y in SQUARE_M]
    terrain_pack.add_area(conn, "water", square)
    terrain_pack.add_building(conn, square, {"pnu": "1", "height": 12.5, "name": "가"})
    terrain_pack.add_map_building(conn, square, 3, "주택")
    terrain_pack.add_road_line(conn, "L1", "1", "501", [lonlat(-30, 0), lonlat(30, 0)])
    terrain_pack.add_road_mark(conn, "M1", "2", "531", square, lonlat(0, 1))
    terrain_pack.add_road_mark(conn, "M2", "2", "532", square, None)
    conn.commit()
    conn.close()
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})
    shared = json.loads(json.dumps(context3d.shared_ground(LON0, LAT0, 50, folder=folder)))
    assert shared["tiles"] == [] and shared["phase"] is None  # no ground tiles: no heights
    back = context3d.from_shared(frame, shared, 50)
    assert back["grid"] is None and back["contours"] == []
    (kind, ring), = back["areas"]
    assert kind == "water" and ring == pytest.approx(np.array(SQUARE_M), abs=0.01)
    (house,) = back["buildings"]
    assert house["pnu"] == "1" and house["height"] == 12.5 and house["name"] == "가"
    assert np.asarray(house["ring"]) == pytest.approx(np.asarray(square), abs=1e-7)  # lon/lat again, on this PC
    assert back["map_buildings"][0]["floors"] == 3 and back["map_buildings"][0]["use"] == "주택"
    (line,) = back["paint"]["lines"]
    assert line["type"] == "1" and line["kind"] == "501" and line["points"] == pytest.approx(np.array([[-30, 0], [30, 0]]), abs=0.01)
    one, two = back["paint"]["marks"]
    assert one["ahead"] == pytest.approx(np.array([0, 1]), abs=0.01) and two["ahead"] is None
    assert two["ring"] == pytest.approx(np.array(SQUARE_M), abs=0.01)


def test_without_an_access_key_or_an_answer_the_ground_is_left_to_the_caller(relay_on, tmp_path, monkeypatch):
    assert site_relay.ground(LON0, LAT0, 200, folder=tmp_path) is None  # nothing on the server here
    assert not (tmp_path / site_relay.CACHE).exists()  # not kept: asked again next time
    relay_on["down"] = True
    assert site_relay.ground(LON0, LAT0, 200, folder=tmp_path) is None
    assert site_relay.ground(LON0, LAT0, 2000, folder=tmp_path) is None  # beyond what the relay sends
    monkeypatch.delenv(relay.TOKEN_ENV)
    count = len(relay_on["asked"])
    assert site_relay.ground(LON0, LAT0, 200, folder=tmp_path) is None and len(relay_on["asked"]) == count


def test_the_kept_answers_stay_under_their_size_dropping_the_least_recently_used(tmp_path):
    for k, name in enumerate(("a", "b", "c")):
        path = tmp_path / f"ground_{name}.json.gz"
        path.write_bytes(b"x" * 100)
        os.utime(path, (k, k))
    site_relay.trim(tmp_path, limit=250)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ground_b.json.gz", "ground_c.json.gz"]


def test_ledger_rows_come_from_the_relay_in_parts_and_only_for_what_was_asked(relay_on, monkeypatch):
    monkeypatch.setattr(site_relay, "MAX_PNUS", 2)
    relay_on["ledger"] = {"1": [{"name": "가"}], "3": [], "9": [{"name": "not asked"}]}
    found, meta = site_relay.ledger(["3", "1", "2", "1"])
    assert found == {"1": [{"name": "가"}], "3": []} and meta == {"month": "2026-09", "relay": True}
    assert [b["pnus"] for _url, b in relay_on["asked"]] == [["1", "2"], ["3"]]
    relay_on["down"] = True
    assert site_relay.ledger(["1"]) == ({}, None)


def test_surroundings_take_the_relays_ledger_and_ask_data_go_kr_only_for_the_rest(relay_on, tmp_path, monkeypatch):
    fake_vworld_layers(monkeypatch)
    monkeypatch.setattr(context3d, "LIVE_NEAR", 0.0)  # every parcel off the site is "far"
    relay_on["ledger"] = {"1111010100100020000": [{"dong": "", "purpose": "업무시설", "building_area_m2": 400.0,
                                                   "floors_above": 3, "height_m": 11.2}]}
    live = []
    monkeypatch.setattr(context3d, "_ledger_rows", lambda pnu: live.append(pnu) or [])
    out = context3d.build(plan_for_site(), 200, folder=tmp_path, use_cache=False)
    tall = next(b for b in out["buildings"] if b["name"] == "대장 높이")
    assert tall["height"] == 11.2 and tall["height_source"] == "ledger"
    assert "1111010100100020000" not in live and "1111010100100010000" in live  # the site itself: live
    assert out["ledger_source"]["month"] == "2026-09"


def test_at_a_seam_a_point_takes_the_tile_whose_own_square_holds_it():
    # Two tiles meeting at x = 10, each with two border cells over the other (solved apart: 1 m vs 2 m).
    west = {"x0": 0.0, "y0": 0.0, "dx": 2.0, "dy": 2.0, "z": np.full((6, 8), 1.0), "core": [0.0, 0.0, 10.0, 10.0]}
    east = {"x0": 6.0, "y0": 0.0, "dx": 2.0, "dy": 2.0, "z": np.full((6, 8), 2.0), "core": [10.0, 0.0, 20.0, 10.0]}
    x = np.array([7.0, 9.9, 10.0, 12.0])
    got = context3d._tiles_sample([west, east], x, np.full(4, 5.0))
    assert got.tolist() == [1.0, 1.0, 2.0, 2.0]  # either order of the tiles
    assert context3d._tiles_sample([east, west], x, np.full(4, 5.0)).tolist() == [1.0, 1.0, 2.0, 2.0]
    old = [{k: v for k, v in p.items() if k != "core"} for p in (east, west)]  # an answer without cores
    assert context3d._tiles_sample(old, x, np.full(4, 5.0)).tolist() == [2.0, 2.0, 2.0, 2.0]
