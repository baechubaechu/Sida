"""JSON API of the presentation domain: the deck of a project as it stands, and its files.

    GET /api/projects/{name}/presentation                         the slides, to show
    GET /api/projects/{name}/presentation/file?format=pptx|pdf|zip  the file, made when asked

Nothing is kept: the deck is read from the presentation editor's document and the newest Rhino
snapshot each time, so a file always has the figures of the model as last sent. The logic is in
slides.py and deck.py.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from sida import workspace
from sida.experts.presentation import deck, slides
from sida.i18n import t


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/presentation")

    def source(name: str):
        """The project's folder and the editor's document (None when the editor has not run)."""
        config = load_config()
        path = core(workspace.find_project, config, name).resolve()
        try:
            document = workspace.module_document(config, name, slides.EDITOR)["content"]
        except LookupError:
            document = None
        return path, document

    @router.get("")
    def read(name: str) -> dict:
        """
        The deck: {source, title, slides, notes, snapshot, figure_rows, formats, written}. `source`
        is "editor" when the presentation editor listed the slides, "default" when Sida laid them
        out by rule; a slide's `figure` is None or {key, kind, title, ready, why, file?};
        `figure_rows` are the rows of the figures table; `written` says whether the editor has run.
        """
        path, document = source(name)
        mats = core(slides.materials, path)
        made = core(slides.deck, path, document, mats)
        for slide in made["slides"]:
            figure = slide["figure"]
            if figure is not None and figure["kind"] == "view" and figure["ready"]:
                figure["file"] = mats["items"][figure["key"]]["file"]
        rows = slides.figure_rows(mats["figures"], mats["limits"]) if mats["figures"] is not None else []
        return {**made, "figure_rows": [list(row) for row in rows], "formats": list(deck.FORMATS), "written": document is not None}

    @router.get("/file")
    def file(name: str, format: str = "pptx") -> Response:
        """The deck as one file: PowerPoint, PDF, or a zip of both with the diagrams (SVG), the captures (PNG) and the figures (CSV)."""
        path, document = source(name)
        try:
            data, file_name = core(deck.make, path, document, format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_presentation_bad", reason=str(exc))) from exc
        return Response(data, media_type=deck.FORMATS[format],
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}", "Cache-Control": "no-store"})

    return router
