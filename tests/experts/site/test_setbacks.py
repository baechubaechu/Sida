"""setbacks.py — 건축선, 대지 안의 공지 and 공동주택 채광 of the 법규 볼륨, from data/envelope_rules.yaml.
Lots and the parcels around them are drawn here in the table's metres (x east, y north)."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import Polygon

from sida.experts.site import envelope, setbacks, site_facts

LOT = [[0, 0], [20, 0], [20, 30], [0, 30]]  # 600 ㎡, long side north–south
PLAN = {"parcels": [{"pnu": "1", "rings": [LOT]}], "frame": {"x": 0.0, "y": 0.0, "angle": 0.0},
        "bounds": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 30}, "origin": {"lon": 127.0, "lat": 37.5}}


def parcel(pnu, mark, x0, y0, x1, y1):
    return {"pnu": pnu, "mark": mark, "rings": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]}


SOUTH_ROAD = parcel("r1", "도", -40, -3, 60, 0)  # 3 m wide
WEST_ROAD = parcel("r2", "도", -6, 0, 0, 60)  # 6 m wide
EAST_LOT = parcel("n1", "대", 20, 0, 40, 30)
NORTH_LOT = parcel("n2", "대", 0, 30, 20, 50)
EAST_PARK = parcel("p1", "공", 20, 0, 30, 30)  # 10 m wide
WEST_LOT = parcel("n3", "대", -20, 0, 0, 30)


def facts(zone="제2종일반주거지역", municipality="서울특별시 중구"):
    limits = site_facts.load_limits()["zones"][zone]
    return {"summary": {"zoning": [{"zone": zone, "pnus": ["1"], "area_m2": 600.0, **limits}], "districts": [],
                        "total_area_m2": 600.0, "area_complete": True, "municipality": municipality, "parcel_count": 1},
            "parcels": [{"pnu": "1"}]}


def compute(parcels, *, zone="제2종일반주거지역", municipality="서울특별시 중구", **kw):
    f = facts(zone, municipality)
    rule = {**envelope.sunlight_rule(f), "applies": False}  # 정북일조 left out: these tests look at the rest
    return envelope.compute(PLAN, f, rule, parcels, lambda pnu: None, floor_height=3.0, **kw)


def grid_h(out):
    return np.array([[np.nan if v is None else (np.inf if v == -1 else v) for v in row] for row in out["grid"]["h"]], dtype=float)


def at(out, x, y):
    g = out["grid"]
    return grid_h(out)[int((y - g["v0"]) // g["step"]), int((x - g["u0"]) // g["step"])]


def lines(out):
    return {x["id"]: x for x in out["lines"]}


@pytest.mark.parametrize(("municipality", "zone", "use", "area", "road", "neighbour", "status"), [
    ("서울특별시 중구", "제2종일반주거지역", "apartment", 0, 3, 3, "read"),  # 서울 [별표 4] 마·라
    ("서울특별시 중구", "제2종일반주거지역", "apartment_city", 0, 2, 2, "read"),
    ("서울특별시 중구", "제2종일반주거지역", "multiplex", 0, 1, 1, "read"),
    ("서울특별시 중구", "제2종일반주거지역", "other", 0, 0, 0, "read"),  # a use the table does not name: none
    ("서울특별시 종로구", "제1종전용주거지역", "other", 0, 0, 1, "read"),  # 전용주거지역 인접 1 m
    ("서울특별시 중구", "준공업지역", "factory", 600, 1.5, 1, "read"),
    ("서울특별시 중구", "일반공업지역", "factory", 600, 0, 0, "read"),  # 일반공업지역 left out
    ("서울특별시 중구", "일반상업지역", "sales", 1500, 3, 0, "read"),  # 인접: 상업지역 left out
    ("서울특별시 중구", "제2종일반주거지역", "sales", 800, 0, 1, "read"),  # under 1,000 ㎡
    ("부산광역시 해운대구", "제2종일반주거지역", "apartment", 0, 2, 2, "check"),  # no ordinance table: the statute's least
])
def test_the_open_space_is_the_first_row_of_the_table_that_fits(municipality, zone, use, area, road, neighbour, status):
    got = setbacks.open_space(municipality, zone, use, area)
    assert (got["road"]["m"], got["neighbour"]["m"], got["status"]) == (road, neighbour, status)
    if got["road"]["m"]:
        assert got["road"]["text"]  # the 원문 row comes along


def test_the_lots_edges_are_told_apart_by_the_parcels_beyond_them():
    found = setbacks.edges(Polygon(LOT), [SOUTH_ROAD, EAST_PARK, NORTH_LOT])
    kinds = [(r["kind"], r["width"]) for r in found["runs"]]
    assert ("road", 3.0) in kinds and ("open", 10.0) in kinds and ("neighbour", None) in kinds
    assert ("unknown", None) in kinds  # the west side: nothing in the map
    assert sum(r["length"] for r in found["runs"]) == pytest.approx(100, abs=0.1)
    assert sorted(c["angle"] for c in found["corners"]) == [90.0] * 4


def test_a_road_under_4m_moves_the_building_line_and_a_corner_of_narrow_roads_is_cut():
    lot = Polygon(LOT)
    narrow = setbacks.building_line(lot, setbacks.edges(lot, [SOUTH_ROAD]))
    assert list(narrow["setbacks"].values()) == [0.5]  # (4 - 3) / 2 from the road's edge (법 제46조①)
    assert narrow["removed"].area == pytest.approx(20 * 0.5, abs=0.2)
    corner = setbacks.building_line(lot, setbacks.edges(lot, [SOUTH_ROAD, WEST_ROAD]))
    # 90°(not under 90) of a 6 m and a 3 m (taken as 4 m) road: 시행령 제31조① 90°~120°, 4~6 m and 6~8 m → 2 m
    assert [c["m"] for c in corner["cuts"]] == [(2.0, 2.0)]
    wide = parcel("r3", "도", -40, -10, 60, 0)  # 10 m: no cut
    assert setbacks.building_line(lot, setbacks.edges(lot, [wide, WEST_ROAD]))["cuts"] == []


def test_without_a_use_only_the_building_line_counts_and_the_card_asks_for_the_use():
    out = compute([SOUTH_ROAD, EAST_LOT, NORTH_LOT])
    ls = lines(out)
    assert ls["open_space"]["value"] == "용도 선택 필요" and ls["daylight"]["value"] == "용도 선택 필요"
    assert ls["building_line"]["status"] == "check" and "0.5m 후퇴" in ls["building_line"]["detail"]
    assert out["building_line_area_m2"] == pytest.approx(10, abs=0.2) and out["roads"][0]["width"] == 3.0
    assert at(out, 10, 0.2) == 0 and np.isinf(at(out, 10, 1.0))  # behind the 건축선: open above
    assert len(out["levels"]) == 1 and out["max_height_m"] is None  # the ground floor shows where building may stand
    assert {x["key"] for x in out["uses"]} >= {"apartment", "multiplex", "other"}


def test_an_apartment_keeps_its_open_space_and_its_daylight_height():
    out = compute([SOUTH_ROAD, EAST_LOT, NORTH_LOT, WEST_LOT], use="apartment")
    ls = lines(out)
    assert (ls["open_space"]["status"], ls["open_space"]["value"]) == ("read", "건축선 3m · 인접 3m")
    assert ls["open_space"]["source"] == "서울특별시 건축 조례 제30조 [별표 4]" and "6미터 이내" in ls["open_space"]["quote"]
    assert at(out, 10, 3.2) == 0  # 0.5 m 건축선 + 3 m from the road
    assert at(out, 18.5, 15) == 0 and at(out, 2, 15) == 0  # 3 m from the neighbours
    # 채광: at most twice the distance to the nearest 인접 대지경계선 (the west side 6.25 m away here)
    assert (ls["daylight"]["status"], ls["daylight"]["value"]) == ("read", "거리의 2배")
    assert at(out, 6.25, 15) == pytest.approx(12.5, abs=0.6)
    # across the road the line is its middle (제86조⑥): 1.5 m beyond the edge
    assert at(out, 10, 4.25) == pytest.approx(2 * (4.25 + 1.5), abs=0.6)
    assert out["max_height_m"] == pytest.approx(2 * 10, abs=1.0)
    for s in out["schemes"]:
        assert s["height_m"] <= out["max_height_m"] + 1e-6
        assert s["footprint_m2"] <= (600 - out["building_line_area_m2"]) * out["bcr"] / 100 + 1e-6


def test_a_multiplex_is_kept_back_instead_of_held_down_and_commerce_has_no_daylight_rule():
    out = compute([SOUTH_ROAD, EAST_LOT, NORTH_LOT], use="multiplex")
    ls = lines(out)
    assert (ls["daylight"]["status"], ls["daylight"]["value"]) == ("read", "인접 경계선에서 1m")
    assert "서울특별시 건축 조례 제35조제3항" in ls["daylight"]["source"]
    assert at(out, 19.2, 15) == 0 and np.isinf(at(out, 17, 15))  # 1 m back, no height cap
    busan = compute([SOUTH_ROAD, EAST_LOT, NORTH_LOT], use="multiplex", municipality="부산광역시 해운대구")
    assert lines(busan)["daylight"]["status"] == "check" and np.isfinite(at(busan, 10, 15))
    shop = compute([SOUTH_ROAD, EAST_LOT, NORTH_LOT], use="apartment", zone="일반상업지역")
    assert lines(shop)["daylight"]["status"] == "none" and np.isinf(at(shop, 10, 15))
    office = compute([SOUTH_ROAD], use="other")
    assert lines(office)["daylight"]["status"] == "none"


def test_a_park_beside_the_lot_counts_as_the_far_side_for_the_open_space():
    out = compute([SOUTH_ROAD, EAST_PARK, NORTH_LOT], use="apartment")
    # the park is 10 m wide, more than the 3 m: no setback on that side, and 채광 counts from its middle
    assert at(out, 19.8, 15) == pytest.approx(2 * (0.2 + 5), abs=0.6)


def test_a_floor_area_changes_the_row_and_none_entered_takes_the_ratio_filled():
    small = compute([SOUTH_ROAD], zone="준공업지역", use="factory", use_area=300)
    big = compute([SOUTH_ROAD], zone="준공업지역", use="factory", use_area=900)
    assert lines(small)["open_space"]["value"] == "건축선 0m · 인접 0m"
    assert lines(big)["open_space"]["value"] == "건축선 1.5m · 인접 1m"
    assumed = compute([SOUTH_ROAD], zone="준공업지역", use="factory")
    assert "용적률을 채운" in lines(assumed)["open_space"]["detail"]  # 600 ㎡ × 400% counts as 500 ㎡ or more


def test_no_map_around_the_lot_says_the_building_line_is_not_known():
    out = compute([], neighbours_error="network", use="apartment")
    ls = lines(out)
    assert ls["building_line"]["value"] == "미확인"
    # every side is taken as an 인접 대지경계선, the strict way, and the line asks for a check
    assert ls["open_space"]["status"] == "check" and at(out, 10, 1) == 0
