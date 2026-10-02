from __future__ import annotations

import time

import pytest

from sida import harness
from sida.harness import (
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


def test_ollama_sends_think_false_by_default(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"message": {"role": "assistant", "content": "ok"}, "eval_count": 1}

    def fake_post(url, json=None, timeout=None):
        captured["body"] = json
        return FakeResp()

    monkeypatch.setattr("sida.harness.requests.post", fake_post)
    p = make_provider("ollama", base_url="http://127.0.0.1:11434")
    out, _ = p.chat("qwen3.5:9b", [{"role": "user", "content": "hi"}], 0.2, 100)
    assert out == "ok"
    assert captured["body"]["think"] is False


def test_ollama_empty_content_with_thinking_is_retryable(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "message": {"role": "assistant", "content": "", "thinking": "…"},
                "done_reason": "length",
                "eval_count": 700,
            }

    monkeypatch.setattr("sida.harness.requests.post", lambda *a, **k: FakeResp())
    p = make_provider("ollama", base_url="http://h", think=True)
    with pytest.raises(LLMError) as ei:
        p.chat("m", [{"role": "user", "content": "hi"}], 0.1, 50)
    assert "thinking" in str(ei.value).lower()


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


def test_worker_ollama_uses_local_profile_model(mock_config):
    from sida.harness import resolve_worker_runtime

    cfg = mock_config
    cfg["conductor"]["provider"] = "ollama"
    cfg["conductor"]["local_profile"] = "local_plus"
    cfg["worker"]["provider"] = "ollama"
    cfg["worker"]["model"] = "openai/gpt-4o-mini"  # cloud id must be replaced
    rt = resolve_worker_runtime(cfg)
    assert rt["provider"] == "ollama"
    assert rt["model"] == "qwen3.5:9b"
    assert rt["num_ctx"] == 16384
    assert rt["base_url"]


def test_needs_openrouter_false_when_fully_local(mock_config):
    from sida.harness import needs_openrouter

    cfg = mock_config
    cfg["conductor"]["provider"] = "ollama"
    cfg["worker"]["provider"] = "ollama"
    cfg["state_update"] = {"mode": "ask", "provider": "conductor"}
    assert needs_openrouter(cfg) is False
    cfg["worker"]["provider"] = "openrouter"
    assert needs_openrouter(cfg) is True
    cfg["worker"]["provider"] = "ollama"
    cfg["state_update"] = {"mode": "ask", "provider": "worker"}
    # worker is ollama → still local
    assert needs_openrouter(cfg) is False
    cfg["conductor"]["provider"] = "openrouter"
    assert needs_openrouter(cfg) is True


def test_load_env_skips_prompt_when_local(mock_config, monkeypatch):
    from sida.harness import load_env

    cfg = mock_config
    cfg["conductor"]["provider"] = "ollama"
    cfg["worker"]["provider"] = "ollama"
    cfg["state_update"] = {"mode": "off"}
    monkeypatch.setattr(
        "sida.setup_env.ensure_api_key",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not ask for key")),
    )
    monkeypatch.setattr("sida.setup_env.read_api_key_from_env", lambda: "")
    assert load_env(config=cfg) == ""


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
    prompt = (ROOT / "agents" / "11_site_reader.md").read_text(encoding="utf-8")
    hs = expected_headers(prompt)
    assert hs == [
        "Site Conditions", "Spatial Conflicts", "Opportunities",
        "Missing Information", "Design Implications", "Handoff",
    ]
    assert missing_headers("# X\n\n## Site Conditions\n- a", hs) == hs[1:]
    assert missing_headers("\n".join(f"## {h}\n-" for h in hs), hs) == []


# --- worker run: archive + header retry -----------------------------------


def test_worker_archives_previous_output(mock_config, agents, project):
    provider = MockProvider()
    out_dir = project.modules_dir
    run_worker_agent("", mock_config, agents[0], project.read_brief(), [], out_dir, provider=provider)
    first = out_dir / "11_site_reader.md"
    assert first.exists()
    # Force a distinct mtime stamp, then rerun.
    import os

    os.utime(first, (first.stat().st_atime - 5, first.stat().st_mtime - 5))
    run_worker_agent("", mock_config, agents[0], project.read_brief(), [], out_dir, provider=provider)
    archived = list((out_dir / "_history").glob("11_site_reader.*.md"))
    assert len(archived) == 1


def test_worker_retries_missing_headers(mock_config, agents, project, scripted, capsys):
    prompt = (ROOT / "agents" / "11_site_reader.md").read_text(encoding="utf-8")
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
    mod = project.modules_dir / "11_site_reader.md"
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
    prompt = (ROOT / "agents" / "31_constraint_mapper.md").read_text(encoding="utf-8")
    full = harness.build_worker_prompt(prompt, "## Site\nbrief has headers too", "(none yet)")
    out, _ = MockProvider().chat("m", [{"role": "user", "content": full}], 0, 10, role="worker")
    assert missing_headers(out, expected_headers(prompt)) == []


@pytest.mark.parametrize("agent_file", sorted(p.name for p in (ROOT / "agents").glob("[1-6]*_*.md")))
def test_every_expert_prompt_has_handoff_and_inputs(agent_file):
    prompt = (ROOT / "agents" / agent_file).read_text(encoding="utf-8")
    hs = expected_headers(prompt)
    assert hs, agent_file
    assert hs[-1] == "Handoff", agent_file
    assert "## Inputs" in prompt, agent_file
    assert "## Role" in prompt and "## Output Format" in prompt


# --- experts: config registry, routing prompt, input selection ------------


def test_config_agents_cover_all_prompt_files(mock_config):
    agents = harness.get_agents(mock_config)
    files = {a["file"].split("/")[-1] for a in agents}
    on_disk = {p.name for p in (ROOT / "agents").glob("[1-6]*_*.md")}
    assert files == on_disk
    ids = [a["id"] for a in agents]
    assert len(ids) == len(set(ids))
    for a in agents:
        assert a.get("phase") and a.get("desc"), a["id"]
        assert a["output"] == a["file"].split("/")[-1]


def test_paths_reference_known_experts(mock_config):
    ids = {a["id"] for a in harness.get_agents(mock_config)}
    paths = harness.get_paths(mock_config)
    assert {"site_driven", "idea_driven", "program_driven", "regulation_driven", "review_prep"} <= set(paths)
    for name, seq in paths.items():
        assert set(seq) <= ids, name
    # entry expert reflects the driver
    assert paths["site_driven"][0] == "site_reader"
    assert paths["idea_driven"][0] == "concept_framer"
    assert paths["program_driven"][0] == "program_analyst"
    assert paths["regulation_driven"][0] == "regulation_checker"
    assert paths["review_prep"][0] == "synthesizer"


def test_inputs_reference_known_experts(mock_config):
    agents = harness.get_agents(mock_config)
    ids = {a["id"] for a in agents}
    for a in agents:
        inputs = harness.agent_inputs(a)
        assert inputs != "legacy", a["id"]
        if isinstance(inputs, list):
            assert set(inputs) <= ids and a["id"] not in inputs, a["id"]
    assert harness.agent_inputs(harness.agent_by_id(agents, "synthesizer")) == "all"
    assert harness.agent_inputs({"id": "x"}) == "legacy"


def test_render_conductor_prompt_lists_every_expert_and_path(mock_config):
    template = (ROOT / "agents" / "00_conductor.md").read_text(encoding="utf-8")
    assert "{{MODULES}}" in template and "{{PATHS}}" in template
    rendered = harness.render_conductor_prompt(template, mock_config)
    assert "{{" not in rendered
    for a in harness.get_agents(mock_config):
        assert f"`{a['id']}`" in rendered
        assert a["desc"] in rendered
    assert "site_driven: site_reader → program_analyst" in rendered
    assert "reads all completed outputs" in rendered
    assert "**analysis**" in rendered and "**communication**" in rendered


def test_select_input_blocks_filters_by_declaration(mock_config, agents, project):
    out = project.modules_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "11_site_reader.md").write_text("SITE TEXT", encoding="utf-8")
    (out / "12_program_analyst.md").write_text("PROGRAM TEXT", encoding="utf-8")
    (out / "61_representation_planner.md").write_text("REPR TEXT", encoding="utf-8")

    reg = harness.agent_by_id(agents, "regulation_checker")  # inputs: site_reader, program_analyst
    blocks, others = harness.select_input_blocks(agents, reg, out)
    joined = "\n".join(blocks)
    assert "SITE TEXT" in joined and "PROGRAM TEXT" in joined
    assert "REPR TEXT" not in joined
    assert others == ["representation_planner"]
    assert blocks[0].startswith("### Site Reader (site_reader)")

    synth = harness.agent_by_id(agents, "synthesizer")  # all
    blocks, others = harness.select_input_blocks(agents, synth, out)
    assert len(blocks) == 3 and others == []

    # own output is never fed back
    (out / "13_regulation_checker.md").write_text("REG TEXT", encoding="utf-8")
    blocks, _ = harness.select_input_blocks(agents, reg, out)
    assert "REG TEXT" not in "\n".join(blocks)

    assert harness.select_input_blocks(agents, {"id": "legacy", "output": "x.md"}, out) is None


