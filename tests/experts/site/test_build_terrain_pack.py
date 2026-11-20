import sys
import zipfile
from types import SimpleNamespace

import pytest

from scripts import build_terrain_pack
from sida.experts.site import terrain_pack


def test_spot_points_and_failed_rebuild_keep_the_last_complete_pack(tmp_path, monkeypatch):
    # POINT records have coordinates but no bounding box. Stand-ins keep pack-only
    # dependencies out of a normal app/test installation.
    shapes = [SimpleNamespace(points=[p]) for p in [(1, 1), (10, 10)]]
    reader = SimpleNamespace(fields=[("DeletionFlag",), ("NUME",)], iterShapes=lambda: iter(shapes),
                             record=lambda i: [42])
    monkeypatch.setitem(sys.modules, "shapefile", SimpleNamespace(Reader=lambda *a, **kw: reader))
    transformer = SimpleNamespace(transform=lambda x, y: (x, y))
    monkeypatch.setitem(sys.modules, "pyproj", SimpleNamespace(
        CRS=SimpleNamespace(from_wkt=lambda wkt: wkt),
        Transformer=SimpleNamespace(from_crs=lambda *args, **kw: transformer)))
    (tmp_path / "N3P_F0020000.shp").touch()
    (tmp_path / "N3P_F0020000.prj").write_text("test")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["build", "--name", "test", "--box", "0,0,2,2",
                                     "--contours", str(tmp_path), "--out", str(out)])
    monkeypatch.setattr(build_terrain_pack, "configure_stdio", lambda: None)
    assert build_terrain_pack.main() == 0
    assert terrain_pack.query(-20, -20, 20, 20, folder=out)["spots"] == [[1, 1, 42]]
    pack, = out.iterdir()
    previous = pack.read_bytes()
    reader.record = lambda i: ["invalid elevation"]
    with pytest.raises(ValueError):
        build_terrain_pack.main()
    assert list(out.iterdir()) == [pack]
    assert pack.read_bytes() == previous
    reader.record = lambda i: [48]
    assert build_terrain_pack.main() == 0
    assert terrain_pack.query(-20, -20, 20, 20, folder=out)["spots"] == [[1, 1, 48]]


def _hdmap_section(root, cpg="EUC-KR"):
    """A tiny made-up 정밀도로지도 section in UTM-K metres: an ordinary road along y = 0 at 30 m, a
    bridge along y = 50 at 40 m with its A3 section, a lane line across both, a road marking on the
    bridge and one on the road, and a sidewalk."""
    import shapefile

    folder = root / "SEC001_시험로" / build_terrain_pack.HDMAP_DIR
    folder.mkdir(parents=True)

    def layer(stem, kind, fields, shapes):
        w = shapefile.Writer(str(folder / stem), shapeType=kind, encoding="cp949" if cpg == "EUC-KR" else "utf-8")
        for name in fields:
            w.field(name, "C", 30)
        for geometry, values in shapes:
            (w.linez if kind == shapefile.POLYLINEZ else w.polyz)([geometry])
            w.record(*values)
        w.close()
        (folder / f"{stem}.cpg").write_text(cpg)
        (folder / f"{stem}.prj").write_text("UTM-K")

    line, poly = shapefile.POLYLINEZ, shapefile.POLYGONZ
    layer("A2_LINK", line, ["ID", "RoadType", "UpdateDate"], [
        ([[0, 0, 30], [20, 0, 30]], ["A2_1", "1", "20230724"]),
        ([[0, 50, 40], [20, 50, 40]], ["A2_2", "3", "20230801"]),  # 교량
    ])
    layer("A3_DRIVEWAYSECTION", poly, ["ID", "Kind", "RoadType"], [
        ([[-2, 45, 40], [22, 45, 40], [22, 55, 40], [-2, 55, 40], [-2, 45, 40]], ["A3_1", "1", "3"]),
    ])
    layer("B2_SURFACELINEMARK", line, ["ID", "Type", "Kind", "R_linkID", "L_linkID"], [
        ([[10, -5, 30.2], [10, 44, 30.2], [10, 46, 40.2], [10, 54, 40.2]], ["B2_1", "111", "515", "", ""]),  # no link: cut at the bridge
    ])
    layer("B3_SURFACEMARK", poly, ["ID", "Type", "Kind", "LinkID"], [
        ([[4, 49, 40.1], [6, 49, 40.1], [6, 51, 40.1], [4, 51, 40.1], [4, 49, 40.1]], ["B3_1", "1", "5371", "A2_2"]),
        ([[4, -1, 30.1], [6, -1, 30.1], [6, 1, 30.1], [4, 1, 30.1], [4, -1, 30.1]], ["B3_2", "1", "5371", "A2_1"]),
        ([[14, -4, 30.1], [18, -4, 30.1], [18, -2, 30.1], [14, -2, 30.1], [14, -4, 30.1]], ["B3_3", "5", "5321", ""]),  # no link
    ])
    layer("A4_SUBSIDIARYSECTION", poly, ["ID", "SubType", "Name"], [
        ([[0, 5, 30.3], [20, 5, 30.3], [20, 8, 30.3], [0, 8, 30.3], [0, 5, 30.3]], ["A4_1", "3", "보도"]),
        ([[0, 20, 99], [5, 20, 99], [5, 25, 99], [0, 20, 99]], ["A4_2", "4", "기타"]),  # not a sidewalk
    ])
    return folder


