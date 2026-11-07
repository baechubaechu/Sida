"""Model bases for a site: the packs' ground stepped by a chosen interval, and its laser files."""

from __future__ import annotations

import io
import zipfile

import pytest

from sida.experts.site import model_base
from tests.experts.site.test_context3d import pack, plan_for_site  # noqa: F401  (pack is a fixture)


def around(*, pack_buildings: bool) -> dict:
    """The table's surroundings, as context3d.build gives them, with one building north of the site."""
    ring = [[-10, 50], [10, 50], [10, 66], [-10, 66]]
    return {
        "building_source": {"name": "GIS건물통합정보" if pack_buildings else "브이월드", "pack": "b" if pack_buildings else ""},
        "buildings": [{"outline": ring, "base": 1.7, "ground": 2.0, "height": 12.0, "height_source": "ledger"}],
        "unknown_buildings": [],
    }


@pytest.fixture(autouse=True)
def fresh_cache():
    model_base._cache.clear()


def test_the_ground_around_the_site_steps_by_the_chosen_interval(pack):  # noqa: F811
    one = model_base.stepped(plan_for_site(), 1.0, 100, folder=pack, around=around(pack_buildings=False))
    # the pack's contours at y = -150, -50, 50, 150 m are 10, 13, 17, 20 m: ±100 m is about 11.5–18.5 m
    assert [s["level"] for s in one["steps"]] == [11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0]
    assert one["datum"] == pytest.approx(15.0, abs=0.3)
    first = one["steps"][0]["polygons"][0]["outline"]
    assert min(x for x, _ in first) == pytest.approx(-100) and max(y for _, y in first) == pytest.approx(100)
    (b,) = one["buildings"]  # the screen may show VWorld's buildings
    assert b["top"] - b["bottom"] == pytest.approx(b["sheets"] * 1.0)
    half = model_base.stepped(plan_for_site(), 0.5, 100, folder=pack, around=around(pack_buildings=False))
    levels = [s["level"] for s in half["steps"]]  # the designer's interval, not a fixed one
    assert levels[:3] == [11.0, 11.5, 12.0] and levels[-1] == 18.0 and len(levels) == 15
    with pytest.raises(ValueError):
        model_base.stepped(plan_for_site(), 0.05, 100, folder=pack, around=around(pack_buildings=False))


def test_without_a_terrain_pack_there_is_no_stepped_ground(tmp_path):
    with pytest.raises(model_base.NoTerrain):
        model_base.stepped(plan_for_site(), 1.0, 100, folder=tmp_path, around=around(pack_buildings=False))


def test_laser_files_hold_pack_buildings_only(pack):  # noqa: F811
    data, summary = model_base.cut_files(plan_for_site(), radius=60, scale=1000, thickness_mm=2, sheet=(300, 200),
                                         folder=pack, around=around(pack_buildings=True))
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert {"assembly.svg", "pieces.csv", "sheet-1.svg", "sheet-1.dxf", "sheet-1-guide.svg"} <= set(names)
    assert summary["interval"] == pytest.approx(2.0) and summary["buildings"] == 1
    assert summary["size_mm"] == [120.0, 120.0] and not summary["buildings_left_out"]
    csv = zipfile.ZipFile(io.BytesIO(data)).read("pieces.csv").decode("utf-8-sig")
    assert "B01.1" in csv
    _, live = model_base.cut_files(plan_for_site(), radius=60, scale=1000, thickness_mm=2, sheet=(300, 200),
                                   folder=pack, around=around(pack_buildings=False))
    assert live["buildings"] == 0 and live["buildings_left_out"]  # VWorld's live outlines are not written down


def test_a_round_range_makes_a_round_model(pack):  # noqa: F811
    import math

    round_view = model_base.stepped(plan_for_site(), 1.0, 100, folder=pack, around=around(pack_buildings=False), shape="circle")
    assert round_view["shape"] == "circle"
    for step in round_view["steps"]:
        for poly in step["polygons"]:
            assert all(math.hypot(x, y) <= 100.5 for x, y in poly["outline"])  # cut to the circle
    first = round_view["steps"][0]["polygons"][0]["outline"]
    assert max(math.hypot(x, y) for x, y in first) == pytest.approx(100, abs=0.5)  # and reaching it
    square_view = model_base.stepped(plan_for_site(), 1.0, 100, folder=pack, around=around(pack_buildings=False))
    assert square_view["shape"] == "square" and max(abs(x) for x, _ in square_view["steps"][0]["polygons"][0]["outline"]) == pytest.approx(100)
    _, summary = model_base.cut_files(plan_for_site(), radius=60, scale=1000, thickness_mm=2, sheet=(300, 200),
                                      folder=pack, around=around(pack_buildings=True), shape="circle")
    assert summary["shape"] == "circle" and summary["radius"] == 60 and summary["size"] is None
    with pytest.raises(ValueError):
        model_base.stepped(plan_for_site(), 1.0, 100, folder=pack, around=around(pack_buildings=False), shape="hexagon")


def test_a_rectangle_range_makes_an_oblong_model(pack):  # noqa: F811
    view = model_base.stepped(plan_for_site(), 1.0, 90, folder=pack, around=around(pack_buildings=False),
                              shape="rect", orient="portrait")
    assert (view["shape"], view["orient"]) == ("rect", "portrait")
    outline = [p for poly in view["steps"][0]["polygons"] for p in poly["outline"]]
    assert max(abs(x) for x, _ in outline) == pytest.approx(60, abs=0.5)  # 2/3 of 90 m east–west
    assert max(abs(y) for _, y in outline) == pytest.approx(90, abs=0.5)
    _, summary = model_base.cut_files(plan_for_site(), radius=60, scale=1000, thickness_mm=2, sheet=(300, 200),
                                      folder=pack, around=around(pack_buildings=True), shape="rect")
    assert (summary["shape"], summary["orient"]) == ("rect", "landscape")
    assert summary["size_mm"] == [120.0, 80.0]
