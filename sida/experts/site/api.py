"""JSON API of the site domain. The logic is in site_facts.py; these routes only adapt it."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from sida import board, telemetry, workspace
from sida.experts.site import context3d, datago, landapi, model_base, site_facts
from sida.i18n import t
from sida.model_base.nesting import DoesNotFit
from sida.project import load_project

MAX_SHAPES = 50  # parcels per shape request: a merged site is a handful, not a 동

# What went wrong with the government API → HTTP status for the screen.
_LAND_STATUS = {"no_key": 503, "invalid_key": 503, "over_limit": 429, "network": 502, "bad_response": 502}


class ParcelSearch(BaseModel):
    query: str


class SiteLookup(BaseModel):
    query: str = ""  # empty: the parcels are taken by PNU alone (step-by-step selection)
    pnus: list[str]


class UseCheck(BaseModel):
    name: str


class OptionState(BaseModel):
    dismissed: bool | None = None
    detailed: bool | None = None


def _land(fn, *args, **kwargs):
    """Call the government API; its failures become HTTP errors the screen can show as is."""
    try:
        return fn(*args, **kwargs)
    except landapi.LandApiError as exc:
        # `fn` may be `core` with the real function as its first argument: name the last one,
        # and report only plain values (an address, a code), never a project path.
        named = [a for a in (fn, *args) if callable(a)][-1]
        inputs = [a for a in args if isinstance(a, (str, int, float)) and not isinstance(a, bool)]
        telemetry.record_failure(f"site:{getattr(named, '__name__', 'lookup')}", exc.kind, inputs=inputs)
        detail = t(exc.MESSAGE_PREFIX + exc.kind, detail=exc.detail).removeprefix("[site] ")
        raise HTTPException(status_code=_LAND_STATUS.get(exc.kind, 502), detail=detail) from exc


def create_router(load_config, core) -> APIRouter:
    router = APIRouter()
    router.include_router(_address_router())
    router.include_router(_project_router(load_config, core))
    return router


def _address_router() -> APIRouter:
    """Step-by-step address selection. Not tied to a project: it only finds parcel numbers."""
    router = APIRouter(prefix="/api/site")

    @router.get("/regions")
    def get_regions(parent: str = "") -> dict:
        parent = parent.strip()
        try:
            found = _land(landapi.regions, parent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_site_region_bad", code=parent)) from exc
        return {"parent": parent, "level": landapi.REGION_LEVELS[len(parent)], "regions": found}

    @router.get("/lots")
    def get_lots(dong_code: str, main: int, sub: int | None = None, mountain: bool = False) -> dict:
        dong_code = dong_code.strip()
        if len(dong_code) != 10 or not dong_code.isdigit():
            raise HTTPException(status_code=400, detail=t("web_site_dong_bad", code=dong_code))
        try:
            candidates = _land(landapi.find_lots, dong_code, main, sub, mountain=mountain)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_site_lot_bad")) from exc
        lot = ("산 " if mountain else "") + (f"{main}-{sub}" if sub else str(main))
        return {"dong_code": dong_code, "lot": lot, "candidates": candidates}

    @router.get("/map")
    def get_map() -> dict:
        return _land(landapi.map_layers)

    @router.get("/parcel-at")
    def get_parcel_at(lon: float, lat: float) -> dict:
        try:
            found = _land(landapi.parcel_at, lon, lat)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_site_point_bad", lon=lon, lat=lat)) from exc
        return {"lon": lon, "lat": lat, "candidates": [found] if found else []}

    @router.get("/shapes")
    def get_shapes(pnu: Annotated[list[str] | None, Query()] = None) -> dict:
        pnus = list(dict.fromkeys(p.strip() for p in pnu or [] if p.strip()))
        if not pnus:
            raise HTTPException(status_code=400, detail=t("web_site_pnus_required"))
        if len(pnus) > MAX_SHAPES:
            raise HTTPException(status_code=400, detail=t("web_site_shapes_limit", n=MAX_SHAPES))
        bad = next((p for p in pnus if len(p) != 19 or not p.isdigit()), None)
        if bad:
            raise HTTPException(status_code=400, detail=t("web_site_pnu_bad", pnu=bad))
        return {"shapes": [{"pnu": p, "shape": _land(landapi.parcel_shape, p)} for p in pnus]}

    @router.get("/uses")
    def get_uses(q: str = "") -> dict:
        query = " ".join(q.split())
        if not query:
            raise HTTPException(status_code=400, detail=t("web_site_use_required"))
        return {"query": query, "uses": _land(datago.search_uses, query)}

    return router


def _project_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/site")

    def search(query: str) -> list[dict]:
        query = " ".join(query.split())
        if not query:
            raise HTTPException(status_code=400, detail=t("web_site_query_required"))
        found = _land(landapi.search_parcels, query)
        if not found:
            telemetry.record_failure("site:search_parcels", "not_found", inputs=(query,))
        return found

    @router.get("")
    def get_site(name: str) -> dict:
        path = core(workspace.find_project, load_config(), name)
        return site_facts.site_view(site_facts.load_facts(path))

    @router.post("/parcels")
    def find_parcels(name: str, body: ParcelSearch) -> dict:
        core(workspace.find_project, load_config(), name)
        keys = ("pnu", "address", "road_address", "building", "matched_by")
        return {"query": body.query.strip(), "candidates": [{k: c.get(k, "") for k in keys} for c in search(body.query)]}

    @router.put("")
    def look_up_site(name: str, body: SiteLookup) -> dict:
        path = core(workspace.find_project, load_config(), name)
        query = " ".join(body.query.split())
        try:
            if query:
                chosen = site_facts.pick_candidates(search(query), body.pnus)
            else:
                chosen = _land(site_facts.candidates_for_pnus, body.pnus)
                query = ", ".join(c["address"] or c["pnu"] for c in chosen)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        facts = core(site_facts.refresh, path, query, chosen)
        project = core(load_project, path)
        core(site_facts.note_lookup, project, query, project.load_history())
        return site_facts.site_view(facts)

    @router.get("/context")
    def get_context(name: str, radius: float = context3d.DEFAULT_RADIUS) -> dict:
        path = core(workspace.find_project, load_config(), name)
        facts = site_facts.load_facts(path)
        if facts is None:
            raise HTTPException(status_code=404, detail=t("web_site_none"))
        if not 50 <= radius <= context3d.MAX_RADIUS:
            raise HTTPException(status_code=400, detail=t("web_site_context_radius", max=int(context3d.MAX_RADIUS)))
        plan = board.site_plan(site_facts.board_summary(facts)["parcels"])
        if plan is None:
            raise HTTPException(status_code=400, detail=t("web_site_context_no_plan"))
        out = _land(context3d.build, plan, radius)
        return {**out, "disclaimer": t("site_context_disclaimer")}

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
        except model_base.NoTerrain as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_no_terrain")) from exc
        except DoesNotFit as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_too_big")) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_bad", reason=str(exc))) from exc

    @router.get("/model-base")
    def get_model_base(name: str, interval: float = 1.5, radius: float = context3d.DEFAULT_RADIUS) -> dict:
        """The ground around the site stepped every `interval` m, with the buildings on it."""
        _path, plan = _site_plan(name)
        return _model(model_base.stepped, plan, interval, radius)

    @router.get("/model-base/files")
    def get_model_base_files(name: str, scale: int = 500, thickness: float = 3.0, sheet: str = "600x400",
                             radius: float = 100.0, hollow: float = 0.0) -> Response:
        """Laser files (zip) for the model ±radius m around the site, cut from sheets of material."""
        path, plan = _site_plan(name)
        w, _, h = sheet.lower().partition("x")
        try:
            size = (float(w), float(h))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_model_base_bad", reason="sheet is WIDTHxHEIGHT mm")) from exc
        if not (100 <= scale <= 5000 and 0.5 <= thickness <= 20 and all(50 <= v <= 3000 for v in size) and 0 <= hollow <= 50):
            raise HTTPException(status_code=400, detail=t("web_model_base_bad", reason="scale 1:100–5000, thickness 0.5–20 mm, sheet 50–3000 mm"))
        data, summary = _model(model_base.cut_files, plan, radius=radius, scale=scale, thickness_mm=thickness,
                               sheet=size, hollow_rim_mm=hollow)
        filename = f"{path.name}_모형바닥_1-{scale}_{thickness:g}mm.zip"
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f"attachment; filename=\"sida-model-base.zip\"; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
            "X-Model-Base": ";".join(f"{k}={v}" for k, v in summary.items() if not isinstance(v, list)),
        })

    @router.get("/ordinance")
    def get_ordinance(name: str) -> dict:
        path = core(workspace.find_project, load_config(), name)
        return site_facts.ordinance_options(site_facts.load_facts(path))

    @router.put("/ordinance/options/{option_id}")
    def put_option(name: str, option_id: str, body: OptionState) -> dict:
        path = core(workspace.find_project, load_config(), name)
        if body.dismissed is None and body.detailed is None:
            raise HTTPException(status_code=422, detail="dismissed or detailed is required")
        try:
            return core(
                site_facts.set_option, path, option_id, dismissed=body.dismissed, detailed=body.detailed
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/uses")
    def check_use(name: str, body: UseCheck) -> dict:
        path = core(workspace.find_project, load_config(), name)
        try:
            facts = _land(core, site_facts.check_use, path, body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return site_facts.site_view(facts)

    @router.delete("/uses/{use}")
    def remove_use(name: str, use: str) -> dict:
        path = core(workspace.find_project, load_config(), name)
        try:
            return site_facts.site_view(core(site_facts.remove_use, path, use))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
