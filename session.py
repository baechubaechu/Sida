#!/usr/bin/env python3
"""One Conductor session inside a project: state, turns, actions, main loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from conductor import ask_conductor
from console import configure_stdio
from harness import (
    ROOT,
    LLMError,
    agent_by_id,
    conductor_provider,
    fail,
    format_usage,
    get_agents,
    load_config,
    load_env,
    render_conductor_prompt,
    resolve_agent,
    resolve_conductor_runtime,
    run_worker_agent,
    worker_provider,
)
from i18n import get_language, t
from project import Project, open_or_create, projects_dir

MAX_READS_PER_TURN = 2
READ_CHAR_LIMIT = 6000


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class Session:
    api_key: str
    config: dict
    agents: list[dict]
    conductor_prompt: str
    project: Project
    project_brief: str
    previous_blocks: list[str]
    history: list[dict]
    c_provider: Any
    w_provider: Any
    created: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def output_dir(self) -> Path:
        return self.project.modules_dir

    def persist(self) -> None:
        self.project.save_history(self.history)
        self.project.save_session(history_messages=len(self.history))

    def reload_brief(self) -> None:
        self.project_brief = self.project.read_brief()

    def refresh_modules(self) -> None:
        self.previous_blocks[:] = load_existing_outputs(self.agents, self.output_dir)

    def user_turns(self) -> int:
        return sum(1 for m in self.history if m.get("role") == "user")

    def completed_ids(self) -> list[str]:
        return completed_ids(self.agents, self.output_dir)

    def note(self, role: str, content: str, *, transcript_role: str | None = None) -> None:
        """Append a synthetic history message and mirror it to the transcript."""
        self.history.append({"role": role, "content": content})
        self.project.append_transcript(transcript_role or "System", content)
        self.persist()


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def load_existing_outputs(agents: list[dict], output_dir: Path) -> list[str]:
    blocks: list[str] = []
    for agent in agents:
        path = output_dir / agent["output"]
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                blocks.append(f"### {agent['name']}\n\n{text}")
    return blocks


def completed_ids(agents: list[dict], output_dir: Path) -> list[str]:
    return [str(a.get("id")) for a in agents if (output_dir / a["output"]).exists()]


def module_completed_note(agent: dict, *, state_updated: bool = False) -> str:
    # Sent to the model — stays English regardless of UI language.
    base = f"[module completed] {agent.get('id')} → {agent.get('output')}. "
    if state_updated:
        return base + "project_state.md has been updated with this module's takeaways."
    return base + "Update project_state.md (Module Status + relevant sections) before the next turn."


def update_state_after_module(session: Session, agent: dict, *, mode: str | None = None) -> bool:
    """
    Propose a project_state.md patch from the module output and apply it according to
    state_update.mode (ask | auto | off). Returns True if the file changed.
    """
    from console import prompt_line
    from state_updater import (
        LLMError as _LLMError,
    )
    from state_updater import (
        propose_state_patch,
        state_diff,
        state_update_settings,
        write_state,
    )

    settings = state_update_settings(session.config)
    mode = mode or settings["mode"]
    if mode == "off":
        return False

    print(t("state_proposing", agent=agent.get("id")))
    try:
        patch, proposed = propose_state_patch(
            session.config,
            session.api_key,
            session.project,
            agent,
            c_provider=session.c_provider,
            w_provider=session.w_provider,
            lang=get_language(),
        )
    except _LLMError as exc:
        print(t("state_propose_failed", reason=str(exc)))
        return False

    current = session.project.state_path.read_text(encoding="utf-8")
    diff = state_diff(current, proposed)
    if not diff.strip():
        print(t("state_no_change"))
        return False

    if mode == "auto":
        write_state(session.project, proposed)
        print(t("state_applied", path=str(session.project.state_path)))
        return True

    print()
    print(diff)
    print()
    answer = (prompt_line(t("state_apply_prompt")) or "").strip().lower()
    if answer in {"n", "no", "ㄴ"}:
        print(t("state_skipped"))
        return False
    write_state(session.project, proposed)
    print(t("state_applied", path=str(session.project.state_path)))
    if answer in {"e", "edit"}:
        from briefs import edit_file_in_editor

        edit_file_in_editor(session.project.state_path)
    return True


def execute_run(session: Session, agent: dict) -> None:
    """Run one module and refresh cached outputs. Raises LLMError on failure."""
    name = agent.get("name", agent.get("id"))
    print()
    print(t("module_running", name=name))
    result = run_worker_agent(
        session.api_key,
        session.config,
        agent,
        session.project_brief,
        session.previous_blocks,
        session.output_dir,
        provider=session.w_provider,
        project_state=session.project.read_state(),
    )
    session.refresh_modules()
    out_path = session.output_dir / agent["output"]
    print(t("module_saved", path=out_path.as_posix()))
    preview = result.strip().splitlines()
    preview_text = "\n".join(preview[:12])
    if len(preview) > 12:
        preview_text += "\n..."
    print(f"\n{t('module_preview', name=name)}\n{preview_text}\n----------------------\n")


def run_module_command(session: Session, agent: dict, user_text: str) -> None:
    """`/run <agent>`: run without a Conductor call, record the outcome."""
    try:
        execute_run(session, agent)
    except LLMError as exc:
        print(t("module_failed", reason=str(exc)))
        print(t("module_nothing_saved", agent=agent.get("id")))
        return
    updated = update_state_after_module(session, agent)
    note = module_completed_note(agent, state_updated=updated)
    session.history.append({"role": "user", "content": user_text})
    session.history.append({"role": "assistant", "content": note})
    session.project.append_transcript("User", user_text)
    session.project.append_transcript("System", note)
    session.persist()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def handle_action(session: Session, action: dict) -> str:
    """
    Execute a Conductor action.
    Returns "exit", "continue", or "read:<agent_id>" (caller re-asks with the file).
    """
    action_type = str(action.get("type", "none")).lower()
    if action_type == "exit":
        return "exit"

    if action_type == "read":
        target = str(action.get("module") or action.get("agent") or "").strip()
        agent = resolve_agent(session.agents, target) or agent_by_id(session.agents, target)
        if not agent:
            print(t("conductor_unknown_read", agent=target))
            return "continue"
        return f"read:{agent.get('id')}"

    if action_type == "run":
        agent_id = str(action.get("agent", "")).strip()
        agent = resolve_agent(session.agents, agent_id) or agent_by_id(session.agents, agent_id)
        if not agent:
            print(t("conductor_unknown_agent", agent=agent_id))
            return "continue"
        try:
            execute_run(session, agent)
        except LLMError as exc:
            print(t("module_failed", reason=str(exc)))
            print(t("module_nothing_saved", agent=agent.get("id")))
            return "continue"
        updated = update_state_after_module(session, agent)
        session.note("user", module_completed_note(agent, state_updated=updated))
        return "continue"

    return "continue"


def conductor_turn(session: Session, user_text: str | None, *, ephemeral: bool = False) -> str:
    """
    One full Conductor exchange including follow-up `read` actions.
    Returns "exit" or "continue". Provider errors are reported, not fatal.
    """
    extra: list[dict] | None = None
    reads = 0
    pending_text = user_text
    while True:
        try:
            reply, action, usage = ask_conductor(
                session.api_key,
                session.config,
                session.conductor_prompt,
                session.project_brief,
                session.previous_blocks,
                session.history,
                session.project.session_id,
                user_text=pending_text,
                project=session.project,
                agents=session.agents,
                output_dir=session.output_dir,
                provider=session.c_provider,
                ephemeral=ephemeral,
                extra_messages=extra,
            )
        except LLMError as exc:
            print()
            print(t("conductor_error", reason=str(exc)))
            print(t("conductor_not_sent"))
            return "continue"

        print(f"\n{t('conductor_label')}{reply}")
        session.project.append_transcript("Conductor", reply)
        session.persist()
        usage_line = format_usage(usage)
        if usage_line:
            print(f"[{usage_line}]")
        if action.get("recovered"):
            print(t("action_recovered", action=action.get("type"), agent=action.get("agent") or action.get("module") or ""))

        outcome = handle_action(session, action)
        if not outcome.startswith("read:"):
            return outcome

        reads += 1
        agent_id = outcome.split(":", 1)[1]
        agent = agent_by_id(session.agents, agent_id)
        content = session.project.read_module(agent["output"]) if agent else None
        if reads > MAX_READS_PER_TURN or not content:
            reason = t("read_reason_empty") if not content else t("read_reason_limit")
            print(t("conductor_read_fail", agent=agent_id, reason=reason))
            return "continue"
        if len(content) > READ_CHAR_LIMIT:
            content = content[:READ_CHAR_LIMIT] + "\n\n[... truncated ...]"
        print(t("conductor_reading", file=agent["output"]))
        session.note("user", f"[read] Showed modules/{agent['output']} to the Conductor.")
        extra = [
            {
                "role": "user",
                "content": (
                    f"MODULE FILE modules/{agent['output']}:\n\n{content}\n\n"
                    "Answer the designer's last question using this file. "
                    "Do not request another read unless strictly necessary."
                ),
            }
        ]
        pending_text = None
        ephemeral = True


# ---------------------------------------------------------------------------
# Session bootstrap / loop
# ---------------------------------------------------------------------------


def opening_prompt(session: Session) -> str:
    """Ephemeral first instruction for the Conductor (never stored in history)."""
    ko = get_language() == "ko"
    if session.history:
        return (
            "세션이 재개되었습니다. 이전 대화는 이미 컨텍스트에 있습니다. "
            "한두 문장으로 짧게 인사하고, 완료된 모듈이 있으면 언급한 뒤 "
            "설계자의 다음 지시를 기다리세요. 요청 없이 모듈을 다시 실행하지 마세요."
            if ko
            else (
                "Session resumed. The previous conversation is already in context. "
                "Greet briefly in one or two sentences, note completed modules if any, "
                "and wait for the designer's next instruction. Do not rerun modules unless asked."
            )
        )
    if session.created or not session.previous_blocks:
        return (
            "새 세션이 시작되었습니다. 짧게 인사하고, 핵심 문제를 한두 문장으로 요약한 뒤 "
            "첫 모듈이나 질문을 제안하세요. 브리프가 매우 완전하고 첫 단계가 분명한 경우가 "
            "아니면 아직 모듈을 실행하지 마세요."
            if ko
            else (
                "A new session just started. Greet briefly, summarize the core problem "
                "in one or two sentences, and suggest the best first module or question. "
                "Do not run a module yet unless the brief is already very complete and "
                "the first step is obvious."
            )
        )
    return (
        "세션이 재개되었습니다. 짧게 인사하고, 이미 있는 모듈을 언급한 뒤 "
        "다음에 유용한 단계를 제안하세요. 요청 없이 모듈을 다시 실행하지 마세요."
        if ko
        else (
            "Session resumed. Greet briefly, note which modules already exist, "
            "and suggest the most useful next step. Do not rerun modules unless asked."
        )
    )


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
    api_key = load_env()
    config = load_config()
    agents = get_agents(config)

    conductor_cfg = config.get("conductor") or {}
    prompt_rel = conductor_cfg.get("prompt", "agents/00_conductor.md")
    prompt_path = ROOT / prompt_rel
    if not prompt_path.exists():
        fail(f"Missing conductor prompt: {prompt_path}")
    conductor_prompt = render_conductor_prompt(
        prompt_path.read_text(encoding="utf-8"), config
    )

    project, detected = open_or_create(target, name=project_name, config=config)
    if created is None:
        created = detected

    try:
        from ollama_boot import ensure_ollama_ready

        ensure_ollama_ready(config)
        c_provider = conductor_provider(config, api_key)
        w_provider = worker_provider(config, api_key)
    except LLMError as exc:
        fail(str(exc))

    return Session(
        api_key=api_key,
        config=config,
        agents=agents,
        conductor_prompt=conductor_prompt,
        project=project,
        project_brief=project.read_brief(),
        previous_blocks=load_existing_outputs(agents, project.modules_dir),
        history=project.load_history(),
        c_provider=c_provider,
        w_provider=w_provider,
        created=created,
    )


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
