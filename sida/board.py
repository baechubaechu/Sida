"""The drafting table (제도판): sheets of paper laid around the site, saved in the project.

Independent of HTTP and of the screen. The table is stored as board.json in the project
folder: {"rev", "papers", "pins"}. The designer adds, moves and edits papers one at a time
(the screen and, later, the experts write to the same table, so nobody saves it whole).

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
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from sida.storage import atomic_write_text

BOARD_FILE = "board.json"
SITE_ID = "site"
KINDS = ("site", "mass", "note", "tracing")  # "expert" papers come from expert runs (later)
DESIGNER_KINDS = ("mass", "note", "tracing")  # what the screen may add
MAX_PAPERS = 300
MAX_CONTEXT = 8  # papers one message may carry
MAX_TEXT = 4000
MAX_TITLE = 120
MAX_BLOCKS = 20
MAX_STROKES = 500
MAX_POINTS = 5000
DEFAULT_FLOOR_HEIGHT = 4.2
PLACEMENT = ("x", "y", "w", "h")
PAPER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
CONTEXT_MODES = ("auto", "full", "names")
LOCAL_PROVIDERS = frozenset({"ollama", "local"})
SELECTED_PREFIX = "[selected on the table] "

_lock = threading.Lock()


class PaperNotFound(LookupError):
    """No paper with this id on the table."""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def board_path(project_path: Path) -> Path:
    return Path(project_path) / BOARD_FILE


def _site_paper() -> dict:
    return {"id": SITE_ID, "kind": "site", "x": 0.0, "y": 0.0, "w": 300.0, "h": 250.0}


def _empty() -> dict:
    return {"rev": 0, "papers": [_site_paper()], "pins": []}


def load_board(project_path: Path) -> dict:
    """The saved table; a new or unreadable one is the site paper alone (rev 0)."""
    path = board_path(project_path)
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("papers"), list):
        return _empty()
    papers = [p for p in data["papers"] if isinstance(p, dict) and p.get("kind") in KINDS]
    if not any(p.get("id") == SITE_ID for p in papers):
        papers.insert(0, _site_paper())
    pins = data.get("pins") if isinstance(data.get("pins"), list) else []
    return {"rev": int(data.get("rev") or 0), "papers": papers, "pins": pins}


def _save(project_path: Path, board: dict) -> dict:
    board["rev"] += 1
    atomic_write_text(board_path(project_path), json.dumps(board, ensure_ascii=False, indent=2) + "\n")
    return board


def _find(board: dict, paper_id: str) -> dict:
    for paper in board["papers"]:
        if paper.get("id") == paper_id:
            return paper
    raise PaperNotFound(paper_id)


def add_paper(project_path: Path, data: dict) -> dict:
    """Lay a new mass, note or tracing sheet on the table. Returns {paper, rev}."""
    kind = str(data.get("kind") or "")
    if kind not in DESIGNER_KINDS:
        raise ValueError(f"kind must be one of {', '.join(DESIGNER_KINDS)}")
    with _lock:
        board = load_board(project_path)
        if len(board["papers"]) >= MAX_PAPERS:
            raise ValueError(f"the table holds at most {MAX_PAPERS} papers")
        paper_id = str(data.get("id") or f"{kind}-{uuid.uuid4().hex[:8]}")
        if not PAPER_ID.fullmatch(paper_id):
            raise ValueError("paper id: letters, digits, '-' and '_' only (at most 64)")
        if any(p.get("id") == paper_id for p in board["papers"]):
            raise ValueError(f"a paper with this id already exists: {paper_id}")
        paper = clean_paper({**data, "id": paper_id, "kind": kind})
        board["papers"].append(paper)
        board = _save(project_path, board)
    return {"paper": paper, "rev": board["rev"]}


def update_paper(project_path: Path, paper_id: str, changes: dict) -> dict:
    """Move or edit one paper (id and kind stay). The site paper only moves. Returns {paper, rev}."""
    changes = {k: v for k, v in changes.items() if k not in {"id", "kind"}}
    with _lock:
        board = load_board(project_path)
        current = _find(board, paper_id)
        if current["kind"] == "site":
            extra = sorted(set(changes) - set(PLACEMENT))
            if extra:
                raise ValueError(f"the site paper only moves; cannot change: {', '.join(extra)}")
        paper = clean_paper({**current, **changes})
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
    return {"rev": board["rev"]}


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
    if isinstance(floors, bool) or not isinstance(floors, int) or not 1 <= floors <= 200:
        raise ValueError(f"blocks[{index}].floors must be a whole number from 1 to 200")
    return {
        "u": _number(raw.get("u", 0), f"blocks[{index}].u"),
        "v": _number(raw.get("v", 0), f"blocks[{index}].v"),
        "w": _number(raw.get("w"), f"blocks[{index}].w", low=0, high=1000),
        "d": _number(raw.get("d"), f"blocks[{index}].d", low=0, high=1000),
        "floors": floors,
    }


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
    for key in PLACEMENT:
        paper[key] = _number(data.get(key, 0), key)
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
    elif kind == "tracing":
        strokes = data.get("strokes", [])
        if not isinstance(strokes, list) or len(strokes) > MAX_STROKES:
            raise ValueError(f"strokes must be a list of at most {MAX_STROKES}")
        paper["title"] = title
        paper["strokes"] = [_stroke(s, i) for i, s in enumerate(strokes)]
        paper["overlaid"] = bool(data.get("overlaid", False))
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
            papers.append(_find(board, paper_id))
        except PaperNotFound:
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
    return paper.get("title") or kind


KIND_WORDS = {"site": "site", "mass": "massing scheme", "note": "note", "tracing": "tracing sheet"}


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
    kind = paper["kind"]
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
    if kind == "mass":
        area = (site or {}).get("area_m2")
        f = mass_figures(paper, area)
        parts = [
            f"{_m(b['w'])} m × {_m(b['d'])} m × {b['floors']} floors" for b in paper["blocks"]
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


def board_index(board: dict) -> str:
    return "\n".join(
        f"- {p['id']} · {KIND_WORDS.get(p['kind'], p['kind'])} \"{paper_name(p)}\""
        for p in board["papers"]
    )


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
    parts = ["DRAWING TABLE (the designer's workspace; ids are for read_board):", board_index(board)]
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
        paper = _find(board, paper_id)
    except PaperNotFound:
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


def context_view(project_path: Path, config: dict, ids: list[str] | None) -> dict:
    """What the models would be sent for this selection (for the screen to show)."""
    selection = select(project_path, ids)
    board = load_board(project_path)
    mode = context_mode(config)
    return {
        "mode": mode,
        "papers": [{"id": p["id"], "name": paper_name(p)} for p in (selection.papers if selection else ())],
        "conductor": conductor_block(selection, board, mode),
        "expert": expert_block(selection),
    }
