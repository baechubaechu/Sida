"""JSON API of the model domain: model bases and model boards for a site's surroundings, under
the site's paths (/api/projects/{name}/site/model-base...). The logic is in model_base.py."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from sida import board, workspace
from sida.experts.model import model_base
from sida.experts.site import context3d, context_range, site_facts
from sida.experts.site.api import _land, asked_range
from sida.i18n import t
from sida.model_base import board as model_board
from sida.model_base.nesting import DoesNotFit
from sida.model_base.output import FORMATS as model_board_formats


class BoardSettings(BaseModel):
    """A model board (model_base.settings); what is left out takes the default."""

    board: str | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    orient: str | None = None
    scale: int | None = None
    thickness_mm: float | None = None
    center: list[float] | None = None
    bed: list[float] | None = None
    save_material: bool | None = None
    formats: list[str] | None = None  # the laser files: some of dxf, pdf, svg (all three when left out)



def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/site")

    def _site_plan(name: str) -> tuple:
        path = core(workspace.find_project, load_config(), name)
        facts = site_facts.load_facts(path)
        if facts is None:
            raise HTTPException(status_code=404, detail=t("web_site_none"))
        plan = board.site_plan(site_facts.board_summary(facts)["parcels"])
        if plan is None:
            raise HTTPException(status_code=400, detail=t("web_site_context_no_plan"))
        return path, plan

    def _model(fn, *args, **kwargs):
        try:
            return _land(fn, *args, **kwargs)
        except model_board.FrameOutside as exc:
            raise HTTPException(status_code=400, detail=t("web_model_board_outside", m=f"{exc.overflow_m:.0f}")) from exc
        except model_board.NoFit as exc:
            raise HTTPException(status_code=400, detail=t("web_model_board_no_fit")) from exc
        except model_base.NoTerrain as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_no_terrain")) from exc
        except DoesNotFit as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_too_big")) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_bad", reason=str(exc))) from exc

    @router.get("/model-base")
    def get_model_base(name: str, interval: float = 1.5, radius: float | None = None, size: str | None = None,
                       shape: str | None = None, orient: str | None = None) -> dict:
        """The ground around the site stepped every `interval` m, with the buildings on it, in the
        range asked for (or the project's saved range; see _range)."""
        path, plan = _site_plan(name)
        radius, shape, orient = asked_range(path, radius, size, shape, orient)
        out = _model(model_base.stepped, plan, interval, radius, shape=shape, orient=orient)
        return {**out, "size": next((k for k, r in context3d.SIZES.items() if r == radius), None)}

    @router.get("/model-base/files")
    def get_model_base_files(name: str, scale: int = 500, thickness: float = 3.0, sheet: str = "600x400",
                             radius: float | None = None, hollow: float = 0.0, size: str | None = None,
                             shape: str | None = None, orient: str | None = None, formats: str = "dxf,pdf,svg") -> Response:
        """Laser files (zip) for the model of the range asked for (or the project's saved range; see
        _range), cut from sheets of material."""
        path, plan = _site_plan(name)
        radius, shape, orient = asked_range(path, radius, size, shape, orient)
        w, _, h = sheet.lower().partition("x")
        try:
            size = (float(w), float(h))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_bad", reason="sheet is WIDTHxHEIGHT mm")) from exc
        if not (100 <= scale <= 5000 and 0.5 <= thickness <= 20 and all(50 <= v <= 3000 for v in size) and 0 <= hollow <= 50):
            raise HTTPException(status_code=400, detail=t("web_model_base_bad", reason="scale 1:100–5000, thickness 0.5–20 mm, sheet 50–3000 mm"))
        data, summary = _model(model_base.cut_files, plan, radius=radius, scale=scale, thickness_mm=thickness,
                               sheet=size, hollow_rim_mm=hollow, shape=shape, orient=orient, formats=formats)
        filename = f"{path.name}_모형바닥_1-{scale}_{thickness:g}mm.zip"
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f"attachment; filename=\"sida-model-base.zip\"; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
            "X-Model-Base": _summary_header(summary),
        })

    def _summary_header(summary: dict) -> str:
        """k=v;k=v: sizes joined by x (594.0x420.0), names by + (dxf+pdf)."""
        def text(v):
            if isinstance(v, list):
                return ("+" if all(isinstance(n, str) for n in v) else "x").join(str(n) for n in v)
            return v
        return ";".join(f"{k}={text(v)}" for k, v in summary.items())

    def _board_range(path) -> dict:
        saved = context_range.load(path)
        return {"radius": saved["radius"], "shape": saved["shape"], "range_orient": saved["orient"]}

    @router.get("/model-base/fit")
    def get_model_board_fit(name: str, board: str = "W600x900", thickness: float = 3.0, orient: str = "landscape",
                            width: float | None = None, height: float | None = None) -> dict:
        """The standard scale at which this board covers as much of the saved 3D range as it can,
        holding the site, and where it sits: {scale, center, frame_m, board_mm}."""
        path, plan = _site_plan(name)
        try:
            model_board.check_thickness(thickness)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_bad", reason=str(exc))) from exc
        custom = (width, height) if board == model_board.CUSTOM else None
        return _model(model_base.fit_board, plan, board_name=board, orient=orient, custom=custom, **_board_range(path))

    @router.post("/model-base/plan")
    def post_model_board_plan(name: str, body: BoardSettings) -> dict:
        """The board laid on the saved 3D range, for drawing: the summary (scale, frame_m, board_mm,
        interval, layers, sheets, total_height_mm, ...), the frame's outline and each layer's ground
        in table metres. The settings are kept for the project."""
        path, plan = _site_plan(name)
        raw = body.model_dump(exclude_none=True)
        raw.pop("formats", None)
        out = _model(model_base.board_plan, plan, raw, **_board_range(path))
        context_range.save_model(path, model_base.settings({**raw, "center": out["center"]}))
        return out

    @router.post("/model-base/files")
    def post_model_board_files(name: str, body: BoardSettings) -> Response:
        """Laser files (zip) for the board: each layer in place on a board-size sheet, buildings
        laid out on sheets of their own. The settings are kept for the project."""
        path, plan = _site_plan(name)
        raw = body.model_dump(exclude_none=True)
        formats = raw.pop("formats", None) or list(model_board_formats)
        data, summary = _model(model_base.board_files, plan, raw, formats=formats, **_board_range(path))
        context_range.save_model(path, model_base.settings({**raw, "center": summary["center"]}))
        filename = f"{path.name}_모형판_{summary['board']}_1-{summary['scale']}_{summary['thickness_mm']:g}mm.zip"
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f"attachment; filename=\"sida-model-board.zip\"; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
            "X-Model-Base": _summary_header(summary),
        })

    @router.get("/model-base/settings")
    def get_model_board_settings(name: str) -> dict:
        """The last board settings for the project (the defaults when none, or unreadable ones)."""
        path = core(workspace.find_project, load_config(), name)
        try:
            return model_base.settings(context_range.model(path))
        except ValueError:
            return model_base.settings(None)

    return router
