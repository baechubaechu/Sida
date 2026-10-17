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



def api_router(load_config, core):
    from sida.experts.site.api import create_router

    return create_router(load_config, core)
