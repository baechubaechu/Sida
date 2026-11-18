#!/usr/bin/env python3
"""
Make every map pack of a 시·도 from the files downloaded for it, in one go: point at the folder the
downloads are in and it works out the rest.

    python scripts/build_region_packs.py --raw "C:/Users/user/Sida/context_data/raw" --plan
    python scripts/build_region_packs.py --raw "C:/Users/user/Sida/context_data/raw"
    python scripts/build_region_packs.py --raw … --region busan,울산 --no-ground

What it reads (브이월드 공간정보 다운로드, as downloaded; zips are read or unpacked as they are):
  - GIS건물통합정보 AL_D010_<시도 code>_<YYYYMMDD>.zip → <region>-buildings (the newest per 시·도)
  - 연속수치지형도 등고선 N3L_F0010000, 표고점 N3P_F0020000 → <region>-contours
  - 연속수치지형도 도로경계 N3A_A0010000, 보도 N3A_A0033320, 하천경계 N3A_E0010001, 실폭하천
    N3A_E0032111, 호소 N3A_E0052114 (and 건물 N3A_B0010000) → <region>-areas
    as zips (one per layer or several, cut into numbered pieces, zips inside zips) or unzipped
    .shp files; a zip cut with 7-Zip (name.zip.001, .002 …) is joined first.

Which 시·도 a file is for: the nearest folder named after one (부산, 부산광역시, busan, 26, 26_부산),
else the file's own name (AL_D010_26_…, 연속수치지형도_부산.zip, N3L_F0010000_26.zip), else the
layer files inside a zip. --plan shows what was found, on what grounds, and does nothing else;
files it cannot place are listed and skipped (put them in a folder named after their 시·도).

Then, per 시·도: the box is the files' own extent; each pack is made with build_terrain_pack.py
into a work folder and put in place only if it does not hold far less than the pack it replaces
(fewer than 95% of the buildings, lines or areas: a broken download; --accept-drop to take it);
then the ground is solved ahead with build_ground_tiles.py (the 시·도's box, after bringing the
neighbouring 시·도's tiles files up to the new packs, and leaving out tiles another file has).
Last, scripts/check_region_packs.py writes its one-page report.

Run it again after a stop and it carries on: unpacked zips are not unpacked again, a pack whose
downloads have not changed (name, size, time) is not made again (--force to), the ground carries
on where it stopped. What was made from what is kept in <out>/region_packs.json.

Needs the packages for making packs: pip install -e ".[pack]"  (pyshp, pyproj)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sida.console import configure_stdio  # noqa: E402
from sida.experts.site import ground_tiles, regions, terrain_pack  # noqa: E402

KINDS = ("buildings", "contours", "areas")
LAYERS = {
    "contours": ("N3L_F0010000", "N3P_F0020000"),
    "areas": ("N3A_A0010000", "N3A_A0033320", "N3A_E0010001", "N3A_E0032111", "N3A_E0052114", "N3A_B0010000"),
}
COUNTED = {  # the tables whose rows say how much a pack holds
    "buildings": ("buildings",),
    "contours": ("contours", "spots"),
    "areas": ("areas", "map_buildings"),
}
MIN_SHARE = 0.95  # of the pack it replaces
SHP_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg")
STATE = "region_packs.json"
PAD = 0.002  # degrees added around the files' extent
TILE_SECONDS = 35.0  # worker-seconds per ground tile (Seoul: 3,276 tiles, 8 workers, about 4 hours)

AL_D010 = re.compile(r"^AL_D010_(\d{2})_(\d{8})\.zip$", re.IGNORECASE)
LAYER = re.compile(r"(N3[ALP]_[A-Z]\d{7})(?:_(\d{1,3}))?(?!\d)", re.IGNORECASE)
DATE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
JOIN_PART = re.compile(r"^(.+\.zip)\.(\d{3})$", re.IGNORECASE)
SPANNED = re.compile(r"\.z\d{2}$", re.IGNORECASE)


@dataclass
class Source:
    """A downloaded file: a zip (AL_D010 or map layers) or a loose shapefile set (its .shp)."""

    path: Path
    region: regions.Region | None = None
    basis: str = ""  # how the region was told: folder, name, layer code, inside
    kinds: set[str] = field(default_factory=set)
    date: str = ""  # YYYY-MM-DD in its name, if any
    note: str = ""

    def stamp(self) -> list:
        st = self.path.stat()
        return [self.path.name, st.st_size, st.st_mtime_ns]


# ---------------------------------------------------------------------------
# Finding what was downloaded
# ---------------------------------------------------------------------------


def _korean(name: str, info: zipfile.ZipInfo) -> str:
    """A zip entry name as Korean Windows wrote it (cp949 read as cp437), unless flagged UTF-8."""
    if info.flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _kinds_of(names) -> set[str]:
    stems = {Path(n).stem.upper() for n in names}
    found = set()
    for kind, layers in LAYERS.items():
        if any(s == layer or s.startswith(layer + "_") for s in stems for layer in layers):
            found.add(kind)
    return found


def _date(name: str) -> str:
    m = DATE.search(name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def _region_of(path: Path, raw: Path) -> tuple[regions.Region | None, str]:
    """The region a file's folders or own name tell, and which: ('folder' or 'name')."""
    for parent in path.relative_to(raw).parents:
        if parent != Path(".") and (region := regions.find(parent.name)):
            return region, "folder"
    stem = path.name.split(".")[0]
    if m := AL_D010.match(path.name):
        return regions.by_code(m.group(1)), "name"
    named = regions.find(LAYER.sub("", stem).replace("AL_D010", ""))  # 연속수치지형도_부산 but not layer codes
    if named:
        return named, "name"
    m = LAYER.search(stem)
    if m and m.group(2) and (region := regions.by_code(m.group(2))) and len(m.group(2)) == 2:
        return region, "layer code"
    return None, ""


