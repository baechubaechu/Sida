"""height_districts.py — the 고도지구 height from the notice's table (data/height_districts.yaml),
matched to the VWorld 고도지구 pieces under the site. The pieces are drawn here (no network)."""

from __future__ import annotations

import copy
import math

import pytest

from sida.experts.site import envelope, height_districts, landapi, site_facts

LAT, LON = 37.556, 127.010


def piece(area_m2, dyear="2024", dnum="0317", lon=LON, lat=LAT, sigg="중구"):
    """A square 고도지구 piece of `area_m2` around (lon, lat), as VWorld LT_C_UQ123 gives it."""
    side = math.sqrt(area_m2) / 2
    dx = side / (6378137.0 * math.pi / 180 * math.cos(math.radians(lat)))
    dy = side / (6378137.0 * math.pi / 180)
    ring = [[lon - dx, lat - dy], [lon + dx, lat - dy], [lon + dx, lat + dy], [lon - dx, lat + dy], [lon - dx, lat - dy]]
    return {"properties": {"uname": "고도지구", "dyear": dyear, "dnum": dnum, "sido_name": "서울특별시", "sigg_name": sigg},
            "shape": {"type": "Polygon", "coordinates": [ring]}}


def facts(address="서울특별시 중구 신당동 355-7"):
    return {"parcels": [{"pnu": "1", "address": address}]}


@pytest.fixture
def verified(monkeypatch):
    """The table as if a person had checked it against the notice."""
    table = copy.deepcopy(height_districts.load_table())
    table["notices"][0]["verified"] = "2026-11-17"
    monkeypatch.setattr(height_districts, "load_table", lambda: table)


def test_the_places_a_zones_location_names_carry_their_gu_and_dong():
    places = height_districts._places("중구 회현동1가 164, 신당동 432-1979, 432-1632 일대, 용산구 이태원동 204-3, 한남동 일대")
    assert places == {("중구", "회현동1가", "164"), ("중구", "신당동", "432-1979"), ("중구", "신당동", "432-1632"),
                      ("용산구", "이태원동", "204-3")}
    assert height_districts._places("용산구 용산동2가31, 5-1488 일대") == {("용산구", "용산동2가", "31"), ("용산구", "용산동2가", "5-1488")}
    assert height_districts._site_places(facts()) == {("중구", "신당동", "355-7")}


def test_the_table_holds_the_notices_areas():
    for notice in height_districts.load_table()["notices"]:
        for d in notice["districts"].values():
            assert sum(z["area_m2"] for z in d["zones"]) == d["total_m2"]  # checked against the notice's 사유서
    assert piece_area_ok(19109)


def piece_area_ok(area):
    return abs(height_districts.piece_area(piece(area)["shape"]) - area) < area * 0.001


def test_a_piece_is_matched_to_its_zone_by_area_and_old_notices_are_left_aside():
    found = height_districts.pick([piece(19004), piece(52000, "2019", "0362"), piece(70000, "0000", "0000")], facts("서울특별시 중구 신당동 1"))
    assert (found["status"], found["district"], found["zone"]["number"], found["zone"]["max_m"]) == ("matched", "남산 주변", 17, 32)
    assert found["matched_by"] == "area" and found["notice"] == "서울특별시 고시 제2024-317호"
    assert found["notices_seen"] == ["0000-0000", "2019-0362", "2024-0317"]


def test_without_an_area_match_the_sites_jibun_in_a_location_picks_the_zone_else_candidates():
    by_place = height_districts.pick([piece(500000)], facts("서울특별시 중구 신당동 355-7"))
    assert (by_place["status"], by_place["zone"]["number"], by_place["matched_by"]) == ("matched", 17, "location")
    unsure = height_districts.pick([piece(500000)], facts("서울특별시 중구 신당동 999"))
    assert unsure["status"] == "candidates"
    assert {c["number"] for c in unsure["candidates"]} >= {3, 17, 18, 20, 21}  # the zones naming 중구 신당동
    assert height_districts.pick([piece(19004, "2019", "0362")], facts())["status"] == "unknown_notice"
    assert height_districts.pick([], facts())["status"] == "none"


