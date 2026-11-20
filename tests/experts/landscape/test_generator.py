"""generator.py — the three landscape layouts drawn by rule in a region of a small synthetic site."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from sida.experts.landscape import generator as g

LOT = box(0, 0, 36, 44)  # 1,584 ㎡, a 12 m road on the south and an 8 m one on the east
BUILDING = box(3, 12, 31, 37)  # 32 m high: its winter shade falls on the north yard
ROADS = [{"line": LineString([(0, 0), (36, 0)]), "width": 12.0}, {"line": LineString([(36, 0), (36, 44)]), "width": 8.0}]


def inputs(**kw):
    base = {"region": LOT.difference(BUILDING), "lot": LOT, "buildings": [(BUILDING, 32.0)], "roads": ROADS,
            "latitude": 37.57, "open_space_m2": 158.4, "open_space_width": 9.0, "trees_needed": 24, "seed": 1}
    return g.Inputs(**{**base, **kw})


def shape(rings):
    return unary_union([Polygon(r["outer"], r["holes"]) for r in rings]) if rings else Polygon()


@pytest.fixture(scope="module")
def made():
    return {style: g.generate(inputs(), style) for style in g.STYLES}


def test_every_style_stays_in_the_region_and_off_the_building(made):
    region = LOT.difference(BUILDING)
    for style, plan in made.items():
        ground = unary_union([shape(plan["zones"][k]) for k in g.KINDS])
        assert ground.difference(region.buffer(0.1)).area < 0.5, style
        assert ground.area == pytest.approx(region.area, rel=0.02), style  # the whole yard is given a use
        for t in plan["trees"]:
            trunk = Point(t["x"], t["y"])
            assert region.buffer(0.01).contains(trunk) and trunk.distance(BUILDING) >= g.TREE_OFF_BUILDING - 0.01, style
        assert plan["planting_m2"] == pytest.approx(plan["areas"]["lawn"] + plan["areas"]["shade"] + plan["areas"]["hedge"]
                                                    + sum(t["kind"] == "planter" for t in plan["trees"]) * g.PLANTER ** 2, abs=0.2)


def test_the_paths_run_from_the_door_to_the_widest_road(made):
    for style, plan in made.items():
        door = Point(plan["doors"][0])
        assert door.y == pytest.approx(12.0, abs=0.5), style  # the south wall faces the 12 m road
        ends = [Point(p["line"][-1]) for p in plan["paths"]] + [Point(p["line"][0]) for p in plan["paths"]]
        assert min(e.distance(ROADS[0]["line"]) for e in ends) < 0.5, style


def test_the_styles_differ_as_their_names_say(made):
    formal, natural, plaza = made["formal"], made["natural"], made["plaza"]
    # the plaza style opens the road side; the others keep more to plant
    assert plaza["plaza_m2"] > formal["plaza_m2"] and plaza["planting_m2"] < natural["planting_m2"]
    assert any(t["kind"] == "planter" for t in plaza["trees"])
    # every one keeps the 공개 공지 asked, the formal and plaza ones at its 9 m width
    assert all(p["plaza_m2"] >= 158.4 for p in made.values())
    assert formal["plaza_width_ok"] and plaza["plaza_width_ok"]
    # the north yard lies in the building's winter shade: 음지 지피, and shade trees there
    assert natural["areas"]["shade"] > 50 and any(t["kind"] == "shade" for t in natural["trees"])
    # the trees asked are met where the room is (the plaza style plants fewer: it is paved)
    assert formal["trees_in_lot"] >= 24 and natural["trees_in_lot"] >= 20 and plaza["trees_in_lot"] >= 15


def test_the_seed_shuffles_and_a_drawn_region_is_kept_to():
    one = g.generate(inputs(), "natural")
    assert g.generate(inputs(), "natural")["trees"] == one["trees"]  # the same seed, the same plan
    assert g.generate(inputs(seed=7), "natural")["trees"] != one["trees"]
    corner = box(0, 37, 36, 44)  # only the north yard
    small = g.generate(inputs(region=corner, open_space_m2=None, open_space_width=None), "formal")
    ground = unary_union([shape(small["zones"][k]) for k in g.KINDS])
    assert ground.difference(corner.buffer(0.1)).area < 0.5
    assert all(corner.buffer(0.01).contains(Point(t["x"], t["y"])) for t in small["trees"])


def test_the_knobs_change_only_what_they_name(made):
    base = made["formal"]
    assert base["tune"] == g.Tune().as_dict()
    wide = g.generate(inputs(), "formal", g.Tune(plaza="wide"))
    assert wide["plaza_m2"] > base["plaza_m2"] + 10
    small = g.generate(inputs(), "formal", g.Tune(plaza="small"))
    assert small["plaza_m2"] <= base["plaza_m2"]
    assert small["plaza_m2"] >= 158.4 - 1  # never below the 공개 공지 the rules ask
    few = {t: g.generate(inputs(trees_needed=10), "formal", g.Tune(trees=t))["trees_in_lot"] for t in g.TREE_COUNTS}
    assert few == {"law": 10, "more": 13, "most": 15, "room": few["room"]} and few["room"] > 20  # ⌈10 × 1.25⌉, × 1.5, as many as fit
    assert g.generate(inputs(), "formal", g.Tune(trees="most"))["trees_in_lot"] <= few["room"]  # never past what fits
    bare = g.generate(inputs(), "formal", g.Tune(hedge=0))
    assert base["areas"]["hedge"] > 0 and bare["areas"]["hedge"] == 0
    thick = g.generate(inputs(), "formal", g.Tune(hedge=3.0))
    assert thick["areas"]["hedge"] > base["areas"]["hedge"]
    broad = g.generate(inputs(), "formal", g.Tune(path=3.5))
    assert {p["width"] for p in broad["paths"]} == {3.5}
    assert broad["areas"]["path"] > base["areas"]["path"]
    assert broad["tune"] == {"plaza": "normal", "trees": "law", "path": 3.5, "hedge": None}


def test_the_knobs_are_read_from_what_the_api_holds():
    assert g.Tune.read(None) == g.Tune() == g.Tune.read({})
    assert g.Tune.read({"plaza": "widest", "trees": "more", "path": 2, "hedge": 0}) == g.Tune("widest", "more", 2.0, 0.0)
    for bad, key in (({"plaza": "huge"}, "plaza"), ({"trees": 3}, "trees"), ({"path": 1.0}, "path"), ({"path": True}, "path"),
                     ({"hedge": 0.5}, "hedge"), ({"hedge": 4}, "hedge"), ({"colour": "red"}, "tune"), ("wide", "tune")):
        with pytest.raises(ValueError, match=key):
            g.Tune.read(bad)
    assert g.Tune().words() == []
    assert g.Tune("wide", "most", 2.0, 0.0).words() == ["광장 넓게", "나무 50% 더", "길 2.0m", "관목 띠 없음"]
