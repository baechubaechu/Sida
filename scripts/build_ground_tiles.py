#!/usr/bin/env python3
"""
Solve the ground of a region ahead of time (sida/experts/site/ground_tiles.py), so building a
site's surroundings reads the heights instead of solving them. Run it after making or changing
a contours or roads pack: it solves again only the tiles whose heights changed (until then the
app solves the ground near the changed packs per site as before).

    python scripts/build_ground_tiles.py --name seoul
    python scripts/build_ground_tiles.py --name seoul --box 126.76,37.41,127.19,37.72 --workers 8
    python scripts/build_ground_tiles.py --name gyeonggi --box 126.3,36.9,127.9,38.3 --skip-others

Without --box it covers the height packs' extent. --skip-others leaves out the tiles another
tiles file in the folder already has and still counts (a 도 whose box takes in a 광역시). The tiles go to
~/Sida/context_data/<name>.ground.sqlite (outside the repository). An interrupted run carries on
where it stopped when started again.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import ExitStack, closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sida.experts.site import context3d, ground_tiles, terrain_pack  # noqa: E402

MAX_WORKERS = 8  # Windows ran out of system resources (WinError 1450) with 23 workers on 3,276 tiles
IN_FLIGHT = 4  # tiles handed out per worker at a time, not the whole region at once


def solved(pool, todo, folder: Path, ahead: int, fn=None):
    """((ix, iy), fn(ix, iy, folder=folder)) for each of `todo` as the pool finishes them, with at
    most `ahead` handed out at a time. fn: context3d.solve_tile unless given."""
    fn = fn or context3d.solve_tile
    waiting = iter(todo)
    running = {}
    while True:
        for key in waiting:
            running[pool.submit(fn, *key, folder=folder)] = key
            if len(running) >= ahead:
                break
        if not running:
            return
        finished, _ = wait(running, return_when=FIRST_COMPLETED)
        for future in finished:
            yield running.pop(future), future.result()


def solved_elsewhere(path: Path, folder: Path) -> set[tuple[int, int]]:
    """The tiles of the folder's other tiles files that are made from the packs as they are now."""
    out: set[tuple[int, int]] = set()
    for other in ground_tiles.files(folder):
        if other != path and ground_tiles.current(other, folder):
            out |= ground_tiles.done(other)
    return out


def build(name: str, folder: Path, box=None, workers: int = 1, log=print, skip_others: bool = False) -> Path:
    """Make (or finish, or bring up to the packs now) <name>.ground.sqlite in the folder for the
    box (default: the packs' extent). skip_others: not the tiles another file already has."""
    box = box or ground_tiles.extent(folder)
    if box is None:
        raise SystemExit("no contours or roads pack in " + str(folder))
    path = folder / f"{name}{ground_tiles.SUFFIX}"
    started, made = time.perf_counter(), 0
    with ExitStack() as stack:
        pool = stack.enter_context(ProcessPoolExecutor(max_workers=workers)) if workers > 1 else None

        def each(keys, fn):
            if pool is not None:
                return solved(pool, keys, folder, workers * IN_FLIGHT, fn)
            return ((key, fn(*key, folder=folder)) for key in keys)

        if path.exists() and ground_tiles.usable(ground_tiles.info(path)):
            conn = stack.enter_context(closing(sqlite3.connect(path)))
            dropped = ground_tiles.refresh(conn, folder, lambda keys: each(keys, context3d.tile_digest), log)
            if dropped:
                log(f"{dropped} tiles whose heights changed to solve again")
            missing = sorted(ground_tiles.done(path) - set(ground_tiles.inputs(conn)))
            if missing:  # a file from before the digests: record them (the packs have not changed for these)
                log(f"recording the heights of {len(missing)} tiles")
                for k, (key, digest) in enumerate(each(missing, context3d.tile_digest), 1):
                    ground_tiles.set_inputs(conn, *key, digest)
                    if k % 200 == 0:
                        conn.commit()
                conn.commit()
            have = ground_tiles.done(path)
        else:
            have = set()
            conn = stack.enter_context(closing(
                ground_tiles.create(path, folder, name=name, box=",".join(f"{v:g}" for v in box))))
        elsewhere = solved_elsewhere(path, folder) - have if skip_others else set()
        todo = [(ix, iy) for ix, iy in ground_tiles.tiles_in_box(*box) if (ix, iy) not in have | elsewhere]
        others = f", {len(elsewhere)} in other files" if skip_others else ""
        log(f"{len(todo)} tiles to solve ({len(have)} already done{others}) in {path}")
        for k, (key, (tile, digest)) in enumerate(each(todo, context3d.solve_tile), 1):
            if tile is not None:
                ground_tiles.add(conn, tile)
                made += 1
            else:
                ground_tiles.mark_empty(conn, *key)
            ground_tiles.set_inputs(conn, *key, digest)
            if k % 50 == 0 or k == len(todo):
                conn.commit()
                log(f"  {k}/{len(todo)}  {time.perf_counter() - started:.0f} s")
        conn.commit()
    log(f"{made} tiles with ground, {time.perf_counter() - started:.0f} s")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", required=True, help="file name, e.g. seoul")
    ap.add_argument("--box", help="west,south,east,north in degrees (default: the height packs' extent)")
    ap.add_argument("--workers", type=int, default=max(1, min(MAX_WORKERS, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--folder", type=Path, default=terrain_pack.TERRAIN_DIR)
    ap.add_argument("--skip-others", action="store_true", help="leave out tiles another tiles file has")
    args = ap.parse_args()
    box = tuple(float(v) for v in args.box.split(",")) if args.box else None
    build(args.name, args.folder, box, args.workers, skip_others=args.skip_others)
    return 0


if __name__ == "__main__":
    sys.exit(main())
