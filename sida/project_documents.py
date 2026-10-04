"""Core document editing for CLI and web front ends, with optimistic conflict checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sida.errors import SidaError
from sida.project import Project
from sida.state_revisions import preserve_revisions, without_revisions
from sida.storage import atomic_write_text


class DocumentConflict(SidaError):
    """The document or proposal source changed; reload before saving or approving."""


@dataclass(frozen=True)
class Document:
    kind: str
    content: str
    revision: str


def _document_path(project: Project | Path, kind: str) -> Path:
    root = project.path if isinstance(project, Project) else Path(project)
    if kind == "brief":
        return root / "brief.md"
    if kind == "state":
        return root / "project_state.md"
    raise ValueError("editable document must be brief or state")


def _revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_document(project: Project | Path, kind: str) -> Document:
    raw = _document_path(project, kind).read_text(encoding="utf-8")
    content = without_revisions(raw) if kind == "state" else raw
    return Document(kind=kind, content=content, revision=_revision(raw))


def save_document(project: Project | Path, kind: str, content: str, *, expected_revision: str) -> Document:
    """Preserve arbitrary Markdown; reject stale edits before writing any backup.

The revision check covers changes since the document was read. It is not an OS
lock against a separate editor writing concurrently during this save.
"""
    path = _document_path(project, kind)
    current = path.read_text(encoding="utf-8")
    if _revision(current) != expected_revision:
        raise DocumentConflict("문서가 변경됐습니다. 최신 내용을 불러온 뒤 다시 저장하세요.")
    edited = content.replace("\r\n", "\n").replace("\r", "\n")
    if kind == "state":
        edited = preserve_revisions(edited, current)
    if edited == current:
        return read_document(project, kind)
    backup = path.with_name(path.stem + ".prev" + path.suffix)
    atomic_write_text(backup, current)
    atomic_write_text(path, edited)
    return read_document(project, kind)
