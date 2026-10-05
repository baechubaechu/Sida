"""JSON API of the site domain. The logic is in site_facts.py; these routes only adapt it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sida import workspace
from sida.experts.site import landapi, site_facts
from sida.i18n import t

# What went wrong with the government API → HTTP status for the screen.
_LAND_STATUS = {"no_key": 503, "invalid_key": 503, "over_limit": 429, "network": 502, "bad_response": 502}


class ParcelSearch(BaseModel):
    query: str


class SiteLookup(BaseModel):
    query: str
    pnus: list[str]


class OptionState(BaseModel):
    dismissed: bool | None = None
    detailed: bool | None = None


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/site")

    def search(query: str) -> list[dict]:
        query = " ".join(query.split())
        if not query:
            raise HTTPException(status_code=400, detail=t("web_site_query_required"))
        try:
            return landapi.search_parcels(query)
        except landapi.LandApiError as exc:
            detail = t(f"site_err_{exc.kind}", detail=exc.detail).removeprefix("[site] ")
            raise HTTPException(status_code=_LAND_STATUS.get(exc.kind, 502), detail=detail) from exc

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
        try:
            chosen = site_facts.pick_candidates(search(body.query), body.pnus)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return site_facts.site_view(core(site_facts.refresh, path, body.query.strip(), chosen))

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