def test_the_line_gives_a_height_only_from_a_checked_table_and_one_ground_figure(verified):
    matched = height_districts.pick([piece(19004)], facts())
    line, height = height_districts.line(matched, entered=None)
    assert (line["status"], line["value"], height) == ("read", "32m", 32.0)
    assert line["source"] == "서울특별시 고시 제2024-317호" and "남산 주변 17번 구역: 32m이하" in line["quote"]
    entered, h = height_districts.line(matched, entered=30)
    assert (entered["source"], h) == ("사용자 입력", 30) and "남산 주변 17번 구역" in entered["detail"]
    road = height_districts.pick([piece(22500)], facts())  # 남산 3번: 도로면 +4m
    line, height = height_districts.line(road, entered=None)
    assert (line["status"], line["value"], height) == ("check", "도로면 +4m이하", None)
    relaxed = height_districts.pick([piece(53311, sigg="용산구")], facts())  # 남산 5번: 20m, 완화시 28m
    line, height = height_districts.line(relaxed, entered=None)
    assert height == 20 and "완화시 28m는 위원회 심의가 필요해 쓰지 않음" in line["detail"]


def test_a_table_not_yet_checked_shows_the_height_but_does_not_cut():
    line, height = height_districts.line(height_districts.pick([piece(19004)], facts()), entered=None)
    assert (line["status"], line["value"], height) == ("check", "32m (대조 전)", None)
    assert height_districts.line({"status": "error"}, entered=None)[0]["value"] == "입력 필요"


def test_the_envelope_is_cut_to_the_notices_height_where_the_site_lies_in_a_height_district(verified, monkeypatch):
    from tests.experts.site.test_envelope import PLAN

    limits = site_facts.load_limits()["zones"]["일반상업지역"]
    f = {"summary": {"zoning": [{"zone": "일반상업지역", "pnus": ["1"], "area_m2": 504.0, **limits}],
                     "districts": [{"name": "고도지구", "relation": "포함"}], "total_area_m2": 504.0, "area_complete": True,
                     "municipality": "서울특별시 중구", "parcel_count": 1},
         "parcels": [{"pnu": "1", "address": "서울특별시 중구 신당동 355-7"}]}
    asked = []

    def at(layer, lon, lat, http_get=None):
        asked.append((layer, round(lon, 3), round(lat, 3)))
        return [piece(19004)]

    monkeypatch.setattr(landapi, "districts_at", at)
    district = envelope.district_at(PLAN, f)
    assert asked == [("LT_C_UQ123", 127.0, 37.5)] and district["zone"]["number"] == 17
    out = envelope.compute(PLAN, f, envelope.sunlight_rule(f), [], lambda pnu: None, floor_height=4.0, district=district)
    lines = {x["id"]: x for x in out["lines"]}
    assert out["district_height_m"] == 32 and out["max_height_m"] == 32 and out["height_limit_m"] is None
    assert out["height_district"]["limit"] == "32m이하" and lines["height"]["value"] == "32m"
    assert all(s["height_m"] <= 32 for s in out["schemes"])
    # what the designer enters wins
    out = envelope.compute(PLAN, f, envelope.sunlight_rule(f), [], lambda pnu: None, floor_height=4.0, district=district, height_cap=20)
    assert out["max_height_m"] == 20 and out["district_height_m"] is None

    def down(*a, **k):
        raise landapi.LandApiError("network")

    monkeypatch.setattr(landapi, "districts_at", down)
    assert envelope.district_at(PLAN, f)["status"] == "error"


def test_district_pieces_are_asked_for_by_point_on_a_district_layer_only():
    calls = []

    def fake(url, params):
        calls.append(params)
        return {"response": {"status": "OK", "result": {"featureCollection": {"features": [
            {"properties": piece(100)["properties"], "geometry": piece(100)["shape"]}]}}}}

    got = landapi.districts_at("LT_C_UQ123", LON, LAT, http_get=fake)
    assert got[0]["properties"]["dnum"] == "0317" and calls[0]["geomFilter"] == f"POINT({LON} {LAT})"
    with pytest.raises(ValueError):
        landapi.districts_at("LP_PA_CBND_BUBUN", LON, LAT, http_get=fake)
    with pytest.raises(ValueError):
        landapi.districts_at("LT_C_UQ123", 0, 0, http_get=fake)


def test_two_zones_of_like_area_are_told_apart_by_the_sites_jibun_or_left_as_candidates():
    both = piece(50400, sigg="용산구")  # within 3% of 남산 6번(49,630㎡, 18m) and 13번(51,113㎡, 15m)
    named = height_districts.pick([both], facts("서울특별시 용산구 한남동 810"))
    assert (named["status"], named["zone"]["number"], named["zone"]["max_m"]) == ("matched", 6, 18)
    unsure = height_districts.pick([both], facts("서울특별시 용산구 한남동 1"))
    assert unsure["status"] == "candidates" and sorted(c["number"] for c in unsure["candidates"]) == [6, 13]
    line, height = height_districts.line(unsure, entered=None)
    assert (line["value"], height) == ("미확인", None) and "남산 주변 6번 구역(18m이하)" in line["detail"]
