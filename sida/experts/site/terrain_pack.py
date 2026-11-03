"""Terrain packs: contour lines, spot heights and ground areas of a region, kept outside the repository.

A pack is one SQLite file (standard library only) made once from the 국토지리정보원
연속수치지형도 downloads (등고선 N3L_F0010000, 표고점 N3P_F0020000, CC BY) by
scripts/build_terrain_pack.py. Points are [lon, lat] in EPSG:4326, so the site code can put
them in the drawing table's own frame (board.site_plan). An R*Tree index on each line's and
point's box makes a site's neighbourhood a fast query.

Packs live in ~/Sida/context_data (TERRAIN_DIR) — raw and processed map data never go in the
repository. `query` reads every pack there that covers the box.

Areas are polygons of what the ground is (KINDS: road, sidewalk, water), for colouring the
ground and cutting it into layers, from the 1:5,000 수치지형도 (도로경계, 보도, 하천경계·실폭하천·
호소). Buildings are the GIS건물통합정보 outlines (국토교통부, CC BY) with the 건축물대장 values
the file carries (BUILDING_FIELDS). Each kind can be its own pack; a pack holds only what it
was made from. Map buildings are the 1:5,000 수치지형도 건물 polygons with their 층수 and 용도,
kept only to fill in floors where GIS건물통합정보 has none.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

TERRAIN_DIR = Path.home() / "Sida" / "context_data"
SUFFIX = ".terrain.sqlite"
FORMAT = 1
KINDS = ("road", "sidewalk", "water")
# What a building keeps from GIS건물통합정보: PNU, 용도, 높이 (m), 지상층수, 건물명, 동명, 기준일.
BUILDING_FIELDS = ("pnu", "use", "height", "floors", "name", "dong", "date")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contours (id INTEGER PRIMARY KEY, elev REAL NOT NULL, points TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS contours_box USING rtree(id, west, east, south, north);
CREATE TABLE IF NOT EXISTS spots (id INTEGER PRIMARY KEY, lon REAL NOT NULL, lat REAL NOT NULL, elev REAL NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS spots_box USING rtree(id, west, east, south, north);
CREATE TABLE IF NOT EXISTS areas (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ring TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS areas_box USING rtree(id, west, east, south, north);
CREATE TABLE IF NOT EXISTS buildings (id INTEGER PRIMARY KEY, ring TEXT NOT NULL, attrs TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS buildings_box USING rtree(id, west, east, south, north);
CREATE TABLE IF NOT EXISTS map_buildings (id INTEGER PRIMARY KEY, ring TEXT NOT NULL, floors REAL NOT NULL, use TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS map_buildings_box USING rtree(id, west, east, south, north);
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


def add_area(conn: sqlite3.Connection, kind: str, ring: list[list[float]]) -> None:
    """One ground area (a KINDS value) as a closed [lon, lat] ring."""
    if kind not in KINDS:
        raise ValueError(f"not an area kind: {kind}")
    if len(ring) < 3:
        return
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    cur = conn.execute(
        "INSERT INTO areas (kind, ring) VALUES (?, ?)",
        (kind, json.dumps([[round(x, 7), round(y, 7)] for x, y in ring], separators=(",", ":"))),
    )
    conn.execute("INSERT INTO areas_box VALUES (?, ?, ?, ?, ?)", (cur.lastrowid, min(lons), max(lons), min(lats), max(lats)))


def add_building(conn: sqlite3.Connection, ring: list[list[float]], attrs: dict) -> None:
    """One building outline ([lon, lat] ring) and its BUILDING_FIELDS values."""
    if len(ring) < 3:
        return
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    kept = {k: attrs.get(k) for k in BUILDING_FIELDS if attrs.get(k) not in (None, "")}
    cur = conn.execute(
        "INSERT INTO buildings (ring, attrs) VALUES (?, ?)",
        (json.dumps([[round(x, 7), round(y, 7)] for x, y in ring], separators=(",", ":")),
         json.dumps(kept, ensure_ascii=False, separators=(",", ":"))),
    )
    conn.execute("INSERT INTO buildings_box VALUES (?, ?, ?, ?, ?)", (cur.lastrowid, min(lons), max(lons), min(lats), max(lats)))


def add_map_building(conn: sqlite3.Connection, ring: list[list[float]], floors: float, use: str = "") -> None:
    """One 1:5,000 수치지형도 building with a known number of floors (above ground)."""
    if len(ring) < 3 or not floors or floors <= 0:
        return
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    cur = conn.execute(
        "INSERT INTO map_buildings (ring, floors, use) VALUES (?, ?, ?)",
        (json.dumps([[round(x, 7), round(y, 7)] for x, y in ring], separators=(",", ":")), float(floors), use or ""),
    )
    conn.execute("INSERT INTO map_buildings_box VALUES (?, ?, ?, ?, ?)", (cur.lastrowid, min(lons), max(lons), min(lats), max(lats)))


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
    Contours, spot heights, ground areas and buildings touching the box, from every pack in the
    folder: {"contours": [{"elev", "points": [[lon, lat]]}], "spots": [[lon, lat, elev]],
    "areas": [{"kind", "ring": [[lon, lat]]}], "buildings": [{"ring", **BUILDING_FIELDS}],
    "map_buildings": [{"ring", "floors", "use"}], "sources": [pack meta]}. Empty lists when no
    pack covers the box.
    """
    out: dict = {"contours": [], "spots": [], "areas": [], "buildings": [], "map_buildings": [], "sources": []}
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
            areas = conn.execute(
                "SELECT a.kind, a.ring FROM areas a JOIN areas_box b ON b.id = a.id "
                "WHERE b.east >= ? AND b.west <= ? AND b.north >= ? AND b.south <= ?",
                (west, east, south, north),
            ).fetchall() if _has_table(conn, "areas") else []
            houses = conn.execute(
                "SELECT h.ring, h.attrs FROM buildings h JOIN buildings_box b ON b.id = h.id "
                "WHERE b.east >= ? AND b.west <= ? AND b.north >= ? AND b.south <= ?",
                (west, east, south, north),
            ).fetchall() if _has_table(conn, "buildings") else []
            mapped = conn.execute(
                "SELECT m.ring, m.floors, m.use FROM map_buildings m JOIN map_buildings_box b ON b.id = m.id "
                "WHERE b.east >= ? AND b.west <= ? AND b.north >= ? AND b.south <= ?",
                (west, east, south, north),
            ).fetchall() if _has_table(conn, "map_buildings") else []
            if lines or points or areas or houses or mapped:
                out["sources"].append(dict(conn.execute("SELECT key, value FROM meta")))
        out["contours"] += [{"elev": elev, "points": json.loads(text)} for elev, text in lines]
        out["spots"] += [[lon, lat, elev] for lon, lat, elev in points]
        out["areas"] += [{"kind": kind, "ring": json.loads(text)} for kind, text in areas]
        out["buildings"] += [{"ring": json.loads(ring), **json.loads(attrs)} for ring, attrs in houses]
        out["map_buildings"] += [{"ring": json.loads(ring), "floors": floors, "use": use} for ring, floors, use in mapped]
    return out


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    """Packs made before areas were added have no areas table."""
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None
