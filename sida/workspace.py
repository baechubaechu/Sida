#!/usr/bin/env python3
"""UI-agnostic project hub operations: list, look up and create projects.

Like engine.py, nothing here prints or reads input — front ends call these and
render the result. (The terminal hub in hub.py predates this and keeps its own flow.)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sida.briefs import BRIEF_FIELD_HEADINGS, build_brief_markdown
from sida.config import ROOT, agent_by_id, get_agents
from sida.engine import history_messages
from sida.i18n import agent_name
from sida.project import (
    SESSION_FILE,
    Project,
    create_blank_project,
    create_project_from_brief,
    ensure_projects_root,
    is_project_dir,
    list_projects,
    section_body,
    slugify,
)

SAMPLE_BRIEF = ROOT / "input" / "sample_brief.md"
BRIEF_FIELD_KEYS = tuple(key for key, _label, _heading in BRIEF_FIELD_HEADINGS)


class ProjectNotFound(LookupError):
    pass


def _updated_at(path: Path) -> str:
    try:
        data = json.loads((path / SESSION_FILE).read_text(encoding="utf-8"))
        return str(data.get("updated_at") or "")
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""


def project_summary(path: Path, agents: list[dict]) -> dict:
    """What a project list needs, read without opening (and so without touching) the project."""
    try:
        brief = (path / "brief.md").read_text(encoding="utf-8")
    except OSError:
        brief = ""
    kind = section_body(brief, "Project Type")
    done = [str(a["id"]) for a in agents if (path / "modules" / str(a["output"])).exists()]
    return {
        "name": path.name,
        "path": str(path),
        "updated_at": _updated_at(path),
        "project_type": "" if kind == "-" else kind,
        "completed": done,
        "expert_count": len(agents),
    }


def list_project_summaries(config: dict) -> list[dict]:
    """Every project, most recently updated first."""
    agents = get_agents(config)
    return [project_summary(path, agents) for path in list_projects(config)]


def find_project(config: dict, name: str) -> Path:
    """Folder of an existing project, by its exact folder name. Raises ProjectNotFound."""
    root = ensure_projects_root(config)
    # A name is one path segment; anything else could point outside the projects folder.
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ProjectNotFound(name)
    path = root / name
    if not is_project_dir(path):
        raise ProjectNotFound(name)
    return path


def create_project(config: dict, name: str, fields: dict[str, str] | None = None) -> tuple[Project, bool]:
    """
    Create a project from the basic brief fields (see briefs.BRIEF_FIELD_HEADINGS).
    If a project with that name already exists it is opened instead.
    Returns (project, created). Raises ValueError for an empty name.
    """
    if not (name or "").strip():
        raise ValueError("project name is empty")
    root = ensure_projects_root(config)
    existed = is_project_dir(root / slugify(name))
    clean = {key: str((fields or {}).get(key) or "").strip() for key in BRIEF_FIELD_KEYS}
    project = create_blank_project(name, config=config, brief_text=build_brief_markdown(clean))
    return project, not existed


def create_sample_project(config: dict) -> tuple[Project, bool]:
    """Create (or open) the project made from input/sample_brief.md. Returns (project, created)."""
    root = ensure_projects_root(config)
    existed = is_project_dir(root / slugify(SAMPLE_BRIEF.stem))
    project = create_project_from_brief(SAMPLE_BRIEF, config=config)
    return project, not existed


# ---------------------------------------------------------------------------
# Session screen: chat history and expert results, read without opening the project
# ---------------------------------------------------------------------------


def _modified_at(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")


def chat_messages(config: dict, path: Path) -> list[dict]:
    """The stored Conductor conversation as chat entries; system entries name their expert."""
    agents = get_agents(config)
    by_output = {str(a["output"]): a for a in agents}
    stub = Project(path=path, name=path.name, session_id="", created_at="", source_brief=None)
    messages = history_messages(stub.load_history())
    for message in messages:
        if message["role"] != "system":
            continue
        if message["event"] == "read":
            agent = by_output.get(message["agent"])
        else:
            agent = agent_by_id(agents, message["agent"])
        if agent is not None:
            message["agent"] = agent["id"]
            message["name"] = agent_name(agent)
    return messages


def expert_entries(config: dict, path: Path) -> list[dict]:
    """One row per expert for the side panel: name, phase, whether and when it last ran."""
    rows = []
    for agent in get_agents(config):
        output = path / "modules" / str(agent["output"])
        rows.append({
            "id": agent["id"],
            "name": agent_name(agent),
            "phase": agent.get("phase", ""),
            "done": output.exists(),
            "updated_at": _modified_at(output) if output.exists() else "",
        })
    return rows


def module_document(config: dict, name: str, agent_id: str) -> dict:
    """An expert's result document (Markdown). Raises LookupError if the expert or output is missing."""
    path = find_project(config, name)
    agent = agent_by_id(get_agents(config), agent_id)
    if agent is None:
        raise LookupError(f"unknown expert: {agent_id}")
    output = path / "modules" / str(agent["output"])
    if not output.is_file():
        raise LookupError(f"not run yet: {agent_id}")
    return {
        "agent": agent["id"],
        "name": agent_name(agent),
        "phase": agent.get("phase", ""),
        "content": output.read_text(encoding="utf-8"),
        "updated_at": _modified_at(output),
    }
