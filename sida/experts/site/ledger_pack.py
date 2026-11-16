"""건축물대장 표제부 for a whole region, from the monthly bulk file, so the surroundings need not
ask data.go.kr parcel by parcel.

건축HUB (www.hub.go.kr) → 원하는대로 건축데이터 → 대용량 데이터 제공 → "표제부 (YYYY년 MM월)"
gives every 표제부 in Korea as one zip (no sign-in; 국토교통부, 이용허락범위 제한 없음), holding
`mart_djy_03.txt`: UTF-8, '|' between values, no header, one 동 per line, the values in the
order COLUMNS lists (checked against data.go.kr getBrTitleInfo replies). scripts/build_ledger_pack.py
keeps the lines of the regions asked for (by 시군구 code prefix) as a pack next to the terrain
packs: ~/Sida/context_data/<name>.ledger.sqlite.

A pack's rows are what datago.buildings gives for a PNU (the same keys and numbers), so the
surroundings can take either. A pack holds every registered 표제부 of its regions: a PNU of a
covered region that is not in it has no 표제부. The month it was made from is in its meta
("month"), as the file names it.
"""

from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import closing
from pathlib import Path

from sida.experts.site import terrain_pack

SUFFIX = ".ledger.sqlite"
FORMAT = 1
MEMBER = "mart_djy_03.txt"
# The values of a mart_djy_03.txt line we keep, by their place on the line.
COLUMNS = {
    "pk": 0, "register_kind": 4, "road_address": 6, "name": 7, "sigungu": 8, "bjdong": 9, "plat_gb": 10,
    "bun": 11, "ji": 12, "dong": 22, "main_or_annex": 24, "plat_area_m2": 25, "building_area_m2": 26,
    "bcr": 27, "total_floor_area_m2": 28, "far": 30, "structure": 32, "purpose": 35, "purpose_detail": 36,
    "height_m": 42, "floors_above": 43, "floors_below": 44, "approved": 60,
}
TEXTS = ("name", "dong", "main_or_annex", "register_kind", "purpose", "purpose_detail", "structure",
         "road_address", "approved")
NUMBERS = ("plat_area_m2", "building_area_m2", "total_floor_area_m2", "bcr", "far", "floors_above",
           "floors_below", "height_m")
WHOLE = ("floors_above", "floors_below")
PLAT_GB = {"0": "1", "1": "2"}  # 대장 대지구분 → the PNU's 11th digit (일반, 산); 블록 etc. have no PNU

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rows (pnu TEXT NOT NULL, {", ".join(f"{k} TEXT" for k in TEXTS)},
  {", ".join(f"{k} REAL" for k in NUMBERS)});
"""


def pnu_of(values: list[str]) -> str | None:
    """The 19-digit PNU of a line's lot, or None for a lot without one (블록·로트 or a bad value)."""
    digit = PLAT_GB.get(values[COLUMNS["plat_gb"]].strip())
    sigungu, bjdong = values[COLUMNS["sigungu"]].strip(), values[COLUMNS["bjdong"]].strip()
    bun, ji = values[COLUMNS["bun"]].strip(), values[COLUMNS["ji"]].strip()
    if not digit or not (len(sigungu) == 5 and len(bjdong) == 5 and sigungu.isdigit() and bjdong.isdigit()):
        return None
    if not (bun.isdigit() and ji.isdigit() and len(bun) <= 4 and len(ji) <= 4):
        return None
    return f"{sigungu}{bjdong}{digit}{bun.zfill(4)}{ji.zfill(4)}"


def row_of(values: list[str]) -> dict:
    """One line as datago.buildings gives a 표제부 row."""
    out: dict = {k: " ".join(values[COLUMNS[k]].split()) for k in TEXTS}
    for k in NUMBERS:
        text = values[COLUMNS[k]].strip()
        try:
            out[k] = float(text) if text else None
        except ValueError:
            out[k] = None
    for k in WHOLE:
        if out[k] is not None:
            out[k] = int(out[k])
    return out


def month_of(name: str) -> str:
    """'2026-09' from a file name like '국토교통부_건축물대장_표제부 (2026년 09월).zip', else ''."""
    m = re.search(r"(\d{4})\s*년\D{0,3}(\d{1,2})\s*월", name)
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else ""