def test_worker_prompt_includes_state_and_other_completed():
    full = harness.build_worker_prompt(
        "AGENT", "BRIEF", "(none yet)",
        project_state="## Meta\n- **Phase**: concept",
        other_completed=["design_critic", "synthesizer"],
    )
    assert "PROJECT STATE" in full and "**Phase**: concept" in full
    assert "OTHER COMPLETED EXPERTS" in full and "design_critic, synthesizer" in full
    assert "Handoff" in full
    bare = harness.build_worker_prompt("AGENT", "BRIEF", "(none yet)")
    assert "PROJECT STATE" not in bare and "OTHER COMPLETED" not in bare


def test_run_worker_uses_declared_inputs_only(mock_config, agents, project, scripted):
    out = project.modules_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "11_site_reader.md").write_text("SITE TEXT", encoding="utf-8")
    (out / "51_design_critic.md").write_text("CRITIC TEXT", encoding="utf-8")
    reg = harness.agent_by_id(agents, "regulation_checker")
    hs = expected_headers((ROOT / reg["file"]).read_text(encoding="utf-8"))
    provider = scripted(["\n\n".join(f"## {h}\n- x" for h in hs)])
    run_worker_agent(
        "", mock_config, reg, project.read_brief(), ["### stale legacy block"], out,
        provider=provider, project_state="STATE TEXT",
    )
    sent = provider.calls[0]["messages"][-1]["content"]
    assert "SITE TEXT" in sent and "STATE TEXT" in sent
    assert "CRITIC TEXT" not in sent and "design_critic" in sent
    assert "stale legacy block" not in sent


