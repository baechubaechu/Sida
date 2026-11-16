"""The deck as data: the slides the presentation editor listed (or a plain default), each with
the material that fills it.

The editor ends its document with one fenced JSON block:

    {"slides": [
      {"layout": "title", "title": "…", "subtitle": "…"},
      {"layout": "text", "title": "…", "bullets": ["…"], "notes": "…"},
      {"layout": "figure", "title": "…", "figure": "diagram:program", "caption": "…", "bullets": ["…"]}]}

`figure` names a material by key: `diagram:<kind>` (a diagram Sida draws of the newest Rhino
snapshot, sida/experts/rhino/diagrams.py), `view:<kind>` (a capture of that snapshot: persp, plan,
…) or `figures` (the table of figures). The editor never supplies a picture or a number; a key
that names nothing is kept as an empty place and said in the deck's notes. Without the block
(the editor not run yet, or an older document) the deck is a default one made by rule: a title,
the figures, every diagram that can be drawn and every capture, with no sentences.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sida.experts.rhino import diagrams
from sida.experts.rhino import snapshot as snap
from sida.project import section_body

EDITOR = "presentation_editor"  # the same id hooks.py answers to
LAYOUTS = ("title", "text", "figure")
MAX_SLIDES = 30
MAX_BULLETS = 8
MAX_TITLE = 120
MAX_LINE = 300
MAX_NOTES = 1500
VIEW_WORDS = {"persp": "투시", "axo": "축측", "eye": "눈높이", "plan": "평면", "elevation": "입면", "section": "단면"}
VIEW_ORDER = ("persp", "axo", "eye", "plan", "elevation", "section")
FIGURES_KEY = "figures"
FIGURES_TITLE = "수치"
_FENCE = re.compile(r"```\s*json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def read_block(markdown: str | None) -> list | None:
    """The slide list in the editor's document: the last fenced JSON block that holds one, or None."""
    for raw in reversed(_FENCE.findall(markdown or "")):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("slides"), list):
            return data["slides"]
    return None


def without_block(markdown: str) -> str:
    """The document without its slide list (the screen shows the list as slides)."""
    return re.sub(r"\n{3,}", "\n\n", _FENCE.sub("", markdown or "")).strip()


def _line(value, limit: int) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def clean(raw: list) -> tuple[list[dict], list[str]]:
    """
    The listed slides, checked: [{layout, title, subtitle, bullets, caption, notes, figure}] and
    what was left out, as notes for the designer. A slide that says nothing is dropped; texts are
    cut to length; the layout follows what the slide holds when it names none (or an unknown one).
    """
    slides: list[dict] = []
    notes: list[str] = []
    for index, item in enumerate(raw):
        if len(slides) >= MAX_SLIDES:
            notes.append(f"슬라이드는 {MAX_SLIDES}장까지만 만듭니다. 나머지 {len(raw) - index}장은 넣지 않았습니다.")
            break
        if not isinstance(item, dict):
            continue
        bullets = [text for text in (_line(b, MAX_LINE) for b in item.get("bullets") or [] if not isinstance(b, (dict, list))) if text] \
            if isinstance(item.get("bullets"), list) else []
        if len(bullets) > MAX_BULLETS:
            notes.append(f"{index + 1}번 슬라이드의 항목은 {MAX_BULLETS}개까지만 넣었습니다.")
        slide = {
            "layout": item.get("layout") if item.get("layout") in LAYOUTS else "",
            "title": _line(item.get("title"), MAX_TITLE),
            "subtitle": _line(item.get("subtitle"), MAX_LINE),
            "bullets": bullets[:MAX_BULLETS],
            "caption": _line(item.get("caption"), MAX_LINE),
            "notes": str(item["notes"]).strip()[:MAX_NOTES] if isinstance(item.get("notes"), str) else "",
            "figure": _line(item.get("figure"), 60),
        }
        if not (slide["title"] or slide["bullets"] or slide["figure"]):
            continue
        if slide["figure"]:
            slide["layout"] = "figure"
        elif slide["layout"] in ("", "figure"):
            slide["layout"] = "title" if not slides and not slide["bullets"] else "text"
        slides.append(slide)
    return slides, notes


def materials(project_path: Path) -> dict:
    """
    What can fill a slide right now, from the newest Rhino snapshot: {snapshot, figures, limits,
    context, items: {key: {key, kind, title, ready, why}}}. Every diagram kind is listed (one that
    cannot be drawn says why); without a snapshot nothing is ready.
    """
    path = Path(project_path)
    saved = snap.latest_snapshot(path)
    items: dict[str, dict] = {}
    if saved is None:
        why = "라이노 작업이 아직 없습니다. 라이노에서 Sida로 보내면 채워집니다."
        for kind, about in diagrams.KINDS.items():
            items[f"diagram:{kind}"] = {"key": f"diagram:{kind}", "kind": "diagram", "title": about["title"], "ready": False, "why": why}
        items[FIGURES_KEY] = {"key": FIGURES_KEY, "kind": "figures", "title": FIGURES_TITLE, "ready": False, "why": why}
        return {"snapshot": None, "figures": None, "limits": [], "context": None, "items": items}
    ctx = diagrams.context(path, around=False)  # the buildings around are fetched only when the site plan is drawn (deck.py)
    fig = snap.figures(saved, ctx["site_area"])
    for state in diagrams.available(saved, ctx):
        key = f"diagram:{state['kind']}"
        items[key] = {"key": key, "kind": "diagram", "title": state["title"], "ready": state["ready"], "why": state["reason"]}
    for view in sorted(saved["views"], key=lambda v: VIEW_ORDER.index(v["kind"]) if v["kind"] in VIEW_ORDER else len(VIEW_ORDER)):
        key = f"view:{view['kind']}"
        if key not in items:  # the first capture of a kind stands for it
            items[key] = {"key": key, "kind": "view", "title": f"라이노 {VIEW_WORDS.get(view['kind'], view['kind'])} 뷰", "ready": True,
                          "why": "", "file": view["file"]}
    items[FIGURES_KEY] = {"key": FIGURES_KEY, "kind": "figures", "title": FIGURES_TITLE, "ready": bool(fig["objects"]),
                          "why": "" if fig["objects"] else diagrams.NOT_READY["no_bodies"]}
    return {"snapshot": saved, "figures": fig, "limits": ctx["limits"], "context": ctx, "items": items}


