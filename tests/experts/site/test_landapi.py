"""landapi.py — VWorld clients against recorded responses (군포시 금정동 689)."""

from __future__ import annotations

import pytest
import requests

from sida.experts.site import landapi
from sida.experts.site.landapi import LandApiError
from tests.conftest import REAL_HTTP_GET, land_fixture

PNU = "4141010500106890014"


def test_search_returns_parcels_with_pnu(fake_vworld):
    parcels = landapi.search_parcels("경기도 군포시 금정동 689")
    assert parcels[0] == {
        "pnu": PNU,
        "address": "경기도 군포시 금정동 689-14",
        "road_address": "엘에스로115번길 63",
        "building": "(주)혜창",
        "x": "126.94597762308629",
        "y": "37.37024989683182",
        "matched_by": "parcel",
    }
    assert all(len(p["pnu"]) == 19 for p in parcels) and len(parcels) > 1
    url, params = fake_vworld.calls[0]
    assert url.endswith("/req/search") and params["category"] == "parcel"
    assert params["query"] == "경기도 군포시 금정동 689" and params["key"] == "test-key"


def test_search_not_found_is_empty_list(fake_vworld):
    fake_vworld.overrides["search"] = land_fixture("search_not_found.json")
    assert landapi.search_parcels("없는동네 999999") == []


def test_search_bad_key_is_invalid_key(fake_vworld):
    fake_vworld.overrides["search"] = land_fixture("search_bad_key.json")
    with pytest.raises(LandApiError) as info:
        landapi.search_parcels("금정동 689")
    assert info.value.kind == "invalid_key" and "인증키" in info.value.detail


def test_missing_key_is_reported_before_any_request(fake_vworld, monkeypatch):
    monkeypatch.delenv("VWORLD_API_KEY")
    with pytest.raises(LandApiError) as info:
        landapi.search_parcels("금정동 689")
    assert info.value.kind == "no_key" and fake_vworld.calls == []


def test_land_use_removes_duplicates_and_keeps_relation(fake_vworld):
    raw = land_fixture(f"getLandUseAttr_{PNU}.json")["landUses"]["field"]
    zones = landapi.land_use(PNU)
    names = [z["name"] for z in zones]
    assert len(raw) == 12 and len(zones) < len(raw)
    assert len(names) == len(set(names))  # API returns several rows twice
    assert {"name": "일반공업지역", "code": "UQA320", "relation": "포함", "updated": "2026-09-06"} in zones
    road = next(z for z in zones if z["name"].startswith("소로1류"))
    assert road["relation"] == "접함"
    _url, params = fake_vworld.calls[0]
    assert params["pnu"] == PNU and params["domain"] == "http://localhost:8765"


def test_land_use_bad_key_and_unknown_parcel(fake_vworld):
    fake_vworld.overrides["getLandUseAttr"] = land_fixture("getLandUseAttr_bad_key.json")
    with pytest.raises(LandApiError) as info:
        landapi.land_use(PNU)
    assert info.value.kind == "invalid_key"

    fake_vworld.overrides["getLandUseAttr"] = land_fixture("getLandUseAttr_unknown_pnu.json")
    assert landapi.land_use("9999999999999999999") == []


def test_land_characteristics_uses_latest_year(fake_vworld):
    rows = land_fixture(f"getLandCharacteristics_{PNU}.json")["landCharacteristicss"]["field"]
    latest_year = max(r["stdrYear"] for r in rows)
    ch = landapi.land_characteristics(PNU)
    assert len(rows) > 5 and ch["year"] == latest_year
    assert ch["land_category"] == "공장용지" and ch["area_m2"] == 1014.3
    assert ch["zone1"] == "일반공업지역" and ch["zone2"] == ""  # "지정되지않음" → empty
    assert ch["terrain_height"] == "평지" and ch["road_side"]
    assert isinstance(ch["official_price"], float)


def test_land_characteristics_none_for_unknown_parcel(fake_vworld):
    assert landapi.land_characteristics("9999999999999999999") is None


class _Reply:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_http_get_retries_timeouts_then_succeeds(monkeypatch):
    monkeypatch.setattr(landapi.time, "sleep", lambda *_: None)
    replies = [requests.Timeout("slow"), _Reply(503), _Reply(200, {"ok": 1})]

    def fake_get(url, params, timeout):
        item = replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(landapi.requests, "get", fake_get)
    assert REAL_HTTP_GET("https://api.vworld.kr/x", {"key": "k"}) == {"ok": 1}
    assert replies == []


