#!/usr/bin/env python3
"""Local web UI for Sida (FastAPI). Runs on this machine only: python webapp.py

Three layers, so the screens can later be replaced without touching the rest:
  1. core functions   workspace.py / engine.py — no HTTP, no printing
  2. JSON API         /api/...  — calls the core and returns data (tests attach here)
  3. HTML pages       / and /p/<project> — calls the same core and renders templates
Keep logic out of the routes and templates; put it in the core.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from sida import config as sida_config
from sida import errors, providers, runtime, workspace
from sida.briefs import BRIEF_FIELD_HEADINGS
from sida.cli import cli_entrypoint
from sida.document_api import create_router as create_document_router
from sida.editing import EditingService
from sida.i18n import get_language, t
from sida.project_documents import DocumentConflict

WEB_DIR = sida_config.ROOT / "webui"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DRIVERS = ("site", "idea", "program", "regulation", "competition")

T = TypeVar("T")


class NewProject(BaseModel):
    name: str
    fields: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core access
# ---------------------------------------------------------------------------


def core(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Translate an application error into an HTTP 500 carrying its message.
    Application errors carry no terminal output or exit behavior.
    """
    try:
        return fn(*args, **kwargs)
    except DocumentConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except providers.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except errors.SidaError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc


def load_config() -> dict:
    return core(sida_config.load_config)


def runtime_summary(config: dict) -> dict:
    """What the hub shows about how models will run, plus setup problems worth flagging."""
    from sida.experts.regulation.rag import key_missing, rag_settings
    from sida.hub_settings import current_run_mode
    from sida.setup_env import read_api_key_from_env

    conductor = runtime.resolve_conductor_runtime(config)
    worker = runtime.resolve_worker_runtime(config)
    api_key = read_api_key_from_env()
    rag = rag_settings(config)
    return {
        "mode": current_run_mode(config),
        "conductor": {"provider": conductor["provider"], "model": conductor["model"]},
        "worker": {"provider": worker["provider"], "model": worker["model"]},
        "rag_enabled": bool(rag["enabled"]),
        "warnings": {
            "openrouter_key_missing": runtime.needs_openrouter(config) and not api_key,
            "rag_key_missing": key_missing(rag),
        },
    }


def project_detail(config: dict, name: str) -> dict:
    path = workspace.find_project(config, name)
    agents = sida_config.get_agents(config)
    summary = workspace.project_summary(path, agents)
    done = set(summary["completed"])
    brief_path = path / "brief.md"
    return {
        **summary,
        "brief": brief_path.read_text(encoding="utf-8") if brief_path.exists() else "",
        "experts": [
            {
                "id": a["id"],
                "name": a.get("name", a["id"]),
                "phase": a.get("phase", ""),
                "done": a["id"] in done,
            }
            for a in agents
        ],
    }


