"""JSON adapter for rating an expert's result; the work lives in telemetry.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sida import config as sida_config
from sida import telemetry, workspace


class Feedback(BaseModel):
    rating: str  # "up" | "down"
    comment: str = ""


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}")

    @router.post("/experts/{agent}/feedback")
    def feedback(name: str, agent: str, body: Feedback) -> dict:
        config = load_config()
        core(workspace.find_project, config, name)
        if sida_config.agent_by_id(sida_config.get_agents(config), agent) is None:
            raise HTTPException(status_code=404, detail=f"not found: {agent}")
        try:
            recorded = telemetry.record_feedback(config, agent, body.rating, body.comment)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # recorded is false when this machine does not send records (settings: telemetry_enabled).
        return {"recorded": recorded}

    return router
