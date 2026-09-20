"""RAG settings, local-file retrieval, worker prompt injection."""

from __future__ import annotations

import harness
import rag
from harness import build_worker_prompt, expected_headers, run_worker_agent
from tests.conftest import ROOT


def test_rag_settings_defaults(mock_config):
    s = rag.rag_settings(mock_config)
    assert s["enabled"] is False
    assert s["provider"] == "http"
    assert s["path"] == "/v1/retrieve"
    assert s["agents"]["regulation_checker"] == "regulation"
    assert s["api_key_env"] == "SIDA_RAG_API_KEY"


def test_retrieve_disabled_returns_empty(mock_config):
    mock_config["rag"] = {"enabled": False}
    agent = {"id": "regulation_checker"}
    assert rag.retrieve_for_agent(mock_config, agent, "철도 하천 건축선") == ""


def test_local_retriever_ranks_railway_for_station_query(tmp_path):
    folder = tmp_path / "regulations"
    folder.mkdir()
    (folder / "rail.md").write_text(
        "# 철도 인접\n\n## 이격\n철도보호지구와 도시철도 역사 인접 건축 이격.\n",
        encoding="utf-8",
    )
    (folder / "stream.md").write_text(
        "# 하천\n\n## 구역\n하천구역과 수변 완충.\n",
        encoding="utf-8",
    )
    (folder / "_draft.md").write_text("# ignore me\n철도\n", encoding="utf-8")
    engine = rag.LocalFileRetriever(tmp_path)
    hits = engine.retrieve(
        "regulation",
        "금정역 철도 인프라 도시철도 환승",
        top_k=3,
        max_chars=4000,
        folder=folder,
    )
    assert hits and hits[0].source.startswith("rail")
    assert all(not p.source.startswith("_") for p in hits)


def test_format_passages_includes_source():
    block = rag.format_passages(
        [rag.Passage(source="kr_x.md", title="X", text="본문 숫자 10m", score=1.0)],
        collection="regulation",
    )
    assert "RETRIEVED KNOWLEDGE" in block
    assert "source: kr_x.md" in block
    assert "본문 숫자 10m" in block


def test_build_retrieval_query_truncates():
    q = rag.build_retrieval_query("brief " * 1000, project_state="state", max_chars=200)
    assert len(q) <= 200


def test_worker_prompt_includes_knowledge_block():
    full = build_worker_prompt(
        "AGENT",
        "BRIEF",
        "(none yet)",
        knowledge_block="RETRIEVED KNOWLEDGE (regulation)\n\nsource: a.md\n\n10m",
    )
    assert "RETRIEVED KNOWLEDGE" in full and "source: a.md" in full
    assert "prefer it for numeric limits" in full.lower() or "RETRIEVED KNOWLEDGE" in full


def test_run_worker_injects_rag_when_enabled(mock_config, agents, project, scripted, monkeypatch):
    mock_config["rag"] = {
        "enabled": True,
        "provider": "local_files",
        "knowledge_dir": str(ROOT / "knowledge"),
        "agents": {"regulation_checker": "regulation"},
        "collections": {"regulation": {"path": "regulations", "top_k": 4, "max_chars": 3000}},
    }
    reg = harness.agent_by_id(agents, "regulation_checker")
    hs = expected_headers((ROOT / reg["file"]).read_text(encoding="utf-8"))
    assert "Sources Used" in hs
    provider = scripted(["\n\n".join(f"## {h}\n- x" for h in hs)])
    # Seed site-ish query terms via brief override
    brief = project.read_brief() + "\n\n철도 하천 환승역 인접\n"
    run_worker_agent(
        "",
        mock_config,
        reg,
        brief,
        [],
        project.modules_dir,
        provider=provider,
        project_state=project.read_state(),
    )
    sent = provider.calls[0]["messages"][-1]["content"]
    assert "RETRIEVED KNOWLEDGE (regulation)" in sent
    assert "source:" in sent


