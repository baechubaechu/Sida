"""Site analysis diagrams (site_diagrams.py): what they draw from, the sun, and each kind."""

from __future__ import annotations

import datetime as dt
import io
import math
import zipfile

import numpy as np
import pytest

from sida.experts.site import site_diagrams as sd
from sida.experts.site import site_sheet

SEOUL = (126.978, 37.5665)


def _square(x0, y0, side):
    return [[x0, y0], [x0 + side, y0], [x0 + side, y0 + side], [x0, y0 + side]]


def _around(**changes) -> dict:
    around = {
        "radius": 150.0, "shape": "square", "orient": "landscape", "origin": {"lon": SEOUL[0], "lat": SEOUL[1]},
        "ground_elev": 30.0,
        "building_source": {"pack": "seoul-buildings", "name": "GIS건물통합정보"},
        "terrain_sources": [{"name": "수치지형도 1:5,000"}],
        "buildings": [
            {"outline": _square(30, 30, 10), "height": 20.0, "height_source": "ledger", "use": "업무시설", "on_site": False},
            {"outline": _square(-60, 20, 12), "height": 9.9, "height_source": "map_estimate", "use": "공동주택", "on_site": False},
            {"outline": _square(-5, -5, 8), "height": 6.0, "height_source": "ledger", "use": "제2종근린생활시설", "on_site": True},
            # VWorld's outline: for the screen only
            {"outline": _square(60, -60, 10), "height": 30.0, "height_source": "file", "use": "", "display_only": True},
            # VWorld's floors without a map fallback: no height in a file
            {"outline": _square(-90, -90, 10), "height": 12.0, "height_source": "api_estimate", "use": ""},
            # VWorld's floors with the 1:5,000 map's to fall back on
            {"outline": _square(90, 90, 10), "height": 12.0, "height_source": "api_estimate", "use": "공장",
             "offline": {"height": 6.6, "source": "map_estimate", "floors": 2}},
        ],
        "unknown_buildings": [{"outline": _square(100, -20, 6), "base": 0.0, "ground_line": [], "name": ""}],
        "areas": [
            {"kind": "road", "ring": [[-150, -40], [150, -40], [150, -20], [-150, -20]]},
            {"kind": "sidewalk", "ring": [[-150, -20], [150, -20], [150, -16], [-150, -16]]},
            {"kind": "water", "ring": [[-150, 100], [150, 100], [150, 110], [-150, 110]]},
        ],
        "trees": {"points": [[0.0, -18.0, 0.0], [8.0, -18.0, 0.0], [400.0, 0.0, 0.0]], "crown": 5.2, "rule": "인도 규칙"},
        "road_marks": {"lines": [{"color": "yellow", "width": 0.15, "pieces": [[[-150, -30, 0], [150, -30, 0]]]}], "marks": []},
        "terrain": None,
        "contours": [],
    }
    return {**around, **changes}


def _mats(**changes) -> dict:
    plan = {"origin": {"lon": SEOUL[0], "lat": SEOUL[1]}, "parcels": [{"rings": [_square(-10, -10, 20)]}]}
    return {"around": _around(**changes), "plan": plan}


def _plane(slope_pct: float, half: float = 150.0, step: float = 4.0) -> dict:
    n = int(2 * half / step) + 1
    z = [slope_pct / 100 * (-half + i * step) for i in range(n) for _j in range(n)]  # rising to the north
    return {"min": -half, "step": step, "n": n, "z": z, "classes": ""}


def test_buildings_are_only_what_a_file_may_hold():
    known, unknown = sd.buildings(_around())
    outlines = [b["outline"][0] for b in known]
    assert [60, -60] not in outlines  # VWorld's outline is left out
    assert [90, 90] in outlines and next(b for b in known if b["outline"][0] == [90, 90])["height"] == 6.6
    assert next(b for b in known if b["outline"][0] == [-60, 20])["estimate"] is True
    assert next(b for b in known if b["outline"][0] == [30, 30])["estimate"] is False
    # VWorld's floors without a fallback, and the buildings without any height: outlines only
    assert sorted(b["outline"][0] for b in unknown) == [[-90, -90], [100, -20]]
    # buildings that did not come from the packs are not drawn at all
    assert sd.buildings(_around(building_source={"pack": "", "name": "브이월드"})) == ([], [])


