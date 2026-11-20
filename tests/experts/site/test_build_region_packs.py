"""scripts/build_region_packs.py — a 시·도's packs from a folder of downloads, on made-up files."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from scripts import build_region_packs as brp
from sida.experts.site import regions, terrain_pack


def a_zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def shp_set(stem: str) -> dict[str, bytes]:
    return {f"{stem}{ext}": b"x" for ext in (".shp", ".shx", ".dbf", ".prj")}


def test_regions_come_from_folders_then_names_then_the_files_inside(tmp_path):
    raw, work = tmp_path / "raw", tmp_path / "work"
    a_zip(raw / "부산" / "N3L_F0010000_3.zip", shp_set("N3L_F0010000_3"))  # a piece number, not a 시·도
    a_zip(raw / "AL_D010_26_20260301.zip", shp_set("AL_D010_26_20260301"))
    a_zip(raw / "연속수치지형도_울산.zip", shp_set("N3A_E0032111_7"))
    a_zip(raw / "N3A_A0010000_31.zip", shp_set("N3A_A0010000_31"))
    a_zip(raw / "data.zip", shp_set("N3P_F0020000_50"))  # told by the layer files inside
    a_zip(raw / "mystery.zip", shp_set("N3A_A0010000_1"))
    a_zip(raw / "경기도_광주시" / "N3L_F0010000.zip", shp_set("N3L_F0010000"))  # two 시·도 in one name
    a_zip(raw / "readme.zip", {"readme.txt": b"x"})
    (raw / "old.z01").write_bytes(b"x")
    whole = io.BytesIO()
    with zipfile.ZipFile(whole, "w") as z:
        for name, data in shp_set("N3L_F0010000_1").items():
            z.writestr(name, data)
    data = whole.getvalue()
    (raw / "split").mkdir()
    (raw / "split" / "서울.zip.001").write_bytes(data[:40])
    (raw / "split" / "서울.zip.002").write_bytes(data[40:])

    found = {s.path.name: s for s in brp.find_sources(raw, work)}
    told = {n: (s.region.name if s.region else None, s.basis, sorted(s.kinds)) for n, s in found.items()}
    assert told["N3L_F0010000_3.zip"] == ("busan", "folder", ["contours"])
    assert told["AL_D010_26_20260301.zip"] == ("busan", "name", ["buildings"])
    assert found["AL_D010_26_20260301.zip"].date == "2026-03-01"
    assert told["연속수치지형도_울산.zip"] == ("ulsan", "name", ["areas"])
    assert told["N3A_A0010000_31.zip"] == ("ulsan", "layer code", ["areas"])
    assert told["data.zip"] == ("jeju", "inside", ["contours"])
    assert told["mystery.zip"] == (None, "", ["areas"])
    assert told["N3L_F0010000.zip"] == (None, "", ["contours"])
    assert told["readme.zip"][2] == []
    assert "7-Zip" in found["old.z01"].note
    assert told["서울.zip"] == ("seoul", "name", ["contours"])
    assert zipfile.is_zipfile(found["서울.zip"].path) and work in found["서울.zip"].path.parents


def test_a_zip_is_unpacked_with_its_folders_and_inner_zips_once_and_nothing_outside(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        for name, data in shp_set("N3A_A0010000").items():
            z.writestr(name, data)
    zpath = a_zip(tmp_path / "gu.zip", {
        "sheetA/N3A_B0010000.shp": b"a", "sheetB/N3A_B0010000.shp": b"b", "sheetA/photo.jpg": b"x",
        "../evil.shp": b"x", "C:/evil.shp": b"x", "35704001.zip": inner.getvalue(),
    })
    dest = tmp_path / "out" / "gu"
    brp.unpack(zpath, dest)
    files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert files == [".unpacked", "35704001/.unpacked", "35704001/N3A_A0010000.dbf", "35704001/N3A_A0010000.prj", "35704001/N3A_A0010000.shp",
                     "35704001/N3A_A0010000.shx", "sheetA/N3A_B0010000.shp", "sheetB/N3A_B0010000.shp"]
    assert not (tmp_path / "evil.shp").exists()
    (dest / "sheetA" / "N3A_B0010000.shp").write_bytes(b"changed")
    brp.unpack(zpath, dest)  # done already: left alone
    assert (dest / "sheetA" / "N3A_B0010000.shp").read_bytes() == b"changed"
    assert [p.stem for p in brp.map_files(dest, "areas")] == ["N3A_A0010000", "N3A_B0010000", "N3A_B0010000"]


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    """A raw folder for 부산 (buildings + contours + areas), with build_terrain_pack and build_ground_tiles
    stood in for: each made pack holds `sizes[kind]` rows. Returns (args for main, calls, sizes)."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    a_zip(raw / "AL_D010_26_20260301.zip", shp_set("AL_D010_26_20260301"))
    a_zip(raw / "부산" / "contours.zip", {**shp_set("N3L_F0010000_1"), **shp_set("N3P_F0020000_1")})
    a_zip(raw / "부산" / "areas.zip", shp_set("N3A_A0010000_2"))
    calls: list[tuple[str, list[str]]] = []
    sizes = {"buildings": 10, "contours": 5, "areas": 3}

    def run_script(script, args, log):
        calls.append((script, list(args)))
        if script != "build_terrain_pack.py":
            return
        name, kind = args[args.index("--name") + 1], next(a[2:] for a in args if a[2:] in sizes)
        folder = Path(args[args.index("--out") + 1])
        conn = terrain_pack.create(folder / f"{name}-{kind}{terrain_pack.SUFFIX}", {"kind": kind})
        for i in range(sizes[kind]):
            ring = [[129 + i * 1e-4, 35], [129.0001 + i * 1e-4, 35], [129 + i * 1e-4, 35.0001]]
            if kind == "buildings":
                terrain_pack.add_building(conn, ring, {"pnu": "", "use": "", "height": None, "floors": None})
            elif kind == "contours":
                terrain_pack.add_contour(conn, 10.0 + i, ring)
            else:
                terrain_pack.add_area(conn, "road", ring)
        conn.commit()
        conn.close()

    monkeypatch.setattr(brp, "run_script", run_script)
    monkeypatch.setattr(brp, "shp_box", lambda shp=None, *, zpath=None: [129.0, 35.0, 129.5, 35.4])
    monkeypatch.setattr(brp.landapi, "sido_boxes", lambda: {"26": [128.5, 34.5, 130.0, 36.0]})
    argv = ["brp", "--raw", str(raw), "--out", str(out), "--no-check", "--workers", "2"]
    return argv, calls, sizes, out


