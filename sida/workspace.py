#!/usr/bin/env python3
"""UI-agnostic project hub operations: list, look up and create projects.

Like engine.py, nothing here prints or reads input — front ends call these and
render the result.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sida.briefs import BRIEF_FIELD_KEYS, build_brief_markdown
from sida.config import ROOT, agent_by_id, agent_inputs, agent_tier, get_agents
from sida.engine import history_messages
from sida.i18n import agent_name
from sida.project import (
    MAIN_TALK,
    SESSION_FILE,
    Project,
    create_blank_project,
    create_project_from_brief,
    ensure_projects_root,
    is_project_dir,
    list_projects,
    replace_section,
    section_body,
    slugify,
)
from sida.project_documents import read_document, save_document
from sida.storage import atomic_write_text
from sida.worker import MODULE_HISTORY_DIRNAME

SAMPLE_BRIEF = ROOT / "data" / "briefs" / "sample_brief.md"


class ProjectNotFound(LookupError):
    pass


# How the designer keeps the project list: the chosen sort and the order the cards were dragged
# into (folder names), in the projects folder (not a project: it has no brief).
LIST_FILE = ".project_list.json"
LIST_SORTS = ("recent", "name", "custom")
LIST_MAX = 5000


def load_list_order(config: dict) -> dict:
    """{"sort", "order"}; a missing or unreadable file gives the default (recent, no order)."""
    try:
        data = json.loads((ensure_projects_root(config) / LIST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    order = data.get("order") if isinstance(data.get("order"), list) else []
    return {
        "sort": data.get("sort") if data.get("sort") in LIST_SORTS else "recent",
        "order": [name for name in order if isinstance(name, str)][:LIST_MAX],
    }


def save_list_order(config: dict, sort: str, order: list[str]) -> dict:
    """Keep the list's sort and custom order. Raises ValueError for an unknown sort."""
    if sort not in LIST_SORTS:
        raise ValueError(f"unknown sort: {sort}")
    names = list(dict.fromkeys(name for name in order if isinstance(name, str) and name.strip()))[:LIST_MAX]
    kept = {"sort": sort, "order": names}
    atomic_write_text(ensure_projects_root(config) / LIST_FILE, json.dumps(kept, ensure_ascii=False))
    return kept


# How the panels beside the drafting table are docked on this PC (webui/app/dock-model.js): each
# side's groups of tabs, which side is folded, and the side widths. The screen checks the panel
# names; here only the shape and the sizes are kept in bounds.
PANEL_LAYOUT_FILE = ".panel_layout.json"
PANEL_SIDES = ("left", "right")
PANEL_RATIOS = ("left", "right", "detail")
PANEL_MAX_GROUPS = 12
PANEL_MAX_TABS = 24


