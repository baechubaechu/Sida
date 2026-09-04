from __future__ import annotations

import time

import pytest

import harness
from harness import (
    LLMError,
    MockProvider,
    _flatten_content,
    _plain_messages,
    _retryable,
    _with_retries,
    archive_module_output,
    build_module_snapshot,
    expected_headers,
    make_provider,
    missing_headers,
    modules_newer_than_state,
    prepare_conductor_context,
    resolve_conductor_runtime,
    run_worker_agent,
    slice_history,
)
from tests.conftest import ROOT

# --- providers -------------------------------------------------------------


def test_make_provider_kinds():
    assert make_provider("openrouter", api_key="k").name == "openrouter"
    assert make_provider("ollama", base_url="http://h:1/v1").base_url == "http://h:1"
    assert make_provider("mock").name == "mock"


def test_make_provider_errors():
    with pytest.raises(LLMError):
        make_provider("openrouter", api_key="")
    with pytest.raises(LLMError):
        make_provider("nope")


def test_flatten_content_and_plain_messages():
    flat = _flatten_content([{"type": "text", "text": "a", "cache_control": {}}, {"type": "text", "text": "b"}])
    assert flat == "a\n\nb"
    assert _plain_messages([{"role": "system", "content": [{"type": "text", "text": "s"}]}]) == [
        {"role": "system", "content": "s"}
    ]


def test_retry_then_success(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _retryable("boom")
        return "ok"

    assert _with_retries(flaky) == "ok"
    assert calls["n"] == 3


def test_non_retryable_raises_immediately(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def hard():
        calls["n"] += 1
        raise LLMError("fatal")

    with pytest.raises(LLMError):
        _with_retries(hard)
    assert calls["n"] == 1


def test_ollama_unreachable_is_llmerror():
    p = make_provider("ollama", base_url="http://127.0.0.1:9")  # closed port
    with pytest.raises(LLMError):
        p.chat("m", [{"role": "user", "content": "hi"}], 0.1, 5)


# --- runtime config -------------------------------------------------------


def test_local_profiles_overlay(mock_config):
    cfg = mock_config
    cfg["conductor"]["provider"] = "ollama"
    cfg["conductor"]["local_profile"] = "local"
    rt = resolve_conductor_runtime(cfg)
    assert rt["model"] == "qwen2.5:7b" and rt["num_ctx"] == 8192 and rt["history_window"] == 12
    cfg["conductor"]["local_profile"] = "local_plus"
    rt = resolve_conductor_runtime(cfg)
    assert rt["model"] == "qwen3.5:9b" and rt["num_ctx"] == 16384 and rt["history_window"] == 16


def test_cloud_runtime_untouched(mock_config):
    mock_config["conductor"]["provider"] = "openrouter"
    rt = resolve_conductor_runtime(mock_config)
    assert rt["provider"] == "openrouter"
    assert rt["num_ctx"] is None


# --- history slicing ------------------------------------------------------


def _pairs(n):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"u{i}"})
        out.append({"role": "assistant", "content": f"a{i}"})
    return out


def test_slice_history_aligns_to_user():
    sliced, truncated = slice_history(_pairs(10), 5)
    assert truncated
    assert sliced[0]["role"] == "user"
    assert len(sliced) <= 5


def test_slice_history_noop_when_small():
    hist = _pairs(3)
    sliced, truncated = slice_history(hist, 100)
    assert not truncated and sliced == hist


# --- headers --------------------------------------------------------------


def test_expected_and_missing_headers():
    prompt = (ROOT / "agents" / "01_site_reader.md").read_text(encoding="utf-8")
    hs = expected_headers(prompt)
    assert hs == ["Site Conditions", "Spatial Conflicts", "Opportunities", "Missing Information", "Design Implications"]
    assert missing_headers("# X\n\n## Site Conditions\n- a", hs) == hs[1:]
    assert missing_headers("\n".join(f"## {h}\n-" for h in hs), hs) == []


