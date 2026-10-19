"""Web conversation jobs: Conductor turns and expert runs on background threads.

Independent of HTTP and templates. A model call takes seconds to minutes, so each
request starts a Job and returns at once; the engine's events are kept on the job with
a sequence number, and a screen polls for the ones it has not seen yet.

One job runs per project at a time. Jobs live in memory only: after a server restart
the conversation is still on disk (history.json, modules/) but running jobs are gone.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sida import config as sida_config
from sida import engine, errors, expert_chat, runtime, telemetry, workspace
from sida.editing import EditingService
from sida.i18n import agent_name
from sida.project_documents import DocumentConflict
from sida.providers import LLMError

MAX_FINISHED_JOBS = 50

Runner = Callable[[Callable[[], None]], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="sida-session-job", daemon=True).start()


@dataclass
class Job:
    id: str
    project: Path
    kind: str  # "opening" | "message" | "expert" | "expert_chat"
    agent: str | None = None
    status: str = "running"  # "running" | "done" | "failed"
    running_agent: str | None = None  # the expert being run right now, if any
    error: str | None = None
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    events: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    def add(self, kind: str, data: dict) -> None:
        with self._lock:
            self.events.append({"seq": len(self.events) + 1, "kind": kind, "data": data})

    def finish(self, error: str | None) -> None:
        with self._lock:
            self.error = error
            self.status = "failed" if error else "done"
            self.finished_at = _now()
        self._done.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def view(self, after: int = 0) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "agent": self.agent,
                "status": self.status,
                "running_agent": self.running_agent,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "events": [e for e in self.events if e["seq"] > after],
            }


class SessionJobs:
    """Start and track conversation jobs; expert runs in "ask" mode leave approvals in `editing`."""

    def __init__(self, editing: EditingService, runner: Runner = start_thread):
        self.editing = editing
        self.runner = runner
        self._guard = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._active: dict[Path, Job] = {}

    # ------------------------------------------------------------------ reading

    def snapshot(self, config: dict, name: str) -> dict:
        """Everything a session screen needs on load: chat, running job, experts, approval."""
        path = workspace.find_project(config, name).resolve()
        job = self._active.get(path)
        pending = self.editing.pending(path)
        proposal = None
        if pending is not None:
            proposal = {
                "id": pending.id,
                "agent": pending.proposal.agent["id"],
                "diff": pending.proposal.diff,
            }
        running = job.running_agent if job is not None else None
        return {
            "messages": workspace.chat_messages(config, path),
            "job": job.view() if job is not None else None,
            "experts": [
                {
                    **entry,
                    "status": _expert_status(entry, running, proposal),
                }
                for entry in workspace.expert_entries(config, path)
            ],
            "proposal": proposal,
        }

    def chat(self, config: dict, name: str, agent_id: str) -> dict:
        """One expert's own chat, plus the project's running job (shared with the main chat)."""
        path = workspace.find_project(config, name).resolve()
        agent = _agent(config, agent_id, LookupError)
        job = self._active.get(path)
        return {
            "agent": agent["id"],
            "name": agent_name(agent),
            "chat": expert_chat.chat_enabled(agent),
            "messages": expert_chat.chat_messages(expert_chat.load_chat(path, agent)),
            "job": job.view() if job is not None else None,
        }

    def job(self, config: dict, name: str, job_id: str, after: int = 0) -> dict:
        path = workspace.find_project(config, name).resolve()
        job = self._jobs.get(job_id)
        if job is None or job.project != path:
            raise LookupError(job_id)
        return job.view(after)

    # ------------------------------------------------------------------ starting

    def start_opening(self, config: dict, name: str) -> Job:
        return self._start(config, name, "opening")

    def start_message(self, config: dict, name: str, text: str) -> Job:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        return self._start(config, name, "message", text=text)

    def start_expert(
        self, config: dict, name: str, agent_id: str, revision: str | None = None
    ) -> Job:
        agent = _agent(config, agent_id, ValueError)
        return self._start(config, name, "expert", agent=agent, text=(revision or "").strip())

    def start_expert_chat(self, config: dict, name: str, agent_id: str, text: str) -> Job:
        agent = _agent(config, agent_id, LookupError)
        if not expert_chat.chat_enabled(agent):
            raise ValueError(f"chat is off for this expert: {agent_id}")
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        return self._start(config, name, "expert_chat", agent=agent, text=text)

    def _start(
        self, config: dict, name: str, kind: str, *, text: str = "", agent: dict | None = None
    ) -> Job:
        path = workspace.find_project(config, name).resolve()
        with self._guard:
            if path in self._active:
                raise DocumentConflict("이 프로젝트에서 이미 실행 중인 작업이 있습니다. 끝난 뒤 다시 보내세요.")
            job = Job(uuid.uuid4().hex, path, kind, agent=agent["id"] if agent else None)
            self._active[path] = job
            self._jobs[job.id] = job
            self._prune()
        self.runner(lambda: self._work(job, config, text, agent))
        return job

    def _prune(self) -> None:
        finished = [j for j in self._jobs.values() if j.status != "running"]
        for old in finished[: max(0, len(finished) - MAX_FINISHED_JOBS)]:
            self._jobs.pop(old.id, None)

    # ------------------------------------------------------------------ working

    def _work(self, job: Job, config: dict, text: str, agent: dict | None) -> None:
        error: str | None = None
        observer = telemetry.JobObserver(config, job.kind, job.agent)
        try:
            session = self._open(job, config, observer)
            if job.kind == "opening":
                turn = engine.converse(session, engine.opening_prompt(session), ephemeral=True)
                error = turn.error
            elif job.kind == "message":
                error = engine.converse(session, text).error
            elif job.kind == "expert_chat":
                reply = expert_chat.expert_chat(session, agent, text)
                error = reply.run.error if reply.run is not None else None
            else:
                command = f"/run {agent['id']} {text}".rstrip()
                result = engine.run_expert_command(session, agent, command, revision=text or None)
                error = result.error
        except (LLMError, errors.SidaError) as exc:
            error = getattr(exc, "message", None) or str(exc)
        except Exception as exc:  # a bug must still end the job, or the project stays busy
            error = f"{type(exc).__name__}: {exc}"
        finally:
            with self._guard:
                if self._active.get(job.project) is job:
                    del self._active[job.project]
            job.finish(error)
            observer.finished(error)

    def _open(
        self, job: Job, config: dict, observer: telemetry.JobObserver | None = None
    ) -> engine.Session:
        def boot(cfg: dict) -> None:
            from sida.ollama_boot import ensure_ollama_ready

            # Never wait for a terminal answer: a missing local model becomes the job's error.
            ensure_ollama_ready(
                cfg,
                prompt_fn=lambda _label: "n",
                print_fn=lambda *parts: job.add("notice", {"message": " ".join(map(str, parts))}),
            )

        api_key = runtime.load_env(config=config)
        # A fresh session per job reads brief, modules and history from disk, so edits made
        # through the document API in between are never overwritten by stale memory.
        session = engine.build_session(config, api_key, job.project, before_providers=boot)
        session.capture_notices = True
        session.emit = self._emitter(job, session, observer)
        return session

    def _emitter(
        self, job: Job, session: engine.Session, observer: telemetry.JobObserver | None = None
    ) -> engine.Emit:
        def emit(kind: str, data: dict) -> None:
            if observer is not None:
                observer.event(kind, data)
            out: dict[str, Any] = {}
            for key, value in data.items():
                if key == "agent" and isinstance(value, dict):
                    out[key] = {"id": value.get("id"), "name": agent_name(value)}
                elif key == "proposal" and isinstance(value, engine.StateProposal):
                    pending = self.editing.hold(job.project, session, value)
                    out[key] = {"id": pending.id, "agent": value.agent["id"], "diff": value.diff}
                elif isinstance(value, Path):
                    out[key] = _relative(value, job.project)
                else:
                    out[key] = value
            if kind == "module_started":
                job.running_agent = out["agent"]["id"]
            elif kind in {"module_saved", "module_failed"}:
                job.running_agent = None
            job.add(kind, out)

        return emit


def _agent(config: dict, agent_id: str, missing: type[Exception]) -> dict:
    agent = sida_config.agent_by_id(sida_config.get_agents(config), agent_id)
    if agent is None:
        raise missing(f"unknown expert: {agent_id}")
    return agent


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _expert_status(entry: dict, running: str | None, proposal: dict | None) -> str:
    """idle (never run) | running | review (a state approval waits) | done"""
    if entry["id"] == running:
        return "running"
    if proposal is not None and proposal["agent"] == entry["id"]:
        return "review"
    return "done" if entry["done"] else "idle"
