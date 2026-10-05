"""site_facts.py — parcels → one site, statutory limits, flags, and the blocks experts receive."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sida import config as sida_config
from sida import worker
from sida.commands import dispatch
from sida.experts.site import landapi, site_facts
from sida.experts.site.landapi import LandApiError
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
    agent = sida_config.agent_by_id(agents, agent_id)
    headers = worker.expected_headers((ROOT / agent["file"]).read_text(encoding="utf-8"))
    provider = scripted(["\n\n".join(f"## {h}\n- x" for h in headers)])
    worker.run_worker_agent(
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


# --- the municipality's ordinance ----------------------------------------------------


def test_municipality_is_the_ordinance_making_body():
    assert site_facts.municipality("제주특별자치도 제주시 연동 100") == "제주특별자치도"
    assert site_facts.municipality("부산광역시 기장군 기장읍 1") == "부산광역시"
    assert site_facts.municipality("강원특별자치도 평창군 평창읍 1") == "강원특별자치도 평창군"
    assert site_facts.municipality("경기도 수원시 장안구 정자동 1") == "경기도 수원시"
    assert site_facts.municipality("전남광주통합특별시 북구 용봉동 300") == "광주광역시"  # former body's ordinance
    assert site_facts.municipality("전남광주통합특별시 여수시 학동 1") == "전남광주통합특별시 여수시"


def test_ordinance_is_attached_and_quoted_for_regulatory_experts(one, fake_ordinance):
    before = "\n".join(site_facts.regulatory_lines(one))
    assert "조회하지 않음(미확인)" in before and site_facts.ordinance_block(one) == ""

    site_facts.attach_ordinance(one)
    assert one["ordinance"]["name"] == "군포시 도시계획 조례"
    assert [c["query"] for c in fake_ordinance.calls if "query" in c] == ["군포시 도시계획 조례"]
    line = "\n".join(site_facts.regulatory_lines(one))
    assert "적용 조례: 군포시 도시계획 조례 (시행 2025-10-10)" in line
    assert "제49조(용도지역안에서의 건폐율), 제53조(용도지역 안에서의 용적률)" in line
    assert "건폐율 법정 상한 70%" in line  # the statutory range is still shown next to it

    block = site_facts.ordinance_block(one)
    assert block.startswith("RETRIEVED KNOWLEDGE (local ordinance)")
    assert "이 대지의 용도지역: 일반공업지역" in block
    assert "source: 군포시 도시계획 조례 제53조 (시행 2025-10-10)" in block
    assert "12. 일반공업지역 : 100분의 350 이하" in block
    # only this site's zone line is sent; the other 15 zones are left out and said so
    assert "11. 전용공업지역" not in block and "(다른 용도지역의 호 15개 생략)" in block
    assert "② 제1항에도 불구하고" in block  # the provisos after the list stay
    # relaxations and tightening: titles only, until the designer asks for the text
    assert "[설계로 얻을 수 있는 완화(선택지)" in block and "제52조(건폐율의 완화)" in block
    assert "[지자체가 구역을 지정했을 때만 적용" in block and "제51조(건폐율의 강화)" in block
    assert "source: 군포시 도시계획 조례 제52조" not in block and "원문은 포함하지 않음" in block
    assert "제34조" not in block  # 경관지구 article: this site is not in one
    assert len(block) < 3200
    assert "조례" not in "\n".join(site_facts.physical_lines(one))


def test_failed_ordinance_lookup_is_shown_as_unknown_not_guessed(one, fake_ordinance):
    from sida.experts.regulation.lawapi import LawApiError

    fake_ordinance.overrides["search"] = LawApiError("network", "ConnectTimeout")
    site_facts.attach_ordinance(one)
    line = "\n".join(site_facts.regulatory_lines(one))
    assert "조례 조문: 미확인(법제처 연결 실패)" in line and "추정하지 말고" in line
    assert site_facts.ordinance_block(one) == "" and site_facts.ordinance_text(one) == ""

    fake_ordinance.overrides["search"] = '{"OrdinSearch": {"totalCnt": "0"}}'
    site_facts.attach_ordinance(one)
    assert "도시·군계획 조례를 찾지 못함" in "\n".join(site_facts.regulatory_lines(one))


def test_only_the_regulatory_expert_receives_the_ordinance(
    mock_config, agents, project, scripted, one, fake_ordinance
):
    mock_config["rag"] = {"enabled": False}  # works without statute search
    site_facts.save_facts(project.path, site_facts.attach_ordinance(one))
    reg = _run("regulation_checker", mock_config, agents, project, scripted)
    site = _run("site_reader", mock_config, agents, project, scripted)
    assert "RETRIEVED KNOWLEDGE (local ordinance)" in reg and "100분의 350 이하" in reg
    assert reg.index("RELEVANT EXPERT OUTPUTS:") < reg.index("RETRIEVED KNOWLEDGE (local ordinance)")
    assert "RETRIEVED KNOWLEDGE (local ordinance)" not in site and "100분의 350" not in site


def test_site_command_saves_and_shows_the_ordinance(make_session, fake_vworld, monkeypatch, capsys):
    s = make_session()
    assert dispatch(s, "/site 조례") == "continue"
    assert "저장된 조례 조문이 없습니다" in capsys.readouterr().out

    _answers(monkeypatch, "1")
    dispatch(s, "/site 경기도 군포시 금정동 689")
    out = capsys.readouterr().out
    assert "경기도 군포시의 도시·군계획 조례를 찾는 중" in out
    assert "적용 조례: 군포시 도시계획 조례 (시행 2025-10-10)" in out
    assert site_facts.load_facts(s.project.path)["ordinance"]["mst"] == "2077621"

    dispatch(s, "/site 조례")
    out = capsys.readouterr().out
    assert "[대지 위치로 정해지는 것]" in out and "[설계 내용으로 얻을 수 있는 완화]" in out
    assert "[행정이 따로 지정하는 것]" in out and "제51조 건폐율의 강화" in out
    assert "(이 대지가 속한 지구·구역은 이 조문에 나오지 않음)" in out

    dispatch(s, "/site 조례 제49조")
    assert "  12. 일반공업지역 : 100분의 70 이하" in capsys.readouterr().out
    dispatch(s, "/site 조례 제999조")
    assert "그런 조문이 없습니다" in capsys.readouterr().out

    dispatch(s, "/site 숨김 제52조")
    assert "제52조" in site_facts.load_facts(s.project.path)["ordinance"]["dismissed"]
    dispatch(s, "/site 조례")
    assert "숨김 제52조 건폐율의 완화" in capsys.readouterr().out
    _answers(monkeypatch, "1")
    dispatch(s, "/site 경기도 군포시 금정동 689")  # looking the site up again keeps the choice
    assert site_facts.load_facts(s.project.path)["ordinance"]["dismissed"] == ["제52조"]
    dispatch(s, "/site 표시 제52조")
    assert site_facts.load_facts(s.project.path)["ordinance"]["dismissed"] == []
    capsys.readouterr()
    dispatch(s, "/site 숨김 제999조")
    assert "그런 조문이 없습니다" in capsys.readouterr().out


def test_ordinance_figures_are_shown_next_to_the_quoted_line(one, fake_ordinance):
    site_facts.attach_ordinance(one)
    values = one["ordinance"]["values"]["일반공업지역"]
    assert values["bcr"]["value"] == 70 and values["far"]["value"] == 350
    text = "\n".join(site_facts.regulatory_lines(one))
    assert "조례값(일반공업지역): 건폐율 70% 이하: 제49조 「일반공업지역 : 100분의 70 이하」" in text
    assert "용적률 350% 이하: 제53조 「일반공업지역 : 100분의 350 이하」" in text
    assert "조례값" in site_facts.describe(one) and "조례값" not in "\n".join(site_facts.physical_lines(one))

    # a proviso, an unclear item, an out-of-range reading and a missing line are all said so
    values["far"] = {**values["far"], "conditional": True}
    assert "용적률 350% 이하 (단서·예외가 붙어 있음 — 원문 확인)" in "\n".join(site_facts.regulatory_lines(one))
    values["far"] = {**values["far"], "value": None}
    assert "용적률 — 한 가지 수치로 정해져 있지 않음, 원문 확인: 제53조" in "\n".join(site_facts.regulatory_lines(one))
    values["far"] = {**values["far"], "out_of_range": True}
    assert "법정 범위를 벗어나 표시하지 않음" in "\n".join(site_facts.regulatory_lines(one))
    values["far"] = None
    assert "용적률 — 조문과 별표에서 이 용도지역의 줄을 찾지 못함" in "\n".join(site_facts.regulatory_lines(one))


# --- every related article, in three groups, dismissible ------------------------------


def test_options_view_groups_every_article_and_marks_what_applies(one, fake_ordinance):
    assert site_facts.ordinance_options(None)["available"] is False
    assert site_facts.ordinance_options(one)["available"] is False  # not looked up yet

    site_facts.attach_ordinance(one)
    view = site_facts.ordinance_options(one)
    assert view["available"] and view["name"] == "군포시 도시계획 조례" and view["error"] is None
    assert view["base"][0]["zone"] == "일반공업지역" and view["base"][0]["bcr"]["value"] == 70
    assert [a["label"] for a in view["articles"]] == ["제49조", "제53조"]
    assert "\n  12. 일반공업지역 : 100분의 70 이하" in view["articles"][0]["text"]

    groups = {g["id"]: g for g in view["groups"]}
    assert list(groups) == ["site", "design", "admin"] and all(g["title"] and g["note"] for g in view["groups"])
    listed = sorted(i["label"] for g in view["groups"] for i in g["items"])
    assert listed == sorted(r["label"] for r in one["ordinance"]["related"])  # nothing filtered out
    assert all(i["text"] for g in view["groups"] for i in g["items"])
    assert all(i["applies"] is False for i in groups["site"]["items"])  # 금정동 689: no such district
    assert all(i["applies"] is None for i in groups["design"]["items"] + groups["admin"]["items"])

    # a site inside a 경관지구: that article applies, is named, and comes first
    one["summary"]["districts"].append({"name": "자연경관지구", "relation": "포함"})
    one["summary"]["districts"].append({"name": "취락지구", "relation": "접함"})  # next to: not in
    site = {i["label"]: i for i in site_facts.ordinance_options(one)["groups"][0]["items"]}
    assert site["제34조"]["applies"] is True and site["제34조"]["matched"] == ["자연경관지구"]
    assert site["제50조"]["applies"] is False  # lists 취락지구, but the site is only next to one
    assert next(iter(site)) == "제34조"
    assert "이 대지가 속한 지구·구역의 조문" in site_facts.ordinance_block(one)
    assert "제34조 (자연ㆍ특화경관지구안에서의 건폐율)" in site_facts.ordinance_block(one)


def test_dismissed_options_are_marked_and_left_out_of_the_expert_block(project, one, fake_ordinance):
    site_facts.save_facts(project.path, site_facts.attach_ordinance(one))
    assert "제52조(건폐율의 완화)" in site_facts.ordinance_block(site_facts.load_facts(project.path))

    view = site_facts.set_option_dismissed(project.path, "제52조", True)
    item = next(i for g in view["groups"] for i in g["items"] if i["id"] == "제52조")
    assert item["dismissed"] is True and item["text"]  # still listed, with its text
    saved = site_facts.load_facts(project.path)
    assert saved["ordinance"]["dismissed"] == ["제52조"]
    assert "제52조(건폐율의 완화)" not in site_facts.ordinance_block(saved)  # not even its title
    assert "제55조" in site_facts.ordinance_block(saved)  # the others are untouched

    site_facts.set_option_dismissed(project.path, "제52조", True)  # twice is the same as once
    assert site_facts.load_facts(project.path)["ordinance"]["dismissed"] == ["제52조"]
    view = site_facts.set_option_dismissed(project.path, "제52조", False)
    assert not any(i["dismissed"] for g in view["groups"] for i in g["items"])
    with pytest.raises(ValueError):
        site_facts.set_option_dismissed(project.path, "제49조", True)  # a base article cannot be hidden
    with pytest.raises(ValueError):
        site_facts.set_option_dismissed(project.path, "제999조", True)


def test_experts_get_the_full_text_only_of_options_the_designer_picked(project, one, fake_ordinance):
    site_facts.save_facts(project.path, site_facts.attach_ordinance(one))

    view = site_facts.set_option(project.path, "제52조", detailed=True)
    picked = next(i for g in view["groups"] for i in g["items"] if i["id"] == "제52조")
    assert picked["detailed"] is True and picked["dismissed"] is False
    block = site_facts.ordinance_block(site_facts.load_facts(project.path))
    assert "설계자가 검토를 요청한 조문의 원문:" in block
    assert "source: 군포시 도시계획 조례 제52조 (건폐율의 완화)" in block and "제52조(건폐율의 완화)\n①" in block
    assert "source: 군포시 도시계획 조례 제55조" not in block and "제55조(" in block  # still title only

    # hiding wins over picking; un-hiding brings the pick back
    hidden = site_facts.set_option(project.path, "제52조", dismissed=True)
    item = next(i for g in hidden["groups"] for i in g["items"] if i["id"] == "제52조")
    assert item["dismissed"] is True and item["detailed"] is False
    assert "건폐율의 완화" not in site_facts.ordinance_block(site_facts.load_facts(project.path))
    site_facts.set_option(project.path, "제52조", dismissed=False)
    assert "source: 군포시 도시계획 조례 제52조" in site_facts.ordinance_block(site_facts.load_facts(project.path))
    site_facts.set_option(project.path, "제52조", detailed=False)
    assert "원문은 포함하지 않음" in site_facts.ordinance_block(site_facts.load_facts(project.path))


def test_applied_district_article_is_cut_to_the_paragraphs_about_ratios(one, fake_ordinance):
    site_facts.attach_ordinance(one)
    one["summary"]["districts"].append({"name": "자연경관지구", "relation": "포함"})
    for r in one["ordinance"]["related"]:
        if r["label"] == "제34조":
            r["text"] = ("제34조(자연경관지구 안에서의 건축제한)① 다음 건축물을 건축하여서는 아니된다.1. 판매시설2. 공장"
                         "② 건폐율은 30퍼센트 이하로 한다.③ 건축물의 높이는 3층 이하로 한다.")
    block = site_facts.ordinance_block(one)
    assert "— 해당: 자연경관지구" in block and "② 건폐율은 30퍼센트 이하로 한다." in block
    assert "판매시설" not in block and "3층 이하" not in block
    assert "(건폐율·용적률을 다루지 않는 항은 생략)" in block
    full = site_facts.ordinance_options(one)["groups"][0]["items"][0]["text"]
    assert "판매시설" in full and "3층 이하" in full  # the designer still sees all of it