# --- config.yaml + config.local.yaml ---------------------------------------


def _write_base(tmp_path):
    base = tmp_path / "config.yaml"
    base.write_text(
        "conductor:\n  provider: openrouter\n  model: m1\n"
        "rag:\n  enabled: false\n  provider: http\n"
        "agents:\n  - id: a\n  - id: b\n",
        encoding="utf-8",
    )
    return base


def test_load_config_without_local_file_is_base_only(tmp_path):
    cfg = harness.load_config(_write_base(tmp_path))
    assert cfg["conductor"] == {"provider": "openrouter", "model": "m1"}
    assert cfg["rag"]["enabled"] is False


def test_load_config_overlays_local_file(tmp_path):
    base = _write_base(tmp_path)
    (tmp_path / "config.local.yaml").write_text(
        "conductor:\n  provider: ollama\nrag:\n  enabled: true\n", encoding="utf-8"
    )
    cfg = harness.load_config(base)
    assert cfg["conductor"] == {"provider": "ollama", "model": "m1"}  # sibling key kept
    assert cfg["rag"] == {"enabled": True, "provider": "http"}
    assert [a["id"] for a in cfg["agents"]] == ["a", "b"]


def test_load_config_ignores_empty_local_file(tmp_path):
    base = _write_base(tmp_path)
    (tmp_path / "config.local.yaml").write_text("# only a comment\n", encoding="utf-8")
    assert harness.load_config(base)["conductor"]["provider"] == "openrouter"


def test_default_load_config_reads_local_config_path():
    # conftest points LOCAL_CONFIG_PATH at a tmp file, never the real one.
    harness.LOCAL_CONFIG_PATH.write_text("projects_dir: /tmp/from-local\n", encoding="utf-8")
    assert harness.load_config()["projects_dir"] == "/tmp/from-local"


def test_committed_defaults_are_cloud_with_rag_off():
    """config.yaml must stay machine-neutral: personal choices belong in config.local.yaml."""
    cfg = harness.load_config(ROOT / "config.yaml")
    assert cfg["conductor"]["provider"] == "openrouter"
    assert cfg["worker"]["provider"] == "openrouter"
    assert cfg["rag"]["enabled"] is False
    assert harness.needs_openrouter(cfg)


# --- local worker input budget ---------------------------------------------


def test_worker_input_budget_only_for_local_with_known_ctx():
    from sida.harness import worker_input_budget

    cloud = {"provider": "openrouter", "num_ctx": None, "max_tokens": 2500}
    assert worker_input_budget(cloud, 100) is None
    assert worker_input_budget({"provider": "ollama", "num_ctx": None, "max_tokens": 2500}, 100) is None
    local = {"provider": "ollama", "num_ctx": 8192, "max_tokens": 2500}
    expected = int((8192 - 2500) * harness.CHARS_PER_TOKEN) - 3000 - harness.BUDGET_MARGIN_CHARS
    assert worker_input_budget(local, 3000) == expected
    assert worker_input_budget(local, 99999) == 0  # fixed parts alone overflow


def test_clip_block_keeps_start_and_handoff():
    from sida.harness import TRIM_MARK, clip_block

    text = "### Site Reader\n\n" + "가" * 5000 + "\n## Handoff\n- → regulation_checker: 철도 이격"
    assert clip_block(text, 99999) == text
    clipped = clip_block(text, 1200)
    assert len(clipped) <= 1200
    assert clipped.startswith("### Site Reader")
    assert TRIM_MARK.strip() in clipped
    assert clipped.endswith("→ regulation_checker: 철도 이격")


