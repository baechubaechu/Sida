"""How the model domain plugs into the core (see sida/experts/__init__.py)."""

from __future__ import annotations

from sida.experts import ExpertRun, PromptBlock

PLANNER = "representation_planner"  # plans the laser-cut site model with its other media


def prompt_blocks(run: ExpertRun) -> list[PromptBlock]:
    """For the representation planner, once the site is looked up and a 3D range is saved: the
    site, the range and what each board would give (prompt.py)."""
    if run.agent.get("id") != PLANNER:
        return []
    from sida.experts.model.prompt import board_facts, ready

    return [board_facts(run)] if ready(run.project_dir) else []


def api_router(load_config, core):
    from sida.experts.model.api import create_router

    return create_router(load_config, core)
