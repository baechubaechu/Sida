from __future__ import annotations

import hub
from session import open_session


def _feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def test_sample_created_flag_first_then_existing(mock_config, monkeypatch):
    monkeypatch.setattr(hub, "load_config", lambda *a, **k: mock_config)
    _feed(monkeypatch, ["s"])
    path, created = hub.project_hub()
    assert created is True and path.name == "sample_brief"
    _feed(monkeypatch, ["s"])
    path2, created2 = hub.project_hub()
    assert created2 is False and path2 == path


def test_open_existing_by_number_not_created(mock_config, project, monkeypatch):
    monkeypatch.setattr(hub, "load_config", lambda *a, **k: mock_config)
    _feed(monkeypatch, ["1"])
    path, created = hub.project_hub()
    assert path == project.path and created is False


def test_new_project_created_flag(mock_config, monkeypatch):
    monkeypatch.setattr(hub, "load_config", lambda *a, **k: mock_config)
    _feed(monkeypatch, ["n", "My House", "주택", "", "", "", "", ""])
    path, created = hub.project_hub()
    assert created is True and path.name == "my_house"
    assert "주택" in (path / "brief.md").read_text(encoding="utf-8")


def test_quit_returns_none(mock_config, monkeypatch):
    monkeypatch.setattr(hub, "load_config", lambda *a, **k: mock_config)
    _feed(monkeypatch, ["q"])
    assert hub.project_hub() is None


def test_open_session_honours_created_override(mock_config, project, monkeypatch):
    import session as sess

    monkeypatch.setattr(sess, "load_env", lambda *a, **k: "dummy")
    monkeypatch.setattr(sess, "load_config", lambda *a, **k: mock_config)
    s = open_session(project.path)  # existing folder -> detected False
    assert s.created is False
    s = open_session(project.path, created=True)
    assert s.created is True