def test_http_get_gives_up_without_leaking_the_key(monkeypatch):
    monkeypatch.setattr(landapi.time, "sleep", lambda *_: None)

    def always_down(url, params, timeout):
        raise requests.ConnectionError(f"failed for {url}?key={params['key']}")

    monkeypatch.setattr(landapi.requests, "get", always_down)
    with pytest.raises(LandApiError) as info:
        REAL_HTTP_GET("https://api.vworld.kr/x", {"key": "SECRET-KEY"})
    assert info.value.kind == "network"
    assert "SECRET-KEY" not in str(info.value) and "SECRET-KEY" not in info.value.detail

    monkeypatch.setattr(landapi.requests, "get", lambda url, params, timeout: _Reply(200, None))
    with pytest.raises(LandApiError) as info:
        REAL_HTTP_GET("https://api.vworld.kr/x", {"key": "k"})
    assert info.value.kind == "bad_response"


def test_road_name_address_is_tried_only_when_the_lot_number_search_finds_nothing(fake_vworld):
    found = landapi.search_parcels("경기도 군포시 금정동 689")
    assert all(p["matched_by"] == "parcel" for p in found)
    assert [params["category"] for _url, params in fake_vworld.calls] == ["parcel"]  # no second call

    fake_vworld.calls.clear()
    road = landapi.search_parcels("  경기도 군포시   공단로140번길 46 ")
    assert [params["category"] for _url, params in fake_vworld.calls] == ["parcel", "road"]
    assert fake_vworld.calls[0][1]["query"] == "경기도 군포시 공단로140번길 46"  # spaces tidied
    assert road == [
        {
            "pnu": "4141010200101810042",
            "address": "경기도 군포시 당정동 181-42",  # 시·군 taken from the road address
            "road_address": "경기도 군포시 공단로140번길 46 (당정동)",
            "building": "",
            "x": "126.9547192570812",
            "y": "37.357037891438715",
            "matched_by": "road",
        }
    ]  # the duplicate row is dropped

    # the same road name in another city is not offered: the typed 시·군·구 must be in the hit
    assert landapi.search_parcels("안양시 공단로140번길 46") == []
    assert landapi.search_parcels("군포시 공단로140번길 46")[0]["pnu"] == "4141010200101810042"


def _road_hits(*roads: tuple[str, str, str]):
    """A road-name search reply (shape as recorded) with the given (pnu, road, parcel) hits."""
    items = [
        {"id": pnu, "address": {"category": "road", "road": road, "parcel": parcel, "bldnm": ""},
         "point": {"x": "127", "y": "37.5"}}
        for pnu, road, parcel in roads
    ]

    def http_get(url, params):
        if params["category"] == "parcel":
            return land_fixture("search_not_found.json")
        return {"response": {"status": "OK", "result": {"items": items}}}

    return http_get


def test_road_search_accepts_short_names_of_special_and_metropolitan_cities():
    seoul = _road_hits(("1168010100107370000", "서울특별시 강남구 테헤란로 152 (역삼동)", "역삼동 737"))
    for typed in ("서울시 강남구 테헤란로 152", "서울특별시 강남구 테헤란로 152", "강남구 테헤란로 152"):
        found = landapi.search_parcels(typed, http_get=seoul)
        assert [p["address"] for p in found] == ["서울특별시 강남구 역삼동 737"], typed
    # the short name still has to be the right city, and every other typed 시·군·구 still counts
    assert landapi.search_parcels("부산시 강남구 테헤란로 152", http_get=seoul) == []
    assert landapi.search_parcels("서울시 서초구 테헤란로 152", http_get=seoul) == []

    # "광주시" is also a 시 in 경기도: a hit in either one is kept
    gwangju = _road_hits(
        ("2917010100100010000", "광주광역시 북구 무등로 1 (중흥동)", "중흥동 1"),
        ("4161010100100010000", "경기도 광주시 무등로 1 (경안동)", "경안동 1"),
        ("2611010100100010000", "부산광역시 중구 무등로 1 (중앙동)", "중앙동 1"),
    )
    found = landapi.search_parcels("광주시 무등로 1", http_get=gwangju)
    assert [p["pnu"][:2] for p in found] == ["29", "41"]


def test_misspelt_address_finds_nothing_and_region_is_read_from_road_addresses(fake_vworld):
    fake_vworld.overrides["search"] = land_fixture("search_not_found.json")
    assert landapi.search_parcels("경기도 군포시 금졍동 689-14") == []  # no correction, no guess
    region = landapi._region_of_road_address
    assert region("경기도 군포시 공단로140번길 46 (당정동)") == "경기도 군포시"
    assert region("서울특별시 종로구 사직로 161") == "서울특별시 종로구"
    assert region("경기도 양평군 양평읍 시민로 5") == "경기도 양평군 양평읍"
    assert region("세종특별자치시 한누리대로 2130") == "세종특별자치시"
    assert region("") == ""


# --- step-by-step address selection (data API: address lists and lot numbers) ------------


def _data_calls(fake_vworld) -> list[dict]:
    return [params for url, params in fake_vworld.calls if url.endswith("/req/data")]


