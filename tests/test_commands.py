from __future__ import annotations

import sys
from pathlib import Path

from commands import dispatch
from project import section_body

FAKE_EDITOR = Path(__file__).parent / "_fixtures" / "fake_editor.py"


def _use_fake_editor(monkeypatch, append: str):
    monkeypatch.setenv("SIDA_EDITOR", f'"{sys.executable}" "{FAKE_EDITOR}" "{append}"')


def test_dispatch_returns_none_for_chat(make_session):
    s = make_session()
    assert dispatch(s, "hello there") is None
    assert dispatch(s, "/nonexistent") is None


def test_dispatch_close_quit(make_session):
    s = make_session()
    assert dispatch(s, "/close") == "close"
    assert dispatch(s, "/hub") == "close"
    assert dispatch(s, "/quit") == "quit"
    assert dispatch(s, "exit") == "quit"


def test_brief_show_and_usage(make_session, capsys):
    s = make_session()
    assert dispatch(s, "/brief") == "continue"
    assert "Geumjeong" in capsys.readouterr().out
    assert dispatch(s, "/brief whatever") == "continue"
    assert "/brief fields" in capsys.readouterr().out


def test_state_show_creates_when_missing(make_session, capsys):
    s = make_session()
    s.project.state_path.unlink()
    assert dispatch(s, "/state") == "continue"
    assert s.project.state_path.exists()
    assert "## Meta" in capsys.readouterr().out


def test_status_and_project(make_session, capsys):
    s = make_session()
    dispatch(s, "/status")
    dispatch(s, "/project")
    out = capsys.readouterr().out
    assert str(s.project.path) in out
    assert "session_id" in out


def test_run_command_with_mock(make_session, capsys):
    s = make_session()
    s.config["state_update"] = {"mode": "off"}
    assert dispatch(s, "/run site_reader") == "continue"
    assert (s.output_dir / "01_site_reader.md").exists()
    assert s.history[-1]["content"].startswith("[module completed]")
    assert dispatch(s, "/run") == "continue"
    assert dispatch(s, "/run nope") == "continue"
    out = capsys.readouterr().out
    assert "nope" in out


def test_brief_edit_with_editor_backs_up_and_notes(make_session, monkeypatch):
    s = make_session()
    _use_fake_editor(monkeypatch, "\n## Added By Editor\n- new section\n")
    assert dispatch(s, "/brief edit") == "continue"
    assert (s.project.path / "brief.prev.md").exists()
    assert "## Added By Editor" in s.project_brief  # session reloaded brief
    assert s.history[-1]["content"].startswith("[system] The project brief was updated")


def test_brief_edit_unchanged_adds_no_note(make_session, monkeypatch):
    s = make_session()
    _use_fake_editor(monkeypatch, "")
    assert dispatch(s, "/brief edit") == "continue"
    assert s.history == []


def test_state_edit_with_editor(make_session, monkeypatch):
    s = make_session()
    _use_fake_editor(monkeypatch, "\n- [2026-09-04] decided X\n")
    assert dispatch(s, "/state edit") == "continue"
    assert "decided X" in s.project.read_state()


def test_brief_fields_keeps_other_sections(make_session, monkeypatch):
    s = make_session()
    answers = iter(["", "", "new core problem", "a, b", "", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    assert dispatch(s, "/brief fields") == "continue"
    brief = s.project.read_brief()
    assert section_body(brief, "Core Problem") == "new core problem"
    assert section_body(brief, "Site Issues") == "- a\n- b"
    assert "## Main Layers" in brief
    assert s.project_brief == brief


def test_editor_failure_is_reported_not_raised(make_session, monkeypatch, capsys):
    s = make_session()
    monkeypatch.setenv("SIDA_EDITOR", "definitely-not-an-editor-xyz")
    assert dispatch(s, "/brief edit") == "continue"
    assert "EDITOR" in capsys.readouterr().out
