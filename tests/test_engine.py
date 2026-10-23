"""engine.py — the session core driven without a terminal: values out, events instead of prints."""

from __future__ import annotations

import re

import pytest

from sida import config as sida_config
from sida import engine, errors
from sida.errors import SidaError
from sida.providers import LLMError
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
    source = (ROOT / "sida" / "engine.py").read_text(encoding="utf-8")
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
    agent = sida_config.agent_by_id(s.agents, "site_reader")
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
    agent = sida_config.agent_by_id(s.agents, "site_reader")
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
    engine.run_module(s, sida_config.agent_by_id(s.agents, "regulation_checker"))
    notices = [d["message"] for k, d in s.events if k == "notice"]
    assert any("[rag]" in m for m in notices)
    assert capsys.readouterr().err == ""  # nothing leaked to the terminal

    s2 = core()
    s2.project_brief = s.project_brief
    s2.config["rag"] = {"enabled": True, "provider": "lawgokr"}
    engine.run_module(s2, sida_config.agent_by_id(s2.agents, "regulation_checker"))
    assert "notice" not in kinds(s2)
    assert "[rag]" in capsys.readouterr().err  # default: printed, as the CLI expects


def test_state_proposal_is_separate_from_applying_it(core):
    s = core()
    agent = sida_config.agent_by_id(s.agents, "site_reader")
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
    agent = sida_config.agent_by_id(s.agents, "site_reader")
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
        errors.fail("브리프가 없습니다", code=3)
    assert info.value.message == "브리프가 없습니다" and info.value.code == 3
    assert isinstance(info.value, Exception)
    assert not isinstance(info.value, SystemExit)
    assert str(info.value) == "브리프가 없습니다"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("changed", ["state", "module", "brief"])
