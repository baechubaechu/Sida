#!/usr/bin/env python3
"""Terminal front end for one Conductor session: printing, prompts, the input loop.

The logic itself lives in engine.py; this module renders its events and asks the
designer the questions (apply this state update? …) that a terminal has to ask inline.
"""

from __future__ import annotations

from pathlib import Path

import engine
from console import configure_stdio
from engine import (  # noqa: F401  (re-exported: commands.py, tests and scripts import them here)
    MAX_READS_PER_TURN,
    READ_CHAR_LIMIT,
    Session,
    completed_ids,
    load_existing_outputs,
    module_completed_note,
    opening_prompt,
)
from harness import (
    LLMError,
    fail,
    load_config,
    load_env,
    resolve_conductor_runtime,
)
from i18n import t
from project import projects_dir

# ---------------------------------------------------------------------------
# Rendering engine events
# ---------------------------------------------------------------------------


def cli_emit(kind: str, data: dict) -> None:
    """Print an engine event the way the terminal UI always has."""
    from console import ROLE_COLOR, agent_look, paint

    if kind == "conductor_reply":
        label = paint(t("conductor_label"), ROLE_COLOR["conductor"], bold=True)
        print(f"\n{label}{data['text']}")
        if data.get("usage"):
            print(f"[{data['usage']}]")
    elif kind == "action_recovered":
        print(t("action_recovered", action=data["action"], agent=data["agent"]))
    elif kind == "conductor_error":
        print()
        print(t("conductor_error", reason=data["reason"]))
        print(t("conductor_not_sent"))
    elif kind == "unknown_agent":
        key = "conductor_unknown_read" if data["action"] == "read" else "conductor_unknown_agent"
        print(t(key, agent=data["agent"]))
    elif kind == "reading":
        print(t("conductor_reading", file=data["file"]))
    elif kind == "read_failed":
        reason = t("read_reason_empty") if data["reason"] == "empty" else t("read_reason_limit")
        print(t("conductor_read_fail", agent=data["agent"], reason=reason))
    elif kind == "module_started":
        agent = data["agent"]
        tag, accent = agent_look(agent.get("id"))
        labeled = f"[{tag}] {agent.get('name', agent.get('id'))}"
        print()
        print(paint(t("module_running", name=labeled), accent, bold=True))
    elif kind == "module_saved":
        agent = data["agent"]
        tag, accent = agent_look(agent.get("id"))
        labeled = f"[{tag}] {agent.get('name', agent.get('id'))}"
        print(paint(t("module_saved", path=data["path"].as_posix()), accent))
        preview_text = data["preview"] + ("\n..." if data["truncated"] else "")
        header = paint(t("module_preview", name=labeled), accent, bold=True)
        rule = paint("----------------------", accent)
        print(f"\n{header}\n{preview_text}\n{rule}\n")
    elif kind == "notice":
        print(data["message"])


def _cli(session: Session) -> Session:
    if session.emit is None:
        session.emit = cli_emit
    return session


# ---------------------------------------------------------------------------
# Expert runs and state updates
# ---------------------------------------------------------------------------


def update_state_after_module(session: Session, agent: dict, *, mode: str | None = None) -> bool:
    """
    Propose a project_state.md patch from the module output and apply it according to
    state_update.mode (ask | auto | off). Returns True if the file changed.
    """
    from console import agent_look, paint, prompt_line

    mode = mode or engine.state_update_mode(session)
    if mode == "off":
        return False

    tag, accent = agent_look(agent.get("id"))
    print(paint(t("state_proposing", agent=f"[{tag}] {agent.get('id')}"), accent))
    try:
        proposal = engine.propose_state(session, agent)
    except LLMError as exc:
        print(t("state_propose_failed", reason=str(exc)))
        return False
    if proposal is None:
        print(t("state_no_change"))
        return False

    if mode == "auto":
        path = engine.apply_state(session, proposal)
        print(t("state_applied", path=str(path)))
        return True

    print()
    print(proposal.diff)
    print()
    answer = (prompt_line(t("state_apply_prompt")) or "").strip().lower()
    if answer in {"n", "no", "ㄴ"}:
        print(t("state_skipped"))
        return False
    path = engine.apply_state(session, proposal)
    print(t("state_applied", path=str(path)))
    if answer in {"e", "edit"}:
        from briefs import edit_file_in_editor

        edit_file_in_editor(session.project.state_path)
    return True


def execute_run(session: Session, agent: dict) -> None:
    """Run one module and refresh cached outputs. Raises LLMError on failure."""
    engine.run_module(_cli(session), agent)


