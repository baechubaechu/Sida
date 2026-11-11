"""How the Rhino domain plugs into the core (see sida/experts/__init__.py).

The experts get a short summary of the designer's newest Rhino snapshot (the figures Sida
computed from what Rhino measured and the layers' meanings), never the geometry. The JSON API
the Rhino plugin talks to is api.py.
"""

from __future__ import annotations

from sida.experts import FACTS, ExpertRun, PromptBlock


def prompt_blocks(run: ExpertRun) -> list[PromptBlock]:
    from sida import board
    from sida.experts.rhino import snapshot

    latest = snapshot.latest_snapshot(run.project_dir)
    if latest is None:
        return []
    area = (board.site_summary(run.project_dir) or {}).get("area_m2")
    return [PromptBlock(snapshot.prompt_text(latest, snapshot.figures(latest, area)), FACTS)]


def api_router(load_config, core):
    from sida.experts.rhino.api import create_router

    return create_router(load_config, core)
