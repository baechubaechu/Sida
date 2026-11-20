"""JSON API of the 자동 조경 (landscape.py); these routes only adapt it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StrictBool

from sida import workspace
from sida.experts.landscape import landscape
from sida.experts.site import landapi
from sida.i18n import t


class Settings(BaseModel):
    mass: str | None = None  # the mass scheme the buildings come from; null: the first on the table
    region: list[list[float]] | None = None  # a ring on the table (m); null: the whole lot
    style: str | None = None  # formal | natural | plaza
    seed: int | None = None  # 다시 섞기
    use: str | None = None  # the building's use for 공개 공지 (rules.uses), "other" or null
    placed: StrictBool | None = None  # the plan shown is placed on the table


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}/landscape")

    def payload(path, kept_only: bool = False) -> dict:
        try:
            return core(landscape.plans, path, kept_only=kept_only)
        except LookupError as exc:
            if str(exc) == "no_site":
                raise HTTPException(status_code=404, detail=t("web_site_none")) from exc
            raise HTTPException(status_code=400, detail=t("web_landscape_no_plan")) from exc
        except ValueError as exc:
            key = "web_landscape_region_too_big" if str(exc) == "region_too_big" else "web_landscape_region"
            raise HTTPException(status_code=400, detail=t(key)) from exc
        except landapi.LandApiError as exc:  # the road edges are asked once; a failure is not kept
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("")
    def get_landscape(name: str, placed_only: bool = False) -> dict:
        """The three layouts (정형·자연형·광장형) for the site, the mass scheme and the region picked,
        each with how it stands against the 조경·교목·공개 공지 the rules ask. `placed_only` (the
        table opening): nothing is worked out unless a plan is placed, and no map is asked."""
        path = core(workspace.find_project, load_config(), name)
        if placed_only:
            settings = landscape.load_settings(path)
            if not settings["placed"]:
                return {"settings": {k: settings[k] for k in landscape.SHOWN_SETTINGS}, "plans": []}
            return payload(path, kept_only=True)
        return payload(path)

    @router.put("")
    def put_landscape(name: str, body: Settings) -> dict:
        """Keep what the designer picked (only the fields sent; null clears `mass`, `region`, `use`)
        and give the layouts again."""
        path = core(workspace.find_project, load_config(), name)
        try:
            landscape.save_settings(path, body.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=t("web_landscape_setting", name=str(exc))) from exc
        return payload(path)

    return router