def test_a_시도_is_made_from_its_folder_and_made_again_only_when_its_downloads_change(downloads, monkeypatch):
    argv, calls, sizes, out = downloads
    monkeypatch.setattr(sys, "argv", argv)
    assert brp.main() == 0
    made = [(s, a[a.index("--name") + 1], next(x for x in a if x.startswith("--") and x[2:] in sizes))
            for s, a in calls if s == "build_terrain_pack.py"]
    assert made == [("build_terrain_pack.py", "busan", "--buildings"), ("build_terrain_pack.py", "busan", "--contours"),
                    ("build_terrain_pack.py", "busan", "--areas")]
    first = calls[0][1]
    assert first[first.index("--box") + 1] == "128.99800,34.99800,129.50200,35.40200"  # the files' extent, padded
    assert first[first.index("--source-date") + 1] == "2026-03-01"
    ground = calls[-1]
    assert ground[0] == "build_ground_tiles.py" and "--skip-others" in ground[1] and ground[1][1] == "busan"
    for kind in sizes:
        assert (out / f"busan-{kind}{terrain_pack.SUFFIX}").exists()
    state = json.loads((out / brp.STATE).read_text(encoding="utf-8"))
    assert state["regions"]["busan"]["buildings"]["counts"] == {"buildings": 10}
    assert not (out / "region-work" / "busan" / "unpacked").exists()  # unpacked files go once the packs are made
    # again with the same downloads: nothing is made, only the ground is carried on
    calls.clear()
    assert brp.main() == 0
    assert [s for s, _ in calls] == ["build_ground_tiles.py"]
    # a new month of buildings: only that pack is made again
    a_zip(Path(argv[argv.index("--raw") + 1]) / "AL_D010_26_20260401.zip", shp_set("AL_D010_26_20260401"))
    calls.clear()
    assert brp.main() == 0
    assert [a[a.index("--source-date") + 1] for s, a in calls if s == "build_terrain_pack.py"] == ["2026-04-01"]


