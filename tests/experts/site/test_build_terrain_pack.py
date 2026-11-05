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
