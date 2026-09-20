#!/usr/bin/env python3
"""Project workspace helpers — one folder per design session."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness import ROOT, fail, load_config

SESSION_FILE = "session.json"
BRIEF_FILE = "brief.md"
STATE_FILE = "project_state.md"
TRANSCRIPT_FILE = "transcript.md"
HISTORY_FILE = "history.json"
MODULES_DIRNAME = "modules"
STATE_TEMPLATE_PATH = ROOT / "templates" / "project_state.md"
DEFAULT_PROJECTS_DIR = Path.home() / "Sida" / "projects"


def _slugify(name: str) -> str:
    text = name.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "_", text)
    text = text.strip("_")
    return text or f"project_{uuid.uuid4().hex[:8]}"


def slugify(name: str) -> str:
    return _slugify(name)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def module_status_rows(agents: list[dict] | None = None) -> str:
    """`| id | pending | |` rows for every expert in config, grouped as configured."""
    if agents is None:
        try:
            from harness import get_agents

            agents = get_agents(load_config())
        except SystemExit:
            agents = []
    rows = [f"| {a.get('id')} | pending | |" for a in (agents or []) if a.get("id")]
    return "\n".join(rows) if rows else "| (no experts configured) | | |"


def _replace_section(text: str, heading: str, body: str) -> str:
    """
    Replace the body under `## {heading}` (up to the next `## ` or `# ` line).
    If the section does not exist, append it at the end.
    """
    pattern = re.compile(
        rf"(^## {re.escape(heading)}\s*\n)(.*?)(?=^#{{1,2}} |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    replacement_body = body.strip() + "\n\n"
    if match:
        return text[: match.start(2)] + replacement_body + text[match.end(2):]
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return f"{text}{sep}## {heading}\n{replacement_body}"


def section_body(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*\n(.*?)(?=^#{{1,2}} |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def resolve_projects_dir(config: dict | None = None) -> Path:
    """User-facing projects root. Default: ~/Sida/projects"""
    if config is None:
        try:
            config = load_config()
        except SystemExit:
            config = {}

    raw = (config or {}).get("projects_dir") or str(DEFAULT_PROJECTS_DIR)
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    else:
        path = path.resolve()
    return path


def projects_dir() -> Path:
    return resolve_projects_dir()


@dataclass
class Project:
    path: Path
    name: str
    session_id: str
    created_at: str
    source_brief: str | None

    @property
    def brief_path(self) -> Path:
        return self.path / BRIEF_FILE

    @property
    def modules_dir(self) -> Path:
        return self.path / MODULES_DIRNAME

    @property
    def session_path(self) -> Path:
        return self.path / SESSION_FILE

    @property
    def transcript_path(self) -> Path:
        return self.path / TRANSCRIPT_FILE

    @property
    def history_path(self) -> Path:
        return self.path / HISTORY_FILE

    @property
    def state_path(self) -> Path:
        return self.path / STATE_FILE

    def read_brief(self) -> str:
        if not self.brief_path.exists():
            fail(f"Missing brief in project: {self.brief_path}")
        return self.brief_path.read_text(encoding="utf-8")

    def read_state(self) -> str | None:
        if not self.state_path.exists():
            return None
        text = self.state_path.read_text(encoding="utf-8").strip()
        return text or None

    def read_module(self, output_name: str) -> str | None:
        path = self.modules_dir / output_name
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8").strip()
        return text or None

    def update_brief_sections(self, updates: dict[str, str]) -> str:
        """
        Replace only the given `## Section` bodies in brief.md.
        Unknown sections and any extra content are preserved. Empty values are ignored.
        Returns the new brief text.
        """
        current = self.read_brief()
        backup = self.path / "brief.prev.md"
        backup.write_text(current, encoding="utf-8")

        text = current
        for heading, body in updates.items():
            body = body.strip()
            if not body:
                continue
            text = _replace_section(text, heading, body)
        self.brief_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        return text

    def updated_at(self) -> str:
        if self.session_path.exists():
            try:
                data = json.loads(self.session_path.read_text(encoding="utf-8"))
                return str(data.get("updated_at") or "")
            except (json.JSONDecodeError, OSError):
                pass
        return ""

    def init_state(self, *, force: bool = False, agents: list[dict] | None = None) -> None:
        """Create project_state.md from template if missing.

        The Module Status table is generated from config agents so new experts
        appear automatically.
        """
        if self.state_path.exists() and not force:
            return
        if STATE_TEMPLATE_PATH.exists():
            template = STATE_TEMPLATE_PATH.read_text(encoding="utf-8")
        else:
            template = (
                "# Project State\n\n## Meta\n\n- **Project**:\n\n"
                "## Module Status\n\n| Module | Status | Key takeaway |\n"
                "|--------|--------|--------------|\n{{MODULE_ROWS}}\n"
            )
        content = template.replace("- **Project**:", f"- **Project**: {self.name}", 1)
        content = content.replace("{{MODULE_ROWS}}", module_status_rows(agents))
        self.state_path.write_text(content, encoding="utf-8")

    def load_history(self) -> list[dict]:
        """Load Conductor chat history (user/assistant turns only)."""
        if not self.history_path.exists():
            return []
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        history: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                history.append({"role": role, "content": content})
        return history

    def save_history(self, history: list[dict]) -> None:
        """Persist Conductor chat history so Ctrl+C / resume keeps the conversation."""
        clean: list[dict] = []
        for item in history:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                clean.append({"role": role, "content": content})
        self.history_path.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def save_session(self, **extra: object) -> None:
        data = {
            "name": self.name,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": _utc_now(),
            "source_brief": self.source_brief,
            "path": str(self.path),
        }
        data.update(extra)
        self.session_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def append_transcript(self, role: str, text: str) -> None:
        stamp = _utc_now()
        block = f"### {role} ({stamp})\n\n{text.strip()}\n\n"
        with self.transcript_path.open("a", encoding="utf-8") as f:
            f.write(block)

    def rename(self, new_name: str, config: dict | None = None) -> None:
        """Rename project folder and update session metadata. Can be done anytime."""
        new_slug = slugify(new_name)
        if not new_slug:
            raise ValueError("New project name is empty")
        if new_slug == self.name and self.path.name == new_slug:
            return

        root = ensure_projects_root(config)
        new_path = root / new_slug
        if new_path.exists():
            raise ValueError(f"A project named '{new_slug}' already exists")

        old_path = self.path
        old_name = self.name
        old_path.rename(new_path)
        self.path = new_path
        self.name = new_slug
        self.save_session(renamed_from=old_name, previous_path=str(old_path))


def ensure_projects_root(config: dict | None = None) -> Path:
    root = resolve_projects_dir(config)
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_project_dir(path: Path) -> bool:
    return path.is_dir() and (path / BRIEF_FILE).exists()


def load_project(path: Path) -> Project:
    path = path.resolve()
    if not is_project_dir(path):
        fail(
            f"Not a project folder (missing {BRIEF_FILE}): {path}\n"
            f"Create one with: python chat.py input/your_brief.md"
        )

    session_id = f"sida-{path.name}-{uuid.uuid4().hex[:8]}"
    created_at = _utc_now()
    source_brief = None

    session_path = path / SESSION_FILE
    if session_path.exists():
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
            session_id = str(data.get("session_id") or session_id)
            created_at = str(data.get("created_at") or created_at)
            source_brief = data.get("source_brief")
        except (json.JSONDecodeError, OSError):
            pass

    project = Project(
        path=path,
        name=path.name,
        session_id=session_id,
        created_at=created_at,
        source_brief=str(source_brief) if source_brief else None,
    )
    project.modules_dir.mkdir(parents=True, exist_ok=True)
    if not project.transcript_path.exists():
        project.transcript_path.write_text(
            f"# Transcript — {project.name}\n\n", encoding="utf-8"
        )
    project.init_state()
    _run_migrations(project)
    project.save_session(resumed_at=_utc_now())
    return project


def _run_migrations(project: Project) -> None:
    """Rename legacy module files and sync Module Status rows. Prints notes once."""
    from migrate import migrate_project

    try:
        from harness import get_agents

        agents = get_agents(load_config())
    except SystemExit:
        agents = []
    notes = migrate_project(project, agents)
    if not notes:
        return
    try:
        from i18n import t

        print(t("migrate_applied", n=len(notes)))
        for note in notes:
            print(f"  · {note}")
    except Exception:
        for note in notes:
            print(f"[migrate] {note}")


def create_project_from_brief(
    brief_path: Path,
    name: str | None = None,
    config: dict | None = None,
) -> Project:
    brief_path = brief_path.resolve()
    if not brief_path.exists():
        fail(f"Missing input file: {brief_path}")

    root = ensure_projects_root(config)
    project_name = _slugify(name or brief_path.stem)
    project_path = root / project_name

    if project_path.exists():
        return load_project(project_path)

    project_path.mkdir(parents=True, exist_ok=False)
    (project_path / MODULES_DIRNAME).mkdir(parents=True, exist_ok=True)

    shutil.copy2(brief_path, project_path / BRIEF_FILE)

    session_id = f"sida-{project_name}-{uuid.uuid4().hex[:8]}"
    created_at = _utc_now()
    try:
        source = str(brief_path.relative_to(ROOT))
    except ValueError:
        source = str(brief_path)

    project = Project(
        path=project_path,
        name=project_name,
        session_id=session_id,
        created_at=created_at,
        source_brief=source,
    )
    project.transcript_path.write_text(
        f"# Transcript — {project.name}\n\n", encoding="utf-8"
    )
    project.init_state()
    project.save_session()
    return project


EMPTY_BRIEF_TEMPLATE = """# Project Brief

