"""Ground heights worked out ahead of time, so the surroundings do not solve the ground per site.

The ground between the 1:5,000 contours, spot heights and 정밀도로지도 road points is the
smoothest surface through them (context3d.solve_ground). That is the slow part of building a
site's surroundings, and it does not depend on the site: scripts/build_ground_tiles.py solves it
once for a whole region in tiles and keeps them in a file next to the terrain packs
(TERRAIN_DIR, `*.ground.sqlite`). A site then reads its heights from the tiles.

- A tile is TILE_LON × TILE_LAT degrees (about 880 × 890 m in Seoul). It is solved with
  TILE_MARGIN m of map data around it, so its edge is not guessed, and keeps a STEP m grid
  over the tile and two cells beyond (bilinear reads near the edge need them).
- Heights are whole centimetres, each row stored as the differences along it, compressed.
- A tiles file says which height packs it was made from (name, size, modification time,
  SHA-256 and the box their heights cover) and with which SOLVER version. When a pack changes,
  appears or goes, only the tiles whose map data reaches its box (old or new) stop counting: the
  ground there is solved per site as before until scripts/build_ground_tiles.py solves those
  tiles again (refresh). A pack copied without change (a new modification time) still counts:
  its SHA-256 is compared. A new SOLVER makes the whole file stop counting.
- Raw and processed map data stay out of the repository, like the packs. Heights with their
  coordinates are for this PC only (국토지리정보원 보안관리규정: no online exposure).
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

import numpy as np

from sida.experts.site import terrain_pack

SUFFIX = ".ground.sqlite"
FORMAT = 1
SOLVER = 1  # bump when the way the ground is solved changes: older tiles stop counting
TILE_LON = 0.01  # degrees
TILE_LAT = 0.008
STEP = 2.0  # m
TILE_MARGIN = 200.0  # m of map data read around a tile
BORDER = 2  # cells kept beyond the tile on each side
HEIGHT_KINDS = ("contours", "roads")  # the pack kinds that hold heights
HEIGHT_TABLES = ("contours_box", "spots_box", "road_points_box")  # where a pack's heights are
EARTH = 6378137.0  # m; reach() adds a STEP to make up for any difference from context3d's frame

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tiles (
  ix INTEGER NOT NULL, iy INTEGER NOT NULL,
  lon0 REAL NOT NULL, lat0 REAL NOT NULL, east REAL NOT NULL, north REAL NOT NULL,
  x0 REAL NOT NULL, y0 REAL NOT NULL, step REAL NOT NULL, nx INTEGER NOT NULL, ny INTEGER NOT NULL,
  z BLOB NOT NULL,
  PRIMARY KEY (ix, iy)
);
"""


# ---------------------------------------------------------------------------
# Where tiles are
# ---------------------------------------------------------------------------


def tile_of(lon, lat) -> tuple[np.ndarray, np.ndarray]:
    """The (ix, iy) of the tiles holding these points (arrays, or one point)."""
    return (np.floor(np.asarray(lon, dtype=float) / TILE_LON).astype(int),
            np.floor(np.asarray(lat, dtype=float) / TILE_LAT).astype(int))


def tile_box(ix: int, iy: int) -> tuple[float, float, float, float]:
    """west, south, east, north (degrees) of a tile."""
    return ix * TILE_LON, iy * TILE_LAT, (ix + 1) * TILE_LON, (iy + 1) * TILE_LAT


def tiles_in_box(west: float, south: float, east: float, north: float) -> list[tuple[int, int]]:
    """Every tile meeting the box, west to east in rows south to north."""
    x0, y0 = (int(v) for v in tile_of(west, south))
    x1, y1 = (int(v) for v in tile_of(east, north))
    return [(ix, iy) for iy in range(y0, y1 + 1) for ix in range(x0, x1 + 1)]


