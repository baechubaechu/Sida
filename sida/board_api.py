"""JSON adapters for the drawing table; the work lives in board.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from sida import board, workspace


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/board")

    def call(fn, *args, **kwargs):
        try:
            return core(fn, *args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except board.PaperNotFound as exc:
            raise HTTPException(status_code=404, detail=f"not found: {exc.args[0]}") from exc

    def project(name: str):
        return workspace.find_project(load_config(), name).resolve()

    @router.get("")
    def get_board(name: str) -> dict:
        return call(board.load_board, call(project, name))

    @router.post("/papers")
    def add_paper(name: str, body: dict) -> JSONResponse:
        return JSONResponse(call(board.add_paper, call(project, name), body), status_code=201)

    @router.patch("/papers/{paper_id}")
    def update_paper(name: str, paper_id: str, body: dict) -> dict:
        return call(board.update_paper, call(project, name), paper_id, body)

    @router.delete("/papers/{paper_id}")
    def delete_paper(name: str, paper_id: str) -> dict:
        return call(board.delete_paper, call(project, name), paper_id)

    @router.get("/context")
    def context(name: str, ids: str = "") -> dict:
        selected = [i for i in ids.split(",") if i.strip()]
        return call(board.context_view, call(project, name), load_config(), selected)

    return router
