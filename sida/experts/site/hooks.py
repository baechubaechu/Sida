"""How the site domain plugs into the core (see sida/experts/__init__.py)."""

from __future__ import annotations

from sida.experts import FACTS, KNOWLEDGE, ExpertRun, PromptBlock
from sida.experts.site import site_facts
from sida.experts.site.commands import cmd_site
from sida.i18n import t


def prompt_blocks(run: ExpertRun) -> list[PromptBlock]:
    """Saved site facts (and, for regulatory experts, the ordinance articles as written)."""
    try:
        text = site_facts.block_for_agent(run.config, run.agent, run.project_dir)
        ordinance = site_facts.ordinance_block_for_agent(run.config, run.agent, run.project_dir)
    except Exception as exc:  # site facts must never block the expert run
        run.warn(t("site_block_failed", reason=str(exc) or type(exc).__name__))
        return []
    return [PromptBlock(text, FACTS), PromptBlock(ordinance, KNOWLEDGE)]


COMMANDS = {"/site": cmd_site}
