"""Ground tiles made ahead of time (ground_tiles, scripts/build_ground_tiles.py), on made-up packs."""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

import numpy as np
import pytest

from sida.experts.site import context3d, ground_tiles, terrain_pack
from tests.experts.site.test_context3d import LAT0, LON0, lonlat

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def small_tiles(monkeypatch):
    """Coarse grids and a short margin: the same steps on far fewer cells."""
    monkeypatch.setattr(context3d, "SOLVE_STEP", 4.0)
    monkeypatch.setattr(ground_tiles, "STEP", 8.0)
    monkeypatch.setattr(ground_tiles, "TILE_MARGIN", 80.0)


@pytest.fixture
def heights(tmp_path):
    """A contours pack: the ground rises 10 m from y = -150 to y = 150, plus a spot height."""
    conn = terrain_pack.create(tmp_path / f"h{terrain_pack.SUFFIX}", {"name": "h", "source": "made up"})
    for y, elev in ((-150, 10.0), (-50, 13.0), (50, 17.0), (150, 20.0)):
        terrain_pack.add_contour(conn, elev, [lonlat(x, y) for x in range(-600, 601, 20)])
    terrain_pack.add_spot(conn, *lonlat(0, 0), 15.0)
    conn.commit()
    conn.close()
    return tmp_path


def load_script():
    spec = importlib.util.spec_from_file_location("build_ground_tiles", ROOT / "scripts" / "build_ground_tiles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make(folder: Path, box=None) -> Path:
    west, south = lonlat(-150, -150)
    east, north = lonlat(150, 150)
    return load_script().build("t", folder, box or (west, south, east, north), workers=1, log=lambda _m: None)


def test_heights_round_trip_through_a_tile():
    z = np.array([[10.0, 10.25, 9.99], [-3.5, 0.0, 120.01]])
    assert ground_tiles.decode(ground_tiles.encode(z), 3, 2) == pytest.approx(z)


def test_tiles_meeting_a_box_and_the_tile_of_a_point():
    ix, iy = ground_tiles.tile_of(127.005, 37.501)
    assert (int(ix), int(iy)) == (12700, 4687)
    west, south, east, north = ground_tiles.tile_box(12700, 4687)
    assert west <= 127.005 < east and south <= 37.501 < north
    assert ground_tiles.tiles_in_box(126.995, 37.501, 127.005, 37.502) == [(12699, 4687), (12700, 4687)]


def test_the_ground_comes_from_tiles_and_matches_solving_it(heights):
    make(heights)
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})
    from_tiles = context3d.ground(frame, 100, folder=heights)
    solved = context3d.ground(frame, 100, folder=heights, tiles=False)
    assert from_tiles["from_tiles"] and not solved["from_tiles"]
    assert from_tiles["ground_elev"] == pytest.approx(solved["ground_elev"], abs=0.3)
    assert np.abs(from_tiles["grid"] - solved["grid"]).max() < 0.5  # 8 m tiles against a 4 m solve
    assert {c["elev"] for c in from_tiles["contours"]} == {c["elev"] for c in solved["contours"]}


def test_tiles_from_packs_that_changed_since_are_not_used(heights):
    path = make(heights)
    assert ground_tiles.current(path, heights)
    pack = heights / f"h{terrain_pack.SUFFIX}"
    later = time.time() + 10
    os.utime(pack, (later, later))
    assert not ground_tiles.current(path, heights)
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})
    assert context3d.ground(frame, 100, folder=heights)["from_tiles"] is False


def test_a_range_beyond_the_tiles_is_solved_as_before(heights):
    west, south = lonlat(5, 5)
    make(heights, (west, south, west + 0.0001, south + 0.0001))  # one tile only
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})  # its range reaches the next tile west
    g = context3d.ground(frame, 100, folder=heights)
    assert g["from_tiles"] is False and g["grid"] is not None


def test_an_interrupted_run_carries_on(heights):
    path = make(heights)
    first = ground_tiles.done(path)
    assert first
    log = []
    west, south = lonlat(-150, -150)
    east, north = lonlat(150, 150)
    load_script().build("t", heights, (west, south, east, north), workers=1, log=log.append)
    assert log[0].startswith(f"0 tiles to solve ({len(first)} already done)")


def test_a_tile_without_heights_near_it_is_not_made(heights):
    far = ground_tiles.tile_of(129.0, 35.0)
    assert context3d.make_tile(int(far[0]), int(far[1]), folder=heights) is None
