"""JSON API of the site domain. The logic is in site_facts.py; these routes only adapt it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sida import workspace
from sida.experts.site import landapi, site_facts
from sida.i18n import t
from sida.project import load_project

# What went wrong with the government API → HTTP status for the screen.
_LAND_STATUS = {"no_key": 503, "invalid_key": 503, "over_limit": 429, "network": 502, "bad_response": 502}


class ParcelSearch(BaseModel):
    query: str


class SiteLookup(BaseModel):
    query: str = ""  # empty: the parcels are taken by PNU alone (step-by-step selection)
    pnus: list[str]


class OptionState(BaseModel):
    dismissed: bool | None = None
    detailed: bool | None = None


def _land(fn, *args, **kwargs):
    """Call the government API; its failures become HTTP errors the screen can show as is."""
    try:
        return fn(*args, **kwargs)
    except landapi.LandApiError as exc:
        detail = t(f"site_err_{exc.kind}", detail=exc.detail).removeprefix("[site] ")
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

    return router


def _project_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/site")

    def search(query: str) -> list[dict]:
        query = " ".join(query.split())
        if not query:
            raise HTTPException(status_code=400, detail=t("web_site_query_required"))
        return _land(landapi.search_parcels, query)

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

    return router
