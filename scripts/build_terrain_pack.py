#!/usr/bin/env python3
"""
Make map packs (sida/experts/site/terrain_pack.py) from map downloads (VWorld 공간정보 다운로드,
CC BY). Only what lies in the box is kept. Each kind of source goes in its own pack:

  --contours DIR   국토지리정보원 연속수치지형도 등고선 N3L_F0010000*.shp, 표고점 N3P_F0020000*.shp
  --areas DIR      1:5,000 수치지형도 v2.0 SHP sheets (unzipped, any depth), or the same layers of a
                   연속수치지형도 download (N3A_E0032111_11.shp …, a whole 시도): 도로경계 N3A_A0010000,
                   보도 N3A_A0033320, 하천경계 N3A_E0010001, 실폭하천 N3A_E0032111, 호소 N3A_E0052114,
                   and 건물 N3A_B0010000 (층수, 용도: floors where GIS건물통합정보 has none)
  --buildings PATH GIS건물통합정보 AL_D010_<시도>_<날짜>.zip (or a folder of them: the newest by the
                   date in the name is taken; pyshp reads the zip as it is)
  --hdmap PATH     국토지리정보원 정밀도로지도 downloads (국토정보플랫폼, 공공누리 제1유형): the
                   "(B110)정밀도로지도_….zip" files as they are, or a folder of them or of what
                   they unzip to. Only the HDMap_UTMK_정표고 layers are read: road heights from
                   A2_LINK 주행경로링크 (RoadType 1), B2_SURFACELINEMARK 노면선표시, B3_SURFACEMARK
                   노면표시 and A4_SUBSIDIARYSECTION 보도 (not on bridges or in tunnels: A3 sections
                   and A2 links of other RoadTypes), one point per metre; the 보도 as sidewalk areas;
                   the lane lines and road marks themselves, with their Type and Kind codes, for
                   drawing (road_marks.py); a mark keeps the direction of the link it names

Needs two packages the app itself does not: pip install -e ".[pack]"  (pyshp, pyproj)

    python scripts/build_terrain_pack.py --name seoul --box 126.76,37.41,127.19,37.72 \\
        --contours DIR --source-date 2026-10-01
    python scripts/build_terrain_pack.py --name seoul-junggu --box 126.96,37.54,127.03,37.58 --areas DIR
    python scripts/build_terrain_pack.py --name seoul --box 126.76,37.41,127.19,37.72 --buildings DIR
    python scripts/build_terrain_pack.py --name seoul-junggu --box 126.96,37.54,127.03,37.58 --hdmap DIR

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
    "roads": "국토지리정보원 정밀도로지도(UTM-K 정표고), 공공누리 1유형",
}
HDMAP_DIR = "HDMap_UTMK_정표고"  # the 정밀도로지도 layers in UTM-K with heights above sea level
HDMAP_LAYERS = ("A2_LINK", "A3_DRIVEWAYSECTION", "A4_SUBSIDIARYSECTION", "B2_SURFACELINEMARK", "B3_SURFACEMARK")
GROUND_ROAD = 1  # RoadType 1 일반도로; 2 터널, 3 교량, 4 지하차도, 5 고가차도 are not the ground
SIDEWALK = 3  # A4_SUBSIDIARYSECTION SubType 3: 보도
ROAD_POINT_GAP = 1.0  # m: at most one road point per cell of this size, and lines densified to it
OFF_GROUND_REACH = 2.0  # m: B2/B3/A4 points this close to a bridge or tunnel link are not the ground
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
    ap.add_argument("--hdmap", type=Path, help="정밀도로지도 zips, or a folder of them or of what they unzip to")
    ap.add_argument("--source-date", default="", help="the download's 기준일 / 갱신일 (contours, areas)")
    ap.add_argument("--out", type=Path, default=terrain_pack.TERRAIN_DIR)
    args = ap.parse_args()
    if Path(args.name).name != args.name or args.name in {"", ".", ".."}:
        ap.error("--name must be a single file name")
    if not (args.contours or args.areas or args.buildings or args.hdmap):
        ap.error("give --contours, --areas, --buildings or --hdmap")

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
            for shp in layer_files(args.areas, layer):
                tr, own = projected(shp)
                for shape in shapefile.Reader(str(shp)[:-4], encoding="euc_kr").iterShapes():
                    if outside(shape.bbox, own):
                        continue
                    for part in parts(shape)[:1]:  # the outer ring; holes are not drawn
                        lons, lats = tr.transform(*zip(*part, strict=True))
                        terrain_pack.add_area(conn, kind, [list(p) for p in zip(lons, lats, strict=True)])
                        count += 1
        houses = 0
        for shp in layer_files(args.areas, "N3A_B0010000"):
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

    if args.hdmap:
        started = time.perf_counter()
        path, conn = pack("roads", args.source_date)
        cells: dict[tuple[int, int], list[float]] = {}  # 1 m cell in the file's metres → [x, y, z sums, n]
        date, sections, walks, tr = "", 0, 0, None
        lines = marks = 0
        for _section, layers in hdmap_sections(args.hdmap):
            if not {"A2_LINK", "prj"} <= layers.keys():
                continue
            sections += 1
            crs = CRS.from_wkt(layers["prj"])
            tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            back = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            xs, ys = back.transform([west, east, west, east], [south, south, north, north])
            own = (min(xs), min(ys), max(xs), max(ys))
            points, sidewalks, when, paint = road_heights(layers, own)
            date = max(date, when)
            for ref, type_, kind, run in paint["lines"]:
                lons, lats = tr.transform(*zip(*run, strict=True))
                terrain_pack.add_road_line(conn, ref, type_, kind, [list(q) for q in zip(lons, lats, strict=True)])
                lines += 1
            for ref, type_, kind, ring, ahead in paint["marks"]:
                lons, lats = tr.transform(*zip(*ring, strict=True))
                to = list(tr.transform(*ahead)) if ahead else None
                terrain_pack.add_road_mark(conn, ref, type_, kind, [list(q) for q in zip(lons, lats, strict=True)], to)
                marks += 1
            for x, y, z in points:
                c = cells.setdefault((int(x // ROAD_POINT_GAP), int(y // ROAD_POINT_GAP)), [0.0, 0.0, 0.0, 0])
                c[0] += x
                c[1] += y
                c[2] += z
                c[3] += 1
            for ring in sidewalks:
                lons, lats = tr.transform(*zip(*ring, strict=True))
                terrain_pack.add_area(conn, "sidewalk", [list(q) for q in zip(lons, lats, strict=True)])
                walks += 1
        if not cells:
            raise ValueError("no 정밀도로지도 road heights found in the requested area")
        for x, y, z, n in cells.values():
            lon, lat = tr.transform(x / n, y / n)
            terrain_pack.add_road_point(conn, lon, lat, round(z / n, 3))
        conn.execute("UPDATE meta SET value = ? WHERE key = 'source_date'", (args.source_date or _date(date),))
        done(path, conn, f"{len(cells)} road points, {walks} sidewalks, {lines} lane lines, {marks} road marks "
             f"from {sections} sections", started)
    return 0


def cpg_encoding(text: str | None) -> str:
    """The encoding a shapefile's .cpg names (EUC-KR → cp949, which reads it and more); cp949 without one."""
    name = (text or "").strip().lower().replace("-", "_")
    if name in ("utf_8", "utf8", "65001"):
        return "utf-8"
    return "cp949"


