"""Pictures the designer shows the Conductor with a message (2026-11-17 지훈: the Rhino view as it
is now goes to the model with the question).

A domain makes the picture (hook `conductor_views`, sida/experts/__init__.py). This module keeps
it in the project (talk_views/<stamp>.png, and a .json beside it that says what it shows and
what the domain's figures were at that moment), writes its file name into the message as the
talk's history stores it, and gives the newest one back for the talk's later messages. A
picture is for form and composition only: every figure still goes to the model as text
(sida/conductor.py VIEW_RULE). Experts are sent no pictures.

Nothing here knows which domain made a picture, and nothing is sent anywhere but to the
Conductor's model with the designer's own message.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from sida.storage import atomic_write_text

DIR = "talk_views"
PREFIX = "[pictures shown] "
MAX_VIEWS = 2  # pictures that go with one message
MAX_BYTES = 4 * 1024 * 1024
MAX_TEXT = 4000  # the figures kept beside a picture
# What a picture may be, told by how its bytes begin (a domain's word for it is not trusted).
KINDS = (("image/png", ".png", b"\x89PNG\r\n\x1a\n"), ("image/jpeg", ".jpg", b"\xff\xd8\xff"))
FILE = re.compile(r"\d{8}-\d{6}-\d{6}-\d\.(?:png|jpg)")


def media_type(data) -> str | None:
    """image/png or image/jpeg when the bytes are a picture of a size that may be sent, else None."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        return None
    return next((media for media, _ext, magic in KINDS if data.startswith(magic)), None)


def ask(project_path: Path, hooks=None) -> list[dict]:
    """The pictures the domains have for the message being sent now (hook `conductor_views`):
    [{"data", "media_type", "about", "facts"}], at most MAX_VIEWS. Never raises: a picture must
    not stop a message."""
    from sida.experts import domain_hooks

    out: list[dict] = []
    for _domain, module in domain_hooks() if hooks is None else hooks:
        give = getattr(module, "conductor_views", None)
        if give is None:
            continue
        try:
            given = give(Path(project_path)) or []
        except Exception:
            continue
        for view in given:
            media = media_type(view.get("data")) if isinstance(view, dict) else None
            if media:
                out.append({"data": view["data"], "media_type": media,
                            "about": " ".join(str(view.get("about") or "").split())[:300],
                            "facts": str(view.get("facts") or "").strip()[:MAX_TEXT]})
    return out[:MAX_VIEWS]


def keep(project_path: Path, asked: list[dict]) -> list[dict]:
    """Write the pictures into the project; the same list with each one's "file"."""
    if not asked:
        return []
    folder = Path(project_path) / DIR
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    kept = []
    for i, view in enumerate(asked[:MAX_VIEWS]):
        ext = next(ext for media, ext, _magic in KINDS if media == view["media_type"])
        file = f"{now:%Y%m%d-%H%M%S-%f}-{i}{ext}"
        (folder / file).write_bytes(view["data"])
        record = {"about": view.get("about", ""), "facts": view.get("facts", ""), "at": now.isoformat(timespec="seconds")}
        atomic_write_text((folder / file).with_suffix(".json"), json.dumps(record, ensure_ascii=False, indent=1) + "\n")
        kept.append({**view, "file": file})
    return kept


def mark(text: str, files: list[str]) -> str:
    """The message as stored in history when pictures went with it: the words, then the pictures' files."""
    return f"{text}\n\n{PREFIX}{' | '.join(files)}" if files else text


def split(content: str) -> tuple[str, list[str]]:
    """Undo mark: (the message without the pictures' line, the files)."""
    head, sep, tail = str(content).rpartition("\n\n" + PREFIX)
    files = tail.split(" | ") if sep else []
    if not files or not all(FILE.fullmatch(file) for file in files):
        return content, []
    return head, files


def path_of(project_path: Path, file: str) -> Path:
    """Where a kept picture is. Raises LookupError for a name that is not one, or a picture that is gone."""
    path = Path(project_path) / DIR / file
    if not FILE.fullmatch(file) or not path.is_file():
        raise LookupError(file)
    return path


def record(project_path: Path, file: str) -> dict:
    """What was kept beside a picture: {"file", "about", "facts", "at"} (empty text when it is gone)."""
    out = {"file": file, "about": "", "facts": "", "at": ""}
    try:
        data = json.loads(path_of(project_path, file).with_suffix(".json").read_text(encoding="utf-8"))
    except (LookupError, OSError, ValueError):
        return out
    if isinstance(data, dict):
        out.update({key: str(data.get(key) or "") for key in ("about", "facts", "at")})
    return out


def latest(project_path: Path, history: list[dict]) -> list[dict]:
    """The pictures of the newest message that had some, read back: [{"data", "media_type",
    "about", "file"}]. Only these go to the model again with the talk's later messages; [] when
    the talk has none or the files are gone."""
    for item in reversed(history):
        if item.get("role") != "user":
            continue
        files = split(str(item.get("content") or ""))[1]
        if not files:
            continue
        out = []
        for file in files:
            try:
                data = path_of(project_path, file).read_bytes()
            except (LookupError, OSError):
                continue
            media = media_type(data)
            if media:
                out.append({"data": data, "media_type": media, "about": record(project_path, file)["about"], "file": file})
        return out
    return []


def forget(project_path: Path, files: list[str]) -> None:
    """Remove kept pictures (the model refused them, or their talk was deleted)."""
    for file in files:
        if not FILE.fullmatch(file):
            continue
        for path in (Path(project_path) / DIR / file, (Path(project_path) / DIR / file).with_suffix(".json")):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def files_in(history: list[dict]) -> list[str]:
    """Every picture a talk's messages name."""
    return [file for item in history if item.get("role") == "user" for file in split(str(item.get("content") or ""))[1]]