def test_a_new_pack_with_far_fewer_buildings_does_not_replace_the_old_one(downloads, monkeypatch):
    argv, calls, sizes, out = downloads
    monkeypatch.setattr(sys, "argv", [*argv, "--no-ground"])
    assert brp.main() == 0
    pack = out / f"busan-buildings{terrain_pack.SUFFIX}"
    before = pack.read_bytes()
    sizes["buildings"] = 9  # 90%: a download cut short
    monkeypatch.setattr(sys, "argv", [*argv, "--no-ground", "--force"])
    assert brp.main() == 0
    assert pack.read_bytes() == before
    record = json.loads((out / brp.STATE).read_text(encoding="utf-8"))["regions"]["busan"]["buildings"]
    assert record["refused"] == ["buildings"] and record["counts"] == {"buildings": 10}
    assert (out / "region-work" / "busan" / "unpacked").exists()  # kept to try again
    monkeypatch.setattr(sys, "argv", [*argv, "--no-ground", "--force", "--accept-drop"])
    assert brp.main() == 0
    assert brp.counts(pack, "buildings") == {"buildings": 9}


def test_the_plan_lists_what_it_found_and_makes_nothing(downloads, monkeypatch, capsys):
    argv, calls, sizes, out = downloads
    a_zip(Path(argv[argv.index("--raw") + 1]) / "mystery.zip", shp_set("N3A_A0010000_1"))
    monkeypatch.setattr(sys, "argv", [*argv, "--plan"])
    assert brp.main() == 0
    text = capsys.readouterr().out
    assert "부산광역시 (busan)" in text and "AL_D010_26_20260301.zip: buildings [name]" in text
    assert "contours.zip: contours [folder]" in text and "지형 칸" in text
    assert "mystery.zip: areas → 부산광역시" in text.split("전국 파일")[1]  # no 시·도 in its name: used where it reaches
    assert calls == [] and not out.exists()


def test_neighbouring_tiles_files_are_brought_up_to_date_first(downloads, monkeypatch):
    argv, calls, sizes, out = downloads
    out.mkdir()
    near, far = out / f"ulsan{brp.ground_tiles.SUFFIX}", out / f"seoul{brp.ground_tiles.SUFFIX}"
    near.touch()
    far.touch()
    boxes = {near: "129.2,35.3,129.5,35.7", far: "126.7,37.4,127.2,37.7"}
    monkeypatch.setattr(brp.ground_tiles, "info", lambda p: {"box": boxes[p]})
    monkeypatch.setattr(brp.ground_tiles, "current", lambda p, folder: False)
    monkeypatch.setattr(sys, "argv", argv)
    assert brp.main() == 0
    ground = [a for s, a in calls if s == "build_ground_tiles.py"]
    assert [a[1] for a in ground] == ["ulsan", "busan"]
    assert ground[0][ground[0].index("--box") + 1] == "129.20000,35.30000,129.50000,35.70000"
    assert "--skip-others" not in ground[0]


def test_a_few_stray_buildings_far_away_do_not_stretch_the_box(downloads, monkeypatch, capsys):
    # The Seoul file of 2026-11-09 holds buildings drawn as far as 129.9°E: its header box reached
    # 부산, and the ground would have been solved over 94,000 tiles instead of 3,300.
    argv, calls, sizes, out = downloads
    monkeypatch.setattr(brp, "shp_box", lambda shp=None, *, zpath=None: [128.9, 33.4, 131.0, 35.4])
    monkeypatch.setattr(brp.landapi, "sido_boxes", lambda: {"26": [128.76, 34.88, 129.31, 35.39], "11": [126.7, 37.4, 127.2, 37.7]})
    monkeypatch.setattr(sys, "argv", [*argv, "--plan"])
    assert brp.main() == 0
    text = capsys.readouterr().out
    assert "시·도 경계로 자름" in text and "범위 128.89800,34.87000,129.32000,35.40000" in text
    monkeypatch.setattr(sys, "argv", argv)
    assert brp.main() == 0
    boxes = {a[a.index("--box") + 1] for s, a in calls if "--box" in a}
    assert boxes == {"128.89800,34.87000,129.32000,35.40000"}  # packs and ground alike
    # a pack made over a box that has since changed is made again, though the downloads are the same
    monkeypatch.setattr(brp.landapi, "sido_boxes", lambda: {"26": [128.76, 34.88, 129.35, 35.39]})
    calls.clear()
    assert brp.main() == 0
    assert len([s for s, _ in calls if s == "build_terrain_pack.py"]) == 3


