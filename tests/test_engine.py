"""engine.py — the session core driven without a terminal: values out, events instead of prints."""

from __future__ import annotations

import re

import pytest

import engine
import harness
from harness import LLMError, SidaError
from tests.conftest import ROOT

NONE = 'ok\n```action\n{"type":"none"}\n```'


@pytest.fixture
def core(make_session):
    """A Session with an event recorder instead of the terminal renderer."""

    def _make(**kw):
        s = make_session(**kw)
        s.events = []
        s.emit = lambda kind, data: s.events.append((kind, data))
        return s

    return _make


def kinds(session):
    return [k for k, _ in session.events]


class Boom:
    name = "boom"

    def chat(self, *a, **k):
        raise LLMError("down")


def test_engine_never_prints_or_reads_input():
    source = (ROOT / "engine.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*print\(", source, flags=re.MULTILINE)
    assert not re.search(r"\binput\(", source)


def test_turn_returns_run_without_running_the_expert(core, scripted, capsys):
    s = core(c_provider=scripted(['시작합니다\n```action\n{"type":"run","agent":"site_reader"}\n```']))
    turn = engine.conductor_turn(s, "사이트부터 보자")
    assert turn.outcome == "run" and turn.agent["id"] == "site_reader"
    assert turn.replies == ["시작합니다"] and turn.error is None
    assert not (s.output_dir / "11_site_reader.md").exists()  # caller decides when to run
    assert kinds(s) == ["conductor_reply"]
    assert s.events[0][1]["text"] == "시작합니다"
    assert capsys.readouterr().out == ""


def test_turn_exit_and_plain_reply(core, scripted):
    s = core(c_provider=scripted([NONE, 'bye\n```action\n{"type":"exit"}\n```']))
    assert engine.conductor_turn(s, "hi").outcome == "continue"
    assert engine.conductor_turn(s, "끝").outcome == "exit"


def test_turn_read_flow_reports_each_step(core, scripted):
    s = core()
    (s.output_dir / "11_site_reader.md").write_text("# Site Reader\n\n- survey", encoding="utf-8")
    s.c_provider = scripted(
        [
            '확인해 볼게요\n```action\n{"type":"read","module":"site_reader"}\n```',
            '측량이 빠졌습니다\n```action\n{"type":"none"}\n```',
        ]
    )
    turn = engine.conductor_turn(s, "뭐가 빠졌지?")
    assert turn.outcome == "continue"
    assert turn.replies == ["확인해 볼게요", "측량이 빠졌습니다"]
    assert kinds(s) == ["conductor_reply", "reading", "conductor_reply"]
    assert s.events[1][1]["file"] == "11_site_reader.md"


def test_turn_read_of_missing_output_and_unknown_agent(core, scripted):
    s = core(c_provider=scripted(['x\n```action\n{"type":"read","module":"design_critic"}\n```']))
    assert engine.conductor_turn(s, "q").outcome == "continue"
    assert s.events[-1] == ("read_failed", {"agent": "design_critic", "reason": "empty"})

    s = core(c_provider=scripted(['x\n```action\n{"type":"run","agent":"zzz"}\n```']))
    turn = engine.conductor_turn(s, "q")
    assert turn.outcome == "continue" and turn.agent is None
    assert s.events[-1] == ("unknown_agent", {"action": "run", "agent": "zzz"})


def test_turn_provider_error_is_returned_not_raised(core, capsys):
    s = core(c_provider=Boom())
    turn = engine.conductor_turn(s, "hello")
    assert turn.outcome == "continue" and turn.error == "down"
    assert s.history == []
    assert s.events == [("conductor_error", {"reason": "down"})]
    assert capsys.readouterr().out == ""


def test_run_module_returns_result_and_events(core, capsys):
    s = core()
    agent = harness.agent_by_id(s.agents, "site_reader")
    run = engine.run_module(s, agent)
    assert run.path == s.output_dir / "11_site_reader.md" and run.path.exists()
    assert run.text.startswith("# Mock Output")
    assert kinds(s) == ["module_started", "module_saved"]
    saved = s.events[1][1]
    assert saved["path"] == run.path and saved["preview"].startswith("# Mock Output")
    assert len(s.previous_blocks) == 1  # cached outputs refreshed
    assert capsys.readouterr().out == ""


