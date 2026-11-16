#!/usr/bin/env python3
"""
Solve the ground of a region ahead of time (sida/experts/site/ground_tiles.py), so building a
site's surroundings reads the heights instead of solving them. Run it after making or changing
a contours or roads pack; until then the app solves the ground per site as before.

    python scripts/build_ground_tiles.py --name seoul
    python scripts/build_ground_tiles.py --name seoul --box 126.76,37.41,127.19,37.72 --workers 8

Without --box it covers the height packs' extent. The tiles go to
~/Sida/context_data/<name>.ground.sqlite (outside the repository). An interrupted run carries on
where it stopped when started again, as long as the packs have not changed since.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import ExitStack, closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sida.experts.site import context3d, ground_tiles, terrain_pack  # noqa: E402


def packs_extent(folder: Path) -> tuple[float, float, float, float] | None:
    """west, south, east, north of the heights in the folder's height packs."""
    boxes = []
    for path in ground_tiles.height_packs(folder):
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            for table in ("contours_box", "spots_box", "road_points_box"):
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
                    row = conn.execute(f"SELECT min(west), min(south), max(east), max(north) FROM {table}").fetchone()  # noqa: S608
                    if row and row[0] is not None:
                        boxes.append(row)
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def build(name: str, folder: Path, box=None, workers: int = 1, log=print) -> Path:
    """Make (or finish) <name>.ground.sqlite in the folder for the box (default: the packs' extent)."""
    box = box or packs_extent(folder)
    if box is None:
        raise SystemExit("no contours or roads pack in " + str(folder))
    path = folder / f"{name}{ground_tiles.SUFFIX}"
    if path.exists() and ground_tiles.current(path, folder):
        have = ground_tiles.done(path)
        conn = sqlite3.connect(path)
    else:
        have = set()
        conn = ground_tiles.create(path, folder, name=name, box=",".join(f"{v:g}" for v in box))
    todo = [(ix, iy) for ix, iy in ground_tiles.tiles_in_box(*box) if (ix, iy) not in have]
    log(f"{len(todo)} tiles to solve ({len(have)} already done) in {path}")
    started, made = time.perf_counter(), 0
    with closing(conn), ExitStack() as stack:
        if workers > 1:
            pool = stack.enter_context(ProcessPoolExecutor(max_workers=workers))
            tiles = (f.result() for f in as_completed(pool.submit(context3d.make_tile, ix, iy, folder=folder) for ix, iy in todo))
        else:
            tiles = (context3d.make_tile(ix, iy, folder=folder) for ix, iy in todo)
        for k, tile in enumerate(tiles, 1):
            if tile is not None:
                ground_tiles.add(conn, tile)
                made += 1
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
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--folder", type=Path, default=terrain_pack.TERRAIN_DIR)
    args = ap.parse_args()
    box = tuple(float(v) for v in args.box.split(",")) if args.box else None
    build(args.name, args.folder, box, args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
