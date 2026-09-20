"""run.py: --path selects a named expert sequence; default runs every expert."""

from __future__ import annotations

import pytest

import run as run_mod
from tests.conftest import ROOT


def test_select_agents_default_is_all(mock_config):
    ids = [a["id"] for a in run_mod._select_agents(mock_config, None)]
    assert ids == [a["id"] for a in mock_config["agents"]]


def test_select_agents_by_path(mock_config):
    ids = [a["id"] for a in run_mod._select_agents(mock_config, "review_prep")]
    assert ids == ["synthesizer", "design_critic", "representation_planner", "presentation_editor"]


def test_select_agents_unknown_path_fails(mock_config):
    with pytest.raises(SystemExit):
        run_mod._select_agents(mock_config, "nope")


def test_run_path_writes_only_path_outputs(mock_config, monkeypatch):
    mock_config["state_update"] = {"mode": "off"}
    monkeypatch.setattr(run_mod, "load_env", lambda: "")
    monkeypatch.setattr(run_mod, "load_config", lambda *a, **k: mock_config)
    run_mod.run(ROOT / "input" / "geumjeong_station_brief.md", path_name="review_prep")
    import project as prj

    projects = prj.list_projects()
    assert len(projects) == 1
    modules = projects[0] / "modules"
    written = sorted(p.name for p in modules.glob("*.md"))
    assert written == [
        "32_synthesizer.md",
        "51_design_critic.md",
        "61_representation_planner.md",
        "62_presentation_editor.md",
    ]
