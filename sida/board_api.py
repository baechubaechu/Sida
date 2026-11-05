"""JSON adapters for the drawing table; the work lives in board.py."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from sida import board, board_export, workspace


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/board")

    def call(fn, *args, **kwargs):
        try:
            return core(fn, *args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (board.PaperNotFound, board.IdeaNotFound) as exc:
            raise HTTPException(status_code=404, detail=f"not found: {exc.args[0]}") from exc

    def project(name: str):
        return workspace.find_project(load_config(), name).resolve()

    @router.get("")
    def get_board(name: str) -> dict:
        return call(board.view, call(project, name))

    @router.post("/papers")
    def add_paper(name: str, body: dict) -> JSONResponse:
        return JSONResponse(call(board.add_paper, call(project, name), body), status_code=201)

    @router.patch("/papers/{paper_id}")
    def update_paper(name: str, paper_id: str, body: dict) -> dict:
        return call(board.update_paper, call(project, name), paper_id, body)

    @router.delete("/papers/{paper_id}")
    def delete_paper(name: str, paper_id: str) -> dict:
        return call(board.delete_paper, call(project, name), paper_id)

    @router.post("/photos")
    def add_photo(
        name: str,
        file: Annotated[UploadFile, File()],
        title: Annotated[str, Form()] = "",
        x: Annotated[float | None, Form()] = None,
        y: Annotated[float | None, Form()] = None,
        w: Annotated[float | None, Form()] = None,
        h: Annotated[float | None, Form()] = None,
    ) -> JSONResponse:
        data = file.file.read(board.MAX_PHOTO_BYTES + 1)
        fields = {"title": title, "x": x, "y": y, "w": w, "h": h}
        return JSONResponse(call(board.add_photo, call(project, name), data, fields), status_code=201)

    @router.get("/photos/{paper_id}")
    def photo(name: str, paper_id: str) -> FileResponse:
        path, media = call(board.photo_file, call(project, name), paper_id)
        # The file behind a photo paper never changes, so the browser may keep it.
        return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @router.post("/tray/{paper_id}/place")
    def place_paper(name: str, paper_id: str, body: dict | None = None) -> dict:
        return call(board.place_paper, call(project, name), paper_id, body or {})

    @router.delete("/tray/{paper_id}")
    def discard_paper(name: str, paper_id: str) -> dict:
        return call(board.discard_paper, call(project, name), paper_id)

    # The idea board: the designer's main ideas, in order (the AI only reads them).
    @router.post("/ideas")
    def add_idea(name: str, body: dict) -> JSONResponse:
        return JSONResponse(call(board.add_idea, call(project, name), body), status_code=201)

    # Declared before /ideas/{idea_id} so "order" is not read as an idea id.
    @router.put("/ideas/order")
    def order_ideas(name: str, body: dict) -> dict:
        return call(board.order_ideas, call(project, name), body.get("ids"))

    @router.patch("/ideas/{idea_id}")
    def update_idea(name: str, idea_id: str, body: dict) -> dict:
        return call(board.update_idea, call(project, name), idea_id, body)

    @router.delete("/ideas/{idea_id}")
    def delete_idea(name: str, idea_id: str) -> dict:
        return call(board.delete_idea, call(project, name), idea_id)

    @router.get("/export")
    def export(name: str, format: str = "dxf", active: str = "") -> Response:
        path = call(project, name)
        data = call(board_export.export_board, path, format, active=active.strip() or None)
        fmt = format.lower()
        filename = f"{path.name}_제도판.{fmt}"
        disposition = f"attachment; filename=\"sida-board.{fmt}\"; filename*=UTF-8''{quote(filename)}"
        return Response(
            data, media_type=board_export.MEDIA_TYPES[fmt],
            headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
        )

    @router.get("/context")
    def context(name: str, ids: str = "") -> dict:
        selected = [i for i in ids.split(",") if i.strip()]
        return call(board.context_view, call(project, name), load_config(), selected)

    return router