def road_heights(layers: dict, own: tuple[float, float, float, float]):
    """
    One 정밀도로지도 section's road-surface heights in the file's metres: ([(x, y, z)], [sidewalk outer
    rings [(x, y)]], latest UpdateDate, paint). Kept: A2 links on ordinary roads (RoadType 1), and the
    lane lines (B2), road markings (B3) and sidewalks (A4 SubType 3) that are not on a bridge or in
    a tunnel: not inside an A3 section whose RoadType isn't 1, nor within OFF_GROUND_REACH m of an
    A2 link whose RoadType isn't 1 (a lane line often names no link). Lines are densified to
    ROAD_POINT_GAP; only points inside `own` (the box in the file's metres) are kept.

    paint is the lane lines and road marks on the ground, for drawing: {"lines": [(ID, Type, Kind,
    [(x, y)])] (a line crossing a bridge is cut there), "marks": [(ID, Type, Kind, ring [(x, y)],
    (x, y) 1 m ahead of its middle along the link it names, or None)]} (a mark on a bridge is left
    out), those touching `own`.
    """
    import shapefile  # pyshp

    def reader(stem):
        files = layers.get(stem)
        if not files:
            return None
        files = dict(files)
        encoding = cpg_encoding(files.pop("cpg", None))
        return shapefile.Reader(**files, encoding=encoding, encodingErrors="replace")

    def column(r, name):
        fields = [f[0].lower() for f in r.fields[1:]]
        return fields.index(name.lower()) if name.lower() in fields else None

    def rows(r):
        return zip(r.iterShapes(), r.iterRecords(), strict=True)

    def text(row, at):
        return "" if at is None else str(row[at] or "").strip()

    def parts(shape):
        bounds = list(shape.parts) + [len(shape.points)]
        zs = list(getattr(shape, "z", None) or [])
        return [[(*shape.points[i][:2], zs[i]) for i in range(a, z) if i < len(zs)] for a, z in zip(bounds, bounds[1:], strict=False)]

    points, sidewalks, date = [], [], ""
    off_lines, off_areas = [], []  # bridges, tunnels, underpasses, overpasses
    links = reader("A2_LINK")
    kind_at, when_at, id_at = column(links, "RoadType"), column(links, "UpdateDate"), column(links, "ID")
    by_id: dict[str, list] = {}  # each link's parts, for the direction of the marks on it
    for shape, row in rows(links):
        if when_at is not None:
            date = max(date, str(row[when_at] or ""))
        ground = _int(row[kind_at]) == GROUND_ROAD
        by_id.setdefault(text(row, id_at), []).extend(parts(shape))
        for part in parts(shape):
            if ground:
                points += _dense(part)
            else:
                off_lines.append(part)
    sections = reader("A3_DRIVEWAYSECTION")
    if sections is not None:
        kind_at = column(sections, "RoadType")
        for shape, row in rows(sections):
            if kind_at is not None and _int(row[kind_at]) != GROUND_ROAD:
                off_areas += [[(x, y) for x, y, _z in ring] for ring in parts(shape)[:1]]
    on_ground = _off_ground_test(off_lines, off_areas)

    def touches(xy):
        return any(own[0] <= x <= own[2] and own[1] <= y <= own[3] for x, y in xy)

    paint: dict[str, list] = {"lines": [], "marks": []}
    r = reader("B2_SURFACELINEMARK")
    if r is not None:
        id_at, type_at, kind_at = column(r, "ID"), column(r, "Type"), column(r, "Kind")
        for shape, row in rows(r):
            for part in parts(shape):
                points += [p for p in _dense(part) if on_ground(p)]
                for run in _ground_runs(part, on_ground):
                    if touches(run):
                        paint["lines"].append((text(row, id_at), text(row, type_at), text(row, kind_at), run))
    r = reader("B3_SURFACEMARK")
    if r is not None:
        id_at, type_at, kind_at, link_at = column(r, "ID"), column(r, "Type"), column(r, "Kind"), column(r, "LinkID")
        for shape, row in rows(r):
            for k, part in enumerate(parts(shape)):
                dense = _dense(part)
                kept = [p for p in dense if on_ground(p)]
                points += kept
                ring = [(x, y) for x, y, _z in part]
                if k == 0 and len(ring) >= 3 and len(kept) == len(dense) and touches(ring):
                    ahead = _ahead(ring, by_id.get(text(row, link_at)) if text(row, link_at) else None)
                    paint["marks"].append((text(row, id_at), text(row, type_at), text(row, kind_at), ring, ahead))
    walks = reader("A4_SUBSIDIARYSECTION")
    if walks is not None:
        sub_at = column(walks, "SubType")
        for shape, row in rows(walks):
            if sub_at is None or _int(row[sub_at]) != SIDEWALK:
                continue
            ring = parts(shape)[:1]
            if not ring or len(ring[0]) < 3:
                continue
            kept = [p for p in _dense(ring[0]) if on_ground(p)]
            points += kept
            if kept:
                sidewalks.append([(x, y) for x, y, _z in ring[0]])
    inside = [p for p in points if own[0] <= p[0] <= own[2] and own[1] <= p[1] <= own[3]]
    walks_in = [r for r in sidewalks if any(own[0] <= x <= own[2] and own[1] <= y <= own[3] for x, y in r)]
    return inside, walks_in, date, paint


