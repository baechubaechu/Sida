#!/usr/bin/env python3
"""Brief (brief.md) authoring helpers: guided fields and editor-based editing."""

from __future__ import annotations

from pathlib import Path

from console import one_line, open_in_editor, prompt_line
from i18n import t
from project import section_body

# (field key, i18n label key, markdown heading)
BRIEF_FIELD_HEADINGS: list[tuple[str, str, str]] = [
    ("type", "brief_type", "Project Type"),
    ("site", "brief_site", "Site"),
    ("problem", "brief_problem", "Core Problem"),
    ("issues", "brief_issues", "Site Issues"),
    ("intention", "brief_intention", "Design Intention"),
    ("direction", "brief_direction", "Current Design Direction"),
    ("driver", "brief_driver", "Primary Driver"),
]

DRIVER_ALIASES = {
    "site": "site", "사이트": "site", "대지": "site",
    "idea": "idea", "아이디어": "idea", "개념": "idea", "concept": "idea",
    "program": "program", "프로그램": "program",
    "regulation": "regulation", "법규": "regulation", "code": "regulation", "규제": "regulation",
    "competition": "competition", "공모": "competition", "review": "competition", "발표": "competition",
}


def normalize_driver(raw: str) -> str:
    """Map free text to one of site | idea | program | regulation | competition (or keep raw)."""
    key = raw.strip().lower()
    return DRIVER_ALIASES.get(key, raw.strip())


def _issues_to_bullets(raw: str) -> str:
    items = [p.strip() for p in raw.split(",") if p.strip()]
    return "\n".join(f"- {item}" for item in items) if items else "-"


def build_brief_markdown(fields: dict[str, str]) -> str:
    def val(key: str) -> str:
        text = fields.get(key, "").strip()
        return text if text else "-"

    return f"""# Project Brief

## Project Type
{val("type")}

## Site
{val("site")}

## Core Problem
{val("problem")}

## Site Issues
{_issues_to_bullets(fields.get("issues", ""))}

## Design Intention
{val("intention")}

## Current Design Direction
{val("direction")}

## Primary Driver
{normalize_driver(fields.get("driver", "")) or "-"}
"""


def _print_title(key: str) -> None:
    print()
    print("=" * 40)
    print(f"  {t(key)}")
    print("=" * 40)


def collect_basic_brief() -> str | None:
    """Ask for all basic brief fields (new project). Returns markdown or None if cancelled."""
    _print_title("brief_title")
    print(t("brief_intro"))
    print()

    fields: dict[str, str] = {}
    for key, label_key, _heading in BRIEF_FIELD_HEADINGS:
        value = prompt_line(t(label_key))
        if value is None:
            return None
        fields[key] = value
    return build_brief_markdown(fields)


def collect_brief_updates(current_brief: str) -> dict[str, str] | None:
    """
    Ask for the basic brief fields, showing current values.
    Enter keeps the existing text. Returns {heading: new_body} for changed
    fields only, or None if cancelled. Other brief sections are untouched.
    """
    _print_title("brief_title")
    print(t("brief_fields_intro"))
    print()

    updates: dict[str, str] = {}
    for key, label_key, heading in BRIEF_FIELD_HEADINGS:
        current = section_body(current_brief, heading)
        if current and current != "-":
            print(t("brief_current", value=one_line(current)))
        value = prompt_line(t(label_key))
        if value is None:
            return None
        if not value:
            continue
        if key == "issues":
            updates[heading] = _issues_to_bullets(value)
        elif key == "driver":
            updates[heading] = normalize_driver(value)
        else:
            updates[heading] = value
    return updates


def edit_file_in_editor(path: Path, *, backup: Path | None = None) -> bool:
    """
    Open a project file in the user's editor. Writes `backup` first when given.
    Prints status lines. Returns True if the file changed.
    """
    if backup is not None and path.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        from console import resolve_editor

        argv = resolve_editor()
        if not argv:
            raise RuntimeError("no editor found")
        print(t("editor_opening", file=path.name, editor=argv[0]))
        changed, _ = open_in_editor(path, editor=argv)
    except RuntimeError as exc:
        print(t("editor_failed", reason=str(exc), path=str(path)))
        return False
    if changed:
        print(t("editor_saved", path=str(path)))
        if backup is not None:
            print(t("brief_backup", path=str(backup)))
    else:
        print(t("editor_unchanged"))
    return changed
