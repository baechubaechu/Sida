#!/usr/bin/env python3
"""UI-agnostic project hub operations: list, look up and create projects.

Like engine.py, nothing here prints or reads input — front ends call these and
render the result.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sida.briefs import BRIEF_FIELD_KEYS, build_brief_markdown
from sida.config import ROOT, agent_by_id, agent_inputs, get_agents
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
from sida.worker import MODULE_HISTORY_DIRNAME

SAMPLE_BRIEF = ROOT / "data" / "briefs" / "sample_brief.md"


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
    Create a project from the basic brief fields (see briefs.BRIEF_FIELD_KEYS).
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
    """Create (or open) the project made from data/briefs/sample_brief.md. Returns (project, created)."""
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


def _input_ids(agent: dict, agents: list[dict]) -> list[str]:
    """Ids of the experts whose results this one reads (config `inputs`), in config order."""
    ids = [str(a["id"]) for a in agents]
    wanted = agent_inputs(agent)
    if wanted == "all":
        return [i for i in ids if i != agent["id"]]
    if wanted == "legacy":  # no `inputs` key: every expert before it
        return ids[:ids.index(str(agent["id"]))]
    return [i for i in ids if i in wanted and i != agent["id"]]


def expert_entries(config: dict, path: Path) -> list[dict]:
    """One row per expert for the side panel: name, phase, whether and when it last ran."""
    rows = []
    agents = get_agents(config)
    for agent in agents:
        output = path / "modules" / str(agent["output"])
        rows.append({
            "id": agent["id"],
            "name": agent_name(agent),
            "phase": agent.get("phase", ""),
            "done": output.exists(),
            "updated_at": _modified_at(output) if output.exists() else "",
            "chat": bool(agent.get("chat", True)),
            "inputs": _input_ids(agent, agents),
        })
    return rows


def _module_output(config: dict, name: str, agent_id: str) -> tuple[dict, Path]:
    path = find_project(config, name)
    agent = agent_by_id(get_agents(config), agent_id)
    if agent is None:
        raise LookupError(f"unknown expert: {agent_id}")
    return agent, path / "modules" / str(agent["output"])


def module_document(config: dict, name: str, agent_id: str) -> dict:
    """An expert's result document (Markdown). Raises LookupError if the expert or output is missing."""
    agent, output = _module_output(config, name, agent_id)
    if not output.is_file():
        raise LookupError(f"not run yet: {agent_id}")
    return {
        "agent": agent["id"],
        "name": agent_name(agent),
        "phase": agent.get("phase", ""),
        "content": output.read_text(encoding="utf-8"),
        "updated_at": _modified_at(output),
    }


# Earlier results kept by worker.archive_module_output as _history/<stem>.<YYYYmmdd-HHMMSS>[-n].md.
# The stamp is when that result was written, in this PC's local time.
_VERSION_ID = re.compile(r"(\d{8}-\d{6})(?:-(\d+))?")


def _version_files(output: Path) -> dict[str, Path]:
    history = output.parent / MODULE_HISTORY_DIRNAME
    prefix, suffix = f"{output.stem}.", output.suffix
    found = {}
    if history.is_dir():
        for file in history.iterdir():
            if not (file.is_file() and file.name.startswith(prefix) and file.name.endswith(suffix)):
                continue
            version = file.name[len(prefix):len(file.name) - len(suffix)]
            if _VERSION_ID.fullmatch(version) and _saved_at(version):
                found[version] = file
    return found


def _version_key(version: str) -> tuple[str, int]:
    stamp, counter = _VERSION_ID.fullmatch(version).groups()
    return stamp, int(counter or 0)


def _saved_at(version: str) -> str:
    try:
        return datetime.strptime(_version_key(version)[0], "%Y%m%d-%H%M%S").isoformat(timespec="seconds")
    except ValueError:  # not a real date: not a file the app wrote
        return ""


def module_versions(config: dict, name: str, agent_id: str) -> dict:
    """An expert's earlier results, newest first. The current result is module_document."""
    agent, output = _module_output(config, name, agent_id)
    versions = sorted(_version_files(output), key=_version_key, reverse=True)
    return {"agent": agent["id"], "versions": [{"id": v, "saved_at": _saved_at(v)} for v in versions]}


def module_version(config: dict, name: str, agent_id: str, version: str) -> dict:
    """One earlier result. Raises LookupError if the expert or that version is missing."""
    agent, output = _module_output(config, name, agent_id)
    file = _version_files(output).get(version)
    if file is None:
        raise LookupError(f"no such version: {version}")
    return {
        "agent": agent["id"],
        "id": version,
        "saved_at": _saved_at(version),
        "content": file.read_text(encoding="utf-8"),
    }