def _identity_pyproj(monkeypatch):
    transformer = SimpleNamespace(transform=lambda x, y: (x, y))
    monkeypatch.setitem(sys.modules, "pyproj", SimpleNamespace(
        CRS=SimpleNamespace(from_wkt=lambda wkt: wkt),
        Transformer=SimpleNamespace(from_crs=lambda *args, **kw: transformer)))


def test_hdmap_road_heights_leave_out_bridges_and_keep_sidewalks(tmp_path, monkeypatch):
    pytest.importorskip("shapefile")
    _hdmap_section(tmp_path / "hd")
    _identity_pyproj(monkeypatch)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["build", "--name", "t", "--box=-100,-100,100,100",
                                     "--hdmap", str(tmp_path / "hd"), "--out", str(out)])
    monkeypatch.setattr(build_terrain_pack, "configure_stdio", lambda: None)
    assert build_terrain_pack.main() == 0
    (pack,) = out.iterdir()
    assert terrain_pack.info(pack)["kind"] == "roads" and terrain_pack.info(pack)["source_date"] == "2023-08-01"
    found = terrain_pack.query(-100, -100, 100, 100, folder=out)
    zs = [z for _x, _y, z in found["road_points"]]
    assert zs and max(zs) < 31  # nothing from the bridge deck (40 m): not its link, line part or marking
    assert any(abs(z - 30.0) < 0.01 for z in zs) and any(abs(z - 30.3) < 0.01 for z in zs)  # road and sidewalk
    near_bridge = [p for p in found["road_points"] if 45 <= p[1] <= 55]
    assert near_bridge == []  # the unlinked lane line is cut where it crosses the bridge
    assert [a["kind"] for a in found["areas"]] == ["sidewalk"]  # the 보도 only, not SubType 4
    assert found["sources"][0]["source"].startswith("국토지리정보원 정밀도로지도")
    # the paint itself, for drawing: the lane line up to the bridge, the marks on the road with the
    # way their link runs (east), none on the bridge
    (line,) = found["road_lines"]
    assert (line["type"], line["kind"]) == ("111", "515")
    assert line["points"][0] == pytest.approx([10, -5]) and line["points"][-1][1] == pytest.approx(44, abs=0.01)
    assert len(line["points"]) == 2  # the 1 m points the densifying added are taken out again
    marks = {m["kind"]: m for m in found["road_marks"]}
    assert set(marks) == {"5371", "5321"}
    assert marks["5371"]["ahead"] == pytest.approx([6, 0])  # 1 m ahead of its middle, along A2_1
    assert marks["5321"]["ahead"] is None and len(marks["5321"]["ring"]) == 5


def test_hdmap_reads_the_encoding_each_file_names():
    assert build_terrain_pack.cpg_encoding("EUC-KR") == "cp949"  # 중구, 종로구
    assert build_terrain_pack.cpg_encoding("utf_8\n") == "utf-8"  # 청계천
    assert build_terrain_pack.cpg_encoding("UTF-8") == "utf-8"
    assert build_terrain_pack.cpg_encoding(None) == "cp949"