def local_time(stamp: str) -> str:
    """ISO timestamp → 'YYYY-MM-DD HH:MM' in this machine's timezone ('' if unparseable)."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


def project_url(name: str) -> str:
    return f"/p/{quote(name, safe='')}"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def create_app(*, allowed_hosts: frozenset[str] | set[str] = LOCAL_HOSTS) -> FastAPI:
    app = FastAPI(title="Sida", docs_url=None, redoc_url=None)
    app.state.editing = EditingService()
    app.include_router(create_document_router(app.state.editing, load_config, core))
    from sida.experts import expert_routers

    for router in expert_routers(load_config, core):  # each domain's own JSON API
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")
    templates.env.globals.update(t=t, local_time=local_time, project_url=project_url)
    hosts = {h.lower() for h in allowed_hosts}

    @app.middleware("http")
    async def local_requests_only(request: Request, call_next):
        # The server listens on localhost, but a web page in the same browser could still
        # reach it. Refuse foreign Host headers (DNS rebinding) and cross-site writes.
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        if host not in hosts:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and (urlparse(origin).hostname or "").lower() not in hosts:
                return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        return await call_next(request)

    def page(request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
        context.setdefault("lang", get_language())
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def hub_page(request: Request, status_code: int = 200, **extra: Any) -> HTMLResponse:
        config = load_config()
        return page(
            request,
            "hub.html",
            status_code,
            projects=core(workspace.list_project_summaries, config),
            projects_root=str(core(workspace.ensure_projects_root, config)),
            runtime=runtime_summary(config),
            brief_fields=[
                (key, t(label).rstrip(": "))
                for key, label, _heading in BRIEF_FIELD_HEADINGS
                if key != "driver"
            ],
            drivers=DRIVERS,
            form=extra.pop("form", {}),
            **extra,
        )

    @app.exception_handler(workspace.ProjectNotFound)
    async def project_not_found(request: Request, exc: workspace.ProjectNotFound):
        name = str(exc.args[0]) if exc.args else ""
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": f"project not found: {name}"}, status_code=404)
        return page(request, "error.html", 404, message=t("web_not_found", name=name))

    # ----------------------------------------------------------------- JSON API

    @app.get("/api/health")
    def api_health() -> dict:
        return {"ok": True, "app": "sida"}

    @app.get("/api/runtime")
    def api_runtime() -> dict:
        return runtime_summary(load_config())

    @app.get("/api/projects")
    def api_projects() -> dict:
        config = load_config()
        return {
            "root": str(core(workspace.ensure_projects_root, config)),
            "projects": core(workspace.list_project_summaries, config),
        }

    @app.post("/api/projects")
    def api_create_project(body: NewProject) -> JSONResponse:
        config = load_config()
        try:
            project, created = core(workspace.create_project, config, body.name, body.fields)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        summary = workspace.project_summary(project.path, sida_config.get_agents(config))
        return JSONResponse(
            {"project": summary, "created": created}, status_code=201 if created else 200
        )

    @app.post("/api/projects/sample")
    def api_create_sample() -> JSONResponse:
        config = load_config()
        project, created = core(workspace.create_sample_project, config)
        summary = workspace.project_summary(project.path, sida_config.get_agents(config))
        return JSONResponse(
            {"project": summary, "created": created}, status_code=201 if created else 200
        )

    @app.get("/api/projects/{name}")
    def api_project(name: str) -> dict:
        return core(project_detail, load_config(), name)

    # --------------------------------------------------------------- HTML pages

    @app.get("/", response_class=HTMLResponse)
    def hub(request: Request) -> HTMLResponse:
        return hub_page(request)

    @app.post("/projects")
    async def create_project(request: Request, name: str = Form("")):
        form = {key: str(value) for key, value in (await request.form()).items()}
        try:
            project, _created = core(workspace.create_project, load_config(), name, form)
        except ValueError:
            return hub_page(request, 400, form=form, error=t("web_err_name"))
        return RedirectResponse(project_url(project.name), status_code=303)

    @app.post("/projects/sample")
    def create_sample() -> RedirectResponse:
        project, _created = core(workspace.create_sample_project, load_config())
        return RedirectResponse(project_url(project.name), status_code=303)

    @app.get("/p/{name}", response_class=HTMLResponse)
    def project_page(request: Request, name: str) -> HTMLResponse:
        return page(request, "project.html", project=core(project_detail, load_config(), name))

    return app


@cli_entrypoint
def main(argv: list[str] | None = None) -> None:
    import threading
    import webbrowser

    import uvicorn

    from sida.console import configure_stdio

    args = list(sys.argv[1:] if argv is None else argv)
    port = DEFAULT_PORT
    if "--port" in args:
        try:
            port = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            errors.fail("Usage: python webapp.py [--port 8765] [--no-browser]")
    configure_stdio()
    url = f"http://{DEFAULT_HOST}:{port}/"
    print(t("web_serving", url=url))
    if "--no-browser" not in args:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(), host=DEFAULT_HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
