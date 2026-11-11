"""JSON API the Rhino plugin talks to (docs/rhino-api.md). The logic is in snapshot.py.

/api/rhino/hello says Sida is up and which snapshot schema it reads; the rest is under the
project: snapshots (push, list, read, a view image, delete) and figures for a snapshot the
plugin has not saved (the live panel asks every second while the designer models).
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from sida import board, workspace
from sida.experts.rhino import snapshot
from sida.i18n import t


def create_router(load_config, core) -> APIRouter:
    router = APIRouter()

    def project(name: str):
        return core(workspace.find_project, load_config(), name).resolve()

    def call(fn, *args, **kwargs):
        try:
            return core(fn, *args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_rhino_snapshot_bad", reason=str(exc))) from exc
        except snapshot.SnapshotNotFound as exc:
            raise HTTPException(status_code=404, detail=t("web_rhino_snapshot_none", id=exc.args[0])) from exc

    def with_figures(path, saved: dict) -> dict:
        area = (board.site_summary(path) or {}).get("area_m2")
        fig = snapshot.figures(saved, area)
        return {**fig, "lines": snapshot.figure_lines(fig), "limits": snapshot.limits(path)}

    @router.get("/api/rhino/hello")
    def hello() -> dict:
        return {
            "ok": True, "app": "sida", "schema": snapshot.SCHEMA,
            "meanings": [{"code": code, "word": m["word"], "built": m["built"]} for code, m in snapshot.MEANINGS.items()],
            "views": list(snapshot.VIEW_KINDS),
        }

    @router.post("/api/projects/{name}/rhino/snapshots")
    def push(
        name: str,
        snapshot_json: Annotated[str, Form(alias="snapshot")],
        views: Annotated[list[UploadFile], File()] = [],  # noqa: B006 (FastAPI reads the default)
    ) -> JSONResponse:
        """Save a snapshot with its view images (one file per declared view, named as declared);
        the newest snapshot becomes the table's "라이노 작업" paper."""
        path = project(name)
        try:
            raw = json.loads(snapshot_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=t("web_rhino_snapshot_json")) from exc
        files = {v.filename: v.file.read(snapshot.MAX_VIEW_BYTES + 1) for v in views if v.filename}
        saved = call(snapshot.save_snapshot, path, raw, files)
        fig = with_figures(path, saved)
        placed = core(board.rhino_paper, path, {
            "title": saved["rhino"]["file"].rsplit(".", 1)[0] if saved["rhino"]["file"] else "",
            "snapshot": saved["id"], "file": saved["rhino"]["file"], "taken_at": saved["taken_at"],
            "objects": len(saved["objects"]), "layers": saved["layers"], "figures": fig,
        })
        return JSONResponse({"snapshot": snapshot.summary(saved), "figures": fig, "paper": placed["paper"], "rev": placed["rev"]},
                            status_code=201)

    @router.get("/api/projects/{name}/rhino/snapshots")
    def list_all(name: str) -> dict:
        return {"snapshots": snapshot.list_snapshots(project(name))}

    @router.get("/api/projects/{name}/rhino/snapshots/{snapshot_id}")
    def read(name: str, snapshot_id: str) -> dict:
        path = project(name)
        saved = call(snapshot.load_snapshot, path, snapshot_id)
        return {"snapshot": saved, "figures": with_figures(path, saved)}

    @router.get("/api/projects/{name}/rhino/snapshots/{snapshot_id}/views/{file}")
    def view(name: str, snapshot_id: str, file: str) -> FileResponse:
        image = call(snapshot.view_file, project(name), snapshot_id, file)
        # A snapshot's view never changes, so the browser (and the plugin's panel) may keep it.
        return FileResponse(image, media_type="image/png", headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @router.delete("/api/projects/{name}/rhino/snapshots/{snapshot_id}")
    def delete(name: str, snapshot_id: str) -> dict:
        call(snapshot.delete_snapshot, project(name), snapshot_id)
        return {"ok": True}

    @router.post("/api/projects/{name}/rhino/figures")
    def live_figures(name: str, raw: dict) -> dict:
        """Figures for a snapshot that is not saved (the plugin's live panel): the body is the
        snapshot itself, views and meshes left out."""
        path = project(name)
        checked = call(snapshot.clean_snapshot, raw)
        return {"figures": with_figures(path, checked)}

    return router
