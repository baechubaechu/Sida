#!/usr/bin/env python3
"""UI-agnostic session core: state, Conductor turns, expert runs, project-state updates.

Nothing here prints or reads input. Each operation returns a value and reports
progress through `Session.emit` as (kind, data) events, so the terminal (session.py)
and any other front end can drive the same logic and render it their own way.

Event kinds and their data:
  conductor_reply   text, usage
  action_recovered  action, agent
  conductor_error   reason
  unknown_agent     action ("run" | "read"), agent
  reading           file
  read_failed       agent, reason ("empty" | "limit")
  module_started    agent
  module_saved      agent, path, preview, truncated
  notice            message          (only when Session.capture_notices is set)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sida.conductor import ask_conductor
from sida.conductor_context import render_conductor_prompt
from sida.config import ROOT, agent_by_id, get_agents, resolve_agent
from sida.errors import fail
from sida.i18n import get_language
from sida.project import Project, open_or_create
from sida.project_documents import Document, DocumentConflict, read_document, save_document
from sida.providers import format_usage
from sida.runtime import conductor_provider, worker_provider
from sida.state_revisions import content_revision, module_revisions
from sida.worker import run_worker_agent

MAX_READS_PER_TURN = 2
READ_CHAR_LIMIT = 6000
PREVIEW_LINES = 12

Emit = Callable[[str, dict], None]


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
    emit: Emit | None = None
    # When set, warnings from an expert run arrive as "notice" events instead of being printed.
    capture_notices: bool = False
    pending_state: StateProposal | None = None

    @property
    def output_dir(self) -> Path:
        return self.project.modules_dir

    def send(self, kind: str, **data: Any) -> None:
        if self.emit is not None:
            self.emit(kind, data)

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


@dataclass
class Turn:
    """Result of one Conductor exchange. outcome: "continue" | "exit" | "run" (then `agent` is set)."""

    outcome: str
    agent: dict | None = None
    replies: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ModuleRun:
    agent: dict
    text: str
    path: Path


@dataclass
class StateProposal:
    agent: dict
    proposed: str
    diff: str
    original_state: str
    original_brief: str
    module_revision: str


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


# ---------------------------------------------------------------------------
# Session bootstrap
# ---------------------------------------------------------------------------


def build_session(
    config: dict,
    api_key: str,
    target: Path,
    project_name: str | None = None,
    *,
    created: bool | None = None,
    before_providers: Callable[[dict], None] | None = None,
) -> Session:
    """
    Open (or create) the project and assemble a Session. No model call.

    `created` overrides detection when the caller just made the folder.
    `before_providers` runs after the project is open and before providers are built
    (the CLI uses it to start Ollama). Raises LLMError when a provider cannot be built.
    """
    agents = get_agents(config)

    conductor_cfg = config.get("conductor") or {}
    prompt_rel = conductor_cfg.get("prompt", "agents/00_conductor.md")
    prompt_path = ROOT / prompt_rel
    if not prompt_path.exists():
        fail(f"Missing conductor prompt: {prompt_path}")
    conductor_prompt = render_conductor_prompt(prompt_path.read_text(encoding="utf-8"), config)

    project, detected = open_or_create(target, name=project_name, config=config)
    if created is None:
        created = detected

    if before_providers is not None:
        before_providers(config)
    c_provider = conductor_provider(config, api_key)
    w_provider = worker_provider(config, api_key)

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


# ---------------------------------------------------------------------------
# Conductor
# ---------------------------------------------------------------------------


def resolve_action(session: Session, action: dict) -> tuple[str, dict | None]:
    """
    Map a Conductor action to ("exit" | "continue" | "run" | "read", agent).
    Unknown agents are reported with an "unknown_agent" event and become "continue".
    """
    kind = str(action.get("type", "none")).lower()
    if kind == "exit":
        return "exit", None
    if kind not in {"run", "read"}:
        return "continue", None

    if kind == "read":
        target = str(action.get("module") or action.get("agent") or "").strip()
    else:
        target = str(action.get("agent", "")).strip()
    agent = resolve_agent(session.agents, target) or agent_by_id(session.agents, target)
    if not agent:
        session.send("unknown_agent", action=kind, agent=target)
        return "continue", None
    return kind, agent


def conductor_turn(session: Session, user_text: str | None, *, ephemeral: bool = False) -> Turn:
    """
    One full Conductor exchange, following up `read` actions with the module file.
    A `run` action is returned (outcome "run"), not executed — the caller runs the expert.
    Provider errors are reported in the Turn, never raised.
    """
    from sida.providers import LLMError

    extra: list[dict] | None = None
    reads = 0
    pending_text = user_text
    replies: list[str] = []
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
            session.send("conductor_error", reason=str(exc))
            return Turn("continue", replies=replies, error=str(exc))

        replies.append(reply)
        session.project.append_transcript("Conductor", reply)
        session.persist()
        session.send("conductor_reply", text=reply, usage=format_usage(usage))
        if action.get("recovered"):
            session.send(
                "action_recovered",
                action=action.get("type"),
                agent=action.get("agent") or action.get("module") or "",
            )

        kind, agent = resolve_action(session, action)
        if kind != "read":
            return Turn(kind, agent=agent, replies=replies)

        reads += 1
        content = session.project.read_module(agent["output"])
        if reads > MAX_READS_PER_TURN or not content:
            session.send(
                "read_failed", agent=agent["id"], reason="empty" if not content else "limit"
            )
            return Turn("continue", replies=replies)
        if len(content) > READ_CHAR_LIMIT:
            content = content[:READ_CHAR_LIMIT] + "\n\n[... truncated ...]"
        session.send("reading", file=agent["output"])
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
# Expert runs
# ---------------------------------------------------------------------------


def run_module(session: Session, agent: dict) -> ModuleRun:
    """Run one expert and refresh cached outputs. Raises LLMError; nothing is saved then."""
    session.send("module_started", agent=agent)
    notify = None
    if session.capture_notices:

        def notify(message: str) -> None:
            session.send("notice", message=message)

    text = run_worker_agent(
        session.api_key,
        session.config,
        agent,
        session.project_brief,
        session.previous_blocks,
        session.output_dir,
        provider=session.w_provider,
        project_state=session.project.read_state(),
        notify=notify,
    )
    session.refresh_modules()
    path = session.output_dir / agent["output"]
    lines = text.strip().splitlines()
    session.send(
        "module_saved",
        agent=agent,
        path=path,
        preview="\n".join(lines[:PREVIEW_LINES]),
        truncated=len(lines) > PREVIEW_LINES,
    )
    return ModuleRun(agent=agent, text=text, path=path)


def record_action_run(session: Session, agent: dict, *, state_updated: bool) -> None:
    """History note after the Conductor ran an expert."""
    session.note("user", module_completed_note(agent, state_updated=state_updated))


def record_command_run(
    session: Session, agent: dict, user_text: str, *, state_updated: bool
) -> None:
    """History + transcript after the designer ran an expert directly (no Conductor call)."""
    note = module_completed_note(agent, state_updated=state_updated)
    session.history.append({"role": "user", "content": user_text})
    session.history.append({"role": "assistant", "content": note})
    session.project.append_transcript("User", user_text)
    session.project.append_transcript("System", note)
    session.persist()


# ---------------------------------------------------------------------------
# project_state.md updates
# ---------------------------------------------------------------------------


def state_update_mode(session: Session) -> str:
    """ask | auto | off"""
    from sida.state_updater import state_update_settings

    return state_update_settings(session.config)["mode"]


def propose_state(session: Session, agent: dict) -> StateProposal | None:
    """
    Ask the model for a project_state.md patch from the expert's output.
    Returns None when the patch changes nothing. Raises LLMError; the file is untouched.
    """
    from sida.state_updater import propose_state_patch, state_diff

    session.pending_state = None
    patch, proposed = propose_state_patch(
        session.config,
        session.api_key,
        session.project,
        agent,
        c_provider=session.c_provider,
        w_provider=session.w_provider,
        lang=get_language(),
    )
    current = patch.base_state
    diff = state_diff(current, proposed)
    if not diff.strip():
        if module_revisions(current) == module_revisions(proposed):
            return None
        diff = (
            "설계 상태 요약은 같으며, 이 전문가 결과의 상태 반영 기록을 갱신합니다."
            if get_language() == "ko" else
            "The summary is unchanged; record this expert output version as reflected in state."
        )
    proposal = StateProposal(
        agent=agent, proposed=proposed, diff=diff,
        original_state=patch.base_state, original_brief=patch.base_brief,
        module_revision=content_revision(patch.module_output),
    )
    session.pending_state = proposal
    return proposal


def apply_state(session: Session, proposal: StateProposal) -> Path:
    """Write the proposed state (previous version kept as project_state.prev.md)."""
    from sida.state_updater import write_state

    if session.pending_state is not proposal:
        raise DocumentConflict("이미 처리됐거나 현재 세션의 승인안이 아닙니다. 새 갱신안을 만드세요.")
    current_output = session.project.read_module(proposal.agent["output"])
    if (
        session.project.state_path.read_text(encoding="utf-8") != proposal.original_state
        or session.project.read_brief() != proposal.original_brief
        or not current_output
        or content_revision(current_output) != proposal.module_revision
    ):
        raise DocumentConflict("승인안의 입력이 변경됐습니다. 새 갱신안을 만든 뒤 확인하세요.")
    write_state(session.project, proposal.proposed)
    session.pending_state = None
    return session.project.state_path


def discard_state(session: Session, proposal: StateProposal) -> None:
    """Skip a proposal without changing project state or its reflection records."""
    if session.pending_state is not proposal:
        raise DocumentConflict("이미 처리됐거나 현재 세션의 승인안이 아닙니다.")
    session.pending_state = None


def read_editable_document(session: Session, kind: str) -> Document:
    return read_document(session.project, kind)


def edit_document(session: Session, kind: str, content: str, *, expected_revision: str) -> Document:
    """Save a designer edit and refresh the brief used by subsequent model calls."""
    document = save_document(session.project, kind, content, expected_revision=expected_revision)
    if kind == "brief":
        session.reload_brief()
    return document