def test_without_the_boundary_the_packs_are_made_and_the_ground_waits(downloads, monkeypatch, capsys):
    argv, calls, sizes, out = downloads

    def no_key():
        raise RuntimeError("no key")

    monkeypatch.setattr(brp.landapi, "sido_boxes", no_key)
    monkeypatch.setattr(sys, "argv", argv)
    assert brp.main() == 0
    assert [s for s, _ in calls] == ["build_terrain_pack.py"] * 3
    assert "ground skipped" in capsys.readouterr().out
    calls.clear()
    monkeypatch.setattr(sys, "argv", [*argv, "--plan", "--no-api"])
    assert brp.main() == 0
    assert "시·도 경계를 받지 못해 지형 칸을 어림하지 않음" in capsys.readouterr().out


def test_only_the_시도_asked_for(downloads, monkeypatch):
    argv, calls, sizes, out = downloads
    monkeypatch.setattr(sys, "argv", [*argv, "--region", "울산"])
    assert brp.main() == 1  # nothing for 울산 in the folder
    assert calls == []
    assert brp.wanted_regions("busan,26,부산광역시") == {"busan"}
    with pytest.raises(SystemExit):
        brp.wanted_regions("아틀란티스")


def test_regions_are_told_from_names_people_write():
    assert regions.find("부산광역시").name == "busan"
    assert regions.find("busan").name == "busan"
    assert regions.find("26").name == "busan"
    assert regions.find("연속수치지형도_전남광주통합특별시").name == "jeonnam-gwangju"
    assert regions.find("전라남도").name == "jeonnam-gwangju"
    assert regions.find("경기도_광주시") is None  # two 시·도 named
    assert regions.find("2026_11") is None  # numbers inside a name are not codes
    assert regions.by_code("4141010500").name == "gyeonggi"
    assert regions.by_code("42").name == regions.by_code("51").name == "gangwon"
    assert len(regions.REGIONS) == 16


def test_layers_are_told_from_the_korean_names_of_the_newer_downloads():
    assert brp._layer_of("(연속수치지형도)등고선_001") == "N3L_F0010000"
    assert brp._layer_of("(연속수치지형도)도로경계_면_002") == "N3A_A0010000"
    assert brp._layer_of("(연속수치지형도)도로경계_선_001") is None  # the line layer is not the area
    assert brp._layer_of("하천경계_선") is None and brp._layer_of("N3A_E0010001") == "N3A_E0010001"
    assert brp._layer_of("AL_D010_11_20261109") is None
    assert brp._kinds_of(["표고점.shp", "N3A_E0032111.shp"]) == {"contours", "areas"}