def _ground_runs(part, on_ground, tolerance: float = 0.02):
    """The pieces of a line that lie on the ground (see road_heights), as [(x, y)] runs with the
    points the 1 m densifying added taken out again where the line is straight."""
    runs, run = [], []
    for p in _dense(part):
        if on_ground(p):
            run.append((p[0], p[1]))
        else:
            if len(run) >= 2:
                runs.append(run)
            run = []
    if len(run) >= 2:
        runs.append(run)
    return [_simplify(r, tolerance) for r in runs]


def _simplify(points, tolerance):
    """Ramer–Douglas–Peucker: the fewest points within `tolerance` m of the line."""
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    far, at = -1.0, 0
    for i, (x, y) in enumerate(points[1:-1], 1):
        d = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5 if length == 0 else abs(dy * (x - x1) - dx * (y - y1)) / length
        if d > far:
            far, at = d, i
    if far <= tolerance:
        return [points[0], points[-1]]
    return _simplify(points[: at + 1], tolerance)[:-1] + _simplify(points[at:], tolerance)


def _ahead(ring, link_parts):
    """The point 1 m ahead of the ring's middle in the direction of the nearest segment of the
    link (its points run with the traffic), or None without a link."""
    if not link_parts:
        return None
    pts = ring[:-1] if len(ring) > 3 and ring[0] == ring[-1] else ring
    cx, cy = sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)
    best = None
    for part in link_parts:
        for (x1, y1, *_a), (x2, y2, *_b) in zip(part, part[1:], strict=False):
            dx, dy = x2 - x1, y2 - y1
            length2 = dx * dx + dy * dy
            if length2 == 0:
                continue
            t = max(0.0, min(1.0, ((cx - x1) * dx + (cy - y1) * dy) / length2))
            d = (cx - x1 - t * dx) ** 2 + (cy - y1 - t * dy) ** 2
            if best is None or d < best[0]:
                best = (d, dx / length2 ** 0.5, dy / length2 ** 0.5)
    return None if best is None else (cx + best[1], cy + best[2])


