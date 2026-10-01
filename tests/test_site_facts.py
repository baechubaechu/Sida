"""site_facts.py — parcels → one site, statutory limits, flags, and the blocks experts receive."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import harness
import landapi
import site_facts
from commands import dispatch
from landapi import LandApiError
from tests.conftest import ROOT

P14 = "4141010500106890014"
P15 = "4141010500106890015"
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def candidates(*pnus):
    by_pnu = {c["pnu"]: c for c in landapi.search_parcels("경기도 군포시 금정동 689")}
    return [by_pnu[p] for p in pnus]


@pytest.fixture
def one(fake_vworld):
    return site_facts.build_facts("금정동 689-14", candidates(P14), now=NOW)


@pytest.fixture
def merged(fake_vworld):
    return site_facts.build_facts("금정동 689", candidates(P14, P15), now=NOW)


# --- the statutory table -------------------------------------------------------


def test_limits_table_matches_the_decree():
    """국토계획법 시행령 제84조①·제85조① — spot values checked against the statute text."""
    zones = site_facts.load_limits()["zones"]
    assert len(zones) == 21
    assert zones["제1종전용주거지역"] == {"bcr_max": 50, "far_min": 50, "far_max": 100}
    assert zones["제2종일반주거지역"] == {"bcr_max": 60, "far_min": 100, "far_max": 250}
    assert zones["제3종일반주거지역"] == {"bcr_max": 50, "far_min": 100, "far_max": 300}
    assert zones["중심상업지역"] == {"bcr_max": 90, "far_min": 200, "far_max": 1500}
    assert zones["일반상업지역"] == {"bcr_max": 80, "far_min": 200, "far_max": 1300}
    assert zones["일반공업지역"] == {"bcr_max": 70, "far_min": 150, "far_max": 350}
    assert zones["계획관리지역"] == {"bcr_max": 40, "far_min": 50, "far_max": 100}
    assert all(z["far_min"] < z["far_max"] and 0 < z["bcr_max"] <= 90 for z in zones.values())


# --- one parcel ----------------------------------------------------------------


def test_single_parcel_summary(one):
    s = one["summary"]
    assert one["query"] == "금정동 689-14" and one["fetched_at"].startswith("2026-10-01")
    assert s["parcel_count"] == 1 and s["total_area_m2"] == 1014.3 and s["area_complete"]
    assert s["municipality"] == "경기도 군포시"
    assert [z["zone"] for z in s["zoning"]] == ["일반공업지역"]
    assert (s["zoning"][0]["bcr_max"], s["zoning"][0]["far_max"]) == (70, 350)
    district_names = [d["name"] for d in s["districts"]]
    assert "과밀억제권역" in district_names
    assert "도시지역" not in district_names and "일반공업지역" not in district_names  # not repeated
    assert s["roads"] == [{"name": "소로1류(폭 10m~12m)", "relation": "접함"}]
    assert s["missing"] == [] and s["zoning_updated"] == "2026-09-06"


def test_flags_only_for_things_that_need_checking(one):
    flags = one["summary"]["flags"]
    assert any("토지거래계약에관한허가구역" in f for f in flags)
    assert not any("가축사육제한구역" in f for f in flags)  # irrelevant to building design
    assert not any("필지" in f and "하나의 대지" in f for f in flags)  # single parcel


def test_municipality_from_address():
    assert site_facts.municipality("서울특별시 종로구 청운동 1") == "서울특별시"
    assert site_facts.municipality("부산광역시 기장군 기장읍 1") == "부산광역시"
    assert site_facts.municipality("경기도 군포시 금정동 689-14") == "경기도 군포시"
    assert site_facts.municipality("경기도 수원시 영통구 매탄동 10") == "경기도 수원시"
    assert site_facts.municipality("세종특별자치시 조치원읍 신흥리 3") == "세종특별자치시"
    assert site_facts.municipality("강원특별자치도 양양군 현남면 인구리 1") == "강원특별자치도 양양군"


# --- merged parcels --------------------------------------------------------------


def test_merged_parcels_sum_area_and_say_so(merged):
    s = merged["summary"]
    areas = [p["characteristics"]["area_m2"] for p in merged["parcels"]]
    assert s["parcel_count"] == 2 and s["total_area_m2"] == round(sum(areas), 1)
    assert [z["zone"] for z in s["zoning"]] == ["일반공업지역"]
    assert s["zoning"][0]["pnus"] == [P14, P15] and s["zoning"][0]["area_m2"] == s["total_area_m2"]
    assert any("필지 2개" in f and "합병" in f for f in s["flags"])
    assert not any("둘 이상의 용도지역" in f for f in s["flags"])


def test_mixed_zoning_across_parcels_is_flagged(fake_vworld):
    other = {"pnu": "4141010500100010000", "address": "경기도 군포시 금정동 1"}
    mixed_use = {
        "landUses": {
            "field": [
                {"prposAreaDstrcCodeNm": "제2종일반주거지역", "prposAreaDstrcCode": "UQA122",
                 "cnflcAtNm": "포함", "lastUpdtDt": "2026-09-06"},
                {"prposAreaDstrcCodeNm": "제1종지구단위계획구역", "prposAreaDstrcCode": "UQQ300",
                 "cnflcAtNm": "포함", "lastUpdtDt": "2026-09-06"},
                {"prposAreaDstrcCodeNm": "중로2류(폭 15m~20m)", "prposAreaDstrcCode": "UQS220",
                 "cnflcAtNm": "저촉", "lastUpdtDt": "2026-09-06"},
            ]
        }
    }
    real = landapi._http_get

    def http_get(url, params):
        if params.get("pnu") == other["pnu"]:
            if url.endswith("getLandUseAttr"):
                return mixed_use
            return {"landCharacteristicss": {"field": [{"stdrYear": "2025", "stdrMt": "01",
                                                         "lndpclAr": "500", "lndcgrCodeNm": "대"}]}}
        return real(url, params)

    facts = site_facts.build_facts("금정동", candidates(P14) + [other], http_get=http_get, now=NOW)
    s = facts["summary"]
    assert [z["zone"] for z in s["zoning"]] == ["일반공업지역", "제2종일반주거지역"]
    assert s["zoning"][1]["area_m2"] == 500.0 and s["zoning"][1]["pnus"] == [other["pnu"]]
    assert s["total_area_m2"] == 1514.3
    flags = "\n".join(s["flags"])
    assert "둘 이상의 용도지역에 걸침" in flags
    assert "지구단위계획" in flags and "고시" in flags
    assert "중로2류" in flags and "저촉" in flags

    block = site_facts.facts_block(facts, "regulatory")
    assert "일반공업지역 (필지 1개, 1,014.3㎡)" in block
    assert "제2종일반주거지역 (필지 1개, 500.0㎡)" in block


def test_one_parcel_in_two_zones_and_adjacent_districts(fake_vworld):
    """Shape seen on a real parcel (종로구 세종로 1): two zones on one lot, districts merely adjacent."""
    lot = {"pnu": "1111011900100010000", "address": "서울특별시 종로구 세종로 1"}

    def row(name, relation):
        return {"prposAreaDstrcCodeNm": name, "cnflcAtNm": relation, "lastUpdtDt": "2026-09-06"}

    def http_get(url, params):
        if url.endswith("getLandUseAttr"):
            return {"landUses": {"field": [
                row("제1종일반주거지역", "포함"), row("자연녹지지역", "포함"),
                row("개발제한구역", "접함"), row("지구단위계획구역", "접함"),
                row("역사문화환경보존지역", "저촉"), row("건축선", "저촉"),
            ]}}
        return {"landCharacteristicss": {"field": [{"stdrYear": "2026", "stdrMt": "01", "lndpclAr": "1000"}]}}

    facts = site_facts.build_facts("세종로 1", [lot], http_get=http_get, now=NOW)
    s = facts["summary"]
    assert s["municipality"] == "서울특별시"
    assert [(z["zone"], z["partial"]) for z in s["zoning"]] == [
        ("제1종일반주거지역", True), ("자연녹지지역", True)
    ]
    flags = " / ".join(s["flags"])
    assert "둘 이상의 용도지역에 걸침" in flags
    assert "역사문화환경보존지역" in flags and "건축선" in flags
    assert "개발제한구역" not in flags and "지구단위계획" not in flags  # adjacent only
    block = site_facts.facts_block(facts, "regulatory")
    assert "제1종일반주거지역 (필지 일부에 걸침, 면적 비율 미확인)" in block
    assert "개발제한구역(접함)" in block  # still listed, just not flagged
    assert "서울특별시 도시계획조례" in block


# --- partial failure -------------------------------------------------------------


def test_failed_call_is_recorded_as_unknown_not_as_no_regulation(fake_vworld):
    fake_vworld.overrides["getLandUseAttr"] = LandApiError("network", "ReadTimeout")
    facts = site_facts.build_facts("금정동 689-14", candidates(P14), now=NOW)
    s = facts["summary"]
    assert s["missing"] == [
        {"pnu": P14, "address": "경기도 군포시 금정동 689-14", "what": "land_use", "kind": "network"}
    ]
    # Zoning falls back to the land-characteristics record; districts stay unknown.
    assert [z["zone"] for z in s["zoning"]] == ["일반공업지역"] and s["districts"] == []
    block = site_facts.facts_block(facts, "regulatory")
    assert "조회 실패(미확인)" in block and "토지이용계획" in block
    assert s["total_area_m2"] == 1014.3  # the other call still succeeded


def test_all_calls_failing_still_returns_facts_marked_unknown(fake_vworld):
    fake_vworld.overrides["getLandUseAttr"] = LandApiError("network")
    fake_vworld.overrides["getLandCharacteristics"] = LandApiError("network")
    facts = site_facts.build_facts("금정동 689-14", candidates(P14), now=NOW)
    assert facts["summary"]["total_area_m2"] is None and facts["summary"]["zoning"] == []
    assert "용도지역: 미확인" in site_facts.facts_block(facts, "regulatory")
    assert "토지 특성 미확인" in site_facts.facts_block(facts, "physical")


# --- blocks and storage ----------------------------------------------------------


def test_physical_and_regulatory_blocks_split_the_facts(one):
    physical = site_facts.facts_block(one, "physical")
    regulatory = site_facts.facts_block(one, "regulatory")
    assert physical.startswith("SITE FACTS (physical)") and "조회일 2026-10-01" in physical
    assert "1,014.3㎡" in physical and "지목 공장용지" in physical and "현재 건물: (주)혜창" in physical
    assert "건폐율" not in physical and "과밀억제권역" not in physical  # codes are not site_reader's job
    assert "용도지역: 일반공업지역 (전 필지)" in regulatory
    assert "건폐율 법정 상한 70%" in regulatory and "용적률 법정 범위 150~350%" in regulatory
    assert "경기도 군포시 도시계획조례" in regulatory and "verify" in regulatory
    assert "시행령 제84조제1항" in regulatory and "토지이용계획 갱신일 2026-09-06" in regulatory
    assert "소로1류(폭 10m~12m) 접함" in physical and "소로1류(폭 10m~12m) 접함" in regulatory


def test_save_load_round_trip_and_bad_file(tmp_path, one):
    assert site_facts.load_facts(tmp_path) is None
    path = site_facts.save_facts(tmp_path, one)
    assert path.name == "site_facts.json" and site_facts.load_facts(tmp_path) == one
    path.write_text("{broken", encoding="utf-8")
    assert site_facts.load_facts(tmp_path) is None


def test_parse_selection():
    assert site_facts.parse_selection("1", 3) == [0]
    assert site_facts.parse_selection("2, 1,2", 3) == [1, 0]
    assert site_facts.parse_selection("1 3", 3) == [0, 2]
    for bad in ("", "0", "4", "a", "1,x"):
        assert site_facts.parse_selection(bad, 3) is None


# --- experts receive the block -----------------------------------------------------


def _run(agent_id, mock_config, agents, project, scripted):
    agent = harness.agent_by_id(agents, agent_id)
    headers = harness.expected_headers((ROOT / agent["file"]).read_text(encoding="utf-8"))
    provider = scripted(["\n\n".join(f"## {h}\n- x" for h in headers)])
    harness.run_worker_agent(
        "", mock_config, agent, project.read_brief(), [], project.modules_dir, provider=provider
    )
    return provider.calls[0]["messages"][1]["content"]


def test_only_mapped_experts_get_their_block(mock_config, agents, project, scripted, one):
    mock_config["rag"] = {"enabled": False}
    assert "SITE FACTS (" not in _run("site_reader", mock_config, agents, project, scripted)

    site_facts.save_facts(project.path, one)
    site = _run("site_reader", mock_config, agents, project, scripted)
    reg = _run("regulation_checker", mock_config, agents, project, scripted)
    critic = _run("design_critic", mock_config, agents, project, scripted)
    assert "SITE FACTS (physical)" in site and "지목 공장용지" in site and "건폐율 법정" not in site
    assert "SITE FACTS (regulatory)" in reg and "건폐율 법정 상한 70%" in reg
    assert "SITE FACTS (" not in critic
    assert site.index("ORIGINAL PROJECT BRIEF:") < site.index("SITE FACTS (physical)")
    assert site.index("SITE FACTS (physical)") < site.index("RELEVANT EXPERT OUTPUTS:")


def test_broken_facts_file_does_not_block_the_run(mock_config, agents, project, scripted):
    mock_config["rag"] = {"enabled": False}
    site_facts.facts_path(project.path).write_text("{broken", encoding="utf-8")
    assert "SITE FACTS (" not in _run("site_reader", mock_config, agents, project, scripted)


# --- /site command -----------------------------------------------------------------


def _answers(monkeypatch, *replies):
    queue = list(replies)
    monkeypatch.setattr("builtins.input", lambda *_: queue.pop(0))


def test_site_command_without_facts_explains_how(make_session, capsys):
    assert dispatch(make_session(), "/site") == "continue"
    assert "/site 경기도 군포시 금정동 689-14" in capsys.readouterr().out


def test_site_command_looks_up_merged_parcels_and_saves(make_session, fake_vworld, monkeypatch, capsys):
    s = make_session()
    _answers(monkeypatch, "1,2")
    assert dispatch(s, "/site 경기도 군포시 금정동 689") == "continue"
    out = capsys.readouterr().out
    assert "1) 경기도 군포시 금정동 689-14" in out and "일반공업지역" in out and "필지 2개" in out

    facts = site_facts.load_facts(s.project.path)
    assert [p["pnu"] for p in facts["parcels"]] == [P14, P15]
    assert s.history[-1]["content"].startswith("[system] Site facts were looked up")

    assert dispatch(s, "/site") == "continue"  # shows what was saved, no new lookup
    assert "금정동 689-15" in capsys.readouterr().out
    assert sum(1 for url, _ in fake_vworld.calls if url.endswith("/req/search")) == 1


def test_site_command_enter_takes_first_and_zero_cancels(make_session, fake_vworld, monkeypatch):
    s = make_session()
    _answers(monkeypatch, "")
    dispatch(s, "/site 금정동 689")
    assert [p["pnu"] for p in site_facts.load_facts(s.project.path)["parcels"]] == [P14]

    s2 = make_session()
    site_facts.facts_path(s2.project.path).unlink()
    _answers(monkeypatch, "0")
    dispatch(s2, "/site 금정동 689")
    assert site_facts.load_facts(s2.project.path) is None and s2.history == s.history[:0]


def test_site_command_reports_key_and_no_match(make_session, fake_vworld, monkeypatch, capsys):
    s = make_session()
    fake_vworld.overrides["search"] = LandApiError("invalid_key", "등록되지 않은 인증키입니다.")
    dispatch(s, "/site 금정동 689")
    out = capsys.readouterr().out
    assert "키를 거부" in out and "VWORLD_DOMAIN" in out
    assert site_facts.load_facts(s.project.path) is None

    monkeypatch.delenv("VWORLD_API_KEY")
    del fake_vworld.overrides["search"]
    dispatch(s, "/site 금정동 689")
    assert "VWORLD_API_KEY가 없습니다" in capsys.readouterr().out
