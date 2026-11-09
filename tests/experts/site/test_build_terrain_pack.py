import sys
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