def find_sources(raw: Path, work: Path) -> list[Source]:
    """Every download under `raw`, with its region and kinds where they can be told."""
    out: list[Source] = []
    parts: dict[Path, list[Path]] = {}
    for path in sorted(p for p in raw.rglob("*") if p.is_file()):
        if work in path.parents:
            continue
        name = path.name
        if m := JOIN_PART.match(name):
            parts.setdefault(path.with_name(m.group(1)), []).append(path)
            continue
        if SPANNED.search(name):
            out.append(Source(path, note="WinZip 분할 파일(.z01)은 읽지 못함: 7-Zip 등으로 풀어서 넣어 주세요"))
            continue
        if name.lower().endswith(".zip"):
            out.append(_zip_source(path, raw))
        elif name.lower().endswith(".shp"):
            kinds = _kinds_of([name])
            if kinds:
                region, basis = _region_of(path, raw)
                out.append(Source(path, region, basis, kinds, _date(name)))
    for whole, pieces in parts.items():
        joined = _join(whole, sorted(pieces), work / "joined")
        source = _zip_source(joined, raw, as_if=whole)
        source.note = f"{len(pieces)}조각을 이어 붙임"
        out.append(source)
    return out


def _zip_source(path: Path, raw: Path, as_if: Path | None = None) -> Source:
    named = as_if or path
    region, basis = _region_of(named, raw)
    if m := AL_D010.match(named.name):
        return Source(path, region, basis, {"buildings"}, _date(m.group(2)))
    try:
        with zipfile.ZipFile(path) as z:
            names = [_korean(i.filename, i) for i in z.infolist()]
    except (zipfile.BadZipFile, OSError) as exc:
        return Source(path, region, basis, note=f"zip을 열지 못함: {type(exc).__name__}")
    kinds = _kinds_of(names)
    inner = [n for n in names if n.lower().endswith(".zip")]
    if inner and not kinds:
        kinds = set(LAYERS)  # zips inside (1:5,000 sheets): what they hold shows once unpacked
    if region is None:
        found = {r for n in names if (m := LAYER.search(Path(n).stem)) and m.group(2) and len(m.group(2)) == 2
                 and (r := regions.by_code(m.group(2)))}
        if len(found) == 1:
            region, basis = found.pop(), "inside"
    return Source(path, region, basis, kinds, _date(named.name), note=f"안에 zip {len(inner)}개" if inner else "")


def _join(whole: Path, pieces: list[Path], folder: Path) -> Path:
    """The pieces of a 7-Zip split (name.zip.001, .002 …) as one zip, made once."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / whole.name
    stamp = json.dumps([[p.name, p.stat().st_size, p.stat().st_mtime_ns] for p in pieces])
    marker = target.with_name(target.name + ".joined")
    if target.exists() and marker.exists() and marker.read_text(encoding="utf-8") == stamp:
        return target
    part = target.with_name(target.name + ".part")
    with open(part, "wb") as out:
        for piece in pieces:
            with open(piece, "rb") as src:
                shutil.copyfileobj(src, out, 1 << 20)
    os.replace(part, target)
    marker.write_text(stamp, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Unpacking
# ---------------------------------------------------------------------------


def _safe(name: str) -> Path | None:
    """A zip entry's path made safe to unpack under a folder (no drive, no .., no absolute)."""
    bits = [b for b in re.split(r"[\\/]+", name) if b not in ("", ".")]
    if not bits or any(b == ".." or ":" in b for b in bits):
        return None
    return Path(*bits)


