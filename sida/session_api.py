"""JSON adapters for the web session screen; the work lives in session_jobs.py and engine.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sida import workspace
from sida.session_jobs import SessionJobs


class Message(BaseModel):
    text: str


def create_router(jobs: SessionJobs, load_config, core) -> APIRouter:
    router = APIRouter(prefix="/api/projects/{name}")

    def call(fn, *args, **kwargs):
        try:
            return core(fn, *args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except workspace.ProjectNotFound:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=f"not found: {exc.args[0]}") from exc

    def started(job) -> JSONResponse:
        return JSONResponse({"job": job.view()}, status_code=202)

    @router.get("/session")
    def get_session(name: str) -> dict:
        return call(jobs.snapshot, load_config(), name)

    @router.post("/session/opening")
    def opening(name: str) -> JSONResponse:
        return started(call(jobs.start_opening, load_config(), name))

    @router.post("/session/messages")
    def message(name: str, body: Message) -> JSONResponse:
        return started(call(jobs.start_message, load_config(), name, body.text))

    @router.post("/session/experts/{agent}/run")
    def run_expert(name: str, agent: str) -> JSONResponse:
        return started(call(jobs.start_expert, load_config(), name, agent))

    @router.get("/session/jobs/{job_id}")
    def job(name: str, job_id: str, after: int = 0) -> dict:
        return call(jobs.job, load_config(), name, job_id, after)

    @router.get("/modules/{agent}")
    def module(name: str, agent: str) -> dict:
        return call(workspace.module_document, load_config(), name, agent)

    return router
