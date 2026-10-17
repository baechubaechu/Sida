"""POST /api/law/search — the hub's statute Q&A for the web, no terminal and no network."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sida import providers, webapp
from sida.experts.regulation import law_search
from sida.experts.regulation.rag import Passage


@pytest.fixture
def client(mock_config):
    mock_config["rag"] = {
        "enabled": True,
        "provider": "local_files",
        "agents": {"regulation_checker": "regulation"},
        "collections": {"regulation": {"path": "regulations"}},
        "law_search": {"multi_query": False, "top_k": 6, "max_chars": 3000},
    }
    return TestClient(webapp.create_app(allowed_hosts={"testserver"}))


@pytest.fixture
def model(monkeypatch, scripted):
    """The Conductor model the search asks; queue its replies with model.replies."""
    provider = scripted(["건폐율은 대지면적에 대한 건축면적의 비율입니다. [1]"])
    monkeypatch.setattr(law_search, "conductor_provider", lambda config, api_key: provider)
    return provider


def test_search_returns_answer_and_numbered_sources(client, model, monkeypatch):
    found = [
        Passage(source="건축법 제55조", title="건축물의 건폐율", text="대지면적에 대한 건축면적의 비율", score=1.0),
        Passage(source="건축법 제56조", title="건축물의 용적률", text="x" * 950, score=0.5),
    ]
    monkeypatch.setattr(law_search, "retrieve_passages", lambda *a, **k: found)
    r = client.post("/api/law/search", json={"question": "  건폐율이란?  "})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "건폐율이란?"
    assert body["answer"].startswith("건폐율은")
    assert [s["index"] for s in body["sources"]] == [1, 2]
    assert body["sources"][0] == {
        "index": 1,
        "title": "건축물의 건폐율",
        "source": "건축법 제55조",
        "text": "대지면적에 대한 건축면적의 비율",
        "truncated": False,
    }
    assert body["sources"][1]["truncated"] is True
    assert body["warning"] == ""
    # The model saw the retrieved articles, not just the question.
    assert "건축법 제55조" in model.calls[0]["messages"][-1]["content"]


def test_no_articles_found_says_why(client, model, monkeypatch):
    monkeypatch.setattr(law_search, "retrieve_passages", lambda *a, **k: [])
    monkeypatch.setattr(law_search, "last_retrieval_warning", lambda: "법제처 검색 결과 없음")
    body = client.post("/api/law/search", json={"question": "경사로 기준?"}).json()
    assert body["sources"] == [] and body["warning"] == "법제처 검색 결과 없음"


def test_search_is_refused_when_statute_search_is_off(client, mock_config, model):
    mock_config["rag"]["enabled"] = False
    r = client.post("/api/law/search", json={"question": "건폐율이란?"})
    assert r.status_code == 400 and "off" in r.json()["detail"]
    assert model.calls == []  # never answered from the model's memory alone


@pytest.mark.parametrize("question", ["", "   ", "가" * 501])
def test_empty_or_long_question_is_400(client, model, question):
    assert client.post("/api/law/search", json={"question": question}).status_code == 400
    assert model.calls == []


def test_model_failure_is_502(client, monkeypatch):
    class Failing:
        def chat(self, *a, **k):
            raise providers.LLMError("model unreachable")

    monkeypatch.setattr(law_search, "conductor_provider", lambda config, api_key: Failing())
    monkeypatch.setattr(law_search, "retrieve_passages", lambda *a, **k: [])
    r = client.post("/api/law/search", json={"question": "건폐율이란?"})
    assert r.status_code == 502 and "unreachable" in r.json()["detail"]