def figure_rows(fig: dict, limits: list[dict]) -> list[tuple[str, str]]:
    """The figures as the rows of a table (label, value), as Sida computed them; a ratio with its limit where one holds."""
    def ratio(value, ordinance_key, legal_key):
        if value is None:
            return "미확인"
        g = diagrams.gauge(value, limits, ordinance_key, legal_key)
        return f"{value:,.1f}%" + (f" ({g['source']} {g['limit']:g}%)" if g["limit"] is not None else "")

    rows = [
        ("대지면적", f"{fig['site_area_m2']:,.1f}㎡" if fig["site_area_m2"] else "미확인"),
        ("건축면적", f"{fig['footprint_m2']:,.1f}㎡"),
        ("연면적", f"{fig['floor_area_m2']:,.1f}㎡"),
        *((f"  {part['word']}", f"{part['floor_area_m2']:,.1f}㎡") for part in fig["by_meaning"] if len(fig["by_meaning"]) > 1),
        ("건폐율", ratio(fig["coverage_pct"], "ordinance_bcr", "bcr_max")),
        ("용적률", ratio(fig["far_pct"], "ordinance_far", "far_max")),
    ]
    if fig["height_m"] is not None:
        rows.append(("최고 높이", f"{fig['height_m']:,.1f}m"))
    return rows


def default_slides(title: str, mats: dict) -> list[dict]:
    """A deck by rule, without sentences: the title, the figures, each diagram that can be drawn, each capture."""
    def slide(layout, heading, figure=""):
        return {"layout": layout, "title": heading, "subtitle": "", "bullets": [], "caption": "", "notes": "", "figure": figure}

    slides = [slide("title", title)]
    ready = [item for item in mats["items"].values() if item["ready"]]
    slides += [slide("figure", item["title"], item["key"]) for item in ready if item["kind"] == "figures"]
    slides += [slide("figure", item["title"], item["key"]) for item in ready if item["kind"] == "diagram"]
    slides += [slide("figure", item["title"], item["key"]) for item in ready if item["kind"] == "view"]
    return slides


def project_title(project_path: Path) -> str:
    """The project's name as the designer wrote it in the brief, else the folder's name."""
    path = Path(project_path)
    try:
        name = section_body((path / "brief.md").read_text(encoding="utf-8"), "Project Name")
    except OSError:
        name = ""
    return name if name and name != "-" else path.name


def deck(project_path: Path, document: str | None, mats: dict | None = None) -> dict:
    """
    The deck to show and to make files of: {source: "editor" | "default", title, slides, notes,
    snapshot}. Each slide's `figure` is None or the material it names ({key, kind, title, ready,
    why}); a key that names nothing known is kept unready, so the slide keeps its place.
    """
    path = Path(project_path)
    mats = materials(path) if mats is None else mats
    title = project_title(path)
    listed = read_block(document)
    slides, notes = clean(listed) if listed is not None else ([], [])
    source = "editor" if slides else "default"
    if not slides:
        slides = default_slides(title, mats)
    for number, slide in enumerate(slides, start=1):
        key = slide["figure"]
        if not key:
            slide["figure"] = None
            continue
        found = mats["items"].get(key)
        if found is None:
            found = {"key": key, "kind": key.split(":", 1)[0] if ":" in key else key, "title": key, "ready": False,
                     "why": "이 이름의 그림이 없습니다." if mats["snapshot"] is not None else "라이노 작업이 아직 없습니다. 라이노에서 Sida로 보내면 채워집니다."}
        slide["figure"] = {k: found[k] for k in ("key", "kind", "title", "ready", "why")}
        if not found["ready"]:
            notes.append(f"{number}번 슬라이드의 그림({found['title']})은 비어 있습니다. {found['why']}")
    saved = mats["snapshot"]
    return {"source": source, "title": title, "slides": slides, "notes": notes,
            "snapshot": None if saved is None else {"id": saved["id"], "taken_at": saved["taken_at"], "file": saved["rhino"]["file"]}}


def prompt_text(mats: dict) -> str:
    """What the presentation editor may put on slides, by key (the figures as lines, for its sentences)."""
    lines = ["## Slide Materials (made by Sida from the designer's Rhino model; refer to them by key, never describe numbers of your own)", ""]
    if mats["snapshot"] is None:
        lines.append("No Rhino snapshot has been sent yet, so there are no pictures or figures to place. "
                     "List text slides only and say in the document that the model has not been sent.")
        return "\n".join(lines)
    for item in mats["items"].values():
        state = "" if item["ready"] else f" (cannot be made now: {item['why']})"
        lines.append(f"- `{item['key']}`: {item['title']}{state}")
    limits = diagrams.limit_lines(mats["limits"])
    if limits:
        lines += ["", "The limits the ratios are set against (as the site facts have them):"] + [f"- {line}" for line in limits]
    return "\n".join(lines)