def lines(path: Path) -> Iterator[list[str]]:
    """The '|'-split lines of mart_djy_03.txt, read from the zip as it is (or the text file)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            member = next((i.filename for i in z.infolist() if i.filename.endswith(MEMBER)), None)
            if member is None:
                raise ValueError(f"no {MEMBER} in {path.name}")
            with z.open(member) as raw:
                yield from _split(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"))
    else:
        with open(path, encoding="utf-8", errors="replace") as f:
            yield from _split(f)


def _split(text: Iterable[str]) -> Iterator[list[str]]:
    width = max(COLUMNS.values()) + 1
    for line in text:
        values = line.rstrip("\r\n").split("|")
        if len(values) >= width:
            yield values


def build(source: Path, out: Path, prefixes: tuple[str, ...], *, month: str = "", log=print) -> int:
    """
    A pack at `out` (replaced) holding the 표제부 of the 시군구 whose codes start with one of
    `prefixes` (e.g. "11" for Seoul) from the bulk file `source`. Returns the rows kept.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    if tmp.exists():
        tmp.unlink()
    kept = 0
    with closing(sqlite3.connect(tmp)) as conn:
        conn.executescript(_SCHEMA)
        batch = []
        cols = ["pnu", *TEXTS, *NUMBERS]
        insert = f"INSERT INTO rows ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        for n, values in enumerate(lines(source), 1):
            if not values[COLUMNS["sigungu"]].startswith(prefixes):
                continue
            pnu = pnu_of(values)
            if pnu is None:
                continue
            row = row_of(values)
            batch.append([pnu, *(row[k] for k in TEXTS), *(row[k] for k in NUMBERS)])
            if len(batch) >= 50_000:
                conn.executemany(insert, batch)
                kept += len(batch)
                batch = []
                log(f"  {kept} rows kept, {n} lines read")
        conn.executemany(insert, batch)
        kept += len(batch)
        conn.execute("CREATE INDEX rows_pnu ON rows (pnu)")
        meta = {"format": str(FORMAT), "source": "국토교통부 건축물대장 표제부 (건축HUB 대용량 데이터 제공)",
                "month": month or month_of(source.name), "file": source.name, "prefixes": ",".join(prefixes),
                "rows": str(kept)}
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", meta.items())
        conn.commit()
    tmp.replace(out)
    return kept


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def packs(folder: Path | None = None) -> list[Path]:
    """Every ledger pack in the folder (TERRAIN_DIR by default), the newest month first."""
    folder = terrain_pack.TERRAIN_DIR if folder is None else folder
    found = sorted(folder.glob(f"*{SUFFIX}")) if folder.is_dir() else []
    return sorted(found, key=lambda p: info(p).get("month", ""), reverse=True)


def info(path: Path) -> dict:
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            return dict(conn.execute("SELECT key, value FROM meta"))
    except sqlite3.Error:
        return {}


def lookup(pnus: Iterable[str], folder: Path | None = None) -> tuple[dict[str, list[dict]], dict | None]:
    """
    ({pnu: rows} for every PNU a pack's regions cover — [] when it has no 표제부 — and the meta of
    the newest pack used, or None). PNUs no pack covers are left out: ask data.go.kr for those.
    """
    wanted = sorted(set(pnus))
    found: dict[str, list[dict]] = {}
    used = None
    for path in packs(folder):
        meta = info(path)
        prefixes = tuple(p for p in meta.get("prefixes", "").split(",") if p)
        mine = [p for p in wanted if p not in found and p.startswith(prefixes)] if prefixes else []
        if not mine:
            continue
        used = used or meta
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            for pnu in mine:
                found[pnu] = []
            for k in range(0, len(mine), 500):
                part = mine[k:k + 500]
                cur = conn.execute(f"SELECT pnu, {', '.join([*TEXTS, *NUMBERS])} FROM rows "
                                   f"WHERE pnu IN ({', '.join('?' * len(part))})", part)
                for pnu, *values in cur:
                    row = dict(zip([*TEXTS, *NUMBERS], values, strict=True))
                    for key in TEXTS:
                        row[key] = row[key] or ""
                    for key in WHOLE:
                        if row[key] is not None:
                            row[key] = int(row[key])
                    found[pnu].append(row)
    return found, used
