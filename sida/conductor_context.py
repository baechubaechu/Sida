"""What the Conductor is sent: its prompt with the expert list, recent history, expert outputs."""

from __future__ import annotations

from pathlib import Path

from sida.config import agent_inputs, get_agents, get_paths
from sida.runtime import resolve_conductor_runtime
from sida.state_revisions import content_revision, module_revisions, without_revisions


def render_conductor_prompt(template: str, config: dict) -> str:
    """Fill {{MODULES}} and {{PATHS}} from config so the expert list lives in one place."""
    agents = get_agents(config)
    by_phase: dict[str, list[dict]] = {}
    for a in agents:
        by_phase.setdefault(str(a.get("phase") or "other"), []).append(a)
    lines: list[str] = []
    for phase, items in by_phase.items():
        lines.append(f"**{phase}**")
        for a in items:
            desc = str(a.get("desc") or a.get("name") or "").strip()
            inputs = agent_inputs(a)
            if inputs == "all":
                dep = "reads all completed outputs"
            elif isinstance(inputs, list) and inputs:
                dep = "reads: " + ", ".join(inputs)
            else:
                dep = "standalone"
            lines.append(f"- `{a.get('id')}` — {desc}  ({dep})")
        lines.append("")
    modules = "\n".join(lines).rstrip()

    paths = get_paths(config)
    path_lines = [f"- {name}: " + " → ".join(ids) for name, ids in paths.items()]
    paths_text = "\n".join(path_lines) if path_lines else "- (none defined)"

    return template.replace("{{MODULES}}", modules).replace("{{PATHS}}", paths_text)


def get_conductor_context_settings(config: dict) -> dict:
    ctx = (config.get("conductor") or {}).get("context") or {}
    runtime = resolve_conductor_runtime(config)
    return {
        "state_file": str(ctx.get("state_file") or "project_state.md"),
        "history_window": max(0, int(runtime["history_window"])),
        "prefer_state_over_modules": bool(ctx.get("prefer_state_over_modules", True)),
        "provider": runtime["provider"],
        "local_profile": runtime.get("local_profile"),
        "num_ctx": runtime.get("num_ctx"),
    }


def slice_history(history: list[dict], window: int) -> tuple[list[dict], bool]:
    """
    Return recent history for the API and whether older turns were omitted.
    The slice is aligned to start on a user message so pairs are not split.
    """
    if window <= 0 or len(history) <= window:
        return list(history), False
    start = len(history) - window
    while start < len(history) and history[start].get("role") != "user":
        start += 1
    if start >= len(history):
        start = len(history) - window
    return history[start:], True


def modules_newer_than_state(
    agents: list[dict], output_dir: Path, state_path: Path | None
) -> list[dict]:
    """Outputs not represented by the exact accepted revision in project state.

Legacy states without revision records are conservative: keep the full output
until a state proposal for that expert has been accepted.
"""
    if state_path is None or not state_path.exists():
        return []
    revisions = module_revisions(state_path.read_text(encoding="utf-8"))
    fresh = []
    for agent in agents:
        path = output_dir / agent["output"]
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text and revisions.get(str(agent["id"])) != content_revision(text):
            fresh.append(agent)
    return fresh


def build_module_snapshot(
    agents: list[dict], output_dir: Path, fresh: list[dict] | None = None
) -> str:
    """Compact index with full text for outputs not yet reflected in project state."""
    fresh_ids = {a.get("id") for a in (fresh or [])}
    lines = ["Completed module files (see PROJECT STATE for takeaways):", ""]
    any_done = False
    fresh_blocks: list[str] = []
    for agent in agents:
        path = output_dir / agent["output"]
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        any_done = True
        marker = "  (NOT YET REFLECTED in PROJECT STATE — full text below)" if agent.get("id") in fresh_ids else ""
        lines.append(f"- {agent.get('id')} → modules/{agent['output']}{marker}")
        if agent.get("id") in fresh_ids:
            fresh_blocks.append(f"### {agent.get('name', agent.get('id'))} (not yet reflected in PROJECT STATE)\n\n{text}")
    if not any_done:
        return "(no completed modules yet)"
    lines.extend(
        [
            "",
            "Use PROJECT STATE for module status. Do not invent outputs for modules not listed.",
        ]
    )
    if fresh_blocks:
        lines.extend(["", *fresh_blocks])
        lines.append(
            "\nRemind the designer to fold the updated module(s) into project_state.md."
        )
    return "\n".join(lines)


def prepare_conductor_context(
    config: dict,
    agents: list[dict],
    output_dir: Path,
    previous_blocks: list[str],
    history: list[dict],
    project_state: str | None,
    *,
    state_path: Path | None = None,
) -> tuple[str | None, str, list[dict], bool]:
    """
    Build Conductor context blocks.

    Returns: (project_state text or None, module context, history slice, truncated?)
    """
    settings = get_conductor_context_settings(config)
    sliced_history, truncated = slice_history(history, settings["history_window"])

    state_text = without_revisions(project_state).strip() if project_state else None
    prefer_state = settings["prefer_state_over_modules"]

    if state_text and prefer_state:
        fresh = modules_newer_than_state(agents, output_dir, state_path)
        module_context = build_module_snapshot(agents, output_dir, fresh)
    else:
        module_context = "\n\n".join(previous_blocks) if previous_blocks else "(none yet)"

    return state_text, module_context, sliced_history, truncated
