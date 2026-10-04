"""Project editing and pending approval service; independent of HTTP and templates."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from sida import engine, harness, workspace
from sida.project_documents import Document, DocumentConflict, read_document, save_document


@dataclass
class PendingApproval:
    id: str
    session: engine.Session
    proposal: engine.StateProposal


class EditingService:
    """Keep one server-owned approval per project and serialize writes within this service."""

    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[Path, threading.RLock] = {}
        self._pending: dict[Path, PendingApproval] = {}

    def _path_and_lock(self, config: dict, name: str):
        path = workspace.find_project(config, name).resolve()
        with self._guard:
            lock = self._locks.setdefault(path, threading.RLock())
        return path, lock

    def read_document(self, config: dict, name: str, kind: str) -> Document:
        path, lock = self._path_and_lock(config, name)
        with lock:
            return read_document(path, kind)

    def save_document(
        self, config: dict, name: str, kind: str, content: str, *, expected_revision: str
    ) -> Document:
        path, lock = self._path_and_lock(config, name)
        with lock:
            return save_document(path, kind, content, expected_revision=expected_revision)

    def propose_state(self, config: dict, name: str, agent_id: str) -> PendingApproval | None:
        path, lock = self._path_and_lock(config, name)
        with lock:
            agent = harness.agent_by_id(harness.get_agents(config), agent_id)
            if agent is None:
                raise ValueError(f"unknown expert: {agent_id}")
            output = path / "modules" / agent["output"]
            if not output.is_file() or not output.read_text(encoding="utf-8").strip():
                raise ValueError(f"module output missing: {agent_id}")
            # A replacement request invalidates the earlier proposal even if the new call fails.
            self._pending.pop(path, None)
            api_key = harness.load_env(interactive=False, config=config)
            session = engine.build_session(config, api_key, path)
            session.capture_notices = True
            proposal = engine.propose_state(session, agent)
            if proposal is None:
                return None
            pending = PendingApproval(uuid.uuid4().hex, session, proposal)
            self._pending[path] = pending
            return pending

    def _approval(self, path: Path, proposal_id: str) -> PendingApproval:
        pending = self._pending.get(path)
        if pending is None or pending.id != proposal_id:
            raise DocumentConflict("이미 처리됐거나 유효하지 않은 승인안입니다. 새 갱신안을 만드세요.")
        return pending

    def apply_state(self, config: dict, name: str, proposal_id: str) -> Document:
        path, lock = self._path_and_lock(config, name)
        with lock:
            pending = self._approval(path, proposal_id)
            engine.apply_state(pending.session, pending.proposal)
            self._pending.pop(path, None)
            return read_document(path, "state")

    def discard_state(self, config: dict, name: str, proposal_id: str) -> None:
        path, lock = self._path_and_lock(config, name)
        with lock:
            pending = self._approval(path, proposal_id)
            engine.discard_state(pending.session, pending.proposal)
            self._pending.pop(path, None)