def test_hdmap_sections_are_read_from_the_zip_as_downloaded(tmp_path):
    pytest.importorskip("shapefile")
    import zipfile

    folder = _hdmap_section(tmp_path / "hd", cpg="utf_8")
    z = tmp_path / "(B110)정밀도로지도_시험.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in folder.iterdir():
            zf.writestr(f"SEC001_시험로/{build_terrain_pack.HDMAP_DIR}/{f.name}", f.read_bytes())
        zf.writestr("SEC001_시험로/GNSS-INS/log.txt", "not read")
    sections = dict(build_terrain_pack.hdmap_sections(z))
    assert list(sections) == ["SEC001_시험로"]
    layers = sections["SEC001_시험로"]
    assert {"A2_LINK", "A3_DRIVEWAYSECTION", "B2_SURFACELINEMARK", "prj"} <= set(layers)
    assert layers["A2_LINK"]["cpg"] == "utf_8"
    # a zip made on Korean Windows stores cp949 bytes without the UTF-8 flag; zipfile reads them as cp437
    assert build_terrain_pack._korean("SEC001_시험로/HDMap_UTMK_정표고".encode("cp949").decode("cp437")) == "SEC001_시험로/HDMap_UTMK_정표고"


def test_areas_read_sheets_and_the_numbered_files_of_a_continuous_download(tmp_path):
    for name in ("sheet1/N3A_E0032111.shp", "N3A_E0032111_11.shp", "N3A_E0032111_12.shp", "N3A_E00321110.shp", "N3A_E0010001.shp"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).touch()
    found = [p.relative_to(tmp_path).as_posix() for p in build_terrain_pack.layer_files(tmp_path, "N3A_E0032111")]
    assert sorted(found) == ["N3A_E0032111_11.shp", "N3A_E0032111_12.shp", "sheet1/N3A_E0032111.shp"]


def test_buildings_are_read_from_every_shapefile_of_a_split_download(tmp_path, monkeypatch):
    # 브이월드 cuts a large 시·도 into files of a million buildings inside one zip
    # (AL_D010_41_….shp, ….(2).shp, ….(3).shp); pyshp alone refuses a zip with more than one.
    shapefile = pytest.importorskip("shapefile")
    transformer = SimpleNamespace(transform=lambda x, y: (x, y))
    monkeypatch.setitem(sys.modules, "pyproj", SimpleNamespace(
        CRS=SimpleNamespace(from_wkt=lambda wkt: wkt, from_epsg=lambda code: code),
        Transformer=SimpleNamespace(from_crs=lambda *args, **kw: transformer)))
    stems = ["AL_D010_41_20261109", "AL_D010_41_20261109(2)"]
    folder = tmp_path / "files"
    folder.mkdir()
    for n, stem in enumerate(stems):
        w = shapefile.Writer(str(folder / stem), shapeType=shapefile.POLYGON, encoding="cp949")
        for col in build_terrain_pack.BUILDING_COLUMNS.values():
            w.field(col, "C", 30)
        x = 0.5 + n * 0.5
        w.poly([[[x, 0.5], [x + 0.1, 0.5], [x + 0.1, 0.6], [x, 0.5]]])
        w.record(f"41{n:017d}", "주택", "9", "3", "", "", "20261101")
        w.close()
        (folder / f"{stem}.prj").write_text("KOREA_TM")
    download = tmp_path / "AL_D010_41_20261109.zip"
    with zipfile.ZipFile(download, "w") as z:
        for f in sorted(folder.iterdir()):
            z.write(f, f.name)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["build", "--name", "gyeonggi", "--box", "0,0,2,2",
                                     "--buildings", str(download), "--out", str(out)])
    monkeypatch.setattr(build_terrain_pack, "configure_stdio", lambda: None)
    assert build_terrain_pack.main() == 0
    houses = terrain_pack.query(0, 0, 2, 2, folder=out)["buildings"]
    assert sorted(h["pnu"] for h in houses) == ["4100000000000000000", "4100000000000000001"]
    assert [(name.rsplit("/", 1)[-1], prj) for name, prj in terrain_pack.zip_shapefiles(download)] == [
        ("AL_D010_41_20261109(2).shp", "KOREA_TM"), ("AL_D010_41_20261109.shp", "KOREA_TM")]
    single = tmp_path / "one.zip"
    with zipfile.ZipFile(single, "w") as z:
        for f in sorted(folder.glob(f"{stems[0]}.*")):
            z.write(f, f.name)
    assert terrain_pack.zip_shapefiles(single) == [(str(single), "KOREA_TM")]  # pyshp opens the zip as it is