def _dense(part, gap: float = ROAD_POINT_GAP):
    """A line's points with more in between, so no two are farther apart than `gap`."""
    out = part[:1]
    for (x1, y1, z1), (x2, y2, z2) in zip(part, part[1:], strict=False):
        k = max(1, int(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 // gap))
        out += [(x1 + (x2 - x1) * s / k, y1 + (y2 - y1) * s / k, z1 + (z2 - z1) * s / k) for s in range(1, k + 1)]
    return out


def layer_files(root: Path, layer: str) -> list[Path]:
    """The files of one 수치지형도 layer under `root`, at any depth: a 1:5,000 sheet's `<layer>.shp`
    and the pieces of a 연속수치지형도 download, `<layer>_<n>.shp` (one 시도 cut into numbered files)."""
    return sorted(p for p in root.rglob(f"{layer}*.shp") if p.stem == layer or p.stem.startswith(f"{layer}_"))


def _off_ground_test(lines, areas):
    """A test for a point (x, y, z): True unless it lies on a bridge or in a tunnel (see road_heights)."""
    reach = OFF_GROUND_REACH
    segments: dict[tuple[int, int], list] = {}
    for line in lines:
        for (x1, y1, _a), (x2, y2, _b) in zip(line, line[1:], strict=False):
            for cx in range(int((min(x1, x2) - reach) // reach), int((max(x1, x2) + reach) // reach) + 1):
                for cy in range(int((min(y1, y2) - reach) // reach), int((max(y1, y2) + reach) // reach) + 1):
                    segments.setdefault((cx, cy), []).append((x1, y1, x2, y2))
    boxes = [(min(x for x, _ in r), min(y for _, y in r), max(x for x, _ in r), max(y for _, y in r), r) for r in areas]

    def near_line(x, y):
        for x1, y1, x2, y2 in segments.get((int(x // reach), int(y // reach)), ()):
            dx, dy = x2 - x1, y2 - y1
            t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
            if (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2 <= reach * reach:
                return True
        return False

    def in_area(x, y):
        for w, s, e, n, ring in boxes:
            if w <= x <= e and s <= y <= n and _inside(x, y, ring):
                return True
        return False

    return lambda p: not (near_line(p[0], p[1]) or in_area(p[0], p[1]))


def _inside(x, y, ring) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date(text: str) -> str:
    """YYYYMMDD (as the 정밀도로지도 writes it) as YYYY-MM-DD; anything else as it is."""
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) >= 8 and text[:8].isdigit() else text


def hdmap_sections(source: Path):
    """
    (section, {layer: {"shp", "shx", "dbf": file objects, "cpg": text}, "prj": text}) for each
    정밀도로지도 section found in `source`: a downloaded zip (read as it is), or a folder of zips or of
    unzipped sections. Only the HDMAP_DIR layers are read; the rest of a download (GNSS-INS logs,
    photos) is skipped.
    """
    import io
    import zipfile

    zips = [source] if source.suffix.lower() == ".zip" else sorted(source.rglob("*.zip")) if source.is_dir() else []
    for zpath in zips:
        with zipfile.ZipFile(zpath) as z:
            found: dict[str, dict] = {}
            for info in z.infolist():
                name = info.filename if info.flag_bits & 0x800 else _korean(info.filename)
                parts = name.split("/")
                if len(parts) < 3 or parts[-2] != HDMAP_DIR:
                    continue
                stem, _, ext = parts[-1].rpartition(".")
                ext = ext.lower()
                layers = found.setdefault("/".join(parts[:-2]), {})
                if ext == "prj" and stem == "A2_LINK":
                    layers["prj"] = z.read(info).decode("ascii", "ignore")
                elif stem in HDMAP_LAYERS and ext in ("shp", "shx", "dbf"):
                    layers.setdefault(stem, {})[ext] = io.BytesIO(z.read(info))
                elif stem in HDMAP_LAYERS and ext == "cpg":
                    layers.setdefault(stem, {})["cpg"] = z.read(info).decode("ascii", "ignore")
            yield from found.items()
    if source.is_dir():
        for folder in sorted(p for p in source.rglob(HDMAP_DIR) if p.is_dir()):
            layers: dict = {}
            for stem in HDMAP_LAYERS:
                if (folder / f"{stem}.shp").exists():
                    files = {ext: io.BytesIO((folder / f"{stem}.{ext}").read_bytes()) for ext in ("shp", "shx", "dbf")}
                    if (folder / f"{stem}.cpg").exists():
                        files["cpg"] = (folder / f"{stem}.cpg").read_text(encoding="ascii", errors="ignore")
                    layers[stem] = files
            if (folder / "A2_LINK.prj").exists():
                layers["prj"] = (folder / "A2_LINK.prj").read_text(encoding="ascii", errors="ignore")
            yield str(folder.parent.relative_to(source)), layers


def _korean(name: str) -> str:
    """A zip entry name the way Korean Windows wrote it (cp949 bytes read as cp437)."""
    try:
        return name.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


if __name__ == "__main__":
    sys.exit(main())
