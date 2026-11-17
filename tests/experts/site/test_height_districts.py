"""height_districts.py — the 고도지구 height from the notice's table (data/height_districts.yaml),
matched to the VWorld 고도지구 pieces under the site. The pieces are drawn here (no network)."""

from __future__ import annotations

import copy
import math

import pytest

from sida.experts.site import envelope, height_districts, landapi, site_facts

LAT, LON = 37.556, 127.010


def piece(area_m2, dyear="2024", dnum="0317", lon=LON, lat=LAT, sigg="중구", sido="서울특별시"):
    """A square 고도지구 piece of `area_m2` around (lon, lat), as VWorld LT_C_UQ123 gives it."""
    side = math.sqrt(area_m2) / 2
    dx = side / (6378137.0 * math.pi / 180 * math.cos(math.radians(lat)))
    dy = side / (6378137.0 * math.pi / 180)
    ring = [[lon - dx, lat - dy], [lon + dx, lat - dy], [lon + dx, lat + dy], [lon - dx, lat + dy], [lon - dx, lat - dy]]
    return {"properties": {"uname": "고도지구", "dyear": dyear, "dnum": dnum, "sido_name": sido, "sigg_name": sigg},
            "shape": {"type": "Polygon", "coordinates": [ring]}}


def facts(address="서울특별시 중구 신당동 355-7", zone=None, pnu="1"):
    out = {"parcels": [{"pnu": pnu, "address": address}]}
    if zone:
        out["summary"] = {"zoning": [{"zone": zone}]}
    return out


@pytest.fixture
def verified(monkeypatch):
    """The table as a person checked it against the notice (2026-11-17 지훈)."""
    table = copy.deepcopy(height_districts.load_table())
    assert table["notices"][0]["verified"]  # the file itself is checked
    monkeypatch.setattr(height_districts, "load_table", lambda: table)


@pytest.fixture
def unverified(monkeypatch):
    """The table as if no person had checked it yet."""
    table = copy.deepcopy(height_districts.load_table())
    table["notices"][0]["verified"] = None
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
    assert height == 20 and "완화시 28m는 위원회 심의가 필요해 기본 높이로 자름" in line["detail"]
    # the designer looks at the relaxed height: cut to it, said to need the committee's review
    line, height = height_districts.line(relaxed, entered=None, use_relaxed=True)
    assert (line["status"], line["value"], height) == ("conditional", "28m (완화)", 28.0)
    assert "도시계획위원회 심의" in line["detail"] and "기본 20m" in line["detail"]
    # a zone with no relaxed height ignores the switch
    assert height_districts.line(matched, entered=None, use_relaxed=True)[1] == 32.0
    # 높이 산정 (the notice's 비고): rooftop towers and see-through railings within 3m are left out
    assert "옥상 승강기탑·계단탑·투시형 난간은 3m 이내면 높이에 넣지 않음" in line["detail"]
    assert height_districts.rooftop_allowance("서울특별시 고시 제2024-317호") == 3.0
    assert height_districts.rooftop_allowance(None) is None


def test_a_table_not_yet_checked_shows_the_height_but_does_not_cut(unverified):
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
    assert out["rooftop_allowance_m"] == 3.0 and out["use_relaxed"] is False
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


def test_an_unchanged_zone_drawn_under_its_older_notice_number_is_found_among_the_kept_zones():
    # 2026-11-17 실제 대지: 이태원동 137-23 (남산 14번, 23m) lies on a 2019-0362 piece, 한남동 810 on 0000-0000
    by_area = height_districts.pick([piece(1241, "2019", "0362", sigg="용산구")], facts("서울특별시 용산구 이태원동 1"))
    assert (by_area["status"], by_area["zone"]["number"], by_area["matched_by"]) == ("matched", 14, "area")
    assert by_area["kept_as"] == ["2019-0362"] and by_area["notice"] == "서울특별시 고시 제2024-317호"
    by_place = height_districts.pick([piece(90000, "0000", "0000", sigg="용산구")], facts("서울특별시 용산구 이태원동 137-23"))
    assert (by_place["status"], by_place["zone"]["max_m"], by_place["matched_by"]) == ("matched", 23, "location")
    line, _height = height_districts.line(by_place, entered=None)
    assert "예전 고시 번호(0000-0000)로 그려져 있으나 이 고시에서 바뀌지 않은 구역" in line["detail"]
    two = height_districts.pick([piece(90000, "0000", "0000", sigg="용산구")], facts("서울특별시 용산구 한남동 810"))
    assert two["status"] == "candidates" and sorted(c["number"] for c in two["candidates"]) == [7, 8]  # 30m, 36m
    # a zone the notice changed is not taken from an old piece, nor a notice of another region
    assert height_districts.pick([piece(19004, "2019", "0362")], facts())["status"] == "unknown_notice"
    other = piece(1241, "2019", "0362", sigg="용산구", sido="부산광역시")
    assert height_districts.pick([other], facts("서울특별시 용산구 이태원동 1"))["status"] == "unknown_notice"