def _panel_name(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 40


def _clean_panel_layout(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    kept: dict = {}
    for name in PANEL_SIDES:
        side = data.get(name) if isinstance(data.get(name), dict) else {}
        groups = []
        for group in side.get("groups") if isinstance(side.get("groups"), list) else []:
            if not isinstance(group, dict) or not isinstance(group.get("tabs"), list):
                continue
            tabs = [tab for tab in group["tabs"] if _panel_name(tab)][:PANEL_MAX_TABS]
            if not tabs:
                continue
            size = group.get("size")
            size = float(size) if isinstance(size, (int, float)) and not isinstance(size, bool) and 0 < size <= 1000 else 1.0
            active = group.get("active") if group.get("active") in tabs else tabs[0]
            groups.append({"tabs": tabs, "active": active, "size": size})
        kept[name] = {"open": side.get("open") is not False, "groups": groups[:PANEL_MAX_GROUPS]}
    ratios = data.get("ratios") if isinstance(data.get("ratios"), dict) else {}
    kept["ratios"] = {
        key: float(value)
        for key, value in ratios.items()
        if key in PANEL_RATIOS and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 1
    }
    return kept


def load_panel_layout(config: dict) -> dict | None:
    """The kept layout, or None (never saved, or unreadable): the screen then uses its default."""
    try:
        data = json.loads((ensure_projects_root(config) / PANEL_LAYOUT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _clean_panel_layout(data)


def save_panel_layout(config: dict, layout: dict) -> dict:
    """Keep the layout. Raises ValueError for something that is not a layout."""
    kept = _clean_panel_layout(layout)
    if kept is None:
        raise ValueError("panel layout must be an object")
    atomic_write_text(ensure_projects_root(config) / PANEL_LAYOUT_FILE, json.dumps(kept, ensure_ascii=False))
    return kept


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
    visible = [a for a in agents if agent_tier(a) != "held"]
    return {
        "name": path.name,
        "display_name": section_body(brief, "Project Name") or path.name,
        "path": str(path),
        "updated_at": _updated_at(path),
        "project_type": "" if kind == "-" else kind,
        "completed": done,
        "expert_count": len(agents),
        "visible_expert_count": len(visible),
        "visible_completed": [str(a["id"]) for a in visible if str(a["id"]) in done],
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


def delete_project(config: dict, name: str) -> None:
    """Remove a project folder and everything in it. Raises ProjectNotFound; cannot be undone."""
    path = find_project(config, name)
    if path.is_symlink():  # a linked folder may live outside the projects folder; leave it alone
        raise ProjectNotFound(name)
    shutil.rmtree(path)


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


PROJECT_INFO_FIELDS = {
    "display_name": "Project Name", "type": "Project Type", "description": "Design Intention",
}


def project_info(config: dict, name: str) -> dict:
    """Editable labels in the brief; folder ids and saved project data stay stable."""
    doc = read_document(find_project(config, name), "brief")
    values = {key: section_body(doc.content, heading) for key, heading in PROJECT_INFO_FIELDS.items()}
    values = {key: "" if value == "-" else value for key, value in values.items()}
    return {**values, "display_name": values["display_name"] or name, "revision": doc.revision}


def update_project_info(config: dict, name: str, fields: dict[str, str], revision: str) -> dict:
    """Patch only the requested brief sections, preserving other Markdown and stale-edit checks."""
    if set(fields) - PROJECT_INFO_FIELDS.keys():
        raise ValueError("수정할 수 없는 프로젝트 정보입니다.")
    path = find_project(config, name)
    doc = read_document(path, "brief")
    content = doc.content
    for key, raw in fields.items():
        value = raw.strip()
        limit = 6000 if key == "description" else 80
        if len(value) > limit or (key == "display_name" and not value):
            raise ValueError(f"{'프로젝트 이름' if key == 'display_name' else '내용'}은 {'1~' if key == 'display_name' else ''}{limit}자 안에서 입력하세요.")
        if key != "description" and ("\n" in value or "\r" in value):
            raise ValueError("이름과 유형은 한 줄로 입력하세요.")
        if re.search(r"^#{1,2}\s", value, re.MULTILINE):
            raise ValueError("설명에는 문서 구분 제목(#, ##) 대신 일반 문장을 입력하세요.")
        content = replace_section(content, PROJECT_INFO_FIELDS[key], value or "-")
    save_document(path, "brief", content.rstrip() + "\n", expected_revision=revision)
    return project_info(config, name)


# ---------------------------------------------------------------------------
# Session screen: chat history and expert results, read without opening the project
# ---------------------------------------------------------------------------


def _modified_at(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")


def chat_messages(config: dict, path: Path, talk: str = MAIN_TALK) -> list[dict]:
    """A stored Conductor talk as chat entries; system entries name their expert."""
    agents = get_agents(config)
    by_output = {str(a["output"]): a for a in agents}
    stub = Project(
        path=path, name=path.name, session_id="", created_at="", source_brief=None, talk=talk
    )
    messages = history_messages(stub.load_history())
    for message in messages:
        if message["role"] != "system" or "agent" not in message:
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
            "tier": agent_tier(agent),
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