def test_run_worker_skips_rag_when_disabled(mock_config, agents, project, scripted):
    mock_config["rag"] = {"enabled": False}
    reg = harness.agent_by_id(agents, "regulation_checker")
    hs = expected_headers((ROOT / reg["file"]).read_text(encoding="utf-8"))
    provider = scripted(["\n\n".join(f"## {h}\n- x" for h in hs)])
    run_worker_agent(
        "", mock_config, reg, project.read_brief(), [], project.modules_dir, provider=provider
    )
    sent = provider.calls[0]["messages"][-1]["content"]
    # Prompt mentions the phrase; the injected block header is unique
    assert "RETRIEVED KNOWLEDGE (regulation)" not in sent
    assert "source: kr_" not in sent


def test_scaffold_corpus_exists():
    folder = ROOT / "knowledge" / "regulations"
    files = list(folder.glob("kr_*.md"))
    assert len(files) >= 3
    chunks = rag.load_markdown_corpus(folder)
    assert any("철도" in c[2] for c in chunks)


def test_build_retrieve_request_matches_example_schema():
    import json

    example = json.loads((ROOT / "examples" / "rag_retrieve_request.json").read_text(encoding="utf-8"))
    body = rag.build_retrieve_request(
        collection="regulation",
        query="q",
        top_k=6,
        max_chars=6000,
        agent_id="regulation_checker",
        project_brief="BRIEF",
        project_state="STATE",
        expert_outputs="OUT",
        lang="ko",
    )
    assert body["api_version"] == rag.API_VERSION == example["api_version"]
    assert set(body.keys()) == set(example.keys())
    assert set(body["context"].keys()) == {"brief", "project_state", "expert_outputs"}
    assert body["context"]["brief"] == "BRIEF"


def test_parse_retrieve_response_aliases():
    passages = rag.parse_retrieve_response(
        {"results": [{"id": "a.md", "content": "본문", "score": "0.5"}]}
    )
    assert len(passages) == 1
    assert passages[0].source == "a.md" and passages[0].text == "본문" and passages[0].score == 0.5
    assert rag.parse_retrieve_response({"passages": []}) == []
    assert rag.parse_retrieve_response("nope") == []


def test_http_retriever_posts_context_and_parses(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return json.loads(
                (ROOT / "examples" / "rag_retrieve_response.json").read_text(encoding="utf-8")
            )

    import json

    calls = []

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return FakeResp()

    engine = rag.HttpApiRetriever(
        "https://rag.example.com",
        api_key="secret",
        agent_id="regulation_checker",
        project_brief="BRIEF TEXT",
        project_state="STATE TEXT",
        expert_outputs="SITE TEXT",
        session=FakeSession(),
    )
    hits = engine.retrieve("regulation", "철도 하천", top_k=4, max_chars=3000)
    assert len(hits) == 2 and hits[0].source.startswith("kr_railway")
    assert calls[0]["url"] == "https://rag.example.com/v1/retrieve"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret"
    req = calls[0]["json"]
    assert req["api_version"] == "sida.rag.v1"
    assert req["context"]["brief"] == "BRIEF TEXT"
    assert req["context"]["expert_outputs"] == "SITE TEXT"
    assert engine.last_request == req


def test_http_retriever_soft_fails_on_error():
    class BoomSession:
        def post(self, *a, **k):
            raise rag.requests.ConnectionError("down")

    engine = rag.HttpApiRetriever("https://x", session=BoomSession())
    assert engine.retrieve("regulation", "q", top_k=3, max_chars=100) == []


def test_example_files_roundtrip():
    import json

    req = json.loads((ROOT / "examples" / "rag_retrieve_request.json").read_text(encoding="utf-8"))
    resp = json.loads((ROOT / "examples" / "rag_retrieve_response.json").read_text(encoding="utf-8"))
    assert req["collection"] == "regulation"
    passages = rag.parse_retrieve_response(resp)
    block = rag.format_passages(passages, collection="regulation")
    assert "RETRIEVED KNOWLEDGE (regulation)" in block
    assert "source: kr_railway_adjacent.md" in block
