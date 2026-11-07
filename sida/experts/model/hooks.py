"""How the model domain plugs into the core (see sida/experts/__init__.py)."""

from __future__ import annotations

from sida.experts import ExpertRun, PromptBlock


def prompt_blocks(run: ExpertRun) -> list[PromptBlock]:
    """For the model maker: the site, its 3D range and what each board would give (prompt.py)."""
    if run.agent.get("id") != "model_maker":
        return []
    from sida.experts.model.prompt import board_facts

    return [board_facts(run)]


def api_router(load_config, core):
    from sida.experts.model.api import create_router

    return create_router(load_config, core)