def reach(ix: int, iy: int) -> tuple[float, float, float, float]:
    """west, south, east, north of the map data a tile is solved from (context3d.make_tile's
    square: the tile's longer half plus TILE_MARGIN, around its middle), a STEP more to be sure."""
    west, south, east, north = tile_box(ix, iy)
    k = math.pi / 180
    per_lon, per_lat = EARTH * k * math.cos((south + north) / 2 * k), EARTH * k
    half = max((east - west) / 2 * per_lon, (north - south) / 2 * per_lat) + TILE_MARGIN + STEP
    lon, lat = (west + east) / 2, (south + north) / 2
    return lon - half / per_lon, lat - half / per_lat, lon + half / per_lon, lat + half / per_lat


def _meets(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


# ---------------------------------------------------------------------------
# What a tiles file was made from
# ---------------------------------------------------------------------------


def height_packs(folder: Path | None = None) -> list[Path]:
    """The terrain packs in the folder that hold heights (contours, spot heights, road points)."""
    return [p for p in terrain_pack.packs(folder) if terrain_pack.info(p).get("kind", "contours") in HEIGHT_KINDS]


_known: dict[tuple, tuple] = {}  # (path, size, mtime ns) -> (sha256, box): a pack is read once per process


def _measure(path: Path) -> tuple[str, list[float] | None]:
    """(SHA-256, west/south/east/north of the heights or None) of a pack, remembered per file state."""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _known:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                digest.update(chunk)
        _known[key] = (digest.hexdigest(), pack_box(path))
    return _known[key]


def pack_box(path: Path) -> list[float] | None:
    """west, south, east, north of the heights (contours, spot heights, road points) in a pack."""
    boxes = []
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        for table in HEIGHT_TABLES:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
                row = conn.execute(f"SELECT min(west), min(south), max(east), max(north) FROM {table}").fetchone()  # noqa: S608
                if row and row[0] is not None:
                    boxes.append(row)
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def extent(folder: Path | None = None) -> tuple[float, float, float, float] | None:
    """west, south, east, north of the heights in all the folder's height packs."""
    boxes = [b for p in height_packs(folder) if (b := pack_box(p))]
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def made_from(folder: Path | None = None) -> dict[str, dict]:
    """{pack name: {size, mtime (s), sha256, box}} of each height pack: what tiles made now depend on."""
    out = {}
    for p in height_packs(folder):
        st = p.stat()
        sha, box = _measure(p)
        out[p.name] = {"size": st.st_size, "mtime": int(st.st_mtime), "sha256": sha, "box": box}
    return out


def _legacy_made_from(folder: Path | None) -> list[list]:
    """What files made before 2026-11-17 recorded: [name, size, mtime (s)] of each height pack."""
    return [[p.name, p.stat().st_size, int(p.stat().st_mtime)] for p in height_packs(folder)]


def _same(record: dict, path: Path) -> bool:
    st = path.stat()
    if st.st_size != record.get("size"):
        return False
    return int(st.st_mtime) == record.get("mtime") or _measure(path)[0] == record.get("sha256")


def recorded(meta: dict, folder: Path | None = None) -> dict[str, dict] | None:
    """The packs a file's tiles were made from, as made_from() gives them; None when not known
    (a file from before 2026-11-17 whose packs have changed since: none of its tiles count)."""
    if "packs" in meta:
        return json.loads(meta["packs"])
    if json.loads(meta.get("made_from") or "null") == _legacy_made_from(folder):
        return made_from(folder)  # unchanged since: as if recorded now
    return None


def stale_boxes(packs: dict[str, dict], folder: Path | None = None) -> list[list[float]]:
    """The boxes of the height packs changed, added or gone since `packs` (recorded()), old and new."""
    now = {p.name: p for p in height_packs(folder)}
    out = []
    for name in sorted(packs.keys() | now.keys()):
        record, path = packs.get(name), now.get(name)
        if record and path and _same(record, path):
            continue
        if record and record.get("box"):
            out.append(record["box"])
        if path and (box := _measure(path)[1]):
            out.append(box)
    return out


def stale(ix: int, iy: int, boxes: list) -> bool:
    """Whether a tile's map data reaches any of these boxes (stale_boxes)."""
    near = reach(ix, iy)
    return any(_meets(near, box) for box in boxes)


def files(folder: Path | None = None) -> list[Path]:
    """Every tiles file in the folder (TERRAIN_DIR by default), by name."""
    folder = terrain_pack.TERRAIN_DIR if folder is None else folder
    return sorted(folder.glob(f"*{SUFFIX}")) if folder.is_dir() else []


def info(path: Path) -> dict:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        return dict(conn.execute("SELECT key, value FROM meta"))


def usable(meta: dict) -> bool:
    """Whether a file's tiles were made the way tiles are made now (format, solver, step, size)."""
    return (meta.get("format") == str(FORMAT) and meta.get("solver") == str(SOLVER)
            and meta.get("step") == str(STEP) and meta.get("tile") == json.dumps([TILE_LON, TILE_LAT]))


def current(path: Path, folder: Path | None = None) -> bool:
    """Whether every tile in a file still counts: made this way from the height packs now in the folder."""
    try:
        meta = info(path)
    except sqlite3.Error:
        return False
    packs = recorded(meta, folder) if usable(meta) else None
    return packs is not None and not stale_boxes(packs, folder)


def refresh(conn: sqlite3.Connection, folder: Path | None = None) -> int:
    """
    Bring a tiles file up to the height packs now in the folder: drop the tiles whose map data
    reaches a changed, new or removed pack (all of them when the file's packs are not known) and
    record the packs now. Returns how many tiles were dropped; the build solves them again.
    """
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    packs = recorded(meta, folder)
    keys = list(conn.execute("SELECT ix, iy FROM tiles"))
    has_empty = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'empty'").fetchone()
    if has_empty:
        keys += list(conn.execute("SELECT ix, iy FROM empty"))
    boxes = stale_boxes(packs, folder) if packs is not None else None
    drop = [(ix, iy) for ix, iy in keys if boxes is None or stale(ix, iy, boxes)]
    conn.executemany("DELETE FROM tiles WHERE ix = ? AND iy = ?", drop)
    if has_empty:
        conn.executemany("DELETE FROM empty WHERE ix = ? AND iy = ?", drop)
    conn.execute("DELETE FROM meta WHERE key = 'made_from'")
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('packs', ?)", (json.dumps(made_from(folder)),))
    conn.commit()
    return len(drop)


def create(path: Path, folder: Path | None = None, **meta) -> sqlite3.Connection:
    """A new, empty tiles file at `path` (an existing one is replaced) for the folder's packs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    rows = {"format": str(FORMAT), "solver": str(SOLVER), "step": str(STEP),
            "tile": json.dumps([TILE_LON, TILE_LAT]), "packs": json.dumps(made_from(folder)),
            **{k: str(v) for k, v in meta.items()}}
    conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", rows.items())
    return conn


# ---------------------------------------------------------------------------
# One tile
# ---------------------------------------------------------------------------


def encode(z: np.ndarray) -> bytes:
    """Heights (m) as whole centimetres, each row as its differences, compressed."""
    cm = np.rint(np.asarray(z, dtype=float) * 100).astype(np.int32)
    return zlib.compress(np.diff(cm, axis=1, prepend=0).astype("<i4").tobytes(), 6)


def decode(blob: bytes, nx: int, ny: int) -> np.ndarray:
    d = np.frombuffer(zlib.decompress(blob), dtype="<i4").reshape(ny, nx)
    return np.cumsum(d, axis=1, dtype=np.int64) / 100.0


def add(conn: sqlite3.Connection, tile: dict) -> None:
    """One solved tile (as make_tile in context3d gives it)."""
    conn.execute(
        "INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tile["ix"], tile["iy"], tile["lon0"], tile["lat0"], tile["east"], tile["north"], tile["x0"],
         tile["y0"], tile["step"], tile["z"].shape[1], tile["z"].shape[0], encode(tile["z"])),
    )


def mark_empty(conn: sqlite3.Connection, ix: int, iy: int) -> None:
    """A tile with no heights to solve from (outside the packs), so a carried-on run skips it."""
    conn.execute("CREATE TABLE IF NOT EXISTS empty (ix INTEGER NOT NULL, iy INTEGER NOT NULL, PRIMARY KEY (ix, iy))")
    conn.execute("INSERT OR IGNORE INTO empty VALUES (?, ?)", (ix, iy))


def done(path: Path) -> set[tuple[int, int]]:
    """The tiles already in a file, solved or empty (to carry on an interrupted run)."""
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        out = {(ix, iy) for ix, iy in conn.execute("SELECT ix, iy FROM tiles")}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'empty'").fetchone():
            out |= {(ix, iy) for ix, iy in conn.execute("SELECT ix, iy FROM empty")}
        return out


# ---------------------------------------------------------------------------
# Reading heights
# ---------------------------------------------------------------------------


def heights(lon, lat, folder: Path | None = None) -> np.ndarray | None:
    """
    Ground heights (m above sea level) at these points (arrays of the same shape) from the
    tiles files, bilinear between grid points; None when a point lies on a tile that no file has
    or whose map data has changed since (then the caller solves the ground itself).
    """
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    paths, stale_by = [], []
    for p in files(folder):
        try:
            meta = info(p)
        except sqlite3.Error:
            continue
        packs = recorded(meta, folder) if usable(meta) else None
        if packs is not None:
            paths.append(p)
            stale_by.append(stale_boxes(packs, folder))
    if not paths:
        return None
    ix, iy = tile_of(lon.ravel(), lat.ravel())
    out = np.full(lon.size, np.nan)
    wanted = sorted(set(zip(ix.tolist(), iy.tolist(), strict=True)))
    conns = [sqlite3.connect(f"file:{p}?mode=ro", uri=True) for p in paths]
    try:
        for tx, ty in wanted:
            row = None
            for conn, boxes in zip(conns, stale_by, strict=True):
                if stale(tx, ty, boxes):
                    continue
                row = conn.execute("SELECT lon0, lat0, east, north, x0, y0, step, nx, ny, z FROM tiles "
                                   "WHERE ix = ? AND iy = ?", (tx, ty)).fetchone()
                if row:
                    break
            if row is None:
                return None
            lon0, lat0, east, north, x0, y0, step, nx, ny, blob = row
            z = decode(blob, nx, ny)
            here = (ix == tx) & (iy == ty)
            x = (lon.ravel()[here] - lon0) * east
            y = (lat.ravel()[here] - lat0) * north
            out[here] = _bilinear(z, x0, y0, step, x, y)
    finally:
        for conn in conns:
            conn.close()
    return out.reshape(lon.shape)


def _bilinear(z: np.ndarray, x0: float, y0: float, step: float, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    ny, nx = z.shape
    fx = np.clip((x - x0) / step, 0, nx - 1)
    fy = np.clip((y - y0) / step, 0, ny - 1)
    j0 = np.minimum(np.floor(fx).astype(int), nx - 2)
    i0 = np.minimum(np.floor(fy).astype(int), ny - 2)
    tx, ty = fx - j0, fy - i0
    return (z[i0, j0] * (1 - tx) * (1 - ty) + z[i0, j0 + 1] * tx * (1 - ty)
            + z[i0 + 1, j0] * (1 - tx) * ty + z[i0 + 1, j0 + 1] * tx * ty)


def cells(half_x: float, half_y: float) -> tuple[int, int]:
    """Grid points a side for a tile's core half sizes (m), with the border."""
    return (int(math.ceil(half_x / STEP)) + BORDER, int(math.ceil(half_y / STEP)) + BORDER)
