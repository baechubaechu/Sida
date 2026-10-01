"""workspace.py — project hub operations without any UI."""

from __future__ import annotations

import pytest

import workspace
from project import section_body


def test_empty_root_lists_nothing(mock_config):
    assert workspace.list_project_summaries(mock_config) == []


def test_create_project_writes_brief_from_fields(mock_config):
    project, created = workspace.create_project(
        mock_config,
        "성수 주택",
        {"type": "주택", "issues": "경사, 좁은 도로", "driver": "아이디어", "ignored": "x"},
    )
    assert created is True and project.name == "성수_주택"
    brief = project.read_brief()
    assert section_body(brief, "Project Type") == "주택"
    assert section_body(brief, "Site Issues") == "- 경사\n- 좁은 도로"
    assert section_body(brief, "Primary Driver") == "idea"  # normalized like the terminal form
    assert "ignored" not in brief


def test_create_project_with_existing_name_opens_it(mock_config):
    first, created = workspace.create_project(mock_config, "My House", {"type": "주택"})
    again, created_again = workspace.create_project(mock_config, "my house", {"type": "다른 값"})
    assert created is True and created_again is False
    assert again.path == first.path
    assert section_body(again.read_brief(), "Project Type") == "주택"  # brief not overwritten


def test_create_project_rejects_empty_name(mock_config):
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            workspace.create_project(mock_config, bad, {})
    assert workspace.list_project_summaries(mock_config) == []


def test_sample_project_created_once(mock_config):
    project, created = workspace.create_sample_project(mock_config)
    _again, created_again = workspace.create_sample_project(mock_config)
    assert (created, created_again) == (True, False)
    assert project.name == "sample_brief"


def test_summary_reports_type_and_completed_experts(mock_config, project, agents):
    (project.modules_dir / "11_site_reader.md").write_text("# x", encoding="utf-8")
    summary = workspace.list_project_summaries(mock_config)[0]
    assert summary["name"] == project.name
    assert summary["project_type"].startswith("Transit architecture")
    assert summary["completed"] == ["site_reader"]
    assert summary["expert_count"] == len(agents)
    assert summary["updated_at"]


def test_summary_does_not_touch_the_project(mock_config, project):
    before = project.session_path.read_text(encoding="utf-8")
    workspace.list_project_summaries(mock_config)
    assert project.session_path.read_text(encoding="utf-8") == before  # no "resumed" stamp


def test_find_project_only_inside_projects_folder(mock_config, project, tmp_path):
    assert workspace.find_project(mock_config, project.name) == project.path
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "brief.md").write_text("# secret", encoding="utf-8")
    for bad in ("", "nope", "..", "../outside", "..\\outside", str(outside)):
        with pytest.raises(workspace.ProjectNotFound):
            workspace.find_project(mock_config, bad)
