"""The drafting table (제도판): sheets of paper laid around the site, saved in the project.

Independent of HTTP and of the screen. The table is stored as board.json in the project
folder: {"rev", "papers", "tray", "pins"}. The designer adds, moves and edits papers one at
a time (the screen and the AI write to the same file, so nobody saves it whole).

What the AI makes never lands on the table itself (2026-10-26 지훈 결정). It goes to the AI
section, `tray`: massing schemes and notes the Conductor proposes (a change to the designer's
scheme comes as a copy, `based_on` the original) and expert results. The designer moves the
ones they like onto the table (`place_paper`) and throws the rest away.

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
import math
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from sida.storage import atomic_write_text

BOARD_FILE = "board.json"
SITE_ID = "site"
KINDS = ("site", "mass", "note", "tracing", "expert")
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
PAPER_SIZE = {"site": (300, 250), "mass": (300, 210), "note": (200, 140), "tracing": (300, 250), "expert": (320, 270)}
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
    return {"rev": 0, "papers": [_site_paper()], "tray": [], "pins": []}


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
    tray = data.get("tray") if isinstance(data.get("tray"), list) else []
    tray = [p for p in tray if isinstance(p, dict) and p.get("kind") in KINDS]
    pins = data.get("pins") if isinstance(data.get("pins"), list) else []
    return {"rev": int(data.get("rev") or 0), "papers": papers, "tray": tray, "pins": pins}


def _save(project_path: Path, board: dict) -> dict:
    board["rev"] += 1
    atomic_write_text(board_path(project_path), json.dumps(board, ensure_ascii=False, indent=2) + "\n")
    return board


def _find(board: dict, paper_id: str, where: str = "papers") -> dict:
    for paper in board[where]:
        if paper.get("id") == paper_id:
            return paper
    raise PaperNotFound(paper_id)


def _taken(board: dict, paper_id: str) -> bool:
    return any(p.get("id") == paper_id for p in board["papers"] + board["tray"])


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
        if _taken(board, paper_id):
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
        if current["kind"] in {"site", "expert"}:
            extra = sorted(set(changes) - set(PLACEMENT))
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
    return {"rev": board["rev"]}


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
            "title": str(agent.get("name") or agent["id"]),
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
    width, height = PAPER_SIZE.get(kind, (300, 210))  # CSS pixels of paper; the screen shows 1 px as 0.1 m
    for key, default in zip(PLACEMENT, (0, 0, width, height), strict=True):
        paper[key] = _number(data.get(key, default), key)
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
    return paper.get("title") or kind


KIND_WORDS = {
    "site": "site", "mass": "massing scheme", "note": "note", "tracing": "tracing sheet",
    "expert": "expert result",
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
    if kind == "mass":
        area = (site or {}).get("area_m2")
        f = mass_figures(paper, area)
        parts = [
            f"{_m(b['w'])} m × {_m(b['d'])} m × {b['floors']} floors at u {_m(b['u'])}, v {_m(b['v'])}"
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
    and the frame blocks stand in: the middle of the largest parcel and the direction of its
    longest edge (radians from east, within ±90°). None when no parcel has a boundary.
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
    }


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
    return {**board, "site": site, "figures": figures}


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
