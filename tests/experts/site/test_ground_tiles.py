"""Ground tiles made ahead of time (ground_tiles, scripts/build_ground_tiles.py), on made-up packs."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
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


def test_a_pack_copied_without_change_still_counts(heights):
    path = make(heights)
    pack = heights / f"h{terrain_pack.SUFFIX}"
    later = time.time() + 10
    os.utime(pack, (later, later))  # a new modification time, the same bytes
    assert ground_tiles.current(path, heights)
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})
    assert context3d.ground(frame, 100, folder=heights)["from_tiles"] is True


FAR = 2700  # m east of the site: a few tiles away


@pytest.fixture
def two_packs(heights):
    """The contours pack and a second one with one spot height FAR m east."""
    conn = terrain_pack.create(heights / f"r{terrain_pack.SUFFIX}", {"name": "r", "source": "made up"})
    terrain_pack.add_spot(conn, *lonlat(FAR, 0), 30.0)
    conn.commit()
    conn.close()
    return heights


def box_to(x_east: float):
    west, south = lonlat(-150, -150)
    east, north = lonlat(x_east, 150)
    return west, south, east, north


def test_a_changed_pack_drops_only_the_tiles_near_it(two_packs):
    folder = two_packs
    path = make(folder, box_to(FAR + 100))
    every = ground_tiles.done(path)
    far = tuple(int(v) for v in ground_tiles.tile_of(*lonlat(FAR, 0)))
    conn = sqlite3.connect(folder / f"r{terrain_pack.SUFFIX}")
    terrain_pack.add_spot(conn, *lonlat(FAR + 20, 0), 31.0)  # the pack changes where it is
    conn.commit()
    conn.close()
    later = time.time() + 10
    os.utime(folder / f"r{terrain_pack.SUFFIX}", (later, later))
    assert not ground_tiles.current(path, folder)
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})
    assert context3d.ground(frame, 100, folder=folder)["from_tiles"] is True  # far from the change
    assert ground_tiles.heights(*lonlat(FAR, 0), folder=folder) is None  # near it: solved per site
    log = []
    load_script().build("t", folder, box_to(FAR + 100), workers=1, log=log.append)
    dropped = int(log[0].split()[0])
    assert far in ground_tiles.done(path) and 0 < dropped < len(every) / 2
    assert log[1].startswith(f"{dropped} tiles to solve")
    assert ground_tiles.current(path, folder)
    assert float(ground_tiles.heights(*lonlat(FAR + 20, 0), folder=folder)) == pytest.approx(31.0, abs=0.5)


def test_a_new_pack_drops_only_the_tiles_near_it_and_a_removed_one_too(heights):
    path = make(heights, box_to(FAR + 100))
    every = len(ground_tiles.done(path))
    conn = terrain_pack.create(heights / f"r{terrain_pack.SUFFIX}", {"name": "r", "source": "made up"})
    terrain_pack.add_spot(conn, *lonlat(FAR, 0), 30.0)
    conn.commit()
    conn.close()
    frame = context3d.Frame({"lon": LON0, "lat": LAT0})
    assert context3d.ground(frame, 100, folder=heights)["from_tiles"] is True
    log = []
    load_script().build("t", heights, box_to(FAR + 100), workers=1, log=log.append)
    assert 0 < int(log[0].split()[0]) < every / 2
    (heights / f"r{terrain_pack.SUFFIX}").unlink()
    assert not ground_tiles.current(path, heights)
    assert context3d.ground(frame, 100, folder=heights)["from_tiles"] is True


def test_a_file_from_before_still_counts_and_is_carried_over(heights):
    path = make(heights)
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM meta WHERE key = 'packs'")
    conn.execute("INSERT INTO meta VALUES ('made_from', ?)", (json.dumps(ground_tiles._legacy_made_from(heights)),))
    conn.commit()
    conn.close()
    assert ground_tiles.current(path, heights)
    log = []
    west, south = lonlat(-150, -150)
    east, north = lonlat(150, 150)
    load_script().build("t", heights, (west, south, east, north), workers=1, log=log.append)
    assert log[0].startswith("0 tiles to solve")
    assert "packs" in ground_tiles.info(path) and "made_from" not in ground_tiles.info(path)


def test_a_file_from_before_whose_packs_changed_does_not_count(heights):
    path = make(heights)
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM meta WHERE key = 'packs'")
    conn.execute("INSERT INTO meta VALUES ('made_from', ?)", (json.dumps([["h.terrain.sqlite", 1, 1]]),))
    conn.commit()
    conn.close()
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


def test_a_tile_without_heights_near_it_is_not_made_and_not_solved_again(heights):
    far = ground_tiles.tile_of(129.0, 35.0)
    assert context3d.make_tile(int(far[0]), int(far[1]), folder=heights) is None
    west, south = lonlat(-150, -150)
    east, north = lonlat(150, 150)
    box = (west, south, east + 0.03, north)  # three tiles east of the heights: nothing to solve from
    log = []
    path = load_script().build("t", heights, box, workers=1, log=log.append)
    solved = {(ix, iy) for ix, iy in ground_tiles.done(path)}
    assert len(solved) == len(ground_tiles.tiles_in_box(*box)) and "0 tiles" not in log[0]
    log.clear()
    load_script().build("t", heights, box, workers=1, log=log.append)
    assert log[0].startswith(f"0 tiles to solve ({len(solved)} already done)")


def test_the_pool_is_handed_a_few_tiles_at_a_time_not_the_whole_region(monkeypatch):
    from concurrent.futures import Future

    script = load_script()
    monkeypatch.setattr(script.context3d, "make_tile", lambda ix, iy, folder: (ix, iy))
    got, most = [], [0]

    class Pool:
        submitted = 0

        def submit(self, fn, *args, **kwargs):
            self.submitted += 1
            most[0] = max(most[0], self.submitted - len(got))  # handed out and not yet back
            future = Future()
            future.set_result(fn(*args, **kwargs))
            return future

    todo = [(i, 0) for i in range(50)]
    for key, tile in script.solved(Pool(), todo, Path("."), ahead=6):
        assert key == tile
        got.append(tile)
    assert sorted(got) == todo and most[0] <= 6