def test_use_groups_follow_the_words_of_the_main_use():
    assert sd.use_group("공동주택")[0] == "주거"
    assert sd.use_group("제1종근린생활시설")[0] == "근린생활"
    assert sd.use_group("업무시설")[0] == "업무"
    assert sd.use_group("교육연구시설")[0] == "공공·교육·문화"
    assert sd.use_group("공장") == sd.USE_OTHER
    assert sd.use_group("") == sd.USE_UNKNOWN


def test_the_sun_stands_where_the_almanac_puts_it():
    lon, lat = SEOUL

    def noon(year, month, day):  # the highest the sun gets that day, and its bearing then
        return max((sd.sun_position(dt.datetime(year, month, day, 11, tzinfo=sd.KST) + dt.timedelta(minutes=m), lon, lat)
                    for m in range(0, 180)), key=lambda s: s[0])

    winter, equinox, summer = noon(2026, 12, 22), noon(2026, 3, 20), noon(2026, 6, 21)
    assert winter[0] == pytest.approx(90 - lat - 23.44, abs=0.2)
    assert equinox[0] == pytest.approx(90 - lat, abs=0.5)
    assert summer[0] == pytest.approx(90 - lat + 23.44, abs=0.2)
    assert winter[1] == pytest.approx(180, abs=1.0)
    alt, az = sd.sun_position(dt.datetime(2026, 12, 22, 9, tzinfo=sd.KST), lon, lat)
    assert 9 < alt < 14 and 125 < az < 140  # a low morning sun in the south-east
    assert [sd.winter_solstice(y).isoformat() for y in (2024, 2025, 2026)] == ["2024-12-21", "2025-12-22", "2026-12-22"]


def test_a_shadow_reaches_as_far_as_the_height_and_the_sun_say():
    alt, az = 30.0, 180.0  # the sun due south: the shadow falls due north
    shade = sd._shadow(_square(0, 0, 10), 10.0, alt, az)
    x0, y0, x1, y1 = shade.bounds
    assert (x0, y0, x1) == pytest.approx((0, 0, 10))
    assert y1 == pytest.approx(10 + 10 / math.tan(math.radians(alt)))


def _layer(drawing, name):
    return next(layer for layer in drawing["layers"] if layer.get("name") == name)


def _points(layers):
    return [p for layer in layers for p in ([q for poly in layer["polygons"] for ring in poly for q in ring]
                                             if layer["type"] == "fill" else [q for run in layer["lines"] for q in run])
            if layer["type"] != "text"]


def _legend(drawing):
    return {entry["label"]: entry for entry in drawing["legend"]}


def test_every_kind_draws_on_one_sheet():
    mats = _mats(terrain=_plane(7.0))
    for number, kind in enumerate(sd.KINDS, start=1):
        drawing = sd.drawing(kind, mats, year=2026)
        assert drawing["kind"] == kind and drawing["title"] == sd.KINDS[kind] and drawing["number"] == f"{number:02d}"
        assert drawing["layers"] and drawing["legend"] and drawing["footer"]
        svg = site_sheet.to_svg(drawing).decode()
        assert svg.startswith("<svg") and f">{sd.KINDS[kind]}</text>" in svg and 'id="hatch"' in svg
    assert sd.drawing("heights", mats)["subtitle"] == "기본 · 1000 m 정사각 · 건물: GIS건물통합정보"
    assert sd.drawing("heights", mats, "large")["subtitle"].startswith("넓게 · 2000 m 정사각")


