from __future__ import annotations

import json
import os

import project as prj
from project import _replace_section, section_body
from tests.conftest import ROOT

BRIEF = (ROOT / "input" / "geumjeong_station_brief.md").read_text(encoding="utf-8")


def test_replace_section_preserves_others():
    new = _replace_section(BRIEF, "Core Problem", "NEW")
    assert section_body(new, "Core Problem") == "NEW"
    assert "## Main Layers" in new and "## Representation Focus" in new
    assert section_body(new, "Site") == section_body(BRIEF, "Site")


def test_replace_section_appends_when_missing():
    new = _replace_section(BRIEF, "Brand New", "hello")
    assert section_body(new, "Brand New") == "hello"


def test_create_project_initialises_state(project):
    assert project.state_path.exists()
    assert "geumjeong_station_brief" in project.read_state()
    assert project.modules_dir.is_dir()


def test_update_brief_sections_backs_up_and_patches(project):
    project.update_brief_sections({"Core Problem": "patched", "Site Issues": ""})
    assert (project.path / "brief.prev.md").exists()
    assert section_body(project.read_brief(), "Core Problem") == "patched"
    assert "## Main Layers" in project.read_brief()
    # empty value ignored
    assert section_body(project.read_brief(), "Site Issues") == section_body(BRIEF, "Site Issues")


def test_history_roundtrip_filters_bad_items(project):
    project.save_history([{"role": "user", "content": "a"}, {"role": "bogus", "content": "x"}, {"role": "assistant", "content": ""}])
    loaded = project.load_history()
    assert loaded == [{"role": "user", "content": "a"}]


def test_list_projects_most_recent_first(mock_config, project):
    older = project
    newer = prj.create_blank_project("newer", config=mock_config)
    # make sure ordering does not depend on the clock resolution
    s = json.loads(older.session_path.read_text(encoding="utf-8"))
    s["updated_at"] = "2000-01-01T00:00:00+00:00"
    older.session_path.write_text(json.dumps(s), encoding="utf-8")
    names = [p.name for p in prj.list_projects(mock_config)]
    assert names[0] == newer.name and names[-1] == older.name


def test_rename_moves_folder(mock_config, project):
    old_path = project.path
    project.rename("Renamed Project", config=mock_config)
    assert not old_path.exists()
    assert project.path.name == "renamed_project"
    assert project.brief_path.exists()


def test_read_module_none_when_missing(project):
    assert project.read_module("01_site_reader.md") is None
    (project.modules_dir / "01_site_reader.md").write_text("x", encoding="utf-8")
    assert project.read_module("01_site_reader.md") == "x"


def test_init_state_does_not_overwrite(project):
    project.state_path.write_text("# custom", encoding="utf-8")
    project.init_state()
    assert project.read_state() == "# custom"
    project.init_state(force=True)
    assert "## Meta" in project.read_state()


def test_open_or_create_existing_returns_not_created(mock_config, project):
    p, created = prj.open_or_create(project.path, config=mock_config)
    assert not created and p.path == project.path
    assert os.path.samefile(p.brief_path, project.brief_path)