def unpack(zpath: Path, dest: Path, stamp: list | None = None) -> None:
    """The shapefile parts of a zip (and of the zips inside it) under dest, once: a marker with the
    zip's name, size and time says it is done."""
    marker = dest / ".unpacked"
    want = json.dumps(stamp or [zpath.name, zpath.stat().st_size, zpath.stat().st_mtime_ns])
    if marker.exists() and marker.read_text(encoding="utf-8") == want:
        return
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            rel = _safe(_korean(info.filename, info))
            if rel is None or info.is_dir():
                continue
            suffix = rel.suffix.lower()
            if suffix in SHP_PARTS:
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(dest / rel, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
            elif suffix == ".zip":
                inner = dest / rel.with_suffix(".zip.tmp")
                inner.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(inner, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                try:
                    unpack(inner, dest / rel.with_suffix(""), ["inner", info.file_size, info.CRC])
                finally:
                    inner.unlink(missing_ok=True)
    marker.write_text(want, encoding="utf-8")


def gather(sources: list[Source], dest: Path) -> Path:
    """The map files of one region under dest: zips unpacked, loose shapefiles linked (or copied)."""
    dest.mkdir(parents=True, exist_ok=True)
    for source in sources:
        tag = hashlib.sha1(str(source.path).encode("utf-8")).hexdigest()[:8]
        if source.path.suffix.lower() == ".zip":
            unpack(source.path, dest / f"{source.path.stem}-{tag}")
            continue
        folder = dest / f"loose-{tag}"
        folder.mkdir(exist_ok=True)
        for suffix in SHP_PARTS:
            for src in (source.path.with_suffix(suffix), source.path.with_suffix(suffix.upper())):
                target = folder / (source.path.stem + suffix)
                if src.exists() and not target.exists():
                    try:
                        os.link(src, target)
                    except OSError:
                        shutil.copy2(src, target)
    return dest


# ---------------------------------------------------------------------------
# Boxes and counts
# ---------------------------------------------------------------------------


def shp_box(shp: Path | None = None, *, zpath: Path | None = None) -> list[float] | None:
    """west, south, east, north (degrees) of a shapefile, or of the one in a zip, from its header."""
    import shapefile  # pyshp
    from pyproj import CRS, Transformer

    if zpath is not None:
        with zipfile.ZipFile(zpath) as z:
            prj = next((n for n in z.namelist() if n.lower().endswith(".prj")), None)
            prj_text = z.read(prj).decode("ascii", "ignore") if prj else ""
        reader = shapefile.Reader(str(zpath))
    else:
        prj_path = next((p for p in (shp.with_suffix(".prj"), shp.with_suffix(".PRJ")) if p.exists()), None)
        prj_text = prj_path.read_text(encoding="ascii", errors="ignore") if prj_path else ""
        reader = shapefile.Reader(str(shp))
    try:
        if not len(reader):
            return None
        x0, y0, x1, y1 = reader.bbox[:4]
    finally:
        reader.close()
    crs = CRS.from_wkt(prj_text) if prj_text else CRS.from_epsg(5186)  # 중부원점, as build_terrain_pack takes it
    west, south, east, north = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform_bounds(
        x0, y0, x1, y1, densify_pts=21)
    return [west, south, east, north]


def union(boxes) -> list[float] | None:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes) - PAD, min(b[1] for b in boxes) - PAD,
            max(b[2] for b in boxes) + PAD, max(b[3] for b in boxes) + PAD]


def map_files(folder: Path, kind: str) -> list[Path]:
    layers = LAYERS[kind]
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() == ".shp"
                  and any(p.stem.upper() == layer or p.stem.upper().startswith(layer + "_") for layer in layers))


