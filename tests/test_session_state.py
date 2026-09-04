"""Session-level integration of the state updater (ask / auto / off, /state update)."""

from __future__ import annotations

from commands import dispatch
from session import handle_action, update_state_after_module


def _answer(monkeypatch, text):
    monkeypatch.setattr("builtins.input", lambda *_: text)


def test_run_action_ask_mode_apply(make_session, monkeypatch):
    s = make_session()
    _answer(monkeypatch, "y")
    assert handle_action(s, {"type": "run", "agent": "site_reader"}) == "continue"
    state = s.project.read_state()
    assert "| site_reader | done | (mock) takeaway |" in state
    assert (s.project.path / "project_state.prev.md").exists()
    assert s.history[-1]["content"].endswith("has been updated with this module's takeaways.")


def test_run_action_ask_mode_skip(make_session, monkeypatch):
    s = make_session()
    _answer(monkeypatch, "n")
    handle_action(s, {"type": "run", "agent": "site_reader"})
    assert "| site_reader | pending |" in s.project.read_state()
    assert "Update project_state.md" in s.history[-1]["content"]


def test_run_command_auto_mode(make_session, monkeypatch):
    s = make_session()
    s.config["state_update"] = {"mode": "auto"}
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("no prompt in auto")))
    assert dispatch(s, "/run constraint_mapper") == "continue"
    assert "| constraint_mapper | done |" in s.project.read_state()


def test_off_mode_never_calls_model(make_session, scripted):
    s = make_session()
    s.config["state_update"] = {"mode": "off"}
    s.w_provider = scripted(["# Mock\n\n## Site Conditions\n- a\n\n## Spatial Conflicts\n- b\n\n## Opportunities\n- c\n\n## Missing Information\n- d\n\n## Design Implications\n- e"])
    handle_action(s, {"type": "run", "agent": "site_reader"})
    assert len(s.w_provider.calls) == 1  # worker only, no state call
    assert "| site_reader | pending |" in s.project.read_state()


def test_propose_failure_is_reported_not_fatal(make_session, scripted, capsys):
    from harness import LLMError

    s = make_session()
    good = "# Mock\n\n## Site Conditions\n- a\n\n## Spatial Conflicts\n- b\n\n## Opportunities\n- c\n\n## Missing Information\n- d\n\n## Design Implications\n- e"
    s.w_provider = scripted([good, LLMError("state model down")])
    assert handle_action(s, {"type": "run", "agent": "site_reader"}) == "continue"
    assert (s.output_dir / "01_site_reader.md").exists()
    assert "state model down" in capsys.readouterr().out


def test_state_update_command_latest_and_explicit(make_session, monkeypatch, capsys):
    s = make_session()
    s.config["state_update"] = {"mode": "off"}
    dispatch(s, "/run site_reader")
    dispatch(s, "/run design_critic")
    assert "| site_reader | pending |" in s.project.read_state()
    _answer(monkeypatch, "")  # Enter = apply
    assert dispatch(s, "/state update") == "continue"  # latest = design_critic
    state = s.project.read_state()
    assert "| design_critic | done |" in state and "| site_reader | pending |" in state
    assert dispatch(s, "/state update site_reader") == "continue"
    assert "| site_reader | done |" in s.project.read_state()


def test_state_update_command_without_modules(make_session, capsys):
    s = make_session()
    assert dispatch(s, "/state update") == "continue"
    assert "agent id" in capsys.readouterr().out


def test_no_change_path(make_session, scripted, capsys):
    s = make_session()
    (s.output_dir / "01_site_reader.md").write_text("x", encoding="utf-8")
    # A patch that produces an identical file: status pending, no takeaway, today's date already set
    from datetime import date

    s.project.state_path.write_text(
        s.project.read_state().replace("- **Last updated**: YYYY-MM-DD", f"- **Last updated**: {date.today().isoformat()}"),
        encoding="utf-8",
    )
    s.w_provider = scripted(['{"module_status":{"status":"pending","key_takeaway":""}}'])
    assert update_state_after_module(s, s.agents[0]) is False
    out = capsys.readouterr().out
    assert "변경" in out or "changes" in out.lower()
