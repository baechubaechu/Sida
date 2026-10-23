#!/usr/bin/env python3
"""Propose and apply project_state.md updates after a module run.

Flow: module output + current state → one JSON-only model call → structured patch
→ diff preview → user approval (ask) or direct apply (auto). Never rewrites the whole
file; only the Module Status row, Meta lines, and listed bullet sections change.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sida.project import Project
from sida.providers import LLMError
from sida.runtime import (
    conductor_provider,
    resolve_conductor_runtime,
    resolve_worker_runtime,
    worker_provider,
)
from sida.state_revisions import preserve_revisions, record_module_revision, without_revisions
from sida.storage import atomic_write_text

# Sections the model may replace, with their bullet caps (mirrors template comments).
SECTION_CAPS: dict[str, int] = {
    "Core Problem": 3,
    "Current Direction": 5,
    "Confirmed Decisions": 8,
    "Open Questions": 6,
    "Tensions": 4,
    "Missing Information": 6,
    "Recent Notes": 5,
    "Next Focus": 3,
}
STATUS_VALUES = ("pending", "in_progress", "done", "stale")
MODULE_CHAR_LIMIT = 9000


@dataclass
class StatePatch:
    module_id: str
    status: str = "done"
    key_takeaway: str = ""
    meta: dict[str, str] = field(default_factory=dict)  # phase / active_focus
    sections: dict[str, list[str]] = field(default_factory=dict)
    # Captured by orchestration, never supplied by the model.
    base_state: str = ""
    base_brief: str = ""
    module_output: str = ""

    def is_empty(self) -> bool:
        return not (self.key_takeaway or self.meta or self.sections)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def state_update_settings(config: dict) -> dict:
    cfg = dict(config.get("state_update") or {})
    mode = str(cfg.get("mode", "ask")).lower()
    if mode not in {"ask", "auto", "off"}:
        mode = "ask"
    which = str(cfg.get("provider", "worker")).lower()
    if which not in {"worker", "conductor"}:
        which = "worker"
    return {
        "mode": mode,
        "provider": which,
        "max_tokens": int(cfg.get("max_tokens", 900)),
        "temperature": float(cfg.get("temperature", 0.2)),
    }


def _pick_provider(config: dict, api_key: str, settings: dict, *, c_provider=None, w_provider=None):
    if settings["provider"] == "conductor":
        rt = resolve_conductor_runtime(config)
        return (c_provider or conductor_provider(config, api_key)), rt["model"]
    rt = resolve_worker_runtime(config)
    return (w_provider or worker_provider(config, api_key)), rt["model"]


# ---------------------------------------------------------------------------
# Prompt + parse
# ---------------------------------------------------------------------------


def build_state_update_messages(
    state_text: str, module_id: str, module_name: str, module_output: str, *, lang: str
) -> list[dict]:
    caps = "\n".join(f"- {k}: max {v} bullets" for k, v in SECTION_CAPS.items())
    lang_rule = (
        "Write all bullet text and the key takeaway in Korean."
        if lang == "ko"
        else "Write all bullet text and the key takeaway in English."
    )
    system = (
        "You maintain a compact project memory file (PROJECT STATE) for an architectural "
        "design project. A specialist module just finished. Propose the minimal update.\n\n"
        "Output JSON only, no prose, no code fence. Schema:\n"
        "{\n"
        '  "module_status": {"status": "done" | "stale" | "in_progress", "key_takeaway": "<one line, <=120 chars>"},\n'
        '  "meta": {"phase": "<optional>", "active_focus": "<optional one line>"},\n'
        '  "sections": {"<Section Name>": ["<bullet>", ...], ...}\n'
        "}\n\n"
        "Rules:\n"
        "- `sections` values REPLACE the whole bullet list of that section. Include a section "
        "only if it should change; carry over existing bullets that are still valid.\n"
        "- Synthesis only. Never paste module text. One line per bullet, no sub-bullets.\n"
        "- Do not touch sections that the module output does not inform.\n"
        "- Respect caps; when full, merge or drop the least important item.\n"
        f"{caps}\n"
        "- Recent Notes is a rolling log: keep the newest items, prefix new ones with today's date.\n"
        "- Module Status is handled via module_status; do not include it in sections.\n"
        f"- {lang_rule}"
    )
    output = module_output.strip()
    if len(output) > MODULE_CHAR_LIMIT:
        output = output[:MODULE_CHAR_LIMIT] + "\n\n[... truncated ...]"
    user = (
        f"TODAY: {date.today().isoformat()}\n"
        f"MODULE ID: {module_id}\n"
        f"MODULE NAME: {module_name}\n\n"
        f"CURRENT PROJECT STATE:\n\n{state_text.strip()}\n\n"
        f"NEW MODULE OUTPUT:\n\n{output}\n\n"
        "JSON:"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _clean_bullets(items: Any, cap: int) -> list[str]:
    out: list[str] = []
    if not isinstance(items, list):
        return out
    for item in items:
        text = " ".join(str(item).split()).strip()
        text = re.sub(r"^[-*•]\s*", "", text)
        if text and text not in out:
            out.append(text)
    return out[:cap]


def parse_state_patch(raw: str, module_id: str) -> StatePatch:
    """Tolerant parse: fences, leading prose, bad keys → dropped; never raises."""
    text = raw.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return StatePatch(module_id=module_id, status="done")
    if not isinstance(data, dict):
        return StatePatch(module_id=module_id, status="done")

    patch = StatePatch(module_id=module_id)
    ms = data.get("module_status")
    if isinstance(ms, dict):
        status = str(ms.get("status", "done")).lower()
        patch.status = status if status in STATUS_VALUES else "done"
        patch.key_takeaway = " ".join(str(ms.get("key_takeaway", "")).split())[:160]

    meta = data.get("meta")
    if isinstance(meta, dict):
        for key in ("phase", "active_focus"):
            val = " ".join(str(meta.get(key, "")).split())
            if val:
                patch.meta[key] = val[:160]

    sections = data.get("sections")
    if isinstance(sections, dict):
        for heading, items in sections.items():
            canonical = _canonical_heading(str(heading))
            if canonical is None:
                continue
            bullets = _clean_bullets(items, SECTION_CAPS[canonical])
            if bullets:
                patch.sections[canonical] = bullets
    return patch


def _canonical_heading(name: str) -> str | None:
    key = name.strip().lower().replace("_", " ")
    for heading in SECTION_CAPS:
        if heading.lower() == key:
            return heading
    return None


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def replace_section_bullets(text: str, heading: str, bullets: list[str]) -> str:
    """Replace a section's bullets while keeping its leading <!-- guidance --> comment."""
    pattern = re.compile(
        rf"(^## {re.escape(heading)}\s*\n)(.*?)(?=^#{{1,2}} |\Z)", re.MULTILINE | re.DOTALL
    )
    m = pattern.search(text)
    body_lines = "\n".join(f"- {b}" for b in bullets) if bullets else "-"
    if not m:
        sep = "" if text.endswith("\n\n") else "\n"
        return f"{text}{sep}\n## {heading}\n\n{body_lines}\n"
    old_body = m.group(2)
    comment = ""
    cm = re.match(r"\s*(<!--.*?-->)\s*", old_body, re.DOTALL)
    if cm:
        comment = cm.group(1) + "\n\n"
    head = text[: m.start(2)].rstrip("\n") + "\n\n"
    return f"{head}{comment}{body_lines}\n\n{text[m.end(2):]}"


