"""Conductor talks: separate conversations with the Conductor in one project.

The command line at the bottom of the web screen starts a new talk for each question, and the
talk's popup keeps the follow-up questions. Every talk reads the same project (brief, project
state, expert results, drawing table); only the conversation history is its own.

Talk "01" is the project's first conversation, stored in history.json as before. Other talks
are numbered "02", "03", ... and stored in talks/<id>.json, in the same format.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sida.engine import history_messages
from sida.errors import SidaError
from sida.project import MAIN_TALK, TALKS_DIRNAME, talk_history_path
from sida.storage import atomic_write_text

TALK_ID = re.compile(r"\d{2,4}")
TITLE_CHARS = 60
DELETED_DIR = ".deleted"


def _deleted_ids(project_path: Path) -> set[str]:
    return {p.stem for p in (project_path / TALKS_DIRNAME / DELETED_DIR).glob("*.json")
            if TALK_ID.fullmatch(p.stem)}


def talk_ids(project_path: Path) -> list[str]:
    """Active talks, oldest first. "01" exists by default unless explicitly deleted."""
    folder = project_path / TALKS_DIRNAME
    ids = {MAIN_TALK}
    if folder.is_dir():
        ids |= {p.stem for p in folder.glob("*.json") if TALK_ID.fullmatch(p.stem)}
    return sorted(ids - _deleted_ids(project_path), key=int)


def require_talk(project_path: Path, talk_id: str) -> None:
    """LookupError unless `talk_id` is one of the project's talks."""
    if not TALK_ID.fullmatch(talk_id or "") or talk_id not in talk_ids(project_path):
        raise LookupError(f"talk {talk_id}")


def new_talk(project_path: Path) -> str:
    """Start an empty talk and return its id."""
    used = {MAIN_TALK, *talk_ids(project_path), *_deleted_ids(project_path)}
    next_id = max(map(int, used)) + 1
    if next_id > 9999:
        raise ValueError("새 대화를 만들 수 있는 개수를 초과했습니다.")
    talk_id = f"{next_id:02d}"
    path = talk_history_path(project_path, talk_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, "[]\n")
    return talk_id


def delete_talk(project_path: Path, talk_id: str) -> None:
    """Delete only this transcript. Empty tombstones stop ids and the first talk reappearing."""
    require_talk(project_path, talk_id)
    marker = project_path / TALKS_DIRNAME / DELETED_DIR / f"{talk_id}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(marker, "[]\n")  # Contains no conversation text.
    try:
        talk_history_path(project_path, talk_id).unlink(missing_ok=True)
    except OSError as exc:
        marker.unlink(missing_ok=True)  # Keep the original conversation visible on failure.
        raise SidaError(f"대화를 삭제하지 못했습니다. 다시 시도하세요: {exc}") from exc


def _history(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict) and isinstance(m.get("content"), str)]


def _modified_at(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")


def talk_summaries(project_path: Path) -> list[dict]:
    """One line per talk for a list: {id, title, messages, updated_at}.

    `title` is the first question of the talk (empty while nothing was asked); `messages`
    counts what a chat screen shows (questions, answers and expert notes)."""
    out = []
    for talk_id in talk_ids(project_path):
        path = talk_history_path(project_path, talk_id)
        shown = history_messages(_history(path))
        first = next((m["text"] for m in shown if m["role"] == "user"), "")
        out.append({
            "id": talk_id,
            "title": " ".join(first.split())[:TITLE_CHARS],
            "messages": len(shown),
            "updated_at": _modified_at(path),
        })
    return out
