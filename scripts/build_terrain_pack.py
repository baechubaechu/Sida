#!/usr/bin/env python3
"""
Make map packs (sida/experts/site/terrain_pack.py) from map downloads (VWorld 공간정보 다운로드,
CC BY). Only what lies in the box is kept. Each kind of source goes in its own pack:

  --contours DIR   국토지리정보원 연속수치지형도 등고선 N3L_F0010000*.shp, 표고점 N3P_F0020000*.shp
  --areas DIR      1:5,000 수치지형도 v2.0 SHP sheets (unzipped, any depth): 도로경계 N3A_A0010000,
                   보도 N3A_A0033320, 하천경계 N3A_E0010001, 실폭하천 N3A_E0032111, 호소 N3A_E0052114,
                   and 건물 N3A_B0010000 (층수, 용도: floors where GIS건물통합정보 has none)
  --buildings PATH GIS건물통합정보 AL_D010_<시도>_<날짜>.zip (or a folder of them: the newest by the
                   date in the name is taken; pyshp reads the zip as it is)

Needs two packages the app itself does not: pip install -e ".[pack]"  (pyshp, pyproj)

    python scripts/build_terrain_pack.py --name seoul --box 126.76,37.41,127.19,37.72 \\
        --contours DIR --source-date 2026-10-01
    python scripts/build_terrain_pack.py --name seoul-junggu --box 126.96,37.54,127.03,37.58 --areas DIR
    python scripts/build_terrain_pack.py --name seoul --box 126.76,37.41,127.19,37.72 --buildings DIR

A pack goes to ~/Sida/context_data/<name>-<kind>.terrain.sqlite (outside the repository).
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sida.console import configure_stdio  # noqa: E402
from sida.experts.site import terrain_pack  # noqa: E402

SOURCES = {
    "contours": "국토지리정보원 연속수치지형도 등고선(N3L_F0010000)·표고점(N3P_F0020000), CC BY",
    "areas": "국토지리정보원 수치지형도 v2.0 1:5,000 도로경계·보도·하천·호소, CC BY",
    "buildings": "국토교통부 GIS건물통합정보(AL_D010), CC BY",
}
AREA_LAYERS = {
    "N3A_A0010000": "road",  # 도로경계
    "N3A_A0033320": "sidewalk",  # 보도
    "N3A_E0010001": "water",  # 하천경계
    "N3A_E0032111": "water",  # 실폭하천
    "N3A_E0052114": "water",  # 호소
}
# GIS건물통합정보 columns (A0…A28) kept in a pack: 고유번호(PNU), 건축물용도명, 높이, 지상층수,
# 건물명, 동명, 데이터기준일자.
BUILDING_COLUMNS = {"pnu": "A2", "use": "A9", "height": "A16", "floors": "A26", "name": "A24", "dong": "A25", "date": "A22"}
DATED = re.compile(r"AL_D010_\d+_(\d{8})\.zip$", re.IGNORECASE)


def main() -> int:
    configure_stdio()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", required=True, help="pack name, e.g. seoul")
    ap.add_argument("--box", required=True, help="west,south,east,north in degrees (EPSG:4326)")
    ap.add_argument("--contours", type=Path, help="folder with the unzipped contour and spot-height files")
    ap.add_argument("--areas", type=Path, help="folder with the unzipped 1:5,000 sheets")
    ap.add_argument("--buildings", type=Path, help="an AL_D010 zip, or a folder holding them")
    ap.add_argument("--source-date", default="", help="the download's 기준일 / 갱신일 (contours, areas)")
    ap.add_argument("--out", type=Path, default=terrain_pack.TERRAIN_DIR)
    args = ap.parse_args()
    if Path(args.name).name != args.name or args.name in {"", ".", ".."}:
        ap.error("--name must be a single file name")
    if not (args.contours or args.areas or args.buildings):
        ap.error("give --contours, --areas or --buildings")

    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out) as staging, ExitStack() as cleanup:
        return build(args, Path(staging), cleanup)


def build(args, staging: Path, cleanup: ExitStack) -> int:
    import shapefile  # pyshp
    from pyproj import CRS, Transformer

    box = tuple(float(v) for v in args.box.split(","))
    west, south, east, north = box

    def projected(shp: Path):
        """(to lon/lat transformer, the box in the file's own coordinates)."""
        prj = Path(str(shp)[:-4] + ".prj")
        crs = CRS.from_wkt(prj.read_text(encoding="ascii", errors="ignore"))
        tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        back = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        xs, ys = back.transform([west, east, west, east], [south, south, north, north])
        return tr, (min(xs), min(ys), max(xs), max(ys))

    def outside(b, own) -> bool:
        return b[2] < own[0] or b[0] > own[2] or b[3] < own[1] or b[1] > own[3]

    def parts(shape) -> list[list]:
        bounds = list(shape.parts) + [len(shape.points)]
        return [shape.points[a:z] for a, z in zip(bounds, bounds[1:], strict=False)]

    def pack(kind: str, date: str):
        path = staging / f"{args.name}-{kind}{terrain_pack.SUFFIX}"
        conn = terrain_pack.create(path, {
            "name": f"{args.name}-{kind}", "kind": kind, "source": SOURCES[kind], "source_date": date,
            "box": args.box, "made": time.strftime("%Y-%m-%d"),
        })
        cleanup.callback(conn.close)
        return path, conn

    def done(path: Path, conn, counted: str, started: float) -> None:
        conn.commit()
        conn.execute("VACUUM")
        conn.close()
        path = path.replace(args.out / path.name)
        print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB): {counted} in {time.perf_counter() - started:.0f} s")

    if args.contours:
        started = time.perf_counter()
        path, conn = pack("contours", args.source_date)
        lines = points = 0
        for shp in sorted(args.contours.glob("N3L_F0010000*.shp")):
            tr, own = projected(shp)
            reader = shapefile.Reader(str(shp)[:-4], encoding="cp949")
            cont = [f[0] for f in reader.fields[1:]].index("CONT")
            for i, shape in enumerate(reader.iterShapes()):
                if outside(shape.bbox, own):
                    continue
                elev = float(reader.record(i)[cont])
                for part in parts(shape):
                    lons, lats = tr.transform(*zip(*part, strict=True))
                    terrain_pack.add_contour(conn, elev, [list(p) for p in zip(lons, lats, strict=True)])
                    lines += 1
            print(f"{shp.name}: {lines} contour lines so far")
        for shp in sorted(args.contours.glob("N3P_F0020000*.shp")):
            tr, own = projected(shp)
            reader = shapefile.Reader(str(shp)[:-4], encoding="cp949")
            nume = [f[0] for f in reader.fields[1:]].index("NUME")
            for i, shape in enumerate(reader.iterShapes()):
                if not shape.points:
                    continue
                x, y = shape.points[0][:2]
                if own[0] <= x <= own[2] and own[1] <= y <= own[3]:
                    lon, lat = tr.transform(x, y)
                    terrain_pack.add_spot(conn, lon, lat, float(reader.record(i)[nume]))
                    points += 1
        if not (lines or points):
            raise ValueError("no contours or spot heights found in the requested area")
        done(path, conn, f"{lines} lines, {points} spots", started)

    if args.areas:
        started = time.perf_counter()
        path, conn = pack("areas", args.source_date)
        count = 0
        for layer, kind in AREA_LAYERS.items():
            for shp in sorted(args.areas.rglob(f"{layer}.shp")):
                tr, own = projected(shp)
                for shape in shapefile.Reader(str(shp)[:-4], encoding="euc_kr").iterShapes():
                    if outside(shape.bbox, own):
                        continue
                    for part in parts(shape)[:1]:  # the outer ring; holes are not drawn
                        lons, lats = tr.transform(*zip(*part, strict=True))
                        terrain_pack.add_area(conn, kind, [list(p) for p in zip(lons, lats, strict=True)])
                        count += 1
        houses = 0
        for shp in sorted(args.areas.rglob("N3A_B0010000.shp")):
            tr, own = projected(shp)
            # building names hold a few characters outside euc-kr: cp949 reads them, a stray byte is replaced
            reader = shapefile.Reader(str(shp)[:-4], encoding="cp949", encodingErrors="replace")
            names = [f[0] for f in reader.fields[1:]]
            floors_at, use_at = names.index("층수"), names.index("용도")
            for i, shape in enumerate(reader.iterShapes()):
                if not shape.points or outside(shape.bbox, own):
                    continue
                row = reader.record(i)
                try:
                    floors = float(row[floors_at])
                except (TypeError, ValueError):
                    continue
                if floors > 0:
                    lons, lats = tr.transform(*zip(*parts(shape)[0], strict=True))
                    terrain_pack.add_map_building(conn, [list(p) for p in zip(lons, lats, strict=True)], floors, str(row[use_at] or ""))
                    houses += 1
        if not (count or houses):
            raise ValueError("no areas or map buildings found in the requested area")
        done(path, conn, f"{count} areas, {houses} map buildings with floors", started)

    if args.buildings:
        started = time.perf_counter()
        source = args.buildings
        if source.is_dir():
            dated = sorted((m.group(1), f) for f in source.glob("AL_D010_*.zip") if (m := DATED.search(f.name)))
            if not dated:
                print(f"no AL_D010_<시도>_<날짜>.zip in {source}")
                return 1
            source = dated[-1][1]
        reader = shapefile.Reader(str(source), encoding="cp949")
        names = [f[0] for f in reader.fields[1:]]
        at = {k: names.index(col) for k, col in BUILDING_COLUMNS.items()}
        if source.suffix.lower() == ".zip":
            import zipfile

            with zipfile.ZipFile(source) as z:
                prj = next((n for n in z.namelist() if n.lower().endswith(".prj")), None)
                prj_text = z.read(prj).decode("ascii", "ignore") if prj else ""
        else:
            prj_text = Path(str(source)[:-4] + ".prj").read_text(encoding="ascii", errors="ignore")
        crs = CRS.from_wkt(prj_text) if prj_text else CRS.from_epsg(5186)  # the file's 중부원점 by default
        tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        back = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        xs, ys = back.transform([west, east, west, east], [south, south, north, north])
        own = (min(xs), min(ys), max(xs), max(ys))
        date = ""
        path, conn = pack("buildings", "")
        count = 0
        for i, shape in enumerate(reader.iterShapes()):
            if not shape.points or outside(shape.bbox, own):
                continue
            row = reader.record(i)
            attrs = {k: row[j] for k, j in at.items()}
            attrs["date"] = str(attrs.get("date") or "")
            date = max(date, attrs["date"])
            for key in ("height", "floors"):
                try:
                    attrs[key] = float(attrs[key]) or None
                except (TypeError, ValueError):
                    attrs[key] = None
            lons, lats = tr.transform(*zip(*parts(shape)[0], strict=True))
            terrain_pack.add_building(conn, [list(p) for p in zip(lons, lats, strict=True)], attrs)
            count += 1
            if count % 100000 == 0:
                print(f"{count} buildings so far")
        if not count:
            raise ValueError("no buildings found in the requested area")
        conn.execute("UPDATE meta SET value = ? WHERE key = 'source_date'", (args.source_date or date,))
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('file', ?)", (source.name,))
        done(path, conn, f"{count} buildings from {source.name} (기준일 {args.source_date or date})", started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
