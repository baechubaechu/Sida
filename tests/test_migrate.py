"""Legacy module rename + Module Status row sync."""

from __future__ import annotations

from migrate import (
    LEGACY_MODULE_FILES,
    ensure_module_status_rows,
    existing_module_ids,
    migrate_project,
    rename_legacy_history,
    rename_legacy_modules,
)


def test_rename_legacy_modules(tmp_path):
    mods = tmp_path / "modules"
    mods.mkdir()
    (mods / "01_site_reader.md").write_text("SITE", encoding="utf-8")
    (mods / "02_constraint_mapper.md").write_text("CONST", encoding="utf-8")
    notes = rename_legacy_modules(mods)
    assert (mods / "11_site_reader.md").read_text(encoding="utf-8") == "SITE"
    assert (mods / "31_constraint_mapper.md").read_text(encoding="utf-8") == "CONST"
    assert not (mods / "01_site_reader.md").exists()
    assert len(notes) == 2
    # idempotent
    assert rename_legacy_modules(mods) == []


def test_rename_keeps_new_when_both_exist(tmp_path):
    mods = tmp_path / "modules"
    mods.mkdir()
    (mods / "01_site_reader.md").write_text("OLD", encoding="utf-8")
    (mods / "11_site_reader.md").write_text("NEW", encoding="utf-8")
    notes = rename_legacy_modules(mods)
    assert (mods / "11_site_reader.md").read_text(encoding="utf-8") == "NEW"
    assert not (mods / "01_site_reader.md").exists()
    archived = list((mods / "_history").glob("01_site_reader.pre-rename*"))
    assert len(archived) == 1 and archived[0].read_text(encoding="utf-8") == "OLD"
    assert notes and "kept existing" in notes[0]


def test_rename_legacy_history(tmp_path):
    hist = tmp_path / "modules" / "_history"
    hist.mkdir(parents=True)
    (hist / "01_site_reader.20260101-120000.md").write_text("x", encoding="utf-8")
    notes = rename_legacy_history(tmp_path / "modules")
    assert (hist / "11_site_reader.20260101-120000.md").exists()
    assert not (hist / "01_site_reader.20260101-120000.md").exists()
    assert notes


def test_ensure_module_status_rows_appends_missing():
    state = (
        "# Project State\n\n## Module Status\n\n"
        "| Module | Status | Key takeaway |\n"
        "|--------|--------|--------------|\n"
        "| site_reader | done | takeaway |\n\n"
        "## Next Focus\n\n-\n"
    )
    agents = [
        {"id": "site_reader"},
        {"id": "program_analyst"},
        {"id": "regulation_checker"},
    ]
    new, added = ensure_module_status_rows(state, agents)
    assert added == ["program_analyst", "regulation_checker"]
    assert "| site_reader | done | takeaway |" in new
    assert "| program_analyst | pending | |" in new
    assert "| regulation_checker | pending | |" in new
    assert existing_module_ids(new) == {
        "site_reader",
        "program_analyst",
        "regulation_checker",
    }
    # idempotent
    again, added2 = ensure_module_status_rows(new, agents)
    assert added2 == [] and again == new


def test_migrate_project_end_to_end(tmp_path, agents):
    root = tmp_path / "proj"
    mods = root / "modules"
    mods.mkdir(parents=True)
    (mods / "03_design_critic.md").write_text("CRITIC", encoding="utf-8")
    state_path = root / "project_state.md"
    state_path.write_text(
        "# Project State\n\n## Module Status\n\n"
        "| Module | Status | Key takeaway |\n"
        "|--------|--------|--------------|\n"
        "| site_reader | done | x |\n",
        encoding="utf-8",
    )

    class P:
        modules_dir = mods
        state_path = root / "project_state.md"

    notes = migrate_project(P(), agents)
    assert (mods / "51_design_critic.md").read_text(encoding="utf-8") == "CRITIC"
    state = state_path.read_text(encoding="utf-8")
    assert "| site_reader | done | x |" in state
    for a in agents:
        assert f"| {a['id']} |" in state
    assert any("design_critic" in n or "03_" in n for n in notes)
    assert any("Module Status" in n for n in notes)
    # covers mapping table completeness
    assert set(LEGACY_MODULE_FILES) == {
        "01_site_reader.md",
        "02_constraint_mapper.md",
        "03_design_critic.md",
        "04_representation_planner.md",
        "05_presentation_editor.md",
    }


def test_load_project_runs_migration(mock_config, tmp_path, monkeypatch, agents, capsys):
    import project as prj

    monkeypatch.setattr(prj, "DEFAULT_PROJECTS_DIR", tmp_path / "projects")
    root = tmp_path / "projects" / "old_proj"
    (root / "modules").mkdir(parents=True)
    (root / "brief.md").write_text("# Brief\n", encoding="utf-8")
    (root / "modules" / "01_site_reader.md").write_text("OLD SITE", encoding="utf-8")
    (root / "project_state.md").write_text(
        "# Project State\n\n## Module Status\n\n"
        "| Module | Status | Key takeaway |\n"
        "|--------|--------|--------------|\n"
        "| site_reader | done | ok |\n",
        encoding="utf-8",
    )
    project = prj.load_project(root)
    assert (project.modules_dir / "11_site_reader.md").read_text(encoding="utf-8") == "OLD SITE"
    state = project.read_state()
    assert "| program_analyst | pending | |" in state
    out = capsys.readouterr().out
    assert "migrate" in out.lower() or "갱신" in out
