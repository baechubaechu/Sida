#!/usr/bin/env python3
"""One-shot upgrades when opening an existing project folder.

- Rename legacy module files (01_site_reader.md → 11_site_reader.md, …)
- Rename matching stems under modules/_history/
- Ensure project_state.md Module Status has a row for every current expert
"""

from __future__ import annotations

import re
from pathlib import Path

# Old sequential filenames → current phase-grouped filenames (same expert ids).
LEGACY_MODULE_FILES: dict[str, str] = {
    "01_site_reader.md": "11_site_reader.md",
    "02_constraint_mapper.md": "31_constraint_mapper.md",
    "03_design_critic.md": "51_design_critic.md",
    "04_representation_planner.md": "61_representation_planner.md",
    "05_presentation_editor.md": "62_presentation_editor.md",
}

_ROW_RE = re.compile(r"^\|\s*([a-z0-9_]+)\s*\|", re.MULTILINE)
_TABLE_TAIL = re.compile(
    r"(^## Module Status\s*\n(?:.*\n)*?)(\n<!--|\n## |\Z)", re.MULTILINE
)


def rename_legacy_modules(modules_dir: Path) -> list[str]:
    """
    Rename known legacy module outputs in place.
    Skips if the new name already exists. Returns human notes (old → new).
    """
    if not modules_dir.is_dir():
        return []
    notes: list[str] = []
    for old_name, new_name in LEGACY_MODULE_FILES.items():
        old = modules_dir / old_name
        new = modules_dir / new_name
        if not old.exists():
            continue
        if new.exists():
            # Prefer the new file; keep the old one as an archive sibling.
            hist = modules_dir / "_history"
            hist.mkdir(parents=True, exist_ok=True)
            target = hist / f"{old.stem}.pre-rename{old.suffix}"
            counter = 1
            while target.exists():
                target = hist / f"{old.stem}.pre-rename-{counter}{old.suffix}"
                counter += 1
            old.replace(target)
            notes.append(f"{old_name} → _history/{target.name} (kept existing {new_name})")
            continue
        old.rename(new)
        notes.append(f"{old_name} → {new_name}")
    return notes


def rename_legacy_history(modules_dir: Path) -> list[str]:
    """Rename archived files whose stem starts with a legacy module stem."""
    hist = modules_dir / "_history"
    if not hist.is_dir():
        return []
    notes: list[str] = []
    for old_name, new_name in LEGACY_MODULE_FILES.items():
        old_stem = Path(old_name).stem
        new_stem = Path(new_name).stem
        for path in list(hist.glob(f"{old_stem}.*")):
            # e.g. 01_site_reader.20260101-120000.md → 11_site_reader.20260101-120000.md
            suffix = path.name[len(old_stem) :]
            target = hist / f"{new_stem}{suffix}"
            if target.exists():
                continue
            path.rename(target)
            notes.append(f"_history/{path.name} → {target.name}")
    return notes


def existing_module_ids(state_text: str) -> set[str]:
    section = re.search(
        r"^## Module Status\s*\n(.*?)(?=^## |\Z)", state_text, re.MULTILINE | re.DOTALL
    )
    if not section:
        return set()
    return {m.group(1) for m in _ROW_RE.finditer(section.group(1))}


def ensure_module_status_rows(state_text: str, agents: list[dict]) -> tuple[str, list[str]]:
    """
    Append missing Module Status rows for experts now in config.
    Does not alter existing rows (status / takeaway preserved).
    Returns (new_text, list of added agent ids).
    """
    wanted = [str(a["id"]) for a in agents if a.get("id")]
    if not wanted:
        return state_text, []
    present = existing_module_ids(state_text)
    missing = [aid for aid in wanted if aid not in present]
    if not missing:
        return state_text, []

    rows = "\n".join(f"| {aid} | pending | |" for aid in missing)
    m = _TABLE_TAIL.search(state_text)
    if m:
        block = m.group(1).rstrip("\n") + "\n" + rows + "\n"
        text = state_text[: m.start(1)] + block + state_text[m.end(1) :]
        return text, missing

    # No Module Status section — append a full table.
    table = (
        "\n## Module Status\n\n"
        "| Module | Status | Key takeaway |\n"
        "|--------|--------|--------------|\n"
        + "\n".join(f"| {aid} | pending | |" for aid in wanted)
        + "\n"
    )
    return state_text.rstrip() + "\n" + table, missing


def migrate_project(project, agents: list[dict] | None = None) -> list[str]:
    """
    Apply all upgrades for one project. Safe to call repeatedly.
    `project` needs `.modules_dir`, `.state_path`, and optionally `.init_state`.
    """
    notes: list[str] = []
    notes.extend(rename_legacy_modules(project.modules_dir))
    notes.extend(rename_legacy_history(project.modules_dir))

    if agents is None:
        try:
            from harness import get_agents, load_config

            agents = get_agents(load_config())
        except SystemExit:
            agents = []

    if not project.state_path.exists():
        if hasattr(project, "init_state"):
            project.init_state(agents=agents)
        return notes

    state = project.state_path.read_text(encoding="utf-8")
    new_state, added = ensure_module_status_rows(state, agents or [])
    if added:
        project.state_path.write_text(new_state, encoding="utf-8")
        notes.append("state Module Status + " + ", ".join(added))
    return notes