def test_run_module_failure_raises_and_saves_nothing(core):
    s = core(w_provider=Boom())
    agent = harness.agent_by_id(s.agents, "site_reader")
    with pytest.raises(LLMError):
        engine.run_module(s, agent)
    assert not (s.output_dir / "11_site_reader.md").exists()
    assert kinds(s) == ["module_started"]


def test_worker_warnings_become_notice_events_when_captured(core, monkeypatch, capsys):
    monkeypatch.delenv("LAW_OPEN_API_OC")
    s = core()
    project_type = "## Project Type\n환승역\n"
    s.project_brief = s.project_brief + "\n" + project_type  # gives the search something to ask
    s.config["rag"] = {"enabled": True, "provider": "lawgokr"}
    s.capture_notices = True
    engine.run_module(s, harness.agent_by_id(s.agents, "regulation_checker"))
    notices = [d["message"] for k, d in s.events if k == "notice"]
    assert any("[rag]" in m for m in notices)
    assert capsys.readouterr().err == ""  # nothing leaked to the terminal

    s2 = core()
    s2.project_brief = s.project_brief
    s2.config["rag"] = {"enabled": True, "provider": "lawgokr"}
    engine.run_module(s2, harness.agent_by_id(s2.agents, "regulation_checker"))
    assert "notice" not in kinds(s2)
    assert "[rag]" in capsys.readouterr().err  # default: printed, as the CLI expects


def test_state_proposal_is_separate_from_applying_it(core):
    s = core()
    agent = harness.agent_by_id(s.agents, "site_reader")
    engine.run_module(s, agent)
    before = s.project.read_state()

    proposal = engine.propose_state(s, agent)
    assert proposal is not None and "site_reader | done" in proposal.diff
    assert s.project.read_state() == before  # nothing written until applied

    path = engine.apply_state(s, proposal)
    assert path == s.project.state_path
    assert "| site_reader | done | (mock) takeaway |" in s.project.read_state()
    assert (s.project.path / "project_state.prev.md").exists()
    assert engine.state_update_mode(s) == "ask"


def test_state_proposal_none_when_nothing_changes(core, scripted):
    from datetime import date

    s = core()
    s.config["state_update"] = {"mode": "ask", "provider": "worker"}
    (s.output_dir / "11_site_reader.md").write_text("x", encoding="utf-8")
    s.project.state_path.write_text(
        s.project.read_state().replace(
            "- **Last updated**: YYYY-MM-DD", f"- **Last updated**: {date.today().isoformat()}"
        ),
        encoding="utf-8",
    )
    s.w_provider = scripted(['{"module_status":{"status":"pending","key_takeaway":""}}'])
    assert engine.propose_state(s, s.agents[0]) is None


def test_run_records_for_action_and_command(core):
    s = core()
    agent = harness.agent_by_id(s.agents, "site_reader")
    engine.record_action_run(s, agent, state_updated=True)
    assert [m["role"] for m in s.history] == ["user"]
    assert s.history[0]["content"].endswith("has been updated with this module's takeaways.")

    engine.record_command_run(s, agent, "/run site_reader", state_updated=False)
    assert [m["role"] for m in s.history] == ["user", "user", "assistant"]
    assert s.history[1]["content"] == "/run site_reader"
    assert "Update project_state.md" in s.history[2]["content"]
    assert "/run site_reader" in s.project.transcript_path.read_text(encoding="utf-8")


def test_build_session_opens_project_without_terminal(mock_config, project, capsys):
    calls = []
    s = engine.build_session(
        mock_config, "", project.path, created=True, before_providers=calls.append
    )
    assert calls == [mock_config]
    assert s.project.name == project.name and s.created is True
    assert s.emit is None and s.c_provider.name == "mock"
    assert "{{MODULES}}" not in s.conductor_prompt and "site_reader" in s.conductor_prompt
    assert capsys.readouterr().out == ""


def test_fail_raises_catchable_error_with_message(capsys):
    with pytest.raises(SidaError) as info:
        harness.fail("브리프가 없습니다", code=3)
    assert info.value.message == "브리프가 없습니다" and info.value.code == 3
    assert isinstance(info.value, SystemExit)  # the CLI still exits when nothing catches it
    assert "브리프가 없습니다" in capsys.readouterr().err