def test_regions_walk_from_province_to_ri(fake_vworld):
    provinces = landapi.regions()
    assert any(r == {"code": "41", "name": "경기도", "full_name": "경기도", "has_ri": False, "dong_code": ""}
               for r in provinces)
    assert [r["name"] for r in provinces] == sorted(r["name"] for r in provinces)
    first = _data_calls(fake_vworld)[0]
    assert first["data"] == "LT_C_ADSIDO_INFO" and first["geomFilter"] and "attrFilter" not in first
    assert first["geometry"] == "false" and first["key"] == "test-key"

    cities = landapi.regions("41")
    assert all(len(r["code"]) == 5 and r["code"].startswith("41") and r["dong_code"] == "" for r in cities)
    assert {"code": "41410", "full_name": "경기도 군포시"}.items() <= next(
        r for r in cities if r["name"] == "군포시").items()
    assert _data_calls(fake_vworld)[-1]["attrFilter"] == "sig_cd:like:41"

    dongs = {r["name"]: r for r in landapi.regions("41410")}
    # a 동's lots are under its own code + "00": 금정동 689-14 is PNU 4141010500 1 0689 0014
    assert dongs["금정동"] == {
        "code": "41410105", "name": "금정동", "full_name": "경기도 군포시 금정동",
        "has_ri": False, "dong_code": "4141010500",
    }

    towns = sorted((r for r in landapi.regions("41830") if r["has_ri"]), key=lambda r: r["code"])
    assert towns and all(r["name"].endswith(("읍", "면")) and r["dong_code"] == "" for r in towns)
    villages = landapi.regions(towns[0]["code"])
    assert villages and all(
        r["dong_code"] == r["code"] and len(r["code"]) == 10 and r["code"].startswith(towns[0]["code"])
        for r in villages
    )


def test_regions_are_kept_in_memory(fake_vworld):
    assert landapi.regions("41410") == landapi.regions("41410")
    assert len(_data_calls(fake_vworld)) == 1
    landapi.clear_cache()
    landapi.regions("41410")
    assert len(_data_calls(fake_vworld)) == 2


def test_regions_keep_only_children_of_the_parent_and_read_every_page():
    def feature(code, name):
        return {"type": "Feature", "properties": {"sig_cd": code, "sig_kor_nm": name, "full_nm": f"경기도 {name}"}}

    pages = {
        1: [feature("41410", "군포시"), feature("11410", "서대문구"), feature("41410", "군포시")],
        2: [feature("41830", "양평군"), feature("4183", "잘린코드"), feature("41111", "")],
    }

    def http_get(url, params):
        return {"response": {"status": "OK", "page": {"total": "2", "current": str(params["page"])},
                             "result": {"featureCollection": {"features": pages[params["page"]]}}}}

    found = landapi.regions("41", http_get=http_get)
    assert [(r["code"], r["name"]) for r in found] == [("41410", "군포시"), ("41830", "양평군")]


def test_regions_refuse_malformed_codes_without_calling(fake_vworld):
    for bad in ("4", "414", "41410105xx", "abcde", "4141010500"):
        with pytest.raises(ValueError):
            landapi.regions(bad)
    assert fake_vworld.calls == []


def test_regions_report_a_rejected_key(fake_vworld):
    fake_vworld.overrides["data"] = land_fixture("data_bad_key.json")
    with pytest.raises(LandApiError) as info:
        landapi.regions("41")
    assert info.value.kind == "invalid_key"
    del fake_vworld.overrides["data"]
    assert landapi.regions("41")  # a failure is not remembered


def test_find_lots_builds_the_pnu_from_the_parts(fake_vworld):
    lots = landapi.find_lots("4141010500", 689)
    assert _data_calls(fake_vworld)[-1]["attrFilter"] == "pnu:like:414101050010689"
    assert lots and all(lot["pnu"].startswith("414101050010689") and lot["matched_by"] == "lot" for lot in lots)
    assert [lot["pnu"] for lot in lots] == sorted(lot["pnu"] for lot in lots)
    assert PNU in [lot["pnu"] for lot in lots]

    assert landapi.find_lots("4141010500", 689, 14) == [{
        "pnu": PNU, "address": "경기도 군포시 금정동 689-14", "road_address": "", "building": "",
        "matched_by": "lot",
    }]
    assert _data_calls(fake_vworld)[-1]["attrFilter"] == f"pnu:=:{PNU}"

    assert landapi.find_lots("4141010500", 689, mountain=True) == []  # 산 689 does not exist there
    assert _data_calls(fake_vworld)[-1]["attrFilter"] == "pnu:like:414101050020689"
    assert landapi.find_lots("4141010500", 9999, 9999) == []


