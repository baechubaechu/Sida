"""JSON API of the regulation domain. The logic is in law_search.py; these routes only adapt it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sida import telemetry
from sida.experts.regulation import law_search


class LawQuestion(BaseModel):
    question: str


def create_router(load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/law")

    @router.post("/search")
    def search(body: LawQuestion) -> dict:
        config = load_config()
        try:
            result = core(law_search.search_law, config, body.question)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException as exc:
            failed = telemetry.error_kind(exc.detail) or "other"
            telemetry.record_failure("law:search", failed, inputs=(body.question,), config=config)
            raise
        if not result["sources"]:
            telemetry.record_failure("law:search", "no_sources", inputs=(body.question,), config=config)
        return result

    return router