def test_state_approval_rejects_changed_source(core, changed):
    from sida.project_documents import DocumentConflict

    s = core()
    agent = s.agents[0]
    engine.run_module(s, agent)
    proposal = engine.propose_state(s, agent)
    target = {
        "state": s.project.state_path,
        "module": s.output_dir / agent["output"],
        "brief": s.project.brief_path,
    }[changed]
    target.write_text(target.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    before = s.project.state_path.read_bytes()
    with pytest.raises(DocumentConflict):
        engine.apply_state(s, proposal)
    assert s.project.state_path.read_bytes() == before
    assert not (s.project.path / "project_state.prev.md").exists()


def test_discard_state_never_writes_and_replay_cannot_apply(core):
    from sida.project_documents import DocumentConflict

    s = core()
    engine.run_module(s, s.agents[0])
    proposal = engine.propose_state(s, s.agents[0])
    before = s.project.state_path.read_bytes()
    engine.discard_state(s, proposal)
    assert s.project.state_path.read_bytes() == before
    assert s.pending_state is None
    with pytest.raises(DocumentConflict):
        engine.apply_state(s, proposal)


def test_applied_state_cannot_be_applied_twice(core):
    from sida.project_documents import DocumentConflict

    s = core()
    engine.run_module(s, s.agents[0])
    proposal = engine.propose_state(s, s.agents[0])
    engine.apply_state(s, proposal)
    before_backup = (s.project.path / "project_state.prev.md").read_bytes()
    with pytest.raises(DocumentConflict):
        engine.apply_state(s, proposal)
    assert (s.project.path / "project_state.prev.md").read_bytes() == before_backup


def test_editing_brief_refreshes_session_context(core, capsys):
    s = core()
    document = engine.read_editable_document(s, "brief")
    edited = document.content + "\n## 직접 작성한 요구\n- 보행 연결\n"
    saved = engine.edit_document(s, "brief", edited, expected_revision=document.revision)
    assert s.project_brief == saved.content
    assert "보행 연결" in s.project_brief
    assert capsys.readouterr() == ("", "")


def test_identical_summary_for_new_module_version_still_needs_acceptance(core):
    from sida.conductor_context import modules_newer_than_state

    s = core()
    agent = s.agents[0]
    engine.run_module(s, agent)
    proposal = engine.propose_state(s, agent)
    engine.apply_state(s, proposal)
    module = s.output_dir / agent["output"]
    module.write_text(module.read_text(encoding="utf-8") + "\n새 결과\n", encoding="utf-8")
    next_proposal = engine.propose_state(s, agent)
    assert next_proposal is not None
    assert "sida-module-revisions" not in next_proposal.diff
    assert modules_newer_than_state(s.agents, s.output_dir, s.project.state_path) == [agent]
    engine.apply_state(s, next_proposal)
    assert modules_newer_than_state(s.agents, s.output_dir, s.project.state_path) == []


RUN_SITE = '사이트부터 보겠습니다\n```action\n{"type":"run","agent":"site_reader"}\n```'


FOLLOW_UP = '대지 결과를 보니 북측 일조가 관건입니다.\n```action\n{"type":"none"}\n```'


def test_converse_runs_the_expert_and_leaves_the_state_proposal_pending(core, scripted, capsys):
    conductor = scripted([RUN_SITE, FOLLOW_UP])
    s = core(c_provider=conductor)
    before = s.project.read_state()
    turn = engine.converse(s, "대지부터 봐 줘")
    assert turn.outcome == "continue" and turn.error is None
    assert turn.replies == ["사이트부터 보겠습니다", "대지 결과를 보니 북측 일조가 관건입니다."]
    assert (s.output_dir / "11_site_reader.md").exists()
    assert kinds(s) == [
        "conductor_reply", "module_started", "module_saved", "state_proposing", "state_proposed",
        "conductor_reply",
    ]
    # "ask" mode: a web screen approves later; nothing is written to project_state.md now.
    assert s.project.read_state() == before
    assert s.pending_state is s.events[4][1]["proposal"]
    # The Conductor sees the result and is told not to chain while the proposal waits.
    follow_up = conductor.calls[1]["messages"][-1]["content"]
    assert "site_reader" in follow_up and "waiting for the designer's review" in follow_up
    assert "you may run it now" not in follow_up
    assert s.history[-2]["content"].startswith("[module completed] site_reader")
    assert "Update project_state.md" in s.history[-2]["content"]
    assert s.history[-1] == {"role": "assistant", "content": FOLLOW_UP}
    assert not any(m["content"] == follow_up for m in s.history)  # the instruction is not stored
    assert "대지부터 봐 줘" in s.project.transcript_path.read_text(encoding="utf-8")
    assert capsys.readouterr() == ("", "")


def test_converse_in_auto_mode_applies_the_state(core, scripted, mock_config):
    mock_config["state_update"]["mode"] = "auto"
    conductor = scripted([RUN_SITE, FOLLOW_UP])
    s = core(c_provider=conductor)
    engine.converse(s, "대지부터")
    assert kinds(s)[-2:] == ["state_applied", "conductor_reply"]
    assert "| site_reader | done | (mock) takeaway |" in s.project.read_state()
    assert s.history[-2]["content"].endswith("has been updated with this module's takeaways.")
    assert "you may run it now" in conductor.calls[1]["messages"][-1]["content"]


def test_converse_reports_a_failed_expert_without_recording_it(core, scripted):
    conductor = scripted([RUN_SITE, FOLLOW_UP])
    s = core(c_provider=conductor, w_provider=Boom())
    turn = engine.converse(s, "대지부터")
    assert turn.outcome == "run"
    assert kinds(s)[-1] == "module_failed" and s.events[-1][1]["reason"] == "down"
    assert not any("[module completed]" in m["content"] for m in s.history)
    assert len(conductor.calls) == 1  # no follow-up after a failed run


RUN_PROGRAM = '프로그램도 보겠습니다\n```action\n{"type":"run","agent":"program_analyst"}\n```'


def test_converse_chains_experts_up_to_the_limit(core, scripted, mock_config):
    mock_config["state_update"]["mode"] = "auto"
    mock_config["conductor"]["max_expert_runs"] = 2
    conductor = scripted([RUN_SITE, RUN_PROGRAM, RUN_SITE])
    s = core(c_provider=conductor)
    turn = engine.converse(s, "알아서 진행해")
    assert turn.outcome == "continue" and turn.error is None
    assert [d["agent"]["id"] for k, d in s.events if k == "module_saved"] == [
        "site_reader", "program_analyst",
    ]
    # The second follow-up may not run again; the third request is reported, not run.
    assert "you may run it now" in conductor.calls[1]["messages"][-1]["content"]
    assert "Do not run another expert now" in conductor.calls[2]["messages"][-1]["content"]
    assert s.events[-1] == (
        "run_skipped", {"agent": engine.agent_by_id(s.agents, "site_reader"), "reason": "limit", "limit": 2}
    )
    assert len(turn.replies) == 3


def test_converse_does_not_chain_while_a_state_proposal_waits(core, scripted):
    conductor = scripted([RUN_SITE, RUN_PROGRAM])
    s = core(c_provider=conductor)
    engine.converse(s, "대지부터")
    assert kinds(s)[-1] == "run_skipped" and s.events[-1][1]["reason"] == "state_pending"
    assert not (s.output_dir / "12_program_analyst.md").exists()
    assert s.pending_state is not None  # the first proposal is still the one waiting


def test_converse_follow_up_failure_keeps_the_run(core, scripted):
    s = core(c_provider=scripted([RUN_SITE, LLMError("down")]))
    turn = engine.converse(s, "대지부터")
    assert turn.error is None  # the designer's message and the expert run are recorded
    assert s.events[-1] == ("conductor_error", {"reason": "down", "after_run": True})
    assert s.history[-1]["content"].startswith("[module completed] site_reader")
    assert (s.output_dir / "11_site_reader.md").exists()


def test_follow_up_prompt_is_english_and_pins_reply_language(monkeypatch):
    agent = {"id": "site_reader", "name": "대지 분석가"}
    monkeypatch.setattr(engine, "get_language", lambda: "ko")
    assert engine.follow_up_prompt(agent, may_run=True).endswith("Reply in Korean.")
    monkeypatch.setattr(engine, "get_language", lambda: "en")
    assert not engine.follow_up_prompt(agent, may_run=False).endswith("Reply in Korean.")


def test_settle_state_off_does_nothing_and_model_error_is_reported(core):
    s = core()
    agent = s.agents[0]
    engine.run_module(s, agent)
    assert engine.settle_state(s, agent, mode="off").outcome == "off"
    s.w_provider = Boom()
    step = engine.settle_state(s, agent, mode="ask")
    assert step.outcome == "failed" and step.error == "down"
    assert kinds(s)[-1] == "state_failed"


def test_history_messages_hide_actions_and_internal_notes():
    history = [
        {"role": "user", "content": "대지부터"},
        {"role": "assistant", "content": RUN_SITE},
        {"role": "user", "content": "[module completed] site_reader → 11_site_reader.md. Update …"},
        {"role": "user", "content": "[read] Showed modules/11_site_reader.md to the Conductor."},
        {"role": "user", "content": "/run program_analyst"},
        {"role": "assistant", "content": "[module completed] program_analyst → 12_program_analyst.md. …"},
    ]
    messages = engine.history_messages(history)
    assert [(m["role"], m.get("event"), m.get("agent")) for m in messages] == [
        ("user", None, None),
        ("conductor", None, None),
        ("system", "module_completed", "site_reader"),
        ("system", "read", "11_site_reader.md"),
        ("system", "run_requested", "program_analyst"),
        ("system", "module_completed", "program_analyst"),
    ]
    assert messages[1]["text"] == "사이트부터 보겠습니다"


def test_opening_prompt_variants(make_session):
    s = make_session()
    assert "A new session just started" in engine.opening_prompt(s)
    s.history = [{"role": "assistant", "content": "hi"}]
    assert "previous conversation is already in context" in engine.opening_prompt(s)
    s.history = []
    s.created = False
    s.previous_blocks = ["### x\n\ny"]
    assert "note which modules already exist" in engine.opening_prompt(s)


def test_opening_prompt_is_english_and_pins_reply_language(make_session, monkeypatch):
    # The instruction goes to the model: English text, Korean reply only when the UI is Korean.
    s = make_session()
    monkeypatch.setattr("sida.engine.get_language", lambda: "ko")
    ko = engine.opening_prompt(s)
    assert ko.endswith("Reply in Korean.")
    assert not re.search("[가-힣]", ko)
    monkeypatch.setattr("sida.engine.get_language", lambda: "en")
    assert "Korean" not in engine.opening_prompt(s)


def test_tool_only_reply_is_kept_in_history_but_not_shown(core, monkeypatch):
    from sida import conductor

    monkeypatch.setattr(conductor, "_NO_TOOLS", set())

    class Tools:
        name = "tools"

        def __init__(self):
            self.replies = [
                ("", [{"name": "run_expert", "arguments": {"agent": "site_reader"}}]),
                ("북측 일조가 관건입니다.", []),
            ]

        def chat_tools(self, model, messages, tools, temperature, max_tokens, **kw):
            text, calls = self.replies.pop(0)
            return text, calls, {}

    s = core(c_provider=Tools())
    turn = engine.converse(s, "대지부터")
    assert turn.replies == ["북측 일조가 관건입니다."]
    assert kinds(s)[0] == "module_started" and kinds(s)[-1] == "conductor_reply"
    shown = engine.history_messages(s.history)
    assert [(m["role"], m.get("event")) for m in shown] == [
        ("user", None), ("system", "module_completed"), ("conductor", None),
    ]