def test_find_lots_refuses_parts_out_of_range(fake_vworld):
    for args in (("41410105", 689), ("4141010500", 0), ("4141010500", 10000), ("4141010500", 1, 10000)):
        with pytest.raises(ValueError):
            landapi.find_lots(*args)
    assert fake_vworld.calls == []


def test_parcel_by_pnu(fake_vworld):
    assert landapi.parcel_by_pnu(PNU)["address"] == "경기도 군포시 금정동 689-14"
    assert landapi.parcel_by_pnu("4141010500199999999") is None
    with pytest.raises(ValueError):
        landapi.parcel_by_pnu("414101050010689")


NEW_PNU = "1278025024100010000"  # 강진읍 교촌리 1 under 전남광주통합특별시 (새 코드 12780)
OLD_PNU = "4681025024100010000"  # the same parcel under the former 전라남도 (옛 코드 46810)


def test_land_use_for_an_old_pnu_asks_again_under_the_new_numbering(fake_vworld):
    # 브이월드의 토지이용계획 API는 통합 후 새 번호만 받는다: 옛 번호로 저장된 필지도 용도지역이 나와야 한다.
    zones = landapi.land_use(OLD_PNU)
    assert zones and zones[0]["name"]
    pnus = [params.get("pnu") for _url, params in fake_vworld.calls if params.get("pnu")]
    assert pnus == [OLD_PNU, NEW_PNU]


def test_land_characteristics_for_a_new_pnu_asks_again_under_the_old_numbering(fake_vworld):
    # 토지특성 API는 옛 번호만 받는다: 새 번호의 필지도 면적·공시지가가 나와야 한다.
    ch = landapi.land_characteristics(NEW_PNU)
    assert ch and ch["area_m2"] and ch["official_price"]
    pnus = [params.get("pnu") for _url, params in fake_vworld.calls if params.get("pnu")]
    assert pnus == [NEW_PNU, OLD_PNU]


def test_other_numbering_is_not_tried_when_the_first_has_rows_or_the_region_is_unaffected(fake_vworld):
    assert landapi.land_use(NEW_PNU)
    assert [p["pnu"] for _u, p in fake_vworld.calls if "pnu" in p] == [NEW_PNU]  # no second call
    fake_vworld.calls.clear()
    assert landapi.land_characteristics("9999999999999999999") is None  # not 12/46/29: no region lookup
    assert [p["pnu"] for _u, p in fake_vworld.calls if "pnu" in p] == ["9999999999999999999"]
    assert not any(u.endswith("/req/data") for u, _p in fake_vworld.calls)


def test_former_sigungu_codes_cover_every_merged_region():
    # 새 시·군·구 이름과 옛 코드 표가 어긋나면 그 지역만 조용히 토지특성이 빠진다.
    assert len(landapi._FORMER_SIGUNGU) == 27
    assert len(set(landapi._FORMER_SIGUNGU.values())) == 27
    assert all(c.startswith(("46", "29")) and len(c) == 5 for c in landapi._FORMER_SIGUNGU.values())


# --- map: parcel boundary shapes and the parcel at a clicked point ------------------------


def test_parcel_shape_is_the_recorded_boundary_in_lon_lat(fake_vworld):
    shape = landapi.parcel_shape(PNU)
    assert shape["type"] == "MultiPolygon"
    ring = shape["coordinates"][0][0]
    assert ring[0] == [126.94594267669507, 37.3700295146347] and ring[0] == ring[-1]  # closed ring
    assert all(126.94 < lon < 126.95 and 37.36 < lat < 37.38 for lon, lat in ring)  # lon first
    params = _data_calls(fake_vworld)[-1]
    assert params["attrFilter"] == f"pnu:=:{PNU}" and params["geometry"] == "true" and params["crs"] == "EPSG:4326"

    assert landapi.parcel_shape("4141010500199999999") is None  # no such parcel
    with pytest.raises(ValueError):
        landapi.parcel_shape("41410105001068900")


def test_parcel_at_finds_the_parcel_under_a_map_point(fake_vworld):
    found = landapi.parcel_at(126.945978, 37.37025)  # inside 689-14 (recorded reply)
    assert {k: v for k, v in found.items() if k != "shape"} == {
        "pnu": PNU, "address": "경기도 군포시 금정동 689-14", "road_address": "", "building": "",
        "matched_by": "map",
    }
    assert found["shape"] == landapi.parcel_shape(PNU)
    assert _data_calls(fake_vworld)[0]["geomFilter"] == "POINT(126.945978 37.37025)"

    assert landapi.parcel_at(125.0, 34.0) is None  # the sea: VWorld answers NOT_FOUND
    for lon, lat in ((0, 0), (37.37, 126.94), (140.0, 37.0)):  # outside Korea, or lat/lon swapped
        with pytest.raises(ValueError):
            landapi.parcel_at(lon, lat)