def test_fit_worker_inputs_fair_share_and_knowledge_cap():
    from sida.harness import fit_worker_inputs

    short, long_a, long_b = "s" * 500, "a" * 6000, "b" * 9000
    blocks, knowledge, trimmed = fit_worker_inputs([short, long_a, long_b], "", 20000)
    assert (blocks, trimmed) == ([short, long_a, long_b], 0)  # under budget → untouched

    blocks, knowledge, trimmed = fit_worker_inputs([short, long_a, long_b], "k" * 8000, 8000)
    assert len(knowledge) <= 4000  # knowledge capped at half when blocks exist
    assert blocks[0] == short  # short block kept whole
    assert len(blocks[1]) < 6000 and len(blocks[2]) < 9000
    assert sum(len(b) for b in blocks) + len(knowledge) <= 8000
    assert trimmed == 3

    blocks, knowledge, trimmed = fit_worker_inputs([], "k" * 8000, 3000)
    assert len(knowledge) <= 3000 and trimmed == 1  # no blocks → knowledge may use it all


def _valid_output(agent):
    headers = harness.expected_headers((ROOT / agent["file"]).read_text(encoding="utf-8"))
    return "\n\n".join(f"## {h}\n- x" for h in headers)


def test_local_worker_prompt_fits_context_and_reports_trimming(
    mock_config, agents, project, scripted, capsys
):
    from sida.harness import agent_by_id, resolve_worker_runtime

    mock_config["conductor"]["local_profile"] = "local"  # 8K context
    mock_config["worker"]["provider"] = "ollama"
    mock_config["rag"] = {"enabled": False}
    rt = resolve_worker_runtime(mock_config)
    for a in agents[:6]:
        (project.modules_dir / a["output"]).write_text(
            f"# {a['name']}\n\n" + "내용 " * 2500 + "\n## Handoff\n- → synthesizer: 확인\n",
            encoding="utf-8",
        )
    agent = agent_by_id(agents, "synthesizer")  # inputs: all
    provider = scripted([_valid_output(agent)])
    run_worker_agent(
        "", mock_config, agent, project.read_brief(), [], project.modules_dir,
        provider=provider, project_state=project.read_state(),
    )

    sent = sum(len(m["content"]) for m in provider.calls[0]["messages"])
    assert sent <= (rt["num_ctx"] - rt["max_tokens"]) * harness.CHARS_PER_TOKEN
    prompt = provider.calls[0]["messages"][1]["content"]
    assert prompt.startswith("AGENT PROMPT:")  # role is intact
    assert prompt.count("→ synthesizer: 확인") == 6  # every Handoff survived
    assert "[module]" in capsys.readouterr().err


def test_cloud_worker_prompt_is_never_trimmed(mock_config, agents, project, scripted, capsys):
    from sida.harness import agent_by_id

    body = "# Site Reader\n\n" + "내용 " * 20000
    (project.modules_dir / "11_site_reader.md").write_text(body, encoding="utf-8")
    agent = agent_by_id(agents, "synthesizer")
    provider = scripted([_valid_output(agent)])
    run_worker_agent(
        "", mock_config, agent, project.read_brief(), [], project.modules_dir, provider=provider
    )
    assert body.strip() in provider.calls[0]["messages"][1]["content"]
    assert "[module]" not in capsys.readouterr().err


def test_strip_md_comments_removes_guidance_only():
    from sida.harness import strip_md_comments

    text = "## Meta\n\n<!-- multi\n line note -->\n\n- **Phase**: concept  <!-- inline -->\n\n\n\n## Next\n- a"
    out = strip_md_comments(text)
    assert "<!--" not in out and "note" not in out and "inline" not in out
    assert "- **Phase**: concept" in out and "## Next\n- a" in out
    assert "\n\n\n" not in out
    assert strip_md_comments(None) is None and strip_md_comments("") == ""


def test_worker_gets_project_state_without_comments(mock_config, agents, project, scripted):
    from sida.harness import agent_by_id

    state = project.read_state()
    assert "<!--" in state  # the template ships with editing notes
    agent = agent_by_id(agents, "site_reader")
    provider = scripted([_valid_output(agent)])
    run_worker_agent(
        "", mock_config, agent, project.read_brief(), [], project.modules_dir,
        provider=provider, project_state=state,
    )
    prompt = provider.calls[0]["messages"][1]["content"]
    assert "PROJECT STATE" in prompt and "## Module Status" in prompt
    assert "| site_reader | pending |" in prompt  # content kept
    assert "<!--" not in prompt
    assert project.read_state() == state  # the file itself is untouched
