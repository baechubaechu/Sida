"""Terrain packs: contour lines and spot heights of an area, kept outside the repository.

A pack is one SQLite file (standard library only) made once from the 국토지리정보원
연속수치지형도 downloads (등고선 N3L_F0010000, 표고점 N3P_F0020000, CC BY) by
scripts/build_terrain_pack.py. Points are [lon, lat] in EPSG:4326, so the site code can put
them in the drawing table's own frame (board.site_plan). An R*Tree index on each line's and
point's box makes a site's neighbourhood a fast query.

Packs live in ~/Sida/context_data (TERRAIN_DIR) — raw and processed map data never go in the
repository. `query` reads every pack there that covers the box.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

TERRAIN_DIR = Path.home() / "Sida" / "context_data"
SUFFIX = ".terrain.sqlite"
FORMAT = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contours (id INTEGER PRIMARY KEY, elev REAL NOT NULL, points TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS contours_box USING rtree(id, west, east, south, north);
CREATE TABLE IF NOT EXISTS spots (id INTEGER PRIMARY KEY, lon REAL NOT NULL, lat REAL NOT NULL, elev REAL NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS spots_box USING rtree(id, west, east, south, north);
"""


def create(path: Path, meta: dict) -> sqlite3.Connection:
    """A new, empty pack at `path` (an existing file there is replaced)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    rows = {"format": str(FORMAT), **{k: str(v) for k, v in meta.items()}}
    conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", rows.items())
    return conn


def add_contour(conn: sqlite3.Connection, elev: float, points: list[list[float]]) -> None:
    """One contour line: its elevation (m above sea level) and [lon, lat] points."""
    if len(points) < 2:
        return
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    cur = conn.execute(
        "INSERT INTO contours (elev, points) VALUES (?, ?)",
        (float(elev), json.dumps([[round(x, 7), round(y, 7)] for x, y in points], separators=(",", ":"))),
    )
    conn.execute(
        "INSERT INTO contours_box VALUES (?, ?, ?, ?, ?)",
        (cur.lastrowid, min(lons), max(lons), min(lats), max(lats)),
    )


def add_spot(conn: sqlite3.Connection, lon: float, lat: float, elev: float) -> None:
    """One spot height: [lon, lat] and its elevation (m above sea level)."""
    cur = conn.execute("INSERT INTO spots (lon, lat, elev) VALUES (?, ?, ?)", (lon, lat, float(elev)))
    conn.execute("INSERT INTO spots_box VALUES (?, ?, ?, ?, ?)", (cur.lastrowid, lon, lon, lat, lat))


def packs(folder: Path | None = None) -> list[Path]:
    """Every pack in the folder (TERRAIN_DIR by default), by name."""
    folder = TERRAIN_DIR if folder is None else folder
    return sorted(folder.glob(f"*{SUFFIX}")) if folder.is_dir() else []


def info(path: Path) -> dict:
    """A pack's meta values (source, version date, bounds as given when it was made)."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return dict(conn.execute("SELECT key, value FROM meta"))


def query(west: float, south: float, east: float, north: float, folder: Path | None = None) -> dict:
    """
    Contours and spot heights touching the box, from every pack in the folder:
    {"contours": [{"elev", "points": [[lon, lat]]}], "spots": [[lon, lat, elev]],
    "sources": [pack meta]}. Empty lists when no pack covers the box.
    """
    out: dict = {"contours": [], "spots": [], "sources": []}
    for path in packs(folder):
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            lines = conn.execute(
                "SELECT c.elev, c.points FROM contours c JOIN contours_box b ON b.id = c.id "
                "WHERE b.east >= ? AND b.west <= ? AND b.north >= ? AND b.south <= ?",
                (west, east, south, north),
            ).fetchall()
            points = conn.execute(
                "SELECT s.lon, s.lat, s.elev FROM spots s JOIN spots_box b ON b.id = s.id "
                "WHERE b.east >= ? AND b.west <= ? AND b.north >= ? AND b.south <= ?",
                (west, east, south, north),
            ).fetchall()
            if lines or points:
                out["sources"].append(dict(conn.execute("SELECT key, value FROM meta")))
        out["contours"] += [{"elev": elev, "points": json.loads(text)} for elev, text in lines]
        out["spots"] += [[lon, lat, elev] for lon, lat, elev in points]
    return out