def test_every_ready_diagram_goes_into_one_zip_at_its_kept_choice():
    mats = _mats()  # no terrain: that one is left out
    assert site_sheet.label("shadow", mats, {"range": "small", "hour": 12}) == "그림자 · 동지 12시 (좁게 150m)"
    assert site_sheet.label("heights", mats, {}) == "건물 높이 (기본 1000m)"
    assert site_sheet.label("sun_path", mats, {"range": "large"}) == "태양 궤적"
    data, names = site_sheet.bundle(mats, {"shadow": {"range": "small", "hour": 12}}, year=2026)
    assert names[2:] == ["03 건물 높이 (기본 1000m).svg", "04 건물 용도 (기본 1000m).svg", "05 도로·보행 (기본 1000m).svg",
                         "06 물·나무 (기본 1000m).svg", "08 그림자 · 동지 12시 (좁게 150m).svg", "09 태양 궤적.svg",
                         "10 거리 반경 (기본 1000m).svg"]
    assert not any(name.startswith("07 ") for name in names)  # 지형: no ground here
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == names
        assert archive.read(names[0]).startswith(b"<svg")


def test_each_kind_has_its_own_range_and_a_step_either_side(monkeypatch):
    assert [sd.reach("shadow", scope) for scope in sd.RANGES] == [75.0, 100.0, 150.0]
    assert [sd.reach(kind, "default") for kind in sd.KINDS if kind not in ("shadow", "sun_path")] == [500.0] * 8  # 1 km across
    assert [sd.reach("figure_ground", scope) for scope in sd.RANGES] == [400.0, 500.0, 1000.0]  # 800 m to 2 km
    monkeypatch.setitem(sd.SCALE, "heights", sd.GATHER)
    assert sd.reach("heights", "large") == sd.GATHER  # no wider than the ground read: only outlines go past it
    monkeypatch.setitem(sd.SCALE, "heights", sd.SCALES[0])
    assert sd.reach("heights", "small") == sd.SCALES[0]
    with pytest.raises(ValueError):
        sd.reach("heights", "wide")
    sizes = sd.ranges(_around(orient="landscape", shape="rect"), "shadow")
    assert sizes["default"]["side"] == 200 and sizes["default"]["words"].endswith("m 직사각")
    assert sd.ranges(_around(shape="circle"), "terrain")["small"] == {"side": 800, "words": "지름 800 m 원"}
    assert sd.reach("uses", "default", 120.0) == 100.0  # a base between steps takes the nearest
    assert sd.ranges(_around(), "sun_path") == {}


def test_a_small_range_is_cut_to_its_square(monkeypatch):
    monkeypatch.setitem(sd.SCALE, "figure_ground", 100.0)  # small 75 m, large 150 m
    mats = _mats()
    near = sd.drawing("figure_ground", mats, "small")
    points = _points(near["layers"])
    assert points and all(-75 <= x <= 75 and -75 <= y <= 75 for x, y in points)
    wide = sd.drawing("figure_ground", mats, "large")
    assert near["frame"] == [-75, -75, 75, 75] and wide["frame"] == [-150, -150, 150, 150]
    # the figures count what is shown; the site's own old building lies under the site
    assert _legend(near)["건물"]["note"] == "2동" and _legend(wide)["건물"]["note"] == "5동"
    built = float(_legend(near)["건폐 비율 (범위 안)"]["note"].rstrip("%"))
    assert built == pytest.approx((100 + 144) / 150 ** 2 * 100, abs=0.1)  # the two buildings' footprints


def test_a_circle_range_is_cut_to_its_circle(monkeypatch):
    monkeypatch.setitem(sd.SCALE, "streets", 200.0)  # small: 150 m, the edge of the test's streets
    mats = _mats(shape="circle")
    for scope, radius in (("small", 150.0),):
        drawing = sd.drawing("streets", mats, scope)
        assert drawing["shape"] == "circle"
        points = _points(drawing["layers"])
        assert points and max(math.hypot(x, y) for x, y in points) == pytest.approx(radius, abs=0.05)
    assert sd.frame(mats["around"], "streets", "default") == (-200, -200, 200, 200)
    assert "지름 1000 m 원" in sd.drawing("heights", mats)["subtitle"]
    assert b"<circle" in site_sheet.to_svg(sd.drawing("heights", mats))


