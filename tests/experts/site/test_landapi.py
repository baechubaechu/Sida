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


def test_misspelt_address_finds_nothing_and_region_is_read_from_road_addresses(fake_vworld):
    fake_vworld.overrides["search"] = land_fixture("search_not_found.json")
    assert landapi.search_parcels("경기도 군포시 금졍동 689-14") == []  # no correction, no guess
    region = landapi._region_of_road_address
    assert region("경기도 군포시 공단로140번길 46 (당정동)") == "경기도 군포시"
    assert region("서울특별시 종로구 사직로 161") == "서울특별시 종로구"
    assert region("경기도 양평군 양평읍 시민로 5") == "경기도 양평군 양평읍"
    assert region("세종특별자치시 한누리대로 2130") == "세종특별자치시"
    assert region("") == ""
