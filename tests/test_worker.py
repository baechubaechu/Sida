"""Running one expert: input selection, prompt, local context budget, header retry, archiving."""

from __future__ import annotations

import pytest

from sida import config as sida_config
from sida import worker
from sida.providers import (
    MockProvider,
)
from sida.worker import archive_module_output, expected_headers, missing_headers, run_worker_agent
from tests.conftest import ROOT


def test_expected_and_missing_headers():
    prompt = (ROOT / "agents" / "11_site_reader.md").read_text(encoding="utf-8")
    hs = expected_headers(prompt)
    assert hs == [
        "Site Conditions", "Spatial Conflicts", "Opportunities",
        "Missing Information", "Design Implications", "Handoff",
    ]
    assert missing_headers("# X\n\n## Site Conditions\n- a", hs) == hs[1:]
    assert missing_headers("\n".join(f"## {h}\n-" for h in hs), hs) == []


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


@pytest.mark.parametrize("agent_file", sorted(p.name for p in (ROOT / "agents").glob("[1-6]*_*.md")))
def test_every_expert_prompt_has_handoff_and_inputs(agent_file):
    prompt = (ROOT / "agents" / agent_file).read_text(encoding="utf-8")
    hs = expected_headers(prompt)
    assert hs, agent_file
    assert hs[-1] == "Handoff", agent_file
    assert "## Inputs" in prompt, agent_file
    assert "## Role" in prompt and "## Output Format" in prompt


def test_select_input_blocks_filters_by_declaration(mock_config, agents, project):
    out = project.modules_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "11_site_reader.md").write_text("SITE TEXT", encoding="utf-8")
    (out / "12_program_analyst.md").write_text("PROGRAM TEXT", encoding="utf-8")
    (out / "61_representation_planner.md").write_text("REPR TEXT", encoding="utf-8")

    reg = sida_config.agent_by_id(agents, "regulation_checker")  # inputs: site_reader, program_analyst
    blocks, others = worker.select_input_blocks(agents, reg, out)
    joined = "\n".join(blocks)
    assert "SITE TEXT" in joined and "PROGRAM TEXT" in joined
    assert "REPR TEXT" not in joined
    assert others == ["representation_planner"]
    assert blocks[0].startswith("### Site Reader (site_reader)")

    synth = sida_config.agent_by_id(agents, "synthesizer")  # all
    blocks, others = worker.select_input_blocks(agents, synth, out)
    assert len(blocks) == 3 and others == []

    # own output is never fed back
    (out / "13_regulation_checker.md").write_text("REG TEXT", encoding="utf-8")
    blocks, _ = worker.select_input_blocks(agents, reg, out)
    assert "REG TEXT" not in "\n".join(blocks)

    assert worker.select_input_blocks(agents, {"id": "legacy", "output": "x.md"}, out) is None


def test_worker_prompt_includes_state_and_other_completed():
    full = worker.build_worker_prompt(
        "AGENT", "BRIEF", "(none yet)",
        project_state="## Meta\n- **Phase**: concept",
        other_completed=["design_critic", "synthesizer"],
    )
    assert "PROJECT STATE" in full and "**Phase**: concept" in full
    assert "OTHER COMPLETED EXPERTS" in full and "design_critic, synthesizer" in full
    assert "Handoff" in full
    bare = worker.build_worker_prompt("AGENT", "BRIEF", "(none yet)")
    assert "PROJECT STATE" not in bare and "OTHER COMPLETED" not in bare


def test_run_worker_uses_declared_inputs_only(mock_config, agents, project, scripted):
    out = project.modules_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "11_site_reader.md").write_text("SITE TEXT", encoding="utf-8")
    (out / "51_design_critic.md").write_text("CRITIC TEXT", encoding="utf-8")
    reg = sida_config.agent_by_id(agents, "regulation_checker")
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


def test_worker_input_budget_only_for_local_with_known_ctx():
    from sida.worker import worker_input_budget

    cloud = {"provider": "openrouter", "num_ctx": None, "max_tokens": 2500}
    assert worker_input_budget(cloud, 100) is None
    assert worker_input_budget({"provider": "ollama", "num_ctx": None, "max_tokens": 2500}, 100) is None
    local = {"provider": "ollama", "num_ctx": 8192, "max_tokens": 2500}
    expected = int((8192 - 2500) * worker.CHARS_PER_TOKEN) - 3000 - worker.BUDGET_MARGIN_CHARS
    assert worker_input_budget(local, 3000) == expected
    assert worker_input_budget(local, 99999) == 0  # fixed parts alone overflow


def test_clip_block_keeps_start_and_handoff():
    from sida.worker import TRIM_MARK, clip_block

    text = "### Site Reader\n\n" + "가" * 5000 + "\n## Handoff\n- → regulation_checker: 철도 이격"
    assert clip_block(text, 99999) == text
    clipped = clip_block(text, 1200)
    assert len(clipped) <= 1200
    assert clipped.startswith("### Site Reader")
    assert TRIM_MARK.strip() in clipped
    assert clipped.endswith("→ regulation_checker: 철도 이격")


def test_fit_worker_inputs_fair_share_and_knowledge_cap():
    from sida.worker import fit_worker_inputs

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
    headers = worker.expected_headers((ROOT / agent["file"]).read_text(encoding="utf-8"))
    return "\n\n".join(f"## {h}\n- x" for h in headers)


def test_local_worker_prompt_fits_context_and_reports_trimming(
    mock_config, agents, project, scripted, capsys
):
    from sida.config import agent_by_id
    from sida.runtime import resolve_worker_runtime

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
    assert sent <= (rt["num_ctx"] - rt["max_tokens"]) * worker.CHARS_PER_TOKEN
    prompt = provider.calls[0]["messages"][1]["content"]
    assert prompt.startswith("AGENT PROMPT:")  # role is intact
    assert prompt.count("→ synthesizer: 확인") == 6  # every Handoff survived
    assert "[module]" in capsys.readouterr().err


def test_cloud_worker_prompt_is_never_trimmed(mock_config, agents, project, scripted, capsys):
    from sida.config import agent_by_id

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
    from sida.worker import strip_md_comments

    text = "## Meta\n\n<!-- multi\n line note -->\n\n- **Phase**: concept  <!-- inline -->\n\n\n\n## Next\n- a"
    out = strip_md_comments(text)
    assert "<!--" not in out and "note" not in out and "inline" not in out
    assert "- **Phase**: concept" in out and "## Next\n- a" in out
    assert "\n\n\n" not in out
    assert strip_md_comments(None) is None and strip_md_comments("") == ""


def test_worker_gets_project_state_without_comments(mock_config, agents, project, scripted):
    from sida.config import agent_by_id

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