def counts(pack: Path, kind: str) -> dict[str, int]:
    """Rows in the tables that say how much a pack holds (COUNTED); {} for no pack."""
    if not pack.exists():
        return {}
    out = {}
    with closing(sqlite3.connect(f"file:{pack}?mode=ro", uri=True)) as conn:
        for table in COUNTED[kind]:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
                out[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
    return out


def shrunk(old: dict[str, int], new: dict[str, int]) -> list[str]:
    """The tables holding fewer than MIN_SHARE of what the old pack held."""
    return [t for t, n in old.items() if n and new.get(t, 0) < MIN_SHARE * n]


def meets(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def box_text(box) -> str:
    return ",".join(f"{v:.5f}" for v in box)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def read_state(out: Path) -> dict:
    try:
        state = json.loads((out / STATE).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(out: Path, state: dict) -> None:
    part = out / (STATE + ".part")
    part.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(part, out / STATE)


def run_script(script: str, args: list[str], log) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *args]
    log("  $ " + " ".join(cmd[1:]))
    done = subprocess.run(cmd, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{script} stopped with exit code {done.returncode}")


def make_pack(region: regions.Region, kind: str, given: str, box, stamp: list, date: str, args, state: dict,
              log) -> str:
    """One pack of a region, unless made already from the same downloads. Returns what happened."""
    target = args.out / f"{region.name}-{kind}{terrain_pack.SUFFIX}"
    record = state.setdefault("regions", {}).setdefault(region.name, {}).setdefault(kind, {})
    if (not args.force and record.get("inputs") == stamp and target.exists()
            and record.get("pack") == [target.stat().st_size, target.stat().st_mtime_ns]):
        log(f"  {kind}: unchanged downloads, kept {target.name}")
        return "kept"
    staging = args.work / region.name / "new"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    extra = ["--source-date", date] if date else []
    run_script("build_terrain_pack.py", ["--name", region.name, "--box", box_text(box), f"--{kind}", given,
                                         "--out", str(staging), *extra], log)
    made = staging / target.name
    old, new = counts(target, kind), counts(made, kind)
    record.update({"checked_at": time.strftime("%Y-%m-%d %H:%M"), "counts": new, "previous": old,
                   "box": box, "inputs": None, "refused": []})
    less = shrunk(old, new)
    if less and not args.accept_drop:
        record["refused"] = less
        record["counts"] = old
        shutil.rmtree(staging, ignore_errors=True)
        log(f"  {kind}: the new pack holds far less ({new} against {old}); the old one stays (--accept-drop to take it)")
        return "refused"
    shutil.move(str(made), str(target))
    shutil.rmtree(staging, ignore_errors=True)
    record.update({"inputs": stamp, "pack": [target.stat().st_size, target.stat().st_mtime_ns],
                   "made": time.strftime("%Y-%m-%d %H:%M")})
    log(f"  {kind}: {target.name} {new}")
    return "made"


def solve_ground(region: regions.Region, box, args, log) -> None:
    """The region's ground tiles, after the tiles files of the 시·도 around it are brought up to the packs."""
    mine = args.out / f"{region.name}{ground_tiles.SUFFIX}"
    for other in ground_tiles.files(args.out):
        if other == mine:
            continue
        meta = ground_tiles.info(other)
        theirs = [float(v) for v in meta.get("box", "").split(",")] if meta.get("box") else None
        if theirs and len(theirs) == 4 and meets(theirs, box) and not ground_tiles.current(other, args.out):
            log(f"  ground: bringing {other.name} up to the new packs first")
            run_script("build_ground_tiles.py", ["--name", other.name[: -len(ground_tiles.SUFFIX)], "--box",
                                                 box_text(theirs), "--folder", str(args.out), "--workers",
                                                 str(args.workers)], log)
    run_script("build_ground_tiles.py", ["--name", region.name, "--box", box_text(box), "--folder", str(args.out),
                                         "--workers", str(args.workers), "--skip-others"], log)


def wanted_regions(text: str) -> set[str] | None:
    if not text:
        return None
    out = set()
    for item in text.split(","):
        region = regions.by_name(item.strip().lower()) or regions.find(item.strip())
        if region is None:
            raise SystemExit(f"not a 시·도: {item}")
        out.add(region.name)
    return out


def plan_lines(groups: dict[str, list[Source]], lost: list[Source], workers: int, out: Path) -> list[str]:
    lines = []
    for name, sources in groups.items():
        region = regions.by_name(name)
        lines.append(f"{region.label} ({name})")
        for s in sources:
            kinds = ", ".join(sorted(s.kinds)) or "?"
            lines.append(f"  - {s.path.name}: {kinds} [{s.basis}]" + (f" ({s.note})" if s.note else ""))
        box = union(shp_box(zpath=s.path) for s in sources if "buildings" in s.kinds)
        if box:
            tiles = ground_tiles.tiles_in_box(*box)
            have = set().union(*(ground_tiles.done(p) for p in ground_tiles.files(out))) if out.is_dir() else set()
            todo = len([t for t in tiles if t not in have])
            hours = todo * TILE_SECONDS / max(1, workers) / 3600
            lines.append(f"  건물 범위 {box_text(box)}: 지형 칸 {len(tiles)}개 중 {todo}개를 풀어야 함"
                         f"(작업자 {workers}개로 어림 {hours:.1f}시간, 바다·빈 칸은 더 빠름)")
    if lost:
        lines.append("어느 시·도인지 모르는 파일 (시·도 이름 폴더에 넣어 주세요):")
        lines += [f"  - {s.path}" + (f" ({s.note})" if s.note else "") for s in lost]
    return lines


def main() -> int:
    configure_stdio()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("--raw", type=Path, required=True, help="the folder the downloads are in (any depth)")
    ap.add_argument("--region", default="", help="only these 시·도, comma separated (busan, 부산, 26)")
    ap.add_argument("--plan", action="store_true", help="show what was found and stop")
    ap.add_argument("--no-ground", action="store_true", help="make the packs, not the ground tiles")
    ap.add_argument("--no-check", action="store_true", help="no report at the end")
    ap.add_argument("--force", action="store_true", help="make packs again even from unchanged downloads")
    ap.add_argument("--accept-drop", action="store_true", help="take a new pack that holds far less than the old")
    ap.add_argument("--keep-unpacked", action="store_true", help="keep the unpacked shapefiles after the packs")
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--out", type=Path, default=terrain_pack.TERRAIN_DIR)
    ap.add_argument("--work", type=Path, help="room for unpacking (default: <out>/region-work)")
    args = ap.parse_args()
    args.raw = args.raw.expanduser().resolve()
    args.out = args.out.expanduser().resolve()
    args.work = (args.work or args.out / "region-work").expanduser().resolve()
    if not args.raw.is_dir():
        ap.error(f"not a folder: {args.raw}")
    only = wanted_regions(args.region)
    log = lambda m: print(m, flush=True)  # noqa: E731

    sources = find_sources(args.raw, args.work)
    groups: dict[str, list[Source]] = {}
    lost = []
    for s in sources:
        if s.region is None or not s.kinds:
            lost.append(s)
        elif only is None or s.region.name in only:
            groups.setdefault(s.region.name, []).append(s)
    if args.plan or not groups:
        for line in plan_lines(groups, lost, args.workers, args.out) or ["받은 파일을 찾지 못함"]:
            log(line)
        return 0 if groups or args.plan else 1

    args.out.mkdir(parents=True, exist_ok=True)
    state = read_state(args.out)
    failed = []
    for name, group in groups.items():
        region = regions.by_name(name)
        log(f"{region.label} ({name})")
        try:
            buildings = sorted((s for s in group if "buildings" in s.kinds), key=lambda s: s.date)
            maps = [s for s in group if s.kinds & set(LAYERS)]
            folder = gather(maps, args.work / name / "unpacked") if maps else None
            boxes = [shp_box(zpath=buildings[-1].path)] if buildings else []
            files = {kind: map_files(folder, kind) if folder else [] for kind in LAYERS}
            boxes += [shp_box(p) for kind in LAYERS for p in files[kind]]
            box = union(boxes)
            if box is None:
                raise RuntimeError("no shapes in the downloads")
            log(f"  box {box_text(box)}")
            results = {}
            if buildings:
                newest = buildings[-1]
                results["buildings"] = make_pack(region, "buildings", str(newest.path), box, [newest.stamp()],
                                                 newest.date, args, state, log)
            for kind in LAYERS:
                if files[kind]:
                    stamp = sorted(s.stamp() for s in maps if kind in s.kinds)
                    date = max((s.date for s in maps if kind in s.kinds), default="")
                    results[kind] = make_pack(region, kind, str(folder), box, stamp, date, args, state, log)
            state.setdefault("regions", {}).setdefault(name, {})["box"] = box
            write_state(args.out, state)
            if folder and not args.keep_unpacked and "refused" not in results.values():
                shutil.rmtree(folder, ignore_errors=True)
            contours = args.out / f"{name}-contours{terrain_pack.SUFFIX}"
            if not args.no_ground and contours.exists():
                solve_ground(region, box, args, log)
        except (RuntimeError, OSError, zipfile.BadZipFile, sqlite3.Error, ValueError) as exc:
            failed.append(name)
            log(f"  failed: {exc}")
        finally:
            write_state(args.out, state)
    if lost:
        log("어느 시·도인지 모르는 파일은 건너뜀 (--plan으로 확인)")
    if not args.no_check:
        try:
            run_script("check_region_packs.py", ["--folder", str(args.out), "--region", ",".join(groups)], log)
        except RuntimeError as exc:
            log(f"check: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