def test_the_site_lies_over_the_drawing():
    drawing = sd.drawing("heights", _mats())
    site = drawing["layers"][-1]
    assert site["name"] == "site" and site["color"] == sd.LOT and site["stroke"] == sd.LOT
    assert site["polygons"] == [[[[-10, -10], [10, -10], [10, 10], [-10, 10]]]]
    assert "대지" in _legend(drawing)
    assert sd.drawing("sun_path", _mats())["shape"] == "none"  # no map, no site


def test_the_figure_ground_and_nollis(monkeypatch):
    monkeypatch.setitem(sd.SCALE, "figure_nolli", 200.0)
    alone = sd.drawing("figure_ground", _mats())
    assert [layer["name"] for layer in alone["layers"]] == ["buildings", "site"] and alone["layers"][0]["color"] == sd.INK
    nolli = sd.drawing("figure_nolli", _mats())  # ±200 m: 160,000 m²
    assert [layer["name"] for layer in nolli["layers"]] == ["held", "buildings", "site"]
    assert nolli["layers"][0]["color"] == sd.YARD and nolli["layers"][1]["color"] == sd.INK
    legend = _legend(nolli)
    # the road, sidewalk and water faces (6,000 + 1,200 + 3,000 m²) less the 24 m² of a building on the sidewalk
    assert legend["길·광장 (모두가 다니는 빈 땅)"]["note"] == f"{10176 / 160000 * 100:.1f}%"
    # the rest less five buildings (100 + 144 + 100 + 100 + 36 m²)
    assert legend["가구 안 빈 땅 (마당·주차·빈터)"]["note"] == f"{(160000 - 10176 - 480) / 160000 * 100:.1f}%"
    assert legend["건물"]["note"] == "5동 · 0.3%"
    with pytest.raises(ValueError):  # without the map's street faces all open ground would read as held
        sd.drawing("figure_nolli", _mats(areas=[]))


def test_plans_of_buildings_lie_on_the_streets():
    for kind in ("heights", "uses", "distance"):
        drawing = sd.drawing(kind, _mats(), "large", year=2026)  # out to the water at 100 m
        assert [layer["name"] for layer in drawing["layers"][:3]] == ["road", "sidewalk", "water"]
        assert {"도로", "인도", "수계"} <= set(_legend(drawing)) or kind == "distance"


def test_heights_count_each_band_and_hatch_what_is_not_known():
    drawing = sd.drawing("heights", _mats())
    legend = _legend(drawing)
    assert legend["12 m 미만"]["note"] == "2동 · 40%" and legend["12~30 m"]["note"] == "1동 · 20%"
    assert _layer(drawing, "12 m 미만 (추정)")["opacity"] < 1  # floors × a storey height is drawn lighter
    unknown = _layer(drawing, "높이 미확인")
    assert unknown["color"] == sd.HATCH and len(unknown["polygons"]) == 2 and legend["높이 미확인"]["note"] == "2동 · 40%"
    assert any("가장 높은 건물 20.0 m" in line for line in drawing["footer"])
    svg = site_sheet.to_svg(drawing).decode()
    assert 'fill="url(#hatch)"' in svg and "2동 · 40%" in svg


def test_a_class_of_buildings_is_one_union():
    first = [[0, 0], [10, 0], [10, 10], [0, 10]]
    layer = sd._fill([[first], [first[::-1]], [_square(20, 0, 5), [[21, 1], [22, 1], [22, 2], [21, 2]]]], sd.INK)
    turns = [sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1], strict=True))
             for poly in layer["polygons"] for ring in poly]
    assert turns[0] > 0 and turns[1] > 0 and turns[2] > 0 and turns[3] < 0  # outsides one way, holes the other
    assert site_sheet.to_svg({"kind": "x", "title": "x", "frame": [-1, -1, 1, 1], "shape": "box",
                              "layers": [layer]}).count(b"<path") == 2  # one path for the class (and north)


