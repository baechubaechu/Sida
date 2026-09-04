from __future__ import annotations

from harness import LLMError
from session import conductor_turn, handle_action, opening_prompt

NONE = 'ok\n```action\n{"type":"none"}\n```'


def test_handle_action_exit_and_unknowns(make_session, capsys):
    s = make_session()
    assert handle_action(s, {"type": "exit"}) == "exit"
    assert handle_action(s, {"type": "none"}) == "continue"
    assert handle_action(s, {"type": "read", "module": "zzz"}) == "continue"
    assert handle_action(s, {"type": "run", "agent": "zzz"}) == "continue"
    out = capsys.readouterr().out
    assert "zzz" in out


def test_handle_action_read_routes_by_alias(make_session):
    s = make_session()
    assert handle_action(s, {"type": "read", "module": "site reader"}) == "read:site_reader"
    assert handle_action(s, {"type": "read", "agent": "01_site_reader"}) == "read:site_reader"


def test_handle_action_run_success_records_note(make_session):
    s = make_session()
    assert handle_action(s, {"type": "run", "agent": "site_reader"}) == "continue"
    assert (s.output_dir / "01_site_reader.md").exists()
    assert s.history[-1]["content"].startswith("[module completed] site_reader")
    assert len(s.previous_blocks) == 1


def test_handle_action_run_failure_is_not_fatal(make_session, capsys):
    class Boom:
        name = "boom"

        def chat(self, *a, **k):
            raise LLMError("down")

    s = make_session(w_provider=Boom())
    assert handle_action(s, {"type": "run", "agent": "constraint_mapper"}) == "continue"
    assert not (s.output_dir / "02_constraint_mapper.md").exists()
    assert s.history == []
    assert "down" in capsys.readouterr().out


def test_conductor_turn_provider_error_keeps_history(make_session, capsys):
    class Boom:
        name = "boom"

        def chat(self, *a, **k):
            raise LLMError("down")

    s = make_session(c_provider=Boom())
    assert conductor_turn(s, "hello") == "continue"
    assert s.history == []
    assert "down" in capsys.readouterr().out


def test_conductor_turn_read_flow_injects_file_once(make_session, scripted):
    s = make_session()
    (s.output_dir / "01_site_reader.md").write_text("# Site Reader\n\n## Missing Information\n- survey", encoding="utf-8")
    s.refresh_modules()
    provider = scripted(
        [
            'let me check\n```action\n{"type":"read","module":"site_reader"}\n```',
            'it says survey\n```action\n{"type":"none"}\n```',
        ]
    )
    s.c_provider = provider
    assert conductor_turn(s, "what was missing?") == "continue"
    assert len(provider.calls) == 2
    injected = provider.calls[1]["messages"][-1]["content"]
    assert "MODULE FILE modules/01_site_reader.md" in injected and "survey" in injected
    roles = [m["role"] for m in s.history]
    # user question, assistant(read), [read] marker, assistant(answer)
    assert roles == ["user", "assistant", "user", "assistant"]
    assert s.history[2]["content"].startswith("[read]")


def test_conductor_turn_read_limit(make_session, scripted):
    s = make_session()
    (s.output_dir / "01_site_reader.md").write_text("x", encoding="utf-8")
    read = 'again\n```action\n{"type":"read","module":"site_reader"}\n```'
    provider = scripted([read, read, read, NONE])
    s.c_provider = provider
    assert conductor_turn(s, "q") == "continue"
    # 1 initial + MAX_READS_PER_TURN follow-ups, then stop
    assert len(provider.calls) == 3


def test_conductor_turn_read_missing_file(make_session, scripted, capsys):
    s = make_session()
    provider = scripted(['x\n```action\n{"type":"read","module":"design_critic"}\n```'])
    s.c_provider = provider
    assert conductor_turn(s, "q") == "continue"
    assert len(provider.calls) == 1
    assert "design_critic" in capsys.readouterr().out


def test_opening_prompt_variants(make_session):
    s = make_session()
    assert "새 세션" in opening_prompt(s)
    s.history = [{"role": "assistant", "content": "hi"}]
    assert "재개" in opening_prompt(s)
    s.history = []
    s.created = False
    s.previous_blocks = ["### x\n\ny"]
    assert "이미 있는 모듈" in opening_prompt(s)
