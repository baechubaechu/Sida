"""How the Rhino domain plugs into the core (see sida/experts/__init__.py).

The experts get a short summary of the designer's newest Rhino snapshot (the figures Sida
computed from what Rhino measured and the layers' meanings), never the geometry. While a Rhino
document is open on the project, the Conductor is also told how that document stands right now
and what is selected in it (live.py), so a question asked from the panel in Rhino, or from the
Sida screen beside it, is about the model as it is. The JSON API the Rhino plugin talks to is api.py.
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


def conductor_site(project_dir) -> str:
    """The Rhino document open on this project right now, with every Conductor message ("" when none)."""
    from pathlib import Path

    from sida.experts.rhino import live

    return live.brief_for(Path(project_dir).resolve())


def api_router(load_config, core):
    from sida.experts.rhino.api import create_router

    return create_router(load_config, core)
