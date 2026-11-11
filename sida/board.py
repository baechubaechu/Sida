"""The drafting table (제도판): sheets of paper laid around the site, saved in the project.

Independent of HTTP and of the screen. The table is stored as board.json in the project
folder: {"rev", "papers", "tray", "pins", "ideas", "hidden", "people", "layers"}. The designer adds, moves and edits papers one
at a time (the screen and the AI write to the same file, so nobody saves it whole).

`layers` (2026-11-09 지훈, as in Rhino) are the designer's layers, in order: {id, name, parent ('' at
the top, else a layer's id), visible, locked, color ('' or '#rrggbb')}. A paper names its layer in
`layer`, and a block of a mass may name its own (otherwise it is on its scheme's layer); a paper
without one is on the layer of its kind (a table without layers starts with one for each kind,
DEFAULT_LAYERS). Hiding and locking are for the screen: the AI still reads every paper, and the
export writes each layer by its name. Taking a layer away moves what was on it (and its sublayers)
up to the nearest layer still there.

A group (2026-11-09 지훈: "아무 개체끼리 묶을 수 있게") is any papers and blocks that share a
`group` id: picking one on the screen picks them all. Only the screen uses it.

`hidden` (2026-11-07) lists the buildings of the VWorld 3D map the designer hid around the site
(their model ids, so the site's own old building can be taken away from under a scheme). Only the
screen reads it; it is not geometry and does not go to the AI or into the export.

`people` (2026-11-10 지훈: "사람 배치해보는 기능") are the scale figures the designer stands about
the site in 3D, to feel how large a scheme is: {id, x, y, turn, kind, roof}. x and y are metres in
the plan's own coordinates (the site plan's, the same as the surroundings), `turn` is the way the
person faces in degrees clockwise from north, `kind` is PERSON_KINDS, and `roof` (kept only when
true) stands them on the roof of the scheme's building under them instead of the ground. Like
`hidden` they are for the screen only: not sent to the AI, not in the export (yet).

The idea board (`ideas`, 2026-11-05) is the designer's ordered list of main ideas, kept beside
the table. Only the designer writes it; every Conductor call and expert run reads the ideas
that are not set aside (`ideas_block`), and nothing the AI does changes them. A paper dragged off
the table into the idea board (2026-11-07 지훈: "카드를 그 동그라미로 아이디어 보드에 넣는다") is held
inside its idea (`paper`) and is no longer on the table; `place_idea` lays it back (an idea
without a paper goes back as a note).

What the AI makes never lands on the table itself (2026-10-26 지훈 결정). It goes to the AI
section, `tray`: massing schemes and notes the Conductor proposes (a change to the designer's
scheme comes as a copy, `based_on` the original) and expert results. The designer moves the
ones they like onto the table (`place_paper`) and throws the rest away.

A photo (kind "photo") is uploaded as a file with `add_photo` and kept in board_photos/; the
paper names the file. A PDF is a photo paper too, showing one `page` of it. Taking the paper off the table leaves the file for a day, so an undo can
lay it back (`add_paper` with that file); `add_photo` clears files nobody has used since.

Papers the designer selects travel with a message as `context` (paper ids). How much of
them the Conductor is sent depends on what it runs on (conductor.board_context):

  full   a cloud Conductor (OpenRouter, ChatGPT): the selected papers in full, an index of
         every paper on the table, and the read_board tool
  names  a local Conductor (Ollama): one line per selected paper; the detail goes only to
         the experts it runs

Experts always get the selected papers in full. Only the paper names are kept in the
conversation history, so a selection is not sent again on later turns.

Figures for a massing scheme (footprint, floor area, coverage, FAR) are computed here from
the paper's blocks and the site area the site domain reports (hook `board_site`); nothing
the screen computed is trusted, and with no known site area no ratio is given.

The screen reads the table through `view`: the saved papers plus the site drawn in metres
around its middle (`site_plan`) and each scheme's figures. Blocks stand in the site's own
frame: `u` along the long side of its largest parcel, `v` across it, from that parcel's middle.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from sida.errors import SidaError
from sida.i18n import agent_name, t
from sida.storage import atomic_write_text

BOARD_FILE = "board.json"
SITE_ID = "site"
KINDS = ("site", "mass", "note", "tracing", "expert", "photo")
DESIGNER_KINDS = ("mass", "note", "tracing")  # what the screen may add
AI_KINDS = ("mass", "note")  # what the Conductor may put in the AI section
MAX_TRAY = 40  # the AI section keeps the newest papers
PREVIEW_LINES = 12
MAX_PAPERS = 300
MAX_CONTEXT = 8  # papers one message may carry
MAX_TEXT = 4000
MAX_TITLE = 120
MAX_BLOCKS = 20
MAX_STROKES = 500
MAX_POINTS = 5000
DEFAULT_FLOOR_HEIGHT = 4.2
PLACEMENT = ("x", "y", "w", "h")
# What a site or expert paper may change: where it lies, folded or not, its layer and group.
ARRANGE = (*PLACEMENT, "folded", "layer", "group")
PAPER_SIZE = {
    "site": (300, 250), "mass": (300, 210), "note": (200, 140), "tracing": (300, 250), "expert": (320, 270),
    "photo": (300, 225),
}
PAPER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
CONTEXT_MODES = ("auto", "full", "names")
LOCAL_PROVIDERS = frozenset({"ollama", "local"})
SELECTED_PREFIX = "[selected on the table] "
# Photos the designer puts on the table (a site photo, a sketch, a reference image) are kept
# as files next to board.json; the paper holds only the file name.
PHOTO_DIR = "board_photos"
MAX_PHOTO_BYTES = 20 * 1024 * 1024
PHOTO_FILE = re.compile(r"photo-[0-9a-f]{8}\.(?:png|jpg|gif|webp|pdf)")
PHOTO_MEDIA = {
    "png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
}
# A PDF (a drawing exported from CAD) lies on the table as one of its pages, which the screen
# draws from the PDF itself at the size it is shown, so its lines stay sharp however large.
MAX_PDF_PAGE = 9999
ORPHAN_SECONDS = 24 * 3600  # a removed photo's file is kept this long, so the screen can undo
# The idea board: the designer's main ideas, in their order.
MAX_IDEAS = 40
MAX_HIDDEN = 300  # hidden VWorld 3D buildings kept per project
MAX_HIDDEN_ID = 80
# Scale figures (`people`): what each kind is, and how many one table keeps.
PERSON_KINDS = ("stand", "walk", "child")
MAX_PEOPLE = 400
MAX_COORD = 100000.0  # metres from the middle of the site plan
MAX_IDEA_TEXT = 600
MAX_IDEA_PAPERS = 8
TALK_ID = re.compile(r"\d{2,4}")  # the Conductor talk ids of sida/talks.py
MAX_LAYERS = 200
MAX_LAYER_NAME = 60
LAYER_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
# The layers a table starts with: one for each kind of paper (their ids are the kinds).
DEFAULT_LAYERS = (
    ("site", "대지"), ("mass", "매스"), ("tracing", "트레이싱지"), ("note", "메모"), ("photo", "사진"), ("expert", "전문가 결과"),
)


def default_layers() -> list[dict]:
    return [{"id": i, "name": n, "parent": "", "visible": True, "locked": False, "color": ""} for i, n in DEFAULT_LAYERS]

_lock = threading.Lock()


class PaperNotFound(LookupError):
    """No paper with this id on the table."""


class IdeaNotFound(LookupError):
    """No idea with this id on the idea board."""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def board_path(project_path: Path) -> Path:
    return Path(project_path) / BOARD_FILE


def _site_paper() -> dict:
    return {"id": SITE_ID, "kind": "site", "x": 0.0, "y": 0.0, "w": 300.0, "h": 250.0}


def _empty() -> dict:
    return {"rev": 0, "papers": [_site_paper()], "tray": [], "pins": [], "ideas": [], "hidden": [], "people": [], "layers": default_layers()}


log = logging.getLogger(__name__)


def read_board(project_path: Path) -> dict | None:
    """
    The saved table for a prompt (the Conductor's and the experts' reading of it): None when
    there is none, and None with a warning in the log when it cannot be read, so a damaged
    board.json never stops a conversation or an expert run. Edits keep using load_board,
    which refuses to replace a board it cannot read.
    """
    if not board_path(project_path).exists():
        return None
    try:
        return load_board(project_path)
    except SidaError as exc:
        log.warning("%s (read without the drawing table)", exc.message)
        return None


def load_board(project_path: Path) -> dict:
    """Start an empty table only when there is no saved board."""
    path = board_path(project_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SidaError(t("board_read_failed", path=path)) from exc
    if not isinstance(data, dict) or not isinstance(data.get("papers"), list):
        raise SidaError(t("board_read_failed", path=path))
    papers = [p for p in data["papers"] if isinstance(p, dict) and p.get("kind") in KINDS]
    if not any(p.get("id") == SITE_ID for p in papers):
        papers.insert(0, _site_paper())
    tray = data.get("tray") if isinstance(data.get("tray"), list) else []
    tray = [p for p in tray if isinstance(p, dict) and p.get("kind") in KINDS]
    pins = data.get("pins") if isinstance(data.get("pins"), list) else []
    ideas = data.get("ideas") if isinstance(data.get("ideas"), list) else []
    ideas = [i for i in ideas if isinstance(i, dict) and i.get("id") and isinstance(i.get("text"), str)]
    for idea in ideas:
        if "paper" in idea and not (isinstance(idea["paper"], dict) and idea["paper"].get("kind") in KINDS):
            del idea["paper"]
    ideas = [i for i in ideas if i["text"].strip() or "paper" in i]
    there = {p.get("id") for p in papers + tray + [i["paper"] for i in ideas if "paper" in i]}
    for idea in ideas:  # a linked paper taken off the table (or dropped from the AI section) goes
        idea["papers"] = [i for i in idea.get("papers") or [] if i in there]
    hidden = data.get("hidden") if isinstance(data.get("hidden"), list) else []
    hidden = [h for h in hidden if isinstance(h, str) and h]
    people = []
    for raw in data.get("people") if isinstance(data.get("people"), list) else []:
        try:  # a hand-edited person that no longer reads is left out, not the whole table
            person = clean_person(raw, len(people))
        except ValueError:
            continue
        if all(p["id"] != person["id"] for p in people):
            people.append(person)
    try:
        layers = clean_layers(data["layers"]) if isinstance(data.get("layers"), list) and data["layers"] else default_layers()
    except ValueError:
        layers = default_layers()
    return {"rev": int(data.get("rev") or 0), "papers": papers, "tray": tray, "pins": pins, "ideas": ideas,
            "hidden": hidden, "people": people[:MAX_PEOPLE], "layers": layers}


def _save(project_path: Path, board: dict) -> dict:
    board["rev"] += 1
    atomic_write_text(board_path(project_path), json.dumps(board, ensure_ascii=False, indent=2) + "\n")
    return board


def _find(board: dict, paper_id: str, where: str = "papers") -> dict:
    for paper in board[where]:
        if paper.get("id") == paper_id:
            return paper
    raise PaperNotFound(paper_id)


def held_papers(board: dict) -> list[dict]:
    """The papers held in the idea board (off the table, inside their ideas)."""
    return [i["paper"] for i in board.get("ideas") or [] if isinstance(i.get("paper"), dict)]


def _taken(board: dict, paper_id: str) -> bool:
    return any(p.get("id") == paper_id for p in board["papers"] + board["tray"] + held_papers(board))


def add_paper(project_path: Path, data: dict) -> dict:
    """Lay a new mass, note or tracing sheet on the table. Returns {paper, rev}."""
    kind = str(data.get("kind") or "")
    if kind not in DESIGNER_KINDS and kind != "photo":
        raise ValueError(f"kind must be one of {', '.join(DESIGNER_KINDS)}")
    with _lock:
        board = load_board(project_path)
        if kind == "photo":  # an undo laying a removed photo back; new photos come by add_photo
            file = str(data.get("file") or "")
            if not PHOTO_FILE.fullmatch(file) or not (photo_dir(project_path) / file).is_file():
                raise ValueError("a photo is added by uploading it (POST .../board/photos)")
            if any(p.get("file") == file for p in board["papers"]):
                raise ValueError(f"this photo is already on the table: {file}")
        if len(board["papers"]) >= MAX_PAPERS:
            raise ValueError(f"the table holds at most {MAX_PAPERS} papers")
        paper_id = str(data.get("id") or f"{kind}-{uuid.uuid4().hex[:8]}")
        if not PAPER_ID.fullmatch(paper_id):
            raise ValueError("paper id: letters, digits, '-' and '_' only (at most 64)")
        if _taken(board, paper_id):
            raise ValueError(f"a paper with this id already exists: {paper_id}")
        paper = clean_paper({**data, "id": paper_id, "kind": kind})
        board["papers"].append(paper)
        board = _save(project_path, board)
    return {"paper": paper, "rev": board["rev"]}


def update_paper(project_path: Path, paper_id: str, changes: dict) -> dict:
    """Move or edit one paper (id, kind and a photo's file stay). The site paper only moves. Returns {paper, rev}."""
    changes = {k: v for k, v in changes.items() if k not in {"id", "kind", "file"}}
    with _lock:
        board = load_board(project_path)
        current = _find(board, paper_id)
        if current["kind"] in {"site", "expert"}:
            extra = sorted(set(changes) - set(ARRANGE))
            if extra:
                raise ValueError(f"this paper only moves; cannot change: {', '.join(extra)}")
        paper = {**clean_paper({**current, **changes}), **_ai_fields(current)}
        board["papers"][board["papers"].index(current)] = paper
        board = _save(project_path, board)
    return {"paper": paper, "rev": board["rev"]}


def delete_paper(project_path: Path, paper_id: str) -> dict:
    """Take a paper off the table (never the site). Returns {rev}."""
    with _lock:
        board = load_board(project_path)
        paper = _find(board, paper_id)
        if paper["kind"] == "site":
            raise ValueError("the site paper cannot be removed")
        board["papers"].remove(paper)
        board["pins"] = [p for p in board["pins"] if p.get("paper") != paper_id]
        board = _save(project_path, board)
        file = str(paper.get("file") or "")
        if paper["kind"] == "photo" and PHOTO_FILE.fullmatch(file) and (photo_dir(project_path) / file).is_file():
            (photo_dir(project_path) / file).touch()  # kept for an undo; add_photo clears it a day later
    return {"rev": board["rev"]}


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------


def photo_dir(project_path: Path) -> Path:
    return Path(project_path) / PHOTO_DIR


def photo_kind(data: bytes) -> str | None:
    """The file extension for an image the browser can show, read from its first bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"%PDF-"):
        return "pdf"
    return None


def add_photo(project_path: Path, data: bytes, fields: dict | None = None) -> dict:
    """
    Lay an uploaded photo on the table. `fields` may give title, x, y, w, h (the screen sizes
    the paper to the picture). Only PNG, JPEG, GIF, WebP and PDF, at most MAX_PHOTO_BYTES.
    Returns {paper, rev}. Raises ValueError.
    """
    if not data:
        raise ValueError("the photo is empty")
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError(f"a photo may be at most {MAX_PHOTO_BYTES // (1024 * 1024)} MB")
    ext = photo_kind(data)
    if ext is None:
        raise ValueError("a photo must be a PNG, JPEG, GIF or WebP image, or a PDF")
    fields = {k: v for k, v in (fields or {}).items() if k in {"title", "page", *PLACEMENT} and v is not None}
    with _lock:
        board = load_board(project_path)
        if len(board["papers"]) >= MAX_PAPERS:
            raise ValueError(f"the table holds at most {MAX_PAPERS} papers")
        paper_id = f"photo-{uuid.uuid4().hex[:8]}"
        while _taken(board, paper_id):
            paper_id = f"photo-{uuid.uuid4().hex[:8]}"
        file = f"{paper_id}.{ext}"
        paper = clean_paper({**fields, "id": paper_id, "kind": "photo", "file": file})
        folder = photo_dir(project_path)
        _prune_photos(folder, board)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / file).write_bytes(data)
        board["papers"].append(paper)
        try:
            board = _save(project_path, board)
        except OSError:
            (folder / file).unlink(missing_ok=True)
            raise
    return {"paper": paper, "rev": board["rev"]}


def _prune_photos(folder: Path, board: dict) -> None:
    """Remove photo files no paper has used for ORPHAN_SECONDS."""
    if not folder.is_dir():
        return
    import time

    used = {p.get("file") for p in board["papers"] + held_papers(board)}
    old = time.time() - ORPHAN_SECONDS
    for path in folder.iterdir():
        if PHOTO_FILE.fullmatch(path.name) and path.name not in used:
            try:
                if path.stat().st_mtime < old:
                    path.unlink()
            except OSError:
                continue


def photo_file(project_path: Path, paper_id: str) -> tuple[Path, str]:
    """The file of a photo on the table (or held in the idea board) and its media type. Raises PaperNotFound."""
    board = load_board(project_path)
    paper = next((p for p in held_papers(board) if p.get("id") == paper_id), None) or _find(board, paper_id)
    file = str(paper.get("file") or "")
    path = photo_dir(project_path) / file
    if paper.get("kind") != "photo" or not PHOTO_FILE.fullmatch(file) or not path.is_file():
        raise PaperNotFound(paper_id)
    return path, PHOTO_MEDIA[file.rsplit(".", 1)[1]]


# ---------------------------------------------------------------------------
# The AI section
# ---------------------------------------------------------------------------

AI_FIELDS = ("origin", "based_on", "reason", "created_at")


def _ai_fields(paper: dict) -> dict:
    """What marks a paper as made by the AI; kept when it moves to the table and is edited."""
    return {k: paper[k] for k in AI_FIELDS if k in paper}


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_tray(board: dict, paper: dict) -> None:
    board["tray"].append(paper)
    del board["tray"][: max(0, len(board["tray"]) - MAX_TRAY)]


def propose_paper(project_path: Path, data: dict, *, by: str = "conductor") -> dict:
    """
    The Conductor puts a massing scheme or a note in the AI section. `based_on` names the
    designer's scheme it changes; that scheme is left as it is. Returns the paper. Raises ValueError.
    """
    kind = str(data.get("kind") or "")
    if kind not in AI_KINDS:
        raise ValueError(f"kind must be one of {', '.join(AI_KINDS)}")
    with _lock:
        board = load_board(project_path)
        based_on = str(data.get("based_on") or "").strip()
        title = data.get("title")
        if based_on:
            original = _find_any(board, based_on)
            if original["kind"] != kind:
                raise ValueError(f"based_on must be a {kind} paper: {based_on}")
            title = title or f"{paper_name(original)} 수정안"
        paper_id = f"ai-{kind}-{uuid.uuid4().hex[:8]}"
        paper = clean_paper({**data, "title": title, "id": paper_id, "kind": kind})
        paper["origin"] = by
        if based_on:
            paper["based_on"] = based_on
        reason = _text(data.get("reason"), "reason", MAX_TITLE * 2).strip()
        if reason:
            paper["reason"] = reason
        paper["created_at"] = _now()
        _to_tray(board, paper)
        _save(project_path, board)
    return paper


def _find_any(board: dict, paper_id: str) -> dict:
    try:
        return _find(board, paper_id)
    except PaperNotFound:
        try:
            return _find(board, paper_id, "tray")
        except PaperNotFound:
            raise ValueError(f"unknown paper: {paper_id}") from None


def expert_result(project_path: Path, agent: dict, text: str, about: list[str]) -> dict | None:
    """
    An expert's result as a paper in the AI section (only for a project that uses the table).
    The expert's earlier result still waiting there is replaced. Returns the paper or None.
    """
    if not board_path(project_path).exists():
        return None
    lines = [line for line in text.strip().splitlines() if line.strip()]
    with _lock:
        board = load_board(project_path)
        board["tray"] = [
            p for p in board["tray"] if not (p["kind"] == "expert" and p.get("agent") == agent["id"])
        ]
        paper = {
            "id": f"ai-expert-{uuid.uuid4().hex[:8]}",
            "kind": "expert",
            "x": 0.0, "y": 0.0, "w": 320.0, "h": 270.0,
            "agent": str(agent["id"]),
            "title": agent_name(agent),
            "text": "\n".join(lines[:PREVIEW_LINES]),
            "about": [i for i in about if _taken(board, i)],
            "origin": str(agent["id"]),
            "created_at": _now(),
        }
        _to_tray(board, paper)
        _save(project_path, board)
    return paper


def place_paper(project_path: Path, paper_id: str, placement: dict | None = None) -> dict:
    """Move a paper from the AI section onto the table, where it is the designer's. Returns {paper, rev}."""
    placement = {k: v for k, v in (placement or {}).items() if k in PLACEMENT}
    with _lock:
        board = load_board(project_path)
        paper = _find(board, paper_id, "tray")
        board["tray"].remove(paper)
        for key, value in placement.items():
            paper[key] = _number(value, key)
        board["papers"].append(paper)
        board = _save(project_path, board)
    return {"paper": paper, "rev": board["rev"]}


def discard_paper(project_path: Path, paper_id: str) -> dict:
    """Throw a paper in the AI section away. Returns {rev}."""
    with _lock:
        board = load_board(project_path)
        board["tray"].remove(_find(board, paper_id, "tray"))
        board = _save(project_path, board)
    return {"rev": board["rev"]}


# ---------------------------------------------------------------------------
# The idea board: the designer's main ideas (the AI reads them, never writes them)
# ---------------------------------------------------------------------------


def _find_idea(board: dict, idea_id: str) -> dict:
    for idea in board["ideas"]:
        if idea.get("id") == idea_id:
            return idea
    raise IdeaNotFound(idea_id)


def clean_idea(data: dict, board: dict) -> dict:
    """
    An idea as saved: {id, text, papers, talk, off, created_at} and `paper` when it holds a paper
    taken off the table (its text may then be empty). Raises ValueError.
    """
    text = _text(data.get("text"), "text", MAX_IDEA_TEXT).strip()
    held = data.get("paper")
    if not text and not isinstance(held, dict):
        raise ValueError("an idea needs text")
    papers = data.get("papers") or []
    if not isinstance(papers, list) or not all(isinstance(i, str) for i in papers):
        raise ValueError("papers must be a list of paper ids")
    papers = list(dict.fromkeys(papers))
    if len(papers) > MAX_IDEA_PAPERS:
        raise ValueError(f"an idea links at most {MAX_IDEA_PAPERS} papers")
    for paper_id in papers:
        if not _taken(board, paper_id):
            raise ValueError(f"unknown paper on the table: {paper_id}")
    talk = data.get("talk")
    if talk in (None, ""):
        talk = None
    elif not isinstance(talk, str) or not TALK_ID.fullmatch(talk):
        raise ValueError("talk must be a Conductor talk id such as 01")
    off = data.get("off", False)
    if not isinstance(off, bool):
        raise ValueError("off must be true or false")
    idea = {"id": data["id"], "text": text, "papers": papers, "talk": talk, "off": off}
    if isinstance(held, dict):
        idea["paper"] = held
    if data.get("created_at"):
        idea["created_at"] = str(data["created_at"])
    return idea


def add_idea(project_path: Path, data: dict) -> dict:
    """
    Put an idea on the idea board, at the end or at `at` (0 = first). `papers` and `talk`
    link it to papers and a Conductor talk. Returns {idea, rev}. Raises ValueError.
    """
    data = {k: v for k, v in data.items() if k != "paper"}  # a paper comes in by stow_paper
    with _lock:
        board = load_board(project_path)
        if len(board["ideas"]) >= MAX_IDEAS:
            raise ValueError(f"the idea board holds at most {MAX_IDEAS} ideas")
        idea = clean_idea({**data, "id": f"idea-{uuid.uuid4().hex[:8]}", "created_at": _now()}, board)
        at = data.get("at")
        if at is None:
            at = len(board["ideas"])
        if isinstance(at, bool) or not isinstance(at, int):
            raise ValueError("at must be a whole number")
        board["ideas"].insert(max(0, min(at, len(board["ideas"]))), idea)
        board = _save(project_path, board)
    return {"idea": idea, "rev": board["rev"]}


def update_idea(project_path: Path, idea_id: str, changes: dict) -> dict:
    """Rewrite an idea, change its links or set it aside (`off`). Returns {idea, rev}."""
    changes = {k: v for k, v in changes.items() if k in {"text", "papers", "talk", "off"}}  # never `paper`
    with _lock:
        board = load_board(project_path)
        current = _find_idea(board, idea_id)
        idea = clean_idea({**current, **changes}, board)
        board["ideas"][board["ideas"].index(current)] = idea
        board = _save(project_path, board)
    return {"idea": idea, "rev": board["rev"]}


def delete_idea(project_path: Path, idea_id: str) -> dict:
    """Take an idea off the idea board. Returns {rev}."""
    with _lock:
        board = load_board(project_path)
        board["ideas"].remove(_find_idea(board, idea_id))
        board = _save(project_path, board)
    return {"rev": board["rev"]}


def _idea_at(board: dict, at) -> int:
    if at is None:
        return len(board["ideas"])
    if isinstance(at, bool) or not isinstance(at, int):
        raise ValueError("at must be a whole number")
    return max(0, min(at, len(board["ideas"])))


def stow_paper(project_path: Path, paper_id: str, at=None) -> dict:
    """
    Take a paper off the table into the idea board, held inside a new idea at the end or at `at`.
    The site stays on the table. Returns {idea, rev}. Raises ValueError, PaperNotFound.
    """
    with _lock:
        board = load_board(project_path)
        paper = _find(board, paper_id)
        if paper["kind"] == "site":
            raise ValueError("the site paper stays on the table")
        if len(board["ideas"]) >= MAX_IDEAS:
            raise ValueError(f"the idea board holds at most {MAX_IDEAS} ideas")
        index = _idea_at(board, at)
        board["papers"].remove(paper)
        board["pins"] = [p for p in board["pins"] if p.get("paper") != paper_id]
        idea = {"id": f"idea-{uuid.uuid4().hex[:8]}", "text": "", "papers": [], "talk": None, "off": False,
                "paper": paper, "created_at": _now()}
        board["ideas"].insert(index, idea)
        board = _save(project_path, board)
    return {"idea": idea, "rev": board["rev"]}


def place_idea(project_path: Path, idea_id: str, placement: dict | None = None) -> dict:
    """
    Take an idea off the idea board onto the table at `placement` (x, y): the paper it holds goes
    back, and an idea of text only becomes a note. Returns {paper, rev}. Raises ValueError, IdeaNotFound.
    """
    placement = {k: v for k, v in (placement or {}).items() if k in ("x", "y")}
    with _lock:
        board = load_board(project_path)
        idea = _find_idea(board, idea_id)
        if len(board["papers"]) >= MAX_PAPERS:
            raise ValueError(f"the table holds at most {MAX_PAPERS} papers")
        if isinstance(idea.get("paper"), dict):
            paper = dict(idea["paper"])
        else:
            paper = clean_paper({"id": f"note-{uuid.uuid4().hex[:8]}", "kind": "note", "text": idea["text"][:MAX_TEXT]})
        for key, value in placement.items():
            paper[key] = _number(value, key)
        board["ideas"].remove(idea)
        board["papers"].append(paper)
        board = _save(project_path, board)
    return {"paper": paper, "rev": board["rev"]}


def set_hidden(project_path: Path, ids: list) -> dict:
    """
    The VWorld 3D buildings hidden around the site (their model ids, in the order hidden; the same
    id once). Replaces the list; [] shows them all again. Returns {hidden, rev}. Raises ValueError.
    """
    if not isinstance(ids, list) or not all(isinstance(i, str) and 0 < len(i.strip()) <= MAX_HIDDEN_ID for i in ids):
        raise ValueError(f"ids must be a list of building ids (1–{MAX_HIDDEN_ID} characters)")
    ids = list(dict.fromkeys(i.strip() for i in ids))
    if len(ids) > MAX_HIDDEN:
        raise ValueError(f"at most {MAX_HIDDEN} hidden buildings")
    with _lock:
        board = load_board(project_path)
        board["hidden"] = ids
        board = _save(project_path, board)
    return {"hidden": board["hidden"], "rev": board["rev"]}


def clean_person(raw, index: int) -> dict:
    """One scale figure, checked (a new one gets an id). Raises ValueError."""
    if not isinstance(raw, dict):
        raise ValueError(f"people[{index}] must be an object")
    person_id = raw.get("id") or f"person-{uuid.uuid4().hex[:8]}"
    if not (isinstance(person_id, str) and PAPER_ID.fullmatch(person_id)):
        raise ValueError(f"people[{index}].id must be an id")
    kind = raw.get("kind", "stand")
    if kind not in PERSON_KINDS:
        raise ValueError(f"people[{index}].kind must be one of {', '.join(PERSON_KINDS)}")
    x = _number(raw.get("x"), f"people[{index}].x")
    y = _number(raw.get("y"), f"people[{index}].y")
    if abs(x) > MAX_COORD or abs(y) > MAX_COORD:
        raise ValueError(f"people[{index}] is too far from the site")
    turn = _number(raw.get("turn", 0), f"people[{index}].turn") % 360
    roof = raw.get("roof", False)
    if not isinstance(roof, bool):
        raise ValueError(f"people[{index}].roof must be true or false")
    person = {"id": person_id, "x": round(x, 3), "y": round(y, 3), "turn": round(turn, 1) % 360, "kind": kind}
    if roof:
        person["roof"] = True
    return person


def set_people(project_path: Path, raw: list) -> dict:
    """
    The scale figures standing about the site (`people`). Replaces the list; [] takes them all
    away. Returns {people, rev}. Raises ValueError.
    """
    if not isinstance(raw, list):
        raise ValueError("people must be a list")
    if len(raw) > MAX_PEOPLE:
        raise ValueError(f"at most {MAX_PEOPLE} people")
    people = [clean_person(item, index) for index, item in enumerate(raw)]
    if len({p["id"] for p in people}) != len(people):
        raise ValueError("each person needs an id of their own")
    with _lock:
        board = load_board(project_path)
        board["people"] = people
        board = _save(project_path, board)
    return {"people": board["people"], "rev": board["rev"]}


def clean_layers(raw) -> list[dict]:
    """The layers, checked: unique ids, names, parents that exist (no loops). Raises ValueError."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_LAYERS:
        raise ValueError(f"layers must be a list of 1 to {MAX_LAYERS} layers")
    layers: list[dict] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"layers[{index}] must be an object")
        layer_id = str(item.get("id") or "")
        if not PAPER_ID.fullmatch(layer_id) or any(x["id"] == layer_id for x in layers):
            raise ValueError(f"layers[{index}].id must be a unique id")
        name = _text(item.get("name"), "layer name", MAX_LAYER_NAME).strip()
        if not name:
            raise ValueError(f"layers[{index}] needs a name")
        color = str(item.get("color") or "")
        if color and not LAYER_COLOR.fullmatch(color):
            raise ValueError(f"layers[{index}].color must be #rrggbb")
        layers.append({"id": layer_id, "name": name, "parent": str(item.get("parent") or ""),
                       "visible": item.get("visible") is not False, "locked": item.get("locked") is True, "color": color.lower()})
    ids = {x["id"] for x in layers}
    parents = {x["id"]: x["parent"] for x in layers}
    for layer in layers:
        if layer["parent"] and layer["parent"] not in ids:
            raise ValueError(f"layer {layer['id']}: no parent layer {layer['parent']}")
        seen, at = set(), layer["id"]
        while at:
            if at in seen:
                raise ValueError(f"layer {layer['id']} is inside itself")
            seen.add(at)
            at = parents[at]
    return layers


def _layer_home(layer_id: str, old: list[dict], kept: set[str]) -> str:
    """Where things on a layer that is gone go: its nearest ancestor still there ('' for none)."""
    parents = {x["id"]: x["parent"] for x in old}
    at, seen = parents.get(layer_id, ""), set()
    while at and at not in kept and at not in seen:
        seen.add(at)
        at = parents.get(at, "")
    return at if at in kept else ""


def set_layers(project_path: Path, raw: list) -> dict:
    """
    Replace the layers (their order, names, sublayers, visibility, locks, colours). What was on a
    layer left out moves up to its nearest ancestor still there (or back to its kind's layer).
    Returns {layers, rev}. Raises ValueError.
    """
    layers = clean_layers(raw)
    kept = {x["id"] for x in layers}
    with _lock:
        board = load_board(project_path)
        old = board["layers"]

        def rehome(item: dict) -> None:
            if "layer" in item and item["layer"] not in kept:
                home = _layer_home(item["layer"], old, kept)
                if home:
                    item["layer"] = home
                else:
                    del item["layer"]

        for paper in board["papers"] + board["tray"] + held_papers(board):
            rehome(paper)
            for block in paper.get("blocks") or []:
                rehome(block)
        board["layers"] = layers
        board = _save(project_path, board)
    return {"layers": board["layers"], "rev": board["rev"]}


def order_ideas(project_path: Path, ids: list) -> dict:
    """Put the ideas in this order; `ids` names every idea once. Returns {ideas, rev}."""
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError("ids must be a list of idea ids")
    with _lock:
        board = load_board(project_path)
        if sorted(ids) != sorted(i["id"] for i in board["ideas"]):
            raise ValueError("ids must name every idea on the board once")
        by_id = {i["id"]: i for i in board["ideas"]}
        board["ideas"] = [by_id[i] for i in ids]
        board = _save(project_path, board)
    return {"ideas": board["ideas"], "rev": board["rev"]}


# ---------------------------------------------------------------------------
# Validation: what a paper may hold
# ---------------------------------------------------------------------------


def _number(value, what: str, *, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{what} must be a finite number")
    if low is not None and number <= low:
        raise ValueError(f"{what} must be greater than {low:g}")
    if high is not None and number > high:
        raise ValueError(f"{what} must be at most {high:g}")
    return number


def _text(value, what: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text")
    if len(value) > limit:
        raise ValueError(f"{what} is longer than {limit} characters")
    return value


def _block(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"blocks[{index}] must be an object")
    floors = raw.get("floors")
    if isinstance(floors, float) and floors.is_integer():  # a model may write 5.0
        floors = int(floors)
    if isinstance(floors, bool) or not isinstance(floors, int) or not 1 <= floors <= 200:
        raise ValueError(f"blocks[{index}].floors must be a whole number from 1 to 200")
    layer = _tag(raw, "layer", f"blocks[{index}]")
    group = _tag(raw, "group", f"blocks[{index}]")
    block = {
        "u": _number(raw.get("u", 0), f"blocks[{index}].u"),
        "v": _number(raw.get("v", 0), f"blocks[{index}].v"),
        "w": _number(raw.get("w"), f"blocks[{index}].w", low=0, high=1000),
        "d": _number(raw.get("d"), f"blocks[{index}].d", low=0, high=1000),
        "floors": floors,
    }
    # The block's turn in degrees, counter-clockwise from the site's long side (the drawing
    # table's rotate tool); kept only when the block is turned, between -180 and 180.
    turn = _number(raw.get("a", 0), f"blocks[{index}].a", low=-360.0001, high=360) % 360
    turn = round(turn - 360 if turn > 180 else turn, 2)
    if turn:
        block["a"] = turn
    if layer:  # on a layer of its own (otherwise on its scheme's)
        block["layer"] = layer
    if group:
        block["group"] = group
    return block


def _tag(data: dict, key: str, what: str) -> str:
    """A layer or group id on a paper or block ('' for none). Raises ValueError."""
    value = data.get(key)
    if value is None or value == "":
        return ""
    if not (isinstance(value, str) and PAPER_ID.fullmatch(value)):
        raise ValueError(f"{what}.{key} must be an id")
    return value


def _stroke(raw, index: int) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) > MAX_POINTS:
        raise ValueError(f"strokes[{index}] must be a list of at most {MAX_POINTS} points")
    points = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"strokes[{index}] points must be [x, y]")
        points.append([_number(point[0], "stroke x"), _number(point[1], "stroke y")])
    return points


def clean_paper(data: dict) -> dict:
    """A paper with only the fields its kind holds, checked. Raises ValueError."""
    kind = data["kind"]
    paper: dict = {"id": data["id"], "kind": kind}
    width, height = PAPER_SIZE.get(kind, (300, 210))  # CSS pixels of paper; the screen shows 1 px as 0.1 m
    for key, default in zip(PLACEMENT, (0, 0, width, height), strict=True):
        paper[key] = _number(data.get(key, default), key)
    folded = data.get("folded", False)
    if not isinstance(folded, bool):
        raise ValueError("folded must be true or false")
    if folded:  # the designer folded it into a name tag, in plan too (kept only when true)
        paper["folded"] = True
    for key in ("layer", "group"):  # a layer the designer chose (otherwise its kind's); a group
        tag = _tag(data, key, "paper")
        if tag:
            paper[key] = tag
    title = _text(data.get("title"), "title", MAX_TITLE)
    if kind == "mass":
        blocks = data.get("blocks")
        if not isinstance(blocks, list) or not 1 <= len(blocks) <= MAX_BLOCKS:
            raise ValueError(f"a massing scheme needs 1 to {MAX_BLOCKS} blocks")
        paper["title"] = title
        paper["blocks"] = [_block(b, i) for i, b in enumerate(blocks)]
        paper["floor_height"] = _number(
            data.get("floor_height", DEFAULT_FLOOR_HEIGHT), "floor_height", low=0, high=20
        )
    elif kind == "note":
        paper["text"] = _text(data.get("text"), "text", MAX_TEXT)
    elif kind == "expert":  # made by the server from an expert run; only moves afterwards
        for key in ("agent", "title", "text", "about"):
            paper[key] = data.get(key, "" if key != "about" else [])
    elif kind == "tracing":
        strokes = data.get("strokes", [])
        if not isinstance(strokes, list) or len(strokes) > MAX_STROKES:
            raise ValueError(f"strokes must be a list of at most {MAX_STROKES}")
        paper["title"] = title
        paper["strokes"] = [_stroke(s, i) for i, s in enumerate(strokes)]
        paper["overlaid"] = bool(data.get("overlaid", False))
    elif kind == "photo":  # the file is named by the server (add_photo) and never changes
        file = data.get("file")
        if not isinstance(file, str) or not PHOTO_FILE.fullmatch(file):
            raise ValueError("a photo paper needs its uploaded file")
        paper["title"] = title
        paper["file"] = file
        if file.endswith(".pdf"):  # which page of the PDF the paper shows, from 1
            page = _number(data.get("page", 1), "page", low=0, high=MAX_PDF_PAGE)
            if page != int(page):
                raise ValueError("page must be a whole number")
            paper["page"] = int(page)
    return paper


# ---------------------------------------------------------------------------
# What the models are told
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    """The papers sent with one message, as they stood when it was sent."""

    papers: tuple[dict, ...]
    board: dict
    site: dict | None  # {"area_m2": float | None, "lines": [str]} from the site domain


def site_summary(project_path: Path, hooks=None) -> dict | None:
    """What the site domain says about the site for the table (first domain with a `board_site`)."""
    from sida.experts import domain_hooks

    for _domain, module in domain_hooks() if hooks is None else hooks:
        provide = getattr(module, "board_site", None)
        if provide is None:
            continue
        try:
            summary = provide(Path(project_path))
        except Exception:  # site facts must never stop a message
            continue
        if summary:
            return summary
    return None


def site_brief(project_path: Path, hooks=None) -> str:
    """What the domains tell the Conductor about the site with every message (hook `conductor_site`):
    the facts, the lot in the frame blocks stand in, the surroundings. "" when none has any."""
    from sida.experts import domain_hooks

    parts = []
    for _domain, module in domain_hooks() if hooks is None else hooks:
        give = getattr(module, "conductor_site", None)
        if give is None:
            continue
        try:
            text = give(Path(project_path))
        except Exception:  # the site must never stop a message
            continue
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def select(project_path: Path, ids: list[str] | None, *, hooks=None) -> Selection | None:
    """The selected papers, checked; None when nothing is selected. Raises ValueError."""
    ids = [str(i) for i in (ids or [])]
    if not ids:
        return None
    if len(ids) > MAX_CONTEXT:
        raise ValueError(f"select at most {MAX_CONTEXT} papers for one message")
    board = load_board(project_path)
    papers = []
    for paper_id in dict.fromkeys(ids):
        try:
            papers.append(_find_any(board, paper_id))
        except ValueError:
            raise ValueError(f"unknown paper on the table: {paper_id}") from None
    return Selection(tuple(papers), board, site_summary(project_path, hooks))


def paper_name(paper: dict) -> str:
    """The short name a chip and the history show (Korean, like the screen)."""
    kind = paper["kind"]
    if kind == "site":
        return "대지"
    if kind == "note":
        text = " ".join(str(paper.get("text") or "").split())
        return f"메모: {text[:20]}{'…' if len(text) > 20 else ''}" if text else "메모"
    if kind == "mass":
        return paper.get("title") or "매스안"
    if kind == "tracing":
        return paper.get("title") or "트레이싱지"
    if kind == "expert":
        return f"{paper.get('title') or paper.get('agent')} 결과"
    if kind == "photo":
        return paper.get("title") or "사진"
    return paper.get("title") or kind


KIND_WORDS = {
    "site": "site", "mass": "massing scheme", "note": "note", "tracing": "tracing sheet",
    "expert": "expert result", "photo": "photo",
}


def _m(value: float) -> str:
    return f"{value:,.1f}"


def mass_figures(paper: dict, site_area: float | None) -> dict:
    """Footprint, floor area and height from the blocks; ratios only with a known site area."""
    blocks = paper["blocks"]
    footprint = sum(b["w"] * b["d"] for b in blocks)
    floor_area = sum(b["w"] * b["d"] * b["floors"] for b in blocks)
    figures = {
        "footprint_m2": round(footprint, 1),
        "floor_area_m2": round(floor_area, 1),
        "height_m": round(max(b["floors"] for b in blocks) * paper["floor_height"], 1),
        "coverage_pct": None,
        "far_pct": None,
    }
    if site_area:
        figures["coverage_pct"] = round(footprint / site_area * 100, 1)
        figures["far_pct"] = round(floor_area / site_area * 100, 1)
    return figures


def paper_text(paper: dict, site: dict | None) -> str:
    """One paper in full, for a model (English frame, the designer's words as written)."""
    head = f"- {paper['id']} · {KIND_WORDS.get(paper['kind'], paper['kind'])} \"{paper_name(paper)}\""
    if paper.get("based_on"):
        head += f" (AI copy of {paper['based_on']})"
    elif paper.get("origin"):
        head += f" (made by {paper['origin']})"
    if paper.get("reason"):
        head += f" — why: {paper['reason']}"
    kind = paper["kind"]
    if kind == "expert":
        return (
            f"{head}: preview of modules output (read_expert_output {paper.get('agent')} for all of it):\n"
            + "\n".join(f"  {line}" for line in str(paper.get("text") or "").splitlines())
        )
    if kind == "site":
        lines = (site or {}).get("lines") or []
        if not lines:
            return head + ": no site facts saved yet (미확인)"
        return head + ":\n" + "\n".join(f"  - {line}" for line in lines)
    if kind == "note":
        return f"{head}: {paper.get('text') or '(empty)'}"
    if kind == "tracing":
        where = "laid over the site" if paper.get("overlaid") else "set aside next to the site"
        return (
            f"{head}: {len(paper.get('strokes') or [])} pen strokes, {where}. "
            "The drawing itself cannot be read as text; ask the designer what it shows."
        )
    if kind == "photo":
        if str(paper.get("file") or "").endswith(".pdf"):
            return (
                f"{head}: page {paper.get('page', 1)} of a PDF (a drawing or document) the designer put on "
                "the table. The page itself is not sent; ask the designer what it shows if it matters."
            )
        return (
            f"{head}: a photo the designer put on the table. The image itself is not sent; "
            "ask the designer what it shows if it matters."
        )
    if kind == "mass":
        area = (site or {}).get("area_m2")
        f = mass_figures(paper, area)
        parts = [
            f"{_m(b['w'])} m × {_m(b['d'])} m × {b['floors']} floors at u {_m(b['u'])}, v {_m(b['v'])}"
            + (f", turned {b['a']:g}°" if b.get("a") else "")
            for b in paper["blocks"]
        ]
        text = (
            f"{head}: {len(parts)} block(s) — " + "; ".join(parts) + ". "
            f"Building footprint {_m(f['footprint_m2'])} m² (sum of blocks, overlaps not subtracted), "
            f"gross floor area {_m(f['floor_area_m2'])} m², highest {_m(f['height_m'])} m "
            f"at {paper['floor_height']:g} m per floor."
        )
        if f["coverage_pct"] is None:
            return text + " Site area 미확인: coverage and FAR not computed."
        return text + (
            f" Against the site area {_m(area)} m²: building coverage {f['coverage_pct']:.1f}%, "
            f"FAR {f['far_pct']:.1f}%."
        )
    return head


def expert_block(selection: Selection | None) -> str:
    """The selected papers in full, for an expert's prompt ("" when nothing is selected)."""
    if selection is None:
        return ""
    body = "\n".join(paper_text(p, selection.site) for p in selection.papers)
    return (
        "DRAWING TABLE — papers the designer selected with this request. Figures were computed "
        "by Sida from the paper's blocks and the site facts; use them as given and do not "
        "recompute them.\n" + body
    )


def ideas_block(board: dict | None) -> str:
    """
    The designer's main ideas for a model ("" when there are none in play). Ideas set aside
    (`off`) are left out; the model is only told how many there are.
    """
    if not board:
        return ""
    ideas = board.get("ideas") or []
    shown = [i for i in ideas if not i.get("off")]
    if not shown:
        return ""
    names = {p["id"]: paper_name(p) for p in board["papers"] + board["tray"] + held_papers(board)}
    lines = []
    for n, idea in enumerate(shown, 1):
        text = "\n   ".join(line.strip() for line in idea["text"].splitlines() if line.strip())
        if isinstance(idea.get("paper"), dict):
            text = "\n   ".join(part for part in (_held_line(idea["paper"]), text) if part)
        links = [f'{i} "{names[i]}"' for i in idea.get("papers") or [] if i in names]
        if idea.get("talk"):
            links.append(f"Conductor talk {idea['talk']}")
        lines.append(f"{n}. {text}" + (f" (linked: {', '.join(links)})" if links else ""))
    aside = len(ideas) - len(shown)
    return (
        "DESIGNER'S MAIN IDEAS (the idea board, in the designer's order). The designer chose and "
        "wrote these; they are the project's main direction. Keep them in mind in every answer. "
        "You never add, rewrite, reorder or drop them. If a suggestion goes against one, say which "
        "one and why, and leave the choice to the designer.\n"
        + "\n".join(lines)
        + (f"\n({aside} more set aside by the designer for now: do not apply them.)" if aside else "")
    )


def _held_line(paper: dict) -> str:
    """A paper held in the idea board, in one line for a model (a note by its words)."""
    kind = KIND_WORDS.get(paper.get("kind"), str(paper.get("kind")))
    if paper.get("kind") == "note":
        words = " ".join(str(paper.get("text") or "").split())
        return f"[{kind} {paper.get('id')}] {words[:MAX_IDEA_TEXT]}" if words else f"[{kind} {paper.get('id')}]"
    return f'[{kind} {paper.get("id")} "{paper_name(paper)}"]'


def expert_context(project_path: Path, selection: Selection | None) -> str:
    """The idea board and the selected papers, for an expert's prompt ("" for neither)."""
    table = selection.board if selection is not None else read_board(project_path)
    return "\n\n".join(part for part in (ideas_block(table), expert_block(selection)) if part)


def _index(papers: list[dict]) -> str:
    return "\n".join(
        f"- {p['id']} · {KIND_WORDS.get(p['kind'], p['kind'])} \"{paper_name(p)}\""
        for p in papers
    ) or "- (empty)"


def board_index(board: dict) -> str:
    text = _index(board["papers"])
    if board.get("tray"):
        text += (
            "\nAI SECTION (made by you or the experts, not on the table until the designer "
            "moves a paper there):\n" + _index(board["tray"])
        )
    return text


def context_mode(config: dict) -> str:
    """full | names, from conductor.board_context (auto: local Conductor → names)."""
    from sida.runtime import resolve_conductor_runtime

    mode = str((config.get("conductor") or {}).get("board_context") or "auto").lower()
    if mode not in CONTEXT_MODES:
        mode = "auto"
    if mode == "auto":
        provider = resolve_conductor_runtime(config)["provider"]
        return "names" if provider in LOCAL_PROVIDERS else "full"
    return mode


def conductor_block(selection: Selection | None, board: dict | None, mode: str) -> str:
    """
    The table for one Conductor call ("" for none). names: nothing beyond the history line.
    full: the selected papers in full and an index of the table for read_board.
    """
    if mode != "full" or board is None:
        return ""
    parts = [
        "DRAWING TABLE (the designer's workspace; ids are for read_board). You never change "
        "the table: propose_paper puts a new scheme or note in the AI section, and a change to a "
        "scheme on the table comes as a copy with based_on.",
        board_index(board),
    ]
    if selection is not None:
        parts += [
            "",
            "Selected with the designer's last message (figures computed by Sida, use as given):",
            "\n".join(paper_text(p, selection.site) for p in selection.papers),
        ]
    return "\n".join(parts)


def read_paper(project_path: Path, paper_id: str, *, hooks=None) -> str | None:
    """One paper in full for the read_board tool, or None when it is not on the table."""
    board = load_board(project_path)
    try:
        paper = _find_any(board, paper_id)
    except ValueError:
        return None
    return paper_text(paper, site_summary(project_path, hooks))


def mark_text(text: str, selection: Selection | None) -> str:
    """The message as stored in history: the designer's words plus the selected paper names."""
    if selection is None:
        return text
    names = " | ".join(f"{p['id']} = {paper_name(p).replace('|', '/')}" for p in selection.papers)
    return f"{text}\n\n{SELECTED_PREFIX}{names}"


def split_mark(content: str) -> tuple[str, list[dict]]:
    """Undo mark_text for a screen: (the designer's words, [{id, name}] of the selected papers)."""
    head, sep, tail = content.rpartition("\n\n" + SELECTED_PREFIX)
    if not sep or "\n" in tail:
        return content, []
    chips = []
    for part in tail.split(" | "):
        paper_id, eq, name = part.partition(" = ")
        if eq:
            chips.append({"id": paper_id, "name": name})
    return head, chips


# ---------------------------------------------------------------------------
# What the screen draws
# ---------------------------------------------------------------------------

EARTH_RADIUS = 6378137.0  # m, as the map tiles use


def _outer_rings(shape) -> list[list[list[float]]]:
    """The outer ring of each polygon in a GeoJSON Polygon or MultiPolygon ([lon, lat] points)."""
    if not isinstance(shape, dict):
        return []
    coordinates = shape.get("coordinates")
    polygons = {"Polygon": [coordinates], "MultiPolygon": coordinates}.get(shape.get("type")) or []
    rings = []
    for polygon in polygons:
        ring = polygon[0] if isinstance(polygon, list) and polygon else None
        if not isinstance(ring, list):
            continue
        points = [
            [float(p[0]), float(p[1])]
            for p in ring
            if isinstance(p, (list, tuple)) and len(p) >= 2
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in p[:2])
        ]
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        if len(points) >= 3:
            rings.append(points)
    return rings


def _ring_area(ring: list[list[float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True))) / 2


def _centroid(ring: list[list[float]]) -> list[float]:
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        f = x1 * y2 - x2 * y1
        a += f
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    if not a:
        return [sum(x for x, _ in ring) / len(ring), sum(y for _, y in ring) / len(ring)]
    return [cx / (3 * a), cy / (3 * a)]


def site_plan(parcels: list[dict]) -> dict | None:
    """
    The parcels' boundaries in metres around the site's middle (x east, y north), the bounds,
    where that middle lies (`origin`, lon/lat) and the frame blocks stand in: the middle of
    the largest parcel and the direction of its longest edge (radians from east, within ±90°).
    None when no parcel has a boundary.
    """
    found = [(p, _outer_rings(p.get("shape"))) for p in parcels or []]
    points = [pt for _p, rings in found for ring in rings for pt in ring]
    if not points:
        return None
    lon0 = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
    lat0 = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
    k = math.pi / 180
    east = EARTH_RADIUS * k * math.cos(lat0 * k)
    north = EARTH_RADIUS * k

    def local(ring):
        return [[round((lon - lon0) * east, 2), round((lat - lat0) * north, 2)] for lon, lat in ring]

    out = []
    for parcel, rings in found:
        if rings:
            out.append({
                "pnu": parcel.get("pnu", ""),
                "address": parcel.get("address", ""),
                "area_m2": parcel.get("area_m2"),
                "rings": [local(r) for r in rings],
            })
    every = [ring for p in out for ring in p["rings"]]
    largest = max(every, key=_ring_area)
    angle, longest = 0.0, 0.0
    for (x1, y1), (x2, y2) in zip(largest, largest[1:] + largest[:1], strict=True):
        length = math.hypot(x2 - x1, y2 - y1)
        if length > longest:
            longest, angle = length, math.atan2(y2 - y1, x2 - x1)
    if angle > math.pi / 2:
        angle -= math.pi
    elif angle <= -math.pi / 2:
        angle += math.pi
    xs = [x for ring in every for x, _ in ring]
    ys = [y for ring in every for _, y in ring]
    middle = _centroid(largest)
    return {
        "parcels": out,
        "bounds": {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys)},
        "frame": {"x": round(middle[0], 2), "y": round(middle[1], 2), "angle": round(angle, 5)},
        "origin": {"lon": round(lon0, 8), "lat": round(lat0, 8)},
    }


# The view the designer last looked at the table from (2026-11-09 지훈: back after a reload), as
# Rhino keeps its views in the .3dm: beside board.json, not in it, so saving it does not count as an
# edit of the table (no rev). {x, y, span, tilt, turn, z}: the screen's camera numbers.
VIEW_FILE = "table_view.json"
VIEW_KEYS = ("x", "y", "span", "tilt", "turn", "z", "para")  # para: 0 perspective to 1 parallel (iso)


def load_view(project_path: Path) -> dict | None:
    """The kept view, or None (never saved, or not a view)."""
    try:
        data = json.loads((Path(project_path) / VIEW_FILE).read_text(encoding="utf-8"))
        return clean_view(data)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def clean_view(data: dict) -> dict:
    """The view's numbers, checked. Raises ValueError."""
    if not isinstance(data, dict):
        raise ValueError("view must be an object")
    out = {key: _number(data.get(key, 0), f"view {key}") for key in VIEW_KEYS}
    if out["span"] <= 0 or out["span"] > 1e6:
        raise ValueError("view span must be positive")
    if not -1 <= out["tilt"] <= 180:
        raise ValueError("view tilt is out of range")
    if not 0 <= out["para"] <= 1:
        raise ValueError("view para must be between 0 and 1")
    return {key: round(value, 4) for key, value in out.items()}


def save_view(project_path: Path, data: dict) -> dict:
    """Keep the view the table is seen from. Raises ValueError."""
    kept = clean_view(data)
    atomic_write_text(Path(project_path) / VIEW_FILE, json.dumps(kept))
    return kept


def view(project_path: Path, *, hooks=None) -> dict:
    """
    The table as the screen draws it: the saved board, the site (area, fact lines and the
    plan from `site_plan`; None without site facts) and each scheme's figures by paper id.
    """
    board = load_board(project_path)
    summary = site_summary(project_path, hooks)
    area = (summary or {}).get("area_m2")
    figures = {}
    for paper in board["papers"] + board["tray"]:
        if paper.get("kind") != "mass":
            continue
        try:
            figures[paper["id"]] = mass_figures(paper, area)
        except (KeyError, TypeError, ValueError):  # a hand-edited board.json
            continue
    site = None
    if summary is not None:
        site = {
            "area_m2": area,
            "lines": summary.get("lines") or [],
            "plan": site_plan(summary.get("parcels") or []),
        }
    return {**board, "site": site, "figures": figures, "saved_view": load_view(project_path)}


def context_view(project_path: Path, config: dict, ids: list[str] | None) -> dict:
    """What the models would be sent for this selection (for the screen to show)."""
    selection = select(project_path, ids)
    board = load_board(project_path)
    mode = context_mode(config)
    return {
        "mode": mode,
        "papers": [{"id": p["id"], "name": paper_name(p)} for p in (selection.papers if selection else ())],
        "conductor": "\n\n".join(
            part for part in (ideas_block(board), conductor_block(selection, board, mode)) if part
        ),
        "expert": expert_context(project_path, selection),
    }
