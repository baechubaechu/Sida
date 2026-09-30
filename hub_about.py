#!/usr/bin/env python3
"""Hub about page: what Sida is, and what each worker / hub tool does."""

from __future__ import annotations

from console import ROLE_COLOR, agent_look, paint, prompt_line
from harness import get_agents
from i18n import t

PHASE_ORDER = (
    "analysis",
    "concept",
    "synthesis",
    "development",
    "critique",
    "communication",
)


def _phase_label(phase: str) -> str:
    key = f"about_phase_{phase}"
    label = t(key)
    return label if label != key else phase


def worker_label(agent: dict) -> tuple[str, str]:
    """Return (display_name, description) in the current UI language."""
    aid = str(agent.get("id") or "")
    name_key = f"worker_name_{aid}"
    desc_key = f"worker_desc_{aid}"
    name = t(name_key)
    if name == name_key:
        name = str(agent.get("name") or aid)
    desc = t(desc_key)
    if desc == desc_key:
        desc = str(agent.get("desc") or "").strip() or "—"
    return name, desc


def format_about_text(config: dict) -> str:
    """Plain-text about body (used by tests; colors applied when printing)."""
    lines: list[str] = [
        t("about_title"),
        "",
        t("about_overview"),
        "",
        t("about_flow"),
        "",
        t("about_hub_tools_title"),
        t("about_hub_tools"),
        "",
        t("about_workers_title"),
    ]

    by_phase: dict[str, list[dict]] = {}
    for agent in get_agents(config):
        by_phase.setdefault(str(agent.get("phase") or "other"), []).append(agent)

    for phase in [*PHASE_ORDER, *sorted(p for p in by_phase if p not in PHASE_ORDER)]:
        items = by_phase.get(phase) or []
        if not items:
            continue
        lines.append("")
        lines.append(f"—— {_phase_label(phase)} ——")
        for agent in items:
            aid = str(agent.get("id") or "")
            tag, _ = agent_look(aid)
            name, desc = worker_label(agent)
            lines.append(f"  [{tag}] {name}")
            lines.append(f"      {desc}")

    lines.append("")
    lines.append(t("about_footer"))
    return "\n".join(lines)


def print_about(config: dict) -> None:
    """Print the about page with worker colors when the terminal supports it."""
    print()
    print("=" * 40)
    print(paint(f"  {t('about_title')}", ROLE_COLOR.get("conductor", "bright_white"), bold=True))
    print("=" * 40)
    print()
    print(t("about_overview"))
    print()
    print(t("about_flow"))
    print()
    print(paint(t("about_hub_tools_title"), "yellow", bold=True))
    print(t("about_hub_tools"))
    print()
    print(paint(t("about_workers_title"), "cyan", bold=True))

    by_phase: dict[str, list[dict]] = {}
    for agent in get_agents(config):
        by_phase.setdefault(str(agent.get("phase") or "other"), []).append(agent)

    for phase in [*PHASE_ORDER, *sorted(p for p in by_phase if p not in PHASE_ORDER)]:
        items = by_phase.get(phase) or []
        if not items:
            continue
        print()
        print(paint(f"—— {_phase_label(phase)} ——", "dim", bold=True))
        for agent in items:
            aid = str(agent.get("id") or "")
            tag, color = agent_look(aid)
            name, desc = worker_label(agent)
            print(paint(f"  [{tag}] {name}", color, bold=True))
            print(f"      {desc}")

    print()
    print(t("about_footer"))
    print()
    prompt_line(t("about_back"))


def show_hub_about(config: dict) -> None:
    print_about(config)
