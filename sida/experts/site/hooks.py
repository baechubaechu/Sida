"""How the site domain plugs into the core (see sida/experts/__init__.py)."""

from __future__ import annotations

from sida.experts import FACTS, KNOWLEDGE, ExpertRun, PromptBlock
from sida.experts.site import site_facts
from sida.i18n import t


def prompt_blocks(run: ExpertRun) -> list[PromptBlock]:
    """Saved site facts (and, for regulatory experts, the ordinance articles as written)."""
    try:
        text = site_facts.block_for_agent(run.config, run.agent, run.project_dir)
        ordinance = site_facts.ordinance_block_for_agent(run.config, run.agent, run.project_dir)
    except Exception as exc:  # site facts must never block the expert run
        run.warn(t("site_block_failed", reason=str(exc) or type(exc).__name__))
        return []
    # The site's own ordinance goes ahead of general statute search results, so a local
    # model's context trims the search results first.
    return [
        PromptBlock(text, FACTS),
        PromptBlock(ordinance, KNOWLEDGE, priority=10, label=t("prompt_label_ordinance")),
    ]


def board_site(project_dir) -> dict | None:
    """The site as the drafting table needs it: area for the massing ratios, a few fact lines."""
    facts = site_facts.load_facts(project_dir)
    return site_facts.board_summary(facts) if facts else None


def board_export_layers(project_dir) -> list[dict]:
    """The site's surroundings (ground, contours, buildings from map files) for the CAD/Rhino export.
    Nothing when no site is looked up, or when the surroundings cannot be had right now."""
    from sida.board import site_plan
    from sida.experts.site import context3d, context_range, landapi

    facts = site_facts.load_facts(project_dir)
    plan = site_plan(site_facts.board_summary(facts)["parcels"]) if facts else None
    if not plan:
        return []
    picked = context_range.load(project_dir)
    try:
        return context3d.export_layers(context3d.build(plan, picked["radius"], shape=picked["shape"], orient=picked["orient"],
                                       for_export=True))
    except (landapi.LandApiError, ValueError):
        return []


def board_ground(project_dir) -> dict | None:
    """The ground around the site as a height grid (board_export surface form), for standing the
    masses on it in the export. None without a site or a terrain pack over it."""
    from sida.board import site_plan
    from sida.experts.site import context3d, context_range, landapi

    facts = site_facts.load_facts(project_dir)
    plan = site_plan(site_facts.board_summary(facts)["parcels"]) if facts else None
    if not plan:
        return None
    picked = context_range.load(project_dir)
    try:
        around = context3d.build(plan, picked["radius"], shape=picked["shape"], orient=picked["orient"],
                                       for_export=True)
    except (landapi.LandApiError, ValueError):
        return None
    return context3d.ground_surface(around)


def run_needs(config, agent, project_dir) -> str | None:
    """The Conductor runs the site reader only on a looked-up site; the designer picks it first."""
    if agent.get("id") == "site_reader" and site_facts.load_facts(project_dir) is None:
        return "no_site"
    return None


def api_router(load_config, core):
    from sida.experts.site.api import create_router

    return create_router(load_config, core)
