"""RAG settings, local-file retrieval, worker prompt injection."""

from __future__ import annotations

from sida import harness
from sida.experts.regulation import rag
from sida.harness import build_worker_prompt, expected_headers, run_worker_agent
from tests.conftest import ROOT


def test_rag_settings_defaults(mock_config):
    s = rag.rag_settings(mock_config)
    assert s["enabled"] is False  # off until a machine opts in via config.local.yaml
    assert s["provider"] == "lawgokr"  # 법제처 search, called directly
    assert s["agents"]["regulation_checker"] == "regulation"
    assert "base_url" not in s and "api_key" not in s  # no self-hosted server settings


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


# --- warnings when retrieval is on but produced nothing ----------------------
# (the 법제처 provider's own failure modes are covered in tests/experts/regulation/test_lawapi.py)


def _local_config(mock_config, tmp_path):
    mock_config["rag"] = {
        "enabled": True,
        "provider": "local_files",
        "knowledge_dir": str(tmp_path / "knowledge"),
        "agents": {"regulation_checker": "regulation"},
    }
    return mock_config


def test_no_warning_when_rag_off_or_passages_found(mock_config, tmp_path):
    mock_config["rag"] = {"enabled": False}
    assert rag.retrieve_passages(mock_config, "regulation", "q") == []
    assert rag.last_retrieval_warning() is None

    cfg = _local_config(mock_config, tmp_path)
    folder = tmp_path / "knowledge" / "regulation"
    folder.mkdir(parents=True)
    (folder / "kr_rail.md").write_text("# 철도\n\n## 철도보호지구\n철도 경계선 30미터", encoding="utf-8")
    assert len(rag.retrieve_passages(cfg, "regulation", "철도보호지구 경계선")) == 1
    assert rag.last_retrieval_warning() is None


def test_warning_for_no_hits_and_for_a_removed_provider(mock_config, tmp_path):
    cfg = _local_config(mock_config, tmp_path)
    assert rag.retrieve_passages(cfg, "regulation", "철도보호지구") == []  # empty corpus
    assert "찾지 못했" in rag.last_retrieval_warning()

    # A config.local.yaml written for the old self-hosted server keeps working, with a hint.
    cfg["rag"]["provider"] = "http"
    assert rag.retrieve_passages(cfg, "regulation", "철도보호지구") == []
    assert "'http'" in rag.last_retrieval_warning()


def test_warning_cleared_for_agent_without_collection(mock_config, tmp_path):
    cfg = _local_config(mock_config, tmp_path)
    rag.retrieve_passages(cfg, "regulation", "철도보호지구")
    assert rag.last_retrieval_warning()
    assert rag.retrieve_for_agent(cfg, {"id": "site_reader"}, "q") == ""
    assert rag.last_retrieval_warning() is None  # stale warning must not leak to other experts


def test_worker_run_prints_rag_warning(mock_config, agents, project, monkeypatch, capsys, tmp_path):
    from sida.harness import MockProvider, agent_by_id, run_worker_agent

    _local_config(mock_config, tmp_path)  # on, but the corpus is empty
    brief = project.read_brief()
    out = project.modules_dir
    reg = agent_by_id(agents, "regulation_checker")
    run_worker_agent("", mock_config, reg, brief, [], out, provider=MockProvider())
    assert "[rag]" in capsys.readouterr().err

    site = agent_by_id(agents, "site_reader")
    run_worker_agent("", mock_config, site, brief, [], out, provider=MockProvider())
    assert "[rag]" not in capsys.readouterr().err  # only experts that use retrieval warn