def test_a_shapefile_without_its_code_is_unpacked_under_the_code_its_zip_names(tmp_path):
    zpath = a_zip(tmp_path / "(연속수치지형도)등고선_001.zip", shp_set("CONTOUR_001"))
    brp.unpack(zpath, tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").glob("*.shp")) == ["N3L_F0010000_CONTOUR_001.shp"]
    assert brp.map_files(tmp_path / "out", "contours") == [tmp_path / "out" / "N3L_F0010000_CONTOUR_001.shp"]


def test_the_box_is_read_from_the_shapefile_header_in_the_zip(tmp_path):
    shapefile = pytest.importorskip("shapefile")
    w = shapefile.Writer(str(tmp_path / "N3L_F0010000_1"), shapeType=shapefile.POLYLINE)
    w.field("CONT", "N", 10)
    w.line([[[200000, 550000], [200100, 550050]]])
    w.record(10)
    w.close()
    empty = shapefile.Writer(str(tmp_path / "N3L_F0010000_2"), shapeType=shapefile.POLYLINE)
    empty.field("CONT", "N", 10)
    empty.close()
    zpath = tmp_path / "pieces.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in sorted(tmp_path.glob("N3L_*")):
            z.write(f, f.name)
    assert list(brp._headers(zpath)) == [((200000.0, 550000.0, 200100.0, 550050.0), "")]  # the empty one left out
    assert list(brp._headers(tmp_path / "N3L_F0010000_1.shp")) == [((200000.0, 550000.0, 200100.0, 550050.0), "")]


def test_nationwide_pieces_go_to_each_시도_they_reach(downloads, monkeypatch, capsys):
    # 브이월드 cuts the 연속수치지형도 by number over the whole country ((연속수치지형도)등고선_001.zip …),
    # not by 시·도: each 시·도 takes the pieces that reach its boundary.
    argv, calls, sizes, out = downloads
    raw = Path(argv[argv.index("--raw") + 1])
    for f in (raw / "부산").iterdir():
        f.unlink()
    a_zip(raw / "전국" / "(연속수치지형도)등고선_001.zip", shp_set("CONTOUR_001"))
    a_zip(raw / "전국" / "(연속수치지형도)등고선_002.zip", shp_set("CONTOUR_002"))
    far = {"_001": [128.8, 34.9, 129.4, 35.5], "_002": [126.8, 37.4, 127.2, 37.7]}  # the zip or its unpacked shapefile

    def box(shp=None, *, zpath=None):
        path = zpath or shp
        if path.name.startswith("AL_D010"):
            return [129.0, 35.0, 129.5, 35.4]
        return next(b for k, b in far.items() if k in path.name)

    monkeypatch.setattr(brp, "shp_box", box)
    monkeypatch.setattr(brp.landapi, "sido_boxes", lambda: {"26": [128.7, 34.8, 129.4, 35.4], "11": [126.7, 37.4, 127.2, 37.7]})
    seen = {}
    made = brp.run_script

    def run_script(script, args, log):
        if script == "build_terrain_pack.py" and "--contours" in args:
            name = args[args.index("--name") + 1]
            seen[name] = sorted(p.name for p in Path(args[args.index("--contours") + 1]).rglob("*.shp"))
        made(script, args, log)

    monkeypatch.setattr(brp, "run_script", run_script)
    monkeypatch.setattr(sys, "argv", [*argv, "--plan"])
    assert brp.main() == 0
    text = capsys.readouterr().out
    assert "(연속수치지형도)등고선_001.zip: contours → 부산광역시" in text
    assert "(연속수치지형도)등고선_002.zip: contours → 서울특별시" in text
    monkeypatch.setattr(sys, "argv", [*argv, "--no-ground"])
    assert brp.main() == 0
    assert seen == {"busan": ["N3L_F0010000_CONTOUR_001.shp"], "seoul": ["N3L_F0010000_CONTOUR_002.shp"]}
    assert (out / f"seoul-contours{terrain_pack.SUFFIX}").exists()  # a 시·도 with nothing but its pieces
    assert not (out / "region-work" / "전국").exists()  # unpacked once, gone when every 시·도 is done
    calls.clear()
    assert brp.main() == 0
    assert [s for s, _ in calls if s == "build_terrain_pack.py"] == []  # same downloads: nothing made again


def test_contours_and_areas_are_cut_to_the_시도_and_made_again_when_made_a_new_way(downloads, monkeypatch):
    argv, calls, sizes, out = downloads
    monkeypatch.setattr(sys, "argv", [*argv, "--no-ground"])
    assert brp.main() == 0
    sido = {next(a for a in args if a[2:] in sizes): args[args.index("--sido") + 1] if "--sido" in args else None
            for s, args in calls if s == "build_terrain_pack.py"}
    assert sido == {"--buildings": None, "--contours": "26", "--areas": "26"}
    # packs from before (no layout recorded, another format): contours and areas are made again,
    # and holding fewer lines once cut to the 시·도 does not count as a broken download
    state = json.loads((out / brp.STATE).read_text(encoding="utf-8"))
    for kind in ("buildings", "contours", "areas"):
        state["regions"]["busan"][kind].pop("layout", None)
    (out / brp.STATE).write_text(json.dumps(state), encoding="utf-8")
    sizes["contours"] = 2
    calls.clear()
    assert brp.main() == 0
    assert [next(a for a in args if a[2:] in sizes) for s, args in calls if s == "build_terrain_pack.py"] == [
        "--contours", "--areas"]
    assert brp.counts(out / f"busan-contours{terrain_pack.SUFFIX}", "contours")["contours"] == 2
    calls.clear()
    assert brp.main() == 0
    assert [s for s, _ in calls if s == "build_terrain_pack.py"] == []