def test_zones_split_by_zoning_are_told_apart_by_the_sites_zoning():
    huge = piece(900000, sigg="강북구")  # no zone's area: 북한산 주변 1번(1종, 20m) or 2번(2종 이상, 28m)
    first = height_districts.pick([huge], facts("서울특별시 강북구 우이동 100-1", "제1종일반주거지역"))
    assert (first["status"], first["zone"]["number"], first["zone"]["max_m"], first["matched_by"]) == ("matched", 1, 20, "zoning")
    second = height_districts.pick([huge], facts("서울특별시 강북구 우이동 100-1", "제2종일반주거지역"))
    assert (second["zone"]["number"], second["zone"]["max_m"]) == (2, 28)
    line, _h = height_districts.line(second, entered=None)
    assert "대지의 용도지역이 고시 표의 구역과 맞음" in line["detail"]
    unknown = height_districts.pick([huge], facts("서울특별시 강북구 우이동 100-1"))
    assert unknown["status"] == "candidates" and sorted(c["number"] for c in unknown["candidates"]) == [1, 2]
    # an area match for the other 용도지역 is not taken
    wrong = height_districts.pick([piece(248450, sigg="강북구")], facts("서울특별시 강북구 우이동 100-1", "제2종일반주거지역"))
    assert wrong["status"] == "candidates"


def test_a_notices_shortened_dong_names_still_give_the_candidates():
    # 2026-11-17 실제 대지: 창성동 117-1 lies on a 2024-0317 piece that matches no zone's area
    assert height_districts._names_dong("종로구 효자, 창성, 통의, 적선동 일대", "종로구", "창성동")
    assert height_districts._names_dong("강북구 우이동, 인수동, 수유1동, 삼양동 일대", "강북구", "수유동")
    assert not height_districts._names_dong("종로구 효자, 창성, 통의, 적선동 일대", "중구", "창성동")
    assert not height_districts._names_dong("종로구 효자, 창성, 통의, 적선동 일대", "종로구", "청운동")
    found = height_districts.pick([piece(900000, sigg="종로구")], facts("서울특별시 종로구 창성동 117-1"))
    assert found["status"] == "candidates"
    assert sorted((c["district"], c["number"]) for c in found["candidates"]) == [("경복궁 주변", 1), ("경복궁 주변", 3), ("경복궁 주변", 5)]


def test_public_land_takes_its_own_height_and_unknown_ownership_gives_none():
    found = height_districts.pick([piece(10080, sigg="종로구")], facts("서울특별시 종로구 창성동 117"))
    assert (found["district"], found["zone"]["number"]) == ("경복궁 주변", 1)
    public, h = height_districts.line(found, entered=None, public_land=True)
    assert (public["value"], h) == ("12m", 12.0) and "국·공유지(토지소유정보)라 12m" in public["detail"]
    private, h = height_districts.line(found, entered=None, public_land=False)
    assert (private["value"], h) == ("15m", 15.0) and "국·공유지가 아님" in private["detail"]
    unsure, h = height_districts.line(found, entered=None, public_land=None)
    assert (unsure["status"], unsure["value"], h) == ("check", "15m 또는 12m", None)


def test_the_sites_ownership_comes_from_the_land_register(fake_vworld, monkeypatch):
    assert landapi.land_owner("1111011900100010000") == {"kind": "국유지", "public": True}  # 세종로 1
    assert landapi.land_owner("1114010300100310000") == {"kind": "시 도유지", "public": True}  # 태평로1가 31
    assert landapi.land_owner("1111010800101000000") == {"kind": "법인", "public": False}  # 통인동 100
    assert landapi.land_owner("9999999999999999999") is None
    state = facts(pnu="1111011900100010000")
    assert envelope.public_land_of(state) is True
    mixed = {"parcels": state["parcels"] + [{"pnu": "1111010800101000000", "address": "x"}]}
    assert envelope.public_land_of(mixed) is None
    assert envelope.public_land_of(facts(pnu="9999999999999999999")) is None
    # district_at asks only for a zone with a height of its own on 국·공유지
    from tests.experts.site.test_envelope import PLAN

    monkeypatch.setattr(landapi, "districts_at", lambda *a, **k: [piece(10080, sigg="종로구")])
    gyeongbok = envelope.district_at(PLAN, facts("서울특별시 종로구 창성동 117", pnu="1111011900100010000"))
    assert gyeongbok["public_land"] is True
    monkeypatch.setattr(landapi, "districts_at", lambda *a, **k: [piece(19004)])
    assert "public_land" not in envelope.district_at(PLAN, facts())
