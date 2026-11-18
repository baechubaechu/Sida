"""site_relay — the ground and the 건축물대장 of one site from the Sida relay, for a PC without packs."""

from __future__ import annotations

import base64
import json
import os

import numpy as np
import pytest

from sida import relay
from sida.experts.site import context3d, ground_tiles, site_relay, terrain_pack
from tests.experts.site.test_context3d import LAT0, LON0, fake_vworld_layers, lonlat, plan_for_site
from tests.experts.site.test_ground_tiles import make

BASE = "https://relay.test"


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


def test_the_relay_sends_only_local_metres_and_heights_relative_to_the_site(heights):
    make(heights)
    shared = context3d.shared_ground(LON0, LAT0, 100, folder=heights)
    assert shared["grid"] and shared["contours"]
    text = json.dumps(shared)
    assert "elev" not in text and str(LON0) not in text
    n = shared["grid"]["n"]
    grid = ground_tiles.decode(base64.b64decode(shared["grid"]["z"]), n, n)
    middle = grid[grid.shape[0] // 2, grid.shape[1] // 2]
    assert abs(middle) < 0.05  # the ground at the site's middle is 0, not 15 m above the sea
    assert {round(c["z"]) for c in shared["contours"]} == {-2, 2}  # the 13 m and 17 m lines, relative to 15 m
    points = [p for c in shared["contours"] for p in c["points"]]
    assert max(abs(v) for p in points for v in p) <= 100.01  # metres within the range, not degrees


def test_a_pc_without_packs_draws_the_relays_ground_like_the_packs(heights, relay_on, tmp_path, monkeypatch):
    make(heights)
    monkeypatch.setattr(site_relay, "ASK_RADIUS", 100.0)  # the tiles here cover ±150 m
    relay_on["ground"] = lambda body: context3d.shared_ground(body["lon"], body["lat"], body["radius"], folder=heights)
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})
    here = tmp_path / "no_packs"
    remote = context3d.ground(frame, 80, folder=here)
    local = context3d.ground(frame, 80, folder=heights)
    assert remote["relative"] and remote["ground_elev"] == 0 and not local["relative"]
    xs, ys = np.meshgrid(np.linspace(-80, 80, 9), np.linspace(-80, 80, 9))
    on_remote = context3d.sample(remote["grid"], remote["half"], remote["step"], xs.ravel(), ys.ravel())
    on_local = context3d.sample(local["grid"], local["half"], local["step"], xs.ravel(), ys.ravel())
    assert np.abs(on_remote - on_local).max() < 0.05
    assert sorted(round(c["z"], 1) for c in remote["contours"]) == sorted(round(c["z"], 1) for c in local["contours"])
    assert [b for _url, b in relay_on["asked"]] == [{"lon": LON0, "lat": LAT0, "radius": 100.0}]
    # A smaller range and a lost connection: drawn from what was received, not asked again.
    relay_on["down"] = True
    again = context3d.ground(frame, 50, folder=here)
    assert again["relative"] and len(relay_on["asked"]) == 1
    assert list((here / site_relay.CACHE).iterdir())


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
