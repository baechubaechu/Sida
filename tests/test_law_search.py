from __future__ import annotations

from law_search import (
    answer_law_question,
    build_law_messages,
    build_law_queries,
    default_collection,
    merge_passages,
)
from rag import Passage, format_passages


def test_build_law_messages_includes_knowledge():
    msgs = build_law_messages("건폐율?", "RETRIEVED…\nsource: a.md", lang="ko", history=[])
    assert msgs[0]["role"] == "system"
    assert "건축" in msgs[0]["content"]
    assert msgs[-1]["role"] == "user"
    assert "건폐율?" in msgs[-1]["content"]
    assert "source: a.md" in msgs[-1]["content"]


def test_build_law_queries_slope_synonyms_current_question_only():
    qs = build_law_queries(
        "주차장법 시행규칙 부설주차장 경사로 기준?",
        history=[{"role": "user", "content": "이 이전 질문은 무시되어야 함"}],
    )
    assert all("무시" not in q for q in qs)
    assert any("구배" in q or "종단경사" in q for q in qs)
    # prior turn must not be spliced into retrieval queries
    assert not any("무시되어야" in q for q in qs)


def test_merge_passages_prefers_higher_score():
    a = Passage("a", "A", "short", 0.5)
    b = Passage("a", "A", "longer text here", 0.9)
    c = Passage("c", "C", "other", 0.2)
    out = merge_passages([[a, c], [b]], limit=5)
    assert out[0].source == "a" and out[0].score == 0.9


def test_default_collection_from_config(mock_config):
    assert default_collection(mock_config) == "regulation"


def test_answer_law_question_uses_retriever(mock_config, scripted, monkeypatch):
    mock_config["rag"] = {
        "enabled": True,
        "provider": "local_files",
        "agents": {"regulation_checker": "regulation"},
        "collections": {"regulation": {"path": "regulations"}},
        "law_search": {"multi_query": False, "top_k": 6, "max_chars": 3000},
    }
    passages = [Passage(source="x.md", title="건폐율", text="건폐율은 …", score=1.0)]
    monkeypatch.setattr("law_search.retrieve_passages", lambda *a, **k: passages)
    provider = scripted(["조문은 출처에 따릅니다. (source: x.md)"])
    reply, got = answer_law_question(
        mock_config, "", "건폐율이란?", provider=provider, collection="regulation"
    )
    assert "조문" in reply
    assert got == passages
    assert any("RETRIEVED" in m.get("content", "") for m in provider.calls[0]["messages"])


def test_hub_law_returns_to_menu(mock_config, monkeypatch):
    import hub

    called = {"n": 0}

    def fake_law(cfg):
        called["n"] += 1

    monkeypatch.setattr(hub, "load_config", lambda *a, **k: mock_config)
    monkeypatch.setattr(hub, "run_law_search", fake_law)
    it = iter(["l", "q"])
    monkeypatch.setattr("builtins.input", lambda *_: next(it))
    assert hub.project_hub() is None
    assert called["n"] == 1


def test_format_passages_still_works():
    text = format_passages(
        [Passage("a.md", "A", "body", 0.5)], collection="regulation"
    )
    assert "RETRIEVED KNOWLEDGE (regulation)" in text
    assert "source: a.md" in text
