"""What the Conductor is sent: history slice, module snapshot, the rendered prompt."""

from __future__ import annotations

from sida import conductor_context
from sida import config as sida_config
from sida.conductor_context import (
    build_module_snapshot,
    modules_newer_than_state,
    prepare_conductor_context,
    slice_history,
)
from sida.providers import MockProvider
from sida.worker import run_worker_agent
from tests.conftest import ROOT


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

    # Touching state is not evidence of acceptance. Only record this expert's revision.
    from sida.state_updater import propose_state_patch, write_state

    _, proposed = propose_state_patch(
        mock_config, "", project, agents[0], w_provider=provider, lang="ko"
    )
    write_state(project, proposed)
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


def test_updating_one_module_does_not_hide_another(mock_config, agents, project):
    from sida.state_updater import propose_state_patch, write_state

    for agent in agents[:2]:
        (project.modules_dir / agent["output"]).write_text(
            f"# {agent['id']}\n\n아직 반영하지 않은 분석", encoding="utf-8"
        )
    _, proposed = propose_state_patch(
        mock_config, "", project, agents[0], w_provider=MockProvider(), lang="ko"
    )
    write_state(project, proposed)
    fresh = modules_newer_than_state(agents, project.modules_dir, project.state_path)
    assert [a["id"] for a in fresh] == [agents[1]["id"]]
    snapshot = build_module_snapshot(agents, project.modules_dir, fresh)
    assert f"# {agents[1]['id']}" in snapshot


def test_same_timestamp_rerun_is_still_unreflected(mock_config, agents, project):
    import os

    from sida.state_updater import propose_state_patch, write_state

    agent = agents[0]
    module = project.modules_dir / agent["output"]
    module.write_text("original analysis", encoding="utf-8")
    _, proposed = propose_state_patch(
        mock_config, "", project, agent, w_provider=MockProvider(), lang="ko"
    )
    write_state(project, proposed)
    stamp = project.state_path.stat().st_mtime
    module.write_text("new analysis", encoding="utf-8")
    os.utime(module, (stamp, stamp))
    assert modules_newer_than_state(agents, project.modules_dir, project.state_path) == [agent]


def test_render_conductor_prompt_lists_every_expert_and_path(mock_config):
    template = (ROOT / "agents" / "00_conductor.md").read_text(encoding="utf-8")
    assert "{{MODULES}}" in template and "{{PATHS}}" in template
    rendered = conductor_context.render_conductor_prompt(template, mock_config)
    assert "{{" not in rendered
    for a in sida_config.get_agents(mock_config):
        assert f"`{a['id']}`" in rendered
        assert a["desc"] in rendered
    assert "site_driven: site_reader → program_analyst" in rendered
    assert "reads all completed outputs" in rendered
    assert "**analysis**" in rendered and "**communication**" in rendered