def test_contours_are_thinned_and_cut_to_the_시도_outline(tmp_path, monkeypatch):
    # A wavy line inside (its 1 cm wiggles go), a line crossing the outline's edge (its inside
    # part stays) and a line far outside the outline but inside the box (dropped). Spot heights
    # outside the outline go too. The outline comes from 브이월드 for the run only.
    import numpy as np

    wavy = [(0.1 + i * 0.01, 0.1 + (i % 2) * 1e-7) for i in range(51)]  # 0.1 … 0.6, wiggling 1e-7
    crossing = [(0.2, 0.5), (0.5, 0.5), (0.8, 0.5), (1.5, 0.5)]
    far = [(1.6, 1.6), (1.7, 1.7)]
    lines = [SimpleNamespace(bbox=[min(p[0] for p in ps), min(p[1] for p in ps), max(p[0] for p in ps),
                                   max(p[1] for p in ps)], parts=[0], points=ps) for ps in (wavy, crossing, far)]
    spots = [SimpleNamespace(points=[p]) for p in [(0.5, 0.5), (1.8, 1.8)]]

    def reader(path, **kw):
        if path.endswith("N3L_F0010000"):
            return SimpleNamespace(fields=[("DeletionFlag",), ("CONT",)], iterShapes=lambda: iter(lines),
                                   record=lambda i: [10 * (i + 1)])
        return SimpleNamespace(fields=[("DeletionFlag",), ("NUME",)], iterShapes=lambda: iter(spots),
                               record=lambda i: [7])

    monkeypatch.setitem(sys.modules, "shapefile", SimpleNamespace(Reader=reader))
    transformer = SimpleNamespace(transform=lambda x, y: (x, y))
    monkeypatch.setitem(sys.modules, "pyproj", SimpleNamespace(
        CRS=SimpleNamespace(from_wkt=lambda wkt: wkt),
        Transformer=SimpleNamespace(from_crs=lambda *args, **kw: transformer)))
    asked = []

    def outlines(codes, http_get=None):
        asked.append(list(codes))
        return [{"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}]

    monkeypatch.setattr(build_terrain_pack.landapi, "sido_outlines", outlines)
    for name in ("N3L_F0010000", "N3P_F0020000"):
        (tmp_path / f"{name}.shp").touch()
        (tmp_path / f"{name}.prj").write_text("test")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["build", "--name", "t", "--box", "0,0,2,2", "--sido", "26",
                                     "--contours", str(tmp_path), "--out", str(out)])
    monkeypatch.setattr(build_terrain_pack, "configure_stdio", lambda: None)
    assert build_terrain_pack.main() == 0
    assert asked == [["26"]]
    found = terrain_pack.query(-5, -5, 5, 5, folder=out)
    by_elev = {c["elev"]: c["points"] for c in found["contours"]}
    assert sorted(by_elev) == [10, 20]  # the far line is gone
    assert by_elev[10] == [[0.1, 0.1], [0.6, 0.1]]  # 51 points within 0.5 of a straight line: its ends
    xs = [p[0] for p in by_elev[20]]
    assert xs[0] == 0.2 and 1.0 < xs[-1] <= 1.0 + build_terrain_pack.OUTLINE_PAD + 1e-6  # cut at the padded edge
    assert found["spots"] == [[0.5, 0.5, 7]]
    # --contours-tolerance 0 keeps every point; no --sido asks 브이월드 nothing
    asked.clear()
    monkeypatch.setattr(sys, "argv", ["build", "--name", "t", "--box", "0,0,2,2", "--contours-tolerance", "0",
                                     "--contours", str(tmp_path), "--out", str(out)])
    assert build_terrain_pack.main() == 0
    assert asked == []
    by_elev = {c["elev"]: c["points"] for c in terrain_pack.query(-5, -5, 5, 5, folder=out)["contours"]}
    assert len(by_elev[10]) == 51 and sorted(by_elev) == [10, 20, 30]
    assert np.allclose(by_elev[10], wavy)


def test_without_a_boundary_from_vworld_a_cut_pack_is_not_made(tmp_path, monkeypatch):
    monkeypatch.setattr(build_terrain_pack.landapi, "sido_outlines", lambda codes, http_get=None: [])
    with pytest.raises(ValueError, match="no 시·도 boundary"):
        build_terrain_pack.outline(["26"])
