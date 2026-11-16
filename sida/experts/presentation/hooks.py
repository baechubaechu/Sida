"""How the presentation domain plugs into the core (see sida/experts/__init__.py).

The presentation editor is told which materials Sida can put on a slide (the diagrams and
captures of the newest Rhino snapshot, the table of figures), each by its key; the editor lists
slides that name them (slides.py). The files are made from that list by the JSON API (api.py).
"""

from __future__ import annotations

from sida.experts import FACTS, ExpertRun, PromptBlock

EDITOR = "presentation_editor"


def prompt_blocks(run: ExpertRun) -> list[PromptBlock]:
    if run.agent.get("id") != EDITOR:
        return []
    from sida.experts.presentation import slides

    return [PromptBlock(slides.prompt_text(slides.materials(run.project_dir)), FACTS)]


def api_router(load_config, core):
    from sida.experts.presentation.api import create_router

    return create_router(load_config, core)
