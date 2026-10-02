"""lawapi.py and the 법제처 retrieval provider, against recorded law.go.kr responses."""

from __future__ import annotations

import pytest
import requests

from sida import harness
from sida.experts.regulation import lawapi, rag
from sida.experts.regulation.lawapi import LawApiError
from sida.experts.site import site_facts
from tests.conftest import LAW_FIXTURES, REAL_LAW_HTTP_GET, ROOT


def body(name: str) -> str:
    return (LAW_FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fake_law(monkeypatch):
    """Serve recorded aiSearch replies; records (query, scope) for every call."""
    calls: list[tuple[str, int]] = []
    state = {"articles": "articles_stairs.json", "error": None}

    def http_get(url, params):
        calls.append((params["query"], params["search"]))
        assert url == lawapi.SEARCH_URL and params["target"] == "aiSearch" and params["OC"] == "test-oc"
        if state["error"] is not None:
            raise state["error"]
        if params["search"] == lawapi.SCOPE_ANNEXES:
            return body("annex_building_uses.json")
        if "공업" in params["query"]:
            return body("articles_industrial.json")
        return body(state["articles"])

    monkeypatch.setattr(lawapi, "_http_get", http_get)
    http_get.calls = calls
    http_get.state = state
    return http_get


# --- client -------------------------------------------------------------------


def test_ai_search_returns_articles_with_text(fake_law):
    items = lawapi.ai_search("직통계단 설치 기준")
    labels = [f"{i['law']} {i['label']}" for i in items]
    assert "건축법 시행령 제34조" in labels
    assert "건축물의 피난ㆍ방화구조 등의 기준에 관한 규칙 제8조" in labels
    first = items[0]
    assert first["kind"] == "article" and first["title"] and len(first["text"]) > 100
    assert "\n①" in first["text"] or first["text"].startswith("제")  # 항마다 줄을 나눔
    assert first["effective"].count("-") == 2


def test_ai_search_annexes_are_title_only(fake_law):
    items = lawapi.ai_search("용도별 건축물의 종류 다세대주택", scope=lawapi.SCOPE_ANNEXES)
    assert items[0] == {
        "kind": "annex",
        "law": "건축법 시행령",
        "label": "별표 1",
        "title": "용도별 건축물의 종류(제3조의5 관련)",
        "text": "",
        "effective": items[0]["effective"],
    }


def test_article_label_and_text_tidying():
    assert lawapi.article_label("0034", "00") == "제34조"
    assert lawapi.article_label("0027", "02") == "제27조의2"
    assert lawapi.tidy_article_text("제1조(목적)① 가.② 나.") == "제1조(목적)\n① 가.\n② 나."


def test_identical_calls_are_cached_and_long_queries_cut(fake_law):
    lawapi.ai_search("직통계단 설치 기준")
    lawapi.ai_search("직통계단   설치 기준")  # same after whitespace normalization
    assert len(fake_law.calls) == 1
    lawapi.ai_search("가" * 500)
    assert len(fake_law.calls[-1][0]) == lawapi.MAX_QUERY_CHARS
    assert lawapi.ai_search("   ") == [] and len(fake_law.calls) == 2


def test_no_key_and_rejections(fake_law, monkeypatch):
    fake_law.state["articles"] = "denied.json"
    with pytest.raises(LawApiError) as info:
        lawapi.ai_search("직통계단")
    assert info.value.kind == "denied" and "검증에 실패" in info.value.detail

    fake_law.state["articles"] = "not_applied.html"
    with pytest.raises(LawApiError) as info:
        lawapi.ai_search("피난계단")
    assert (info.value.kind, info.value.detail) == ("denied", "not_applied")

    fake_law.state["articles"] = "articles_empty.json"
    assert lawapi.ai_search("long english text") == []

    monkeypatch.delenv("LAW_OPEN_API_OC")
    before = len(fake_law.calls)
    with pytest.raises(LawApiError) as info:
        lawapi.ai_search("방화구획")
    assert info.value.kind == "no_key" and len(fake_law.calls) == before


def test_http_get_error_never_carries_the_oc(monkeypatch):
    monkeypatch.setattr(lawapi.time, "sleep", lambda *_: None)

    def down(url, params, timeout):
        raise requests.ConnectionError(f"{url}?OC={params['OC']}")

    monkeypatch.setattr(lawapi.requests, "get", down)
    with pytest.raises(LawApiError) as info:
        REAL_LAW_HTTP_GET(lawapi.SEARCH_URL, {"OC": "SECRET-OC"})
    assert info.value.kind == "network" and "SECRET-OC" not in str(info.value)


# --- provider -------------------------------------------------------------------


def law_config(mock_config):
    mock_config["rag"] = {
        "enabled": True,
        "provider": "lawgokr",
        "agents": {"regulation_checker": "regulation"},
    }
    return mock_config


def test_provider_turns_articles_into_cited_passages(mock_config, fake_law):
    passages = rag.retrieve_passages(law_config(mock_config), "regulation", "직통계단 설치 기준", top_k=4)
    assert rag.last_retrieval_warning() is None
    sources = [p.source for p in passages]
    assert "law.go.kr/건축법 시행령 제34조" in sources
    article = next(p for p in passages if p.source.endswith("제34조"))
    assert article.title.startswith("건축법 시행령 제34조 (직통계단의 설치)") and "[시행 " in article.title
    assert all(len(p.text) <= rag.LAW_PASSAGE_CHARS for p in passages)
    assert 0 < len(passages) <= 4
    assert all(scope == lawapi.SCOPE_ARTICLES for _q, scope in fake_law.calls)  # annexes not injected
    assert [p.score for p in passages] == sorted((p.score for p in passages), reverse=True)
    block = rag.format_passages(passages, collection="regulation")
    assert "source: law.go.kr/건축법 시행령 제34조" in block


def test_provider_reports_why_it_returned_nothing(mock_config, fake_law, monkeypatch):
    cfg = law_config(mock_config)
    fake_law.state["articles"] = "not_applied.html"
    assert rag.retrieve_passages(cfg, "regulation", "직통계단") == []
    assert "지능형 법령검색" in rag.last_retrieval_warning()

    fake_law.state["articles"] = "denied.json"
    assert rag.retrieve_passages(cfg, "regulation", "피난계단") == []
    assert "거부" in rag.last_retrieval_warning()

    fake_law.state["error"] = LawApiError("network", "ReadTimeout")
    assert rag.retrieve_passages(cfg, "regulation", "방화구획") == []
    assert "law.go.kr" in rag.last_retrieval_warning()

    fake_law.state["error"] = None
    monkeypatch.delenv("LAW_OPEN_API_OC")
    assert rag.retrieve_passages(cfg, "regulation", "내화구조") == []
    assert "LAW_OPEN_API_OC" in rag.last_retrieval_warning()
    assert rag.key_missing(rag.rag_settings(cfg)) is True


# --- focused questions for a project ---------------------------------------------


def facts(zones, districts=()):
    return {
        "summary": {
            "zoning": [{"zone": z} for z in zones],
            "districts": [{"name": n, "relation": r} for n, r in districts],
        }
    }


def test_focus_queries_come_from_site_facts_then_korean_brief():
    site = facts(
        ["일반공업지역"],
        [("과밀억제권역", "포함"), ("제1종지구단위계획구역", "포함"), ("개발제한구역", "접함"),
         ("토지거래계약에관한허가구역", "포함"), ("대공방어협조구역(위탁고도:54-236m)", "포함")],
    )
    brief = "# Brief\n\n## Project Type\n환승역 복합시설\n\n## Core Problem\n- 철도가 도시를 가른다\n"
    queries = rag.focus_queries(brief, site)
    assert queries[:2] == ["일반공업지역에서 건축할 수 있는 건축물", "일반공업지역 건폐율 용적률"]
    assert "제1종지구단위계획구역 건축 제한" in queries
    assert "대공방어협조구역 건축 제한" in queries  # the parenthetical is dropped
    assert not any("개발제한구역" in q or "토지거래" in q or "과밀억제" in q for q in queries)
    assert len(queries) <= rag.LAW_MAX_QUERIES and all(len(q) <= 60 for q in queries)

    assert rag.focus_queries(brief, None) == ["환승역 복합시설 건축 기준", "철도가 도시를 가른다"]


def test_focus_queries_skip_english_and_long_brief_lines():
    brief = (ROOT / "input" / "geumjeong_station_brief.md").read_text(encoding="utf-8")
    assert rag.focus_queries(brief, None) == []  # English brief, no site facts → nothing to ask
    long_ko = "# B\n\n## Project Type\n" + "아주 긴 설명 " * 20 + "\n"
    assert rag.focus_queries(long_ko, None) == []


# --- expert run --------------------------------------------------------------------


def _run_regulation(mock_config, agents, project, scripted):
    agent = harness.agent_by_id(agents, "regulation_checker")
    headers = harness.expected_headers((ROOT / agent["file"]).read_text(encoding="utf-8"))
    provider = scripted(["\n\n".join(f"## {h}\n- x" for h in headers)])
    harness.run_worker_agent(
        "", mock_config, agent, project.read_brief(), [], project.modules_dir, provider=provider
    )
    return provider.calls[0]["messages"][1]["content"]


def test_regulation_checker_searches_with_zoning_from_site_facts(
    mock_config, agents, project, scripted, fake_law, fake_vworld, capsys
):
    law_config(mock_config)
    parcel = {"pnu": "4141010500106890014", "address": "경기도 군포시 금정동 689-14"}
    site_facts.save_facts(project.path, site_facts.build_facts("금정동 689-14", [parcel]))

    prompt = _run_regulation(mock_config, agents, project, scripted)
    asked = [q for q, scope in fake_law.calls if scope == lawapi.SCOPE_ARTICLES]
    assert asked[0] == "일반공업지역에서 건축할 수 있는 건축물"
    assert all(len(q) <= 60 for q in asked)  # never the whole brief
    assert "RETRIEVED KNOWLEDGE (regulation)" in prompt
    assert "source: law.go.kr/국토의 계획 및 이용에 관한 법률 시행령 제71조" in prompt
    assert "[rag]" not in capsys.readouterr().err


def test_regulation_checker_without_anything_to_search_says_so(
    mock_config, agents, project, scripted, fake_law, capsys
):
    law_config(mock_config)  # English brief, no site facts
    prompt = _run_regulation(mock_config, agents, project, scripted)
    assert fake_law.calls == [] and "RETRIEVED KNOWLEDGE (regulation)" not in prompt
    err = capsys.readouterr().err
    assert "[rag]" in err and "/site" in err
