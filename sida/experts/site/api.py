"""JSON API of the site domain. The logic is in site_facts.py; these routes only adapt it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sida import workspace
from sida.experts.site import site_facts


class OptionState(BaseModel):
    dismissed: bool | None = None
    detailed: bool | None = None


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/site")

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