## Project Type
-

## Site
-

## Core Problem
-

## Site Issues
-

## Design Intention
-

## Current Design Direction
-
"""


def create_blank_project(
    name: str,
    config: dict | None = None,
    brief_text: str | None = None,
) -> Project:
    """Create a project with an empty (or provided) brief — no chat required."""
    root = ensure_projects_root(config)
    project_name = _slugify(name)
    if not project_name:
        fail("Project name is empty")
    project_path = root / project_name
    if project_path.exists():
        return load_project(project_path)

    project_path.mkdir(parents=True, exist_ok=False)
    (project_path / MODULES_DIRNAME).mkdir(parents=True, exist_ok=True)
    (project_path / BRIEF_FILE).write_text(
        (brief_text or EMPTY_BRIEF_TEMPLATE).strip() + "\n",
        encoding="utf-8",
    )

    session_id = f"sida-{project_name}-{uuid.uuid4().hex[:8]}"
    project = Project(
        path=project_path,
        name=project_name,
        session_id=session_id,
        created_at=_utc_now(),
        source_brief=None,
    )
    project.transcript_path.write_text(
        f"# Transcript — {project.name}\n\n", encoding="utf-8"
    )
    project.init_state()
    project.save_history([])
    project.save_session()
    return project


def open_or_create(
    target: Path,
    name: str | None = None,
    config: dict | None = None,
) -> tuple[Project, bool]:
    """
    Open a project folder, or create one from a brief markdown file.
    Returns (project, created_new).
    """
    root = ensure_projects_root(config)
    target = Path(target)

    if not target.is_absolute():
        as_repo = (ROOT / target).resolve()
        as_home = (root / target).resolve()
        as_home_named = (root / target.name).resolve()

        if target.suffix.lower() in {".md", ".markdown"}:
            target = as_repo if as_repo.exists() else target.resolve()
        elif is_project_dir(as_home):
            target = as_home
        elif is_project_dir(as_home_named):
            target = as_home_named
        elif as_repo.exists():
            target = as_repo
        elif as_home.exists():
            target = as_home
        else:
            target = as_repo

    if is_project_dir(target):
        return load_project(target), False

    if target.is_dir():
        fail(
            f"Folder exists but is not a project (missing {BRIEF_FILE}): {target}"
        )

    if target.suffix.lower() in {".md", ".markdown"} or target.exists():
        project_name = _slugify(name or target.stem)
        project_path = root / project_name
        if project_path.exists():
            return load_project(project_path), False
        return create_project_from_brief(target, name=name, config=config), True

    fail(f"Cannot open project or brief: {target}")


def _project_sort_key(path: Path) -> tuple[str, str]:
    session_path = path / SESSION_FILE
    stamp = ""
    if session_path.exists():
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
            stamp = str(data.get("updated_at") or "")
        except (json.JSONDecodeError, OSError):
            stamp = ""
    if not stamp:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    return (stamp, path.name)


def list_projects(config: dict | None = None) -> list[Path]:
    """Most recently updated first."""
    root = ensure_projects_root(config)
    return sorted(
        [p for p in root.iterdir() if is_project_dir(p)],
        key=_project_sort_key,
        reverse=True,
    )