# --- worker run: archive + header retry -----------------------------------


def test_worker_archives_previous_output(mock_config, agents, project):
    provider = MockProvider()
    out_dir = project.modules_dir
    run_worker_agent("", mock_config, agents[0], project.read_brief(), [], out_dir, provider=provider)
    first = out_dir / "01_site_reader.md"
    assert first.exists()
    # Force a distinct mtime stamp, then rerun.
    import os

    os.utime(first, (first.stat().st_atime - 5, first.stat().st_mtime - 5))
    run_worker_agent("", mock_config, agents[0], project.read_brief(), [], out_dir, provider=provider)
    archived = list((out_dir / "_history").glob("01_site_reader.*.md"))
    assert len(archived) == 1


def test_worker_retries_missing_headers(mock_config, agents, project, scripted, capsys):
    prompt = (ROOT / "agents" / "01_site_reader.md").read_text(encoding="utf-8")
    hs = expected_headers(prompt)
    bad = "# Site Reader\n\n## Site Conditions\n- only one"
    good = "\n\n".join(f"## {h}\n- x" for h in hs)
    provider = scripted([bad, good])
    result = run_worker_agent("", mock_config, agents[0], project.read_brief(), [], project.modules_dir, provider=provider)
    assert result == good
    assert len(provider.calls) == 2
    assert "missing" in provider.calls[1]["messages"][-1]["content"]


def test_worker_keeps_best_effort_when_retry_still_bad(mock_config, agents, project, scripted, capsys):
    bad = "# Site Reader\n\n## Site Conditions\n- only one"
    provider = scripted([bad, bad])
    result = run_worker_agent("", mock_config, agents[0], project.read_brief(), [], project.modules_dir, provider=provider)
    assert result == bad
    assert "Spatial Conflicts" in capsys.readouterr().err


def test_archive_module_output_none_when_missing(tmp_path):
    assert archive_module_output(tmp_path / "nope.md") is None


# --- conductor context ----------------------------------------------------


def test_fresh_modules_included_until_state_updated(mock_config, agents, project):
    import os

    provider = MockProvider()
    run_worker_agent("", mock_config, agents[0], project.read_brief(), [], project.modules_dir, provider=provider)
    mod = project.modules_dir / "01_site_reader.md"
    # module newer than state
    os.utime(project.state_path, (1, 1))
    fresh = modules_newer_than_state(agents, project.modules_dir, project.state_path)
    assert [a["id"] for a in fresh] == ["site_reader"]
    snap = build_module_snapshot(agents, project.modules_dir, fresh)
    assert "not yet reflected in PROJECT STATE" in snap and "Mock Output" in snap

    # state touched after module -> compact
    later = mod.stat().st_mtime + 10
    os.utime(project.state_path, (later, later))
    fresh2 = modules_newer_than_state(agents, project.modules_dir, project.state_path)
    assert fresh2 == []
    snap2 = build_module_snapshot(agents, project.modules_dir, fresh2)
    assert "Mock Output" not in snap2 and "site_reader" in snap2


def test_prepare_context_falls_back_without_state(mock_config, agents, project):
    blocks = ["### Site Reader\n\nfull text"]
    state, module_ctx, hist, truncated = prepare_conductor_context(
        mock_config, agents, project.modules_dir, blocks, [], None, state_path=None
    )
    assert state is None
    assert module_ctx == blocks[0]
    assert not truncated


def test_mock_worker_matches_output_format():
    prompt = (ROOT / "agents" / "02_constraint_mapper.md").read_text(encoding="utf-8")
    full = harness.build_worker_prompt(prompt, "## Site\nbrief has headers too", "(none yet)")
    out, _ = MockProvider().chat("m", [{"role": "user", "content": full}], 0, 10, role="worker")
    assert missing_headers(out, expected_headers(prompt)) == []
