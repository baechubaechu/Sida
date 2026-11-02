#!/usr/bin/env python3
"""
Make a terrain pack (sida/experts/site/terrain_pack.py) from the 국토지리정보원 연속수치지형도
downloads: 등고선 N3L_F0010000_*.shp and 표고점 N3P_F0020000.shp (VWorld 공간정보 다운로드,
CC BY; unzip them first). Only what lies in the box is kept.

Needs two packages the app itself does not: pip install -e ".[pack]"  (pyshp, pyproj)

    python scripts/build_terrain_pack.py --name seoul --box 126.76,37.41,127.19,37.72 \\
        --source-date 2026-10-01 DIR_WITH_SHP_FILES

The pack goes to ~/Sida/context_data/<name>.terrain.sqlite (outside the repository).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sida.console import configure_stdio  # noqa: E402
from sida.experts.site import terrain_pack  # noqa: E402

SOURCE = "국토지리정보원 연속수치지형도 등고선(N3L_F0010000)·표고점(N3P_F0020000), CC BY (브이월드 다운로드)"


def main() -> int:
    configure_stdio()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path, help="folder with the unzipped .shp/.dbf/.prj files")
    ap.add_argument("--name", required=True, help="pack name, e.g. seoul")
    ap.add_argument("--box", required=True, help="west,south,east,north in degrees (EPSG:4326)")
    ap.add_argument("--source-date", default="", help="the download's 기준일 / 갱신일")
    ap.add_argument("--out", type=Path, default=terrain_pack.TERRAIN_DIR)
    args = ap.parse_args()

    import shapefile  # pyshp
    from pyproj import CRS, Transformer

    west, south, east, north = (float(v) for v in args.box.split(","))
    contours = sorted(args.folder.glob("N3L_F0010000*.shp"))
    spots = sorted(args.folder.glob("N3P_F0020000*.shp"))
    if not contours and not spots:
        print(f"no N3L_F0010000*.shp or N3P_F0020000*.shp in {args.folder}")
        return 1
    path = args.out / f"{args.name}{terrain_pack.SUFFIX}"
    conn = terrain_pack.create(path, {
        "name": args.name, "source": SOURCE, "source_date": args.source_date,
        "box": args.box, "made": time.strftime("%Y-%m-%d"),
    })

    def transformer(shp: Path) -> Transformer:
        crs = CRS.from_wkt(shp.with_suffix(".prj").read_text(encoding="ascii", errors="ignore"))
        return Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    def box_in_source(tr: Transformer) -> tuple[float, float, float, float]:
        back = Transformer.from_crs("EPSG:4326", tr.source_crs, always_xy=True)
        xs, ys = back.transform([west, east, west, east], [south, south, north, north])
        return min(xs), min(ys), max(xs), max(ys)

    started = time.perf_counter()
    lines = 0
    for shp in contours:
        tr = transformer(shp)
        x0, y0, x1, y1 = box_in_source(tr)
        reader = shapefile.Reader(str(shp.with_suffix("")), encoding="cp949")
        cont = [f[0] for f in reader.fields[1:]].index("CONT")
        for i, shape in enumerate(reader.iterShapes()):
            b = shape.bbox
            if b[2] < x0 or b[0] > x1 or b[3] < y0 or b[1] > y1:
                continue
            elev = float(reader.record(i)[cont])
            parts = list(shape.parts) + [len(shape.points)]
            for a, z in zip(parts, parts[1:], strict=False):
                xs, ys = zip(*shape.points[a:z], strict=True)
                lons, lats = tr.transform(xs, ys)
                terrain_pack.add_contour(conn, elev, [list(p) for p in zip(lons, lats, strict=True)])
                lines += 1
        print(f"{shp.name}: {lines} contour lines so far")
    points = 0
    for shp in spots:
        tr = transformer(shp)
        x0, y0, x1, y1 = box_in_source(tr)
        reader = shapefile.Reader(str(shp.with_suffix("")), encoding="cp949")
        nume = [f[0] for f in reader.fields[1:]].index("NUME")
        for i, shape in enumerate(reader.iterShapes()):
            if not shape.points:
                continue
            x, y = shape.points[0]
            if x0 <= x <= x1 and y0 <= y <= y1:
                lon, lat = tr.transform(x, y)
                if west <= lon <= east and south <= lat <= north:
                    terrain_pack.add_spot(conn, lon, lat, float(reader.record(i)[nume]))
                    points += 1
        print(f"{shp.name}: {points} spot heights")
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    size = path.stat().st_size / 1e6
    print(f"wrote {path} ({size:.1f} MB): {lines} lines, {points} spots in {time.perf_counter() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