def update_module_row(text: str, module_id: str, status: str, takeaway: str) -> str:
    takeaway = takeaway.replace("|", "/").strip()
    cell = f" {takeaway} " if takeaway else " "
    row = f"| {module_id} | {status} |{cell}|"
    pattern = re.compile(rf"^\|\s*{re.escape(module_id)}\s*\|.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _match: row, text, count=1)
    # Append to the Module Status table if the row is missing.
    table = re.search(r"(^## Module Status\s*\n(?:.*\n)*?)(\n<!--|\n## |\Z)", text, re.MULTILINE)
    if table:
        block = table.group(1).rstrip("\n") + "\n" + row + "\n"
        return text[: table.start(1)] + block + text[table.end(1) :]
    return text


def update_meta_line(text: str, label: str, value: str) -> str:
    pattern = re.compile(rf"^(- \*\*{re.escape(label)}\*\*:)(.*)$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda m: f"{m.group(1)} {value}", text, count=1)
    return text


def apply_patch(state_text: str, patch: StatePatch, *, today: str | None = None) -> str:
    today = today or date.today().isoformat()
    text = state_text
    text = update_module_row(text, patch.module_id, patch.status, patch.key_takeaway)
    text = update_meta_line(text, "Last updated", today)
    if patch.meta.get("phase"):
        text = update_meta_line(text, "Phase", patch.meta["phase"])
    if patch.meta.get("active_focus"):
        text = update_meta_line(text, "Active focus", patch.meta["active_focus"])
    for heading, bullets in patch.sections.items():
        text = replace_section_bullets(text, heading, bullets)
    return text.rstrip() + "\n"


def state_diff(old: str, new: str) -> str:
    lines = difflib.unified_diff(
        without_revisions(old).splitlines(), without_revisions(new).splitlines(),
        fromfile="project_state.md", tofile="proposed", lineterm="", n=1
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Readable changes (for the approval card)
# ---------------------------------------------------------------------------

# Meta fields left out of the change list: Last updated changes on every run.
_QUIET_META = {"Last updated"}
_OPTION_LIST = re.compile(r"[a-z_]+(?:\s*\|\s*[a-z_]+)+")


def _plain(value: str) -> str:
    """A value without template guidance: comments, option lists, and date masks are empty."""
    value = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL).strip()
    if value in {"-", "YYYY-MM-DD"} or _OPTION_LIST.fullmatch(value):
        return ""
    return value


def _state_parts(text: str) -> tuple[list[str], dict[str, str], dict[str, tuple[str, str]], dict[str, list[str]]]:
    """(headings in order, meta fields, module rows {id: (status, takeaway)}, other sections {heading: items})."""
    text = re.sub(r"<!--.*?-->", "", without_revisions(text), flags=re.DOTALL)
    meta: dict[str, str] = {}
    modules: dict[str, tuple[str, str]] = {}
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        heading, _, body = block.partition("\n")
        heading = heading.strip()
        order.append(heading)
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if heading == "Meta":
            for line in lines:
                m = re.match(r"-\s*\*\*(.+?)\*\*:(.*)$", line)
                if m:
                    meta[m.group(1).strip()] = _plain(m.group(2))
        elif heading == "Module Status":
            for line in lines:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) < 2 or cells[0] in {"", "Module"} or set(cells[0]) <= set("-: "):
                    continue
                modules[cells[0]] = (cells[1], _plain(cells[2]) if len(cells) > 2 else "")
        else:
            items = [_plain(re.sub(r"^[-*]\s*", "", line)) for line in lines]
            sections[heading] = [item for item in items if item]
    return order, meta, modules, sections


def state_changes(old: str, new: str) -> list[dict]:
    """
    What a proposal changes, per "## " section, in the order of the new state.
    Meta and Module Status give {"section", "fields": [{"name", "before", "after", ...}]}
    (a module field also has "takeaway" when its key takeaway changed); bullet sections give
    {"section", "added": [...], "removed": [...]}. Template placeholders count as empty.
    """
    old_order, old_meta, old_modules, old_sections = _state_parts(old)
    order, new_meta, new_modules, new_sections = _state_parts(new)
    changes: list[dict] = []
    for heading in order + [h for h in old_order if h not in order]:
        if heading == "Meta":
            fields = [
                {"name": name, "before": old_meta.get(name, ""), "after": value}
                for name, value in new_meta.items()
                if name not in _QUIET_META and value != old_meta.get(name, "")
            ]
        elif heading == "Module Status":
            fields = []
            for module_id, (status, takeaway) in new_modules.items():
                old_status, old_takeaway = old_modules.get(module_id, ("", ""))
                if (status, takeaway) == (old_status, old_takeaway):
                    continue
                row = {"name": module_id, "before": old_status, "after": status}
                if takeaway != old_takeaway:
                    row["takeaway"] = takeaway
                fields.append(row)
        else:
            before, after = old_sections.get(heading, []), new_sections.get(heading, [])
            added = [item for item in after if item not in before]
            removed = [item for item in before if item not in after]
            if added or removed:
                changes.append({"section": heading, "added": added, "removed": removed})
            continue
        if fields:
            changes.append({"section": heading, "fields": fields})
    return changes


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def propose_state_patch(
    config: dict,
    api_key: str,
    project: Project,
    agent: dict,
    *,
    c_provider=None,
    w_provider=None,
    lang: str = "ko",
) -> tuple[StatePatch, str]:
    """
    Ask the model for a patch and return (patch, proposed_state_text).
    Raises LLMError on provider failure; state file is untouched.
    """
    settings = state_update_settings(config)
    provider, model = _pick_provider(
        config, api_key, settings, c_provider=c_provider, w_provider=w_provider
    )
    if not project.state_path.exists():
        project.init_state()
    state_text = project.state_path.read_text(encoding="utf-8")
    module_output = project.read_module(agent["output"]) or ""
    if not module_output:
        raise LLMError(f"module output missing: {agent['output']}")
    base_brief = project.read_brief()

    messages = build_state_update_messages(
        without_revisions(state_text), str(agent["id"]), str(agent.get("name", agent["id"])), module_output, lang=lang
    )
    from sida.console import agent_look
    from sida.i18n import t
    from sida.providers import provider_chat

    tag, accent = agent_look(agent.get("id"))
    labeled = f"[{tag}] {agent.get('name', agent['id'])}"
    raw, _ = provider_chat(
        provider,
        model,
        messages,
        settings["temperature"],
        settings["max_tokens"],
        role="state_update",
        json_mode=True,
        status=t("busy_state", name=labeled),
        color=accent,
    )
    patch = parse_state_patch(raw, str(agent["id"]))
    patch.base_state = state_text
    patch.base_brief = base_brief
    patch.module_output = module_output
    proposed = preserve_revisions(apply_patch(without_revisions(state_text), patch), state_text)
    if not patch.is_empty():
        proposed = record_module_revision(proposed, str(agent["id"]), module_output)
    return patch, proposed


def write_state(project: Project, new_text: str) -> None:
    backup = project.path / "project_state.prev.md"
    if project.state_path.exists():
        atomic_write_text(backup, project.state_path.read_text(encoding="utf-8"))
    atomic_write_text(project.state_path, new_text)