def _run_and_update(session: Session, agent: dict) -> bool | None:
    """Run an expert, then offer the state update. None if the run failed (reported)."""
    try:
        execute_run(session, agent)
    except LLMError as exc:
        print(t("module_failed", reason=str(exc)))
        print(t("module_nothing_saved", agent=agent.get("id")))
        return None
    return update_state_after_module(session, agent)


def run_module_command(session: Session, agent: dict, user_text: str) -> None:
    """`/run <agent>`: run without a Conductor call, record the outcome."""
    updated = _run_and_update(session, agent)
    if updated is None:
        return
    engine.record_command_run(session, agent, user_text, state_updated=updated)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _run_from_action(session: Session, agent: dict) -> None:
    updated = _run_and_update(session, agent)
    if updated is not None:
        engine.record_action_run(session, agent, state_updated=updated)


def handle_action(session: Session, action: dict) -> str:
    """
    Execute a Conductor action.
    Returns "exit", "continue", or "read:<agent_id>" (caller re-asks with the file).
    """
    kind, agent = engine.resolve_action(_cli(session), action)
    if kind == "read":
        return f"read:{agent.get('id')}"
    if kind == "run":
        _run_from_action(session, agent)
        return "continue"
    return kind


def conductor_turn(session: Session, user_text: str | None, *, ephemeral: bool = False) -> str:
    """
    One full Conductor exchange including follow-up `read` actions and a `run` action.
    Returns "exit" or "continue". Provider errors are reported, not fatal.
    """
    turn = engine.conductor_turn(_cli(session), user_text, ephemeral=ephemeral)
    if turn.outcome == "run":
        _run_from_action(session, turn.agent)
        return "continue"
    return turn.outcome


# ---------------------------------------------------------------------------
# Session bootstrap / loop
# ---------------------------------------------------------------------------


def print_banner(session: Session) -> None:
    project = session.project
    print(t("sess_projects_root", path=projects_dir()))
    print(t("sess_project", path=project.path))
    print(t("sess_brief", path=project.brief_path))
    print(t("sess_modules", path=session.output_dir))
    if project.state_path.exists():
        print(t("sess_state", path=project.state_path))
    runtime = resolve_conductor_runtime(session.config)
    window = int(runtime["history_window"])
    if window > 0:
        print(t("sess_context", n=window))
    if runtime["provider"] in {"ollama", "local"}:
        ctx = runtime.get("num_ctx")
        print(
            t(
                "sess_conductor_local",
                provider=runtime["provider"],
                profile=runtime.get("local_profile") or "local",
                model=runtime["model"],
                ctx=f", ctx={ctx}" if ctx else "",
            )
        )
    else:
        print(t("sess_conductor_cloud", provider=runtime["provider"], model=runtime["model"]))
    if session.created:
        print(t("sess_created"))
    else:
        print(t("sess_resumed"))
        if session.history:
            print(t("sess_loaded_turns", n=session.user_turns()))
    print(t("session_hint"))
    print()


def open_session(
    target: Path, project_name: str | None = None, *, created: bool | None = None
) -> Session:
    """Load config, providers and project; no model call yet.

    `created` overrides detection when the caller (hub) just made the folder.
    """
    configure_stdio()
    config = load_config()
    api_key = load_env(config=config)

    def boot(cfg: dict) -> None:
        from ollama_boot import ensure_ollama_ready

        ensure_ollama_ready(cfg)

    try:
        session = engine.build_session(
            config, api_key, target, project_name, created=created, before_providers=boot
        )
    except LLMError as exc:
        fail(str(exc))
    return _cli(session)


def run_session(
    target: Path, project_name: str | None = None, *, created: bool | None = None
) -> str:
    """
    Run a Conductor session inside one project.
    Returns "close" (back to hub) or "quit" (exit app).
    """
    from commands import dispatch

    session = open_session(target, project_name=project_name, created=created)
    print_banner(session)

    def leave(kind: str) -> str:
        session.persist()
        print(t("session_saved_quit" if kind == "quit" else "session_saved_close"))
        return kind

    if conductor_turn(session, opening_prompt(session), ephemeral=True) == "exit":
        return leave("close")

    while True:
        try:
            user_text = input(f"\n{t('you_prompt')}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return leave("close")

        if not user_text:
            continue

        outcome = dispatch(session, user_text)
        if outcome == "quit":
            return leave("quit")
        if outcome == "close":
            return leave("close")
        if outcome == "continue":
            continue

        session.project.append_transcript("You", user_text)
        if conductor_turn(session, user_text) == "exit":
            return leave("close")