def test_the_shadow_counts_the_hours_in_shade_in_three_bands():
    mats = _mats()
    every = sd.drawing("shadow", mats, year=2026)
    names = [layer.get("name", "") for layer in every["layers"]]
    assert "road" not in names  # the hours map lies on white ground
    bands = [layer for layer in every["layers"] if layer.get("name") in {label for *_r, label in sd.SHADE_BANDS}]
    assert bands and [layer["color"] for layer in bands] == [color for _a, _b, color, label in sd.SHADE_BANDS
                                                             if label in {layer["name"] for layer in bands}]
    assert every["footer"][0].startswith("동지 2026-12-22 9~15시")
    assert sum("대지 그늘" in line for line in every["footer"]) == len(sd.SHADOW_HOURS)
    assert all(_legend(every)[label]["note"].startswith("대지 ") for *_r, label in sd.SHADE_BANDS)
    assert sum(name.startswith("해 ") for name in names) == len(sd.SHADOW_HOURS)  # the sun's place at each hour
    assert any("그림자를 그리지 않았습니다" in note for note in every["notes"])
    assert _layer(every, "no height")["dashed"]
    one = sd.drawing("shadow", mats, hour=12, year=2026)
    assert [layer.get("name") for layer in one["layers"][:2]] == ["road", "sidewalk"]  # one hour lies on the streets
    assert {layer["opacity"] for layer in one["layers"] if layer.get("color") == sd.SHADE} == {0.4}
    svg = site_sheet.to_svg(one).decode()
    assert 'fill-opacity="0.4"' in svg and '>12</text>' in svg


def test_the_hours_in_shade_are_counted_where_shadows_overlap():
    from shapely.geometry import box

    counted = dict(sd._shade_hours([box(0, 0, 2, 1), box(1, 0, 3, 1), box(1, 0, 2, 1)]))
    assert {count: round(ground.area, 6) for count, ground in counted.items()} == {1: 2.0, 3: 1.0}


def test_terrain_bands_the_slope():
    drawing = sd.drawing("terrain", _mats(terrain=_plane(7.0)))
    colours = {layer["color"] for layer in drawing["layers"] if layer["type"] == "fill"}
    assert sd.SLOPE_BANDS[1][2] in colours  # a 7% plane is all 5~10%
    assert sd.SLOPE_BANDS[0][2] not in colours and sd.SLOPE_BANDS[3][2] not in colours
    assert any(layer["type"] == "text" and layer["text"] == "대지 30.0 m" for layer in drawing["layers"])


def test_what_cannot_be_drawn_says_why():
    mats = _mats(building_source={"pack": ""}, areas=[], trees=None)
    ready = {a["kind"]: a for a in sd.available(mats["around"])}
    assert not ready["figure_ground"]["ready"] and not ready["shadow"]["ready"] and not ready["terrain"]["ready"]
    assert ready["sun_path"]["ready"] and ready["distance"]["ready"]
    with pytest.raises(ValueError, match="GIS건물통합정보"):
        sd.drawing("shadow", mats)
    with pytest.raises(ValueError):
        sd.drawing("nope", _mats())
    with pytest.raises(ValueError):
        sd.drawing("heights", _mats(), "middle")
    with pytest.raises(ValueError):
        sd.drawing("shadow", _mats(), hour=17)


def test_choices_are_kept_beside_the_range(tmp_path):
    assert sd.choices(tmp_path)["shadow"] == {"range": "default", "hour": None}
    assert sd.save_choice(tmp_path, "shadow", "small", 10) == {"range": "small", "hour": 10}
    assert sd.save_choice(tmp_path, "heights", "large", 10) == {"range": "large", "hour": None}  # only the shadow has hours
    assert sd.choices(tmp_path)["shadow"] == {"range": "small", "hour": 10}
    for bad in (("nope", "default", None), ("shadow", "wide", None), ("shadow", "default", 20), ("shadow", "default", True)):
        with pytest.raises(ValueError):
            sd.save_choice(tmp_path, *bad)



