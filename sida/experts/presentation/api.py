"""JSON API of the presentation domain: the deck of a project as it stands, and its files.

    GET /api/projects/{name}/presentation                         the slides, to show
    GET /api/projects/{name}/presentation/file?format=pptx|pdf|zip  the file, made when asked
    GET /api/projects/{name}/presentation/diagram/{kind}          a diagram of the deck's model, as SVG

Each takes `scheme` (optional): the massing scheme on the drafting table the deck shows when
there is no Rhino snapshot (the first one otherwise).

Nothing is kept: the deck is read from the presentation editor's document, the newest Rhino
snapshot and the drafting table each time, so a file always has the figures of the model as it
stands. The logic is in slides.py, table.py and deck.py.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from sida import workspace
from sida.experts.presentation import deck, slides
from sida.experts.rhino import diagram_svg
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

    def materials(path, scheme: str) -> dict:
        try:
            return core(slides.materials, path, scheme.strip() or None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_presentation_bad", reason=str(exc))) from exc

    @router.get("")
    def read(name: str, scheme: str = "") -> dict:
        """
        The deck: {source, title, slides, notes, snapshot, model, schemes, figure_rows, formats,
        written}. `source` is "editor" when the presentation editor listed the slides, "default"
        when Sida laid them out by rule; a slide's `figure` is None or {key, kind, title, ready,
        why, file?, paper?} (`paper`: the section or photo paper on the table it shows); `model`
        is {source: "rhino" | "table" | null, scheme: {id, name} | null}, where the figures and
        diagrams come from; `schemes` the massing schemes on the table, to pick from;
        `figure_rows` are the rows of the figures table; `written` says whether the editor has run.
        """
        path, document = source(name)
        mats = materials(path, scheme)
        made = core(slides.deck, path, document, mats)
        for slide in made["slides"]:
            figure = slide["figure"]
            if figure is not None and figure["kind"] == "view" and figure["ready"]:
                figure["file"] = mats["items"][figure["key"]]["file"]
        rows = slides.figure_rows(mats["figures"], mats["limits"]) if mats["figures"] is not None else []
        return {**made, "schemes": mats["schemes"], "figure_rows": [list(row) for row in rows], "formats": list(deck.FORMATS),
                "written": document is not None}

    @router.get("/diagram/{kind}")
    def diagram(name: str, kind: str, scheme: str = "") -> Response:
        """One diagram of the deck's model (the Rhino snapshot, else the scheme on the table), as SVG."""
        path, _document = source(name)
        mats = materials(path, scheme)
        if mats["source"] is None:
            raise HTTPException(status_code=404, detail=t("web_presentation_bad", reason=slides.NOTHING_YET))
        try:
            drawing = core(deck.diagram_of, kind, mats, path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_presentation_bad", reason=str(exc))) from exc
        return Response(diagram_svg.to_svg(drawing), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    @router.get("/file")
    def file(name: str, format: str = "pptx", scheme: str = "") -> Response:
        """The deck as one file: PowerPoint, PDF, or a zip of both with the diagrams (SVG), the captures (PNG) and the figures (CSV)."""
        path, document = source(name)
        try:
            data, file_name = core(deck.make, path, document, format, scheme.strip() or None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_presentation_bad", reason=str(exc))) from exc
        return Response(data, media_type=deck.FORMATS[format],
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}", "Cache-Control": "no-store"})

    return router
