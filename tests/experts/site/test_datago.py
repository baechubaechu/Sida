"""datago.py — 토지이음 행위제한·근거 조문 and 건축물대장, against replies recorded on 2026-10-16."""

from __future__ import annotations

import pytest

from sida.experts.site import datago
from sida.experts.site.landapi import LandApiError

PNU = "4141010500106890014"  # 경기도 군포시 금정동 689-14, 일반공업지역


def test_search_uses_puts_the_exact_name_first(fake_datago):
    uses = datago.search_uses(" 단독주택 ")
    assert uses[0] == {"name": "단독주택", "code": "03650"}
    assert len(uses) == 2
    factories = datago.search_uses("공장")
    assert factories[0]["name"] == "공장" and len(factories) == 50
    url, params = fake_datago.calls[0]
    assert url.endswith("/arLandUseInfoService/DTsearchLunCd") and params["serviceKey"] == "test-key"
    with pytest.raises(ValueError):
        datago.search_uses("  ")


def test_use_rules_reads_permission_per_zone(fake_datago):
    house = datago.use_rules("41410", ["UQA320"], "단독주택")
    assert [(z["zone"], z["code"]) for z in house] == [("일반공업지역", "UQA320")]
    act = house[0]["acts"][0]
    assert (act["act"], act["result"], act["conditions"]) == ("건축", "금지", [])
    assert act["uses"][0]["law"] == "건축법 시행령 별표 1 제1호가목"

    factory = datago.use_rules("41410", ["UQA320", "UBA100"], "공장")
    dense, industrial = factory
    assert dense["zone"] == "과밀억제권역" and dense["zone_law"] == "수도권정비계획법 제6조 제1항 제1호"
    assert [(a["act"], a["result"]) for a in dense["acts"]] == [("업종변경", "금지"), ("신설·증설·이전", "금지")]
    # The provisos are attached as written, by their reference numbers.
    assert dense["acts"][0]["conditions"][0].startswith("공장건축면적 500제곱미터 이상")
    assert len(dense["acts"][0]["conditions"]) == 2
    assert industrial["acts"][0]["result"] == "가능"
    assert [u["name"] for u in industrial["acts"][0]["uses"]] == ["공장", "정비공장"]
    assert fake_datago.calls[-1][1]["ucodeList"] == "UQA320,UBA100"
    assert datago.use_rules("41410", [], "공장") == []


def test_zone_laws_merges_duplicates_and_marks_the_ordinance(fake_datago):
    laws = datago.zone_laws("41410", ["UQA320"])
    texts = [law["text"] for law in laws]
    assert len(laws) == 11  # 13 rows, 제83조 three times
    assert sum(t.startswith("제83조(용도지역ㆍ용도지구") for t in texts) == 1
    local = [law for law in laws if law["local"]]
    assert [law["text"][:7] for law in local] == ["제32조(용도", "[별표 12]"]
    assert all(law["zones"] == ["일반공업지역"] for law in laws)

    both = datago.zone_laws("41410", ["UQA320", "UBA100"])
    assert {z for law in both for z in law["zones"]} == {"일반공업지역", "과밀억제권역"}


def test_buildings_from_the_register(fake_datago):
    (building,) = datago.buildings(PNU)
    assert building["name"] == "(주)혜창" and building["purpose"] == "공장"
    assert building["floors_above"] == 4 and building["floors_below"] == 1
    assert building["bcr"] == pytest.approx(69.843241) and building["approved"] == "20030204"
    assert building["dong"] == ""  # registered as a blank
    params = fake_datago.calls[-1][1]
    assert (params["sigunguCd"], params["bjdongCd"], params["platGbCd"], params["bun"], params["ji"]) == (
        "41410", "10500", "0", "0689", "0014",
    )
    assert datago.buildings("4141010500199990000") == []


def test_lot_params_for_a_mountain_lot():
    assert datago.lot_params("4141010500206890014")["platGbCd"] == "1"


@pytest.mark.parametrize(
    "op, reply, kind",
    [
        ("DTarLandUseInfo", "arlanduse_badkey.json", "invalid_key"),
        ("getBrTitleInfo", "brtitle_badkey.json", "invalid_key"),
        ("DTarLandUseInfo", "eum_noaccept.xml", "bad_response"),
        ("getBrTitleInfo", (200, b"<html>gateway</html>"), "bad_response"),
        ("DTarLandUseInfo", LandApiError("network", "Timeout"), "network"),
    ],
)
def test_service_errors_become_land_api_errors(fake_datago, op, reply, kind):
    fake_datago.overrides[op] = reply
    call = (lambda: datago.buildings(PNU)) if op == "getBrTitleInfo" else (
        lambda: datago.use_rules("41410", ["UQA320"], "공장")
    )
    with pytest.raises(LandApiError) as err:
        call()
    assert err.value.kind == kind


def test_missing_key_is_reported_before_any_call(fake_datago, monkeypatch):
    monkeypatch.delenv("DATA_GO_KR_API_KEY")
    with pytest.raises(LandApiError) as err:
        datago.buildings(PNU)
    assert err.value.kind == "no_key" and fake_datago.calls == []


def test_errors_carry_their_own_messages(fake_datago):
    from sida.i18n import t

    fake_datago.overrides["DTsearchLunCd"] = "arlanduse_badkey.json"
    with pytest.raises(datago.DataGoError) as caught:
        datago.search_uses("공장")
    assert isinstance(caught.value, LandApiError) and caught.value.kind == "invalid_key"
    assert "공공데이터포털" in t(caught.value.MESSAGE_PREFIX + caught.value.kind, detail="x")
    assert "브이월드" in t(LandApiError.MESSAGE_PREFIX + "invalid_key", detail="x")