def test_the_surroundings_are_read_from_the_packs_alone(monkeypatch):
    from sida.experts.site import context3d

    frame = context3d.Frame({"lon": SEOUL[0], "lat": SEOUL[1]})

    def lonlat(ring):
        return [[SEOUL[0] + x / frame.east, SEOUL[1] + y / frame.north] for x, y in ring]

    asked = []

    def fake_ground(fr, radius, **kw):
        asked.append((radius, kw["shape"]))
        return {
            "grid": None, "half": radius, "step": 4.0, "ground_elev": None, "contours": [],
            "sources": [{"kind": "buildings", "name": "seoul-buildings", "source": "GIS건물통합정보"},
                        {"kind": "areas", "name": "seoul-areas", "source": "수치지형도 1:5,000"}],
            "areas": [("road", np.asarray([[-150, -40], [150, -40], [150, -20], [-150, -20]], dtype=float))],
            "buildings": [
                {"ring": lonlat(_square(30, 30, 10)), "use": "업무시설", "height": 20.0, "floors": 5},
                {"ring": lonlat(_square(-60, 20, 12)), "use": "공동주택", "height": 0, "floors": 3},
                {"ring": lonlat(_square(-5, -5, 8)), "use": "", "height": 0, "floors": 0},  # on the site, no height
                {"ring": lonlat(_square(1200, 0, 10)), "use": "", "height": 9.0, "floors": 3},  # beyond the reach
            ],
            "map_buildings": [], "paint": {"lines": [], "marks": []}, "from_tiles": False,
        }

    monkeypatch.setattr(context3d, "ground", fake_ground)
    monkeypatch.setattr(sd, "_gathered", {})
    plan = {"origin": {"lon": SEOUL[0], "lat": SEOUL[1]}, "parcels": [{"rings": [_square(-10, -10, 20)]}]}
    around = sd.gather(plan, shape="circle", orient="landscape")
    assert asked == [(sd.GATHER, "square")]  # once, out to the widest range
    assert around["shape"] == "circle" and around["building_source"] == {"name": "GIS건물통합정보", "pack": "seoul-buildings"}
    office, flats = around["buildings"]
    assert (office["height"], office["height_source"]) == (20.0, "file")
    assert flats["height_source"] == "estimate" and flats["height"] == pytest.approx(3 * context3d.storey_height("공동주택"))
    assert [b["on_site"] for b in around["unknown_buildings"]] == [True]
    known, _unknown = sd.buildings(around)
    assert [b["estimate"] for b in known] == [False, True]
    assert sd.gather(plan, shape="square")["shape"] == "square" and len(asked) == 1  # kept a while
    with pytest.raises(ValueError):
        sd.gather({"parcels": []})


def test_the_shadow_range_holds_every_building_that_shades_the_site():
    plan = _mats()["plan"]  # the lot: ±10 m
    tower = {"outline": _square(106, -105, 10), "height": 60.0, "height_source": "file", "use": "", "on_site": False}
    low = {**tower, "height": 5.0}
    # 150 m south-east, where the 9 o'clock sun stands: a 60 m tower's winter shadow (about 5 × its
    # height then) reaches the lot, a 5 m house's does not
    assert sd.shadow_reach(_around(buildings=[tower]), plan, year=2026) == 200.0
    assert sd.shadow_reach(_around(buildings=[low]), plan, year=2026) == sd.SCALE["shadow"]
    far = {**tower, "outline": _square(513, -474, 10), "height": 300.0}
    assert sd.shadow_reach(_around(buildings=[far]), plan, year=2026) == sd.SHADOW_FIT[1]  # kept within its bounds
    sizes = sd.ranges(_around(buildings=[tower]), "shadow", plan)
    assert [sizes[scope]["side"] for scope in sd.RANGES] == [300, 400, 600]
    drawing = sd.drawing("shadow", _mats(buildings=[tower]), year=2026)
    assert drawing["frame"] == [-200, -200, 200, 200] and "그림자가 닿는 건물" in drawing["footer"][-1]
