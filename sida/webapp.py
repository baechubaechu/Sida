#!/usr/bin/env python3
"""Local web UI for Sida (FastAPI). Runs on this machine only: python webapp.py

Three layers, so the screens can later be replaced without touching the rest:
  1. core functions   workspace.py / engine.py — no HTTP, no printing
  2. JSON API         /api/...  — calls the core and returns data (tests attach here)
  3. screens          /  — the main screen (webui/app/, static files that call the JSON API)
Keep logic out of the routes, templates and scripts; put it in the core.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from sida import chatgpt_auth, errors, providers, runtime, telemetry, workspace
from sida import config as sida_config
from sida.board_api import create_router as create_board_router
from sida.chatgpt_api import create_router as create_chatgpt_router
from sida.document_api import create_router as create_document_router
from sida.editing import EditingService
from sida.i18n import agent_name, get_language, t
from sida.project_documents import DocumentConflict
from sida.session_api import create_router as create_session_router
from sida.session_jobs import SessionJobs
from sida.settings_api import create_router as create_settings_router
from sida.telemetry_api import create_router as create_telemetry_router

WEB_DIR = sida_config.ROOT / "webui"
APP_DIR = WEB_DIR / "app"  # the main screen: plain HTML/CSS/JS, no build step
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

T = TypeVar("T")


class NoCacheFiles(StaticFiles):
    """Static files the browser re-checks on every load, so a pulled update shows at once."""

    def file_response(self, *args: Any, **kwargs: Any):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


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
    """How models will run, plus setup problems worth flagging."""
    from sida.experts.regulation.rag import key_missing, rag_settings
    from sida.settings import current_run_mode, read_key

    conductor = runtime.resolve_conductor_runtime(config)
    worker = runtime.resolve_worker_runtime(config)
    api_key = read_key("OPENROUTER_API_KEY")
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
                "name": agent_name(a),
                "phase": a.get("phase", ""),
                "tier": sida_config.agent_tier(a),
                "done": a["id"] in done,
            }
            for a in agents
        ],
    }


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def create_app(*, allowed_hosts: frozenset[str] | set[str] = LOCAL_HOSTS) -> FastAPI:
    app = FastAPI(title="Sida", docs_url=None, redoc_url=None)
    app.state.editing = EditingService()
    app.include_router(create_document_router(app.state.editing, load_config, core))
    app.state.session_jobs = SessionJobs(app.state.editing)
    app.include_router(create_session_router(app.state.session_jobs, load_config, core))
    app.include_router(create_board_router(load_config, core))
    app.include_router(create_settings_router(load_config, core))
    app.include_router(create_chatgpt_router(load_config, core))
    app.include_router(create_telemetry_router(load_config, core))
    from sida.experts import expert_routers

    for router in expert_routers(load_config, core):  # each domain's own JSON API
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.mount("/app", NoCacheFiles(directory=APP_DIR), name="app")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")
    templates.env.globals.update(t=t)
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

    @app.exception_handler(workspace.ProjectNotFound)
    async def project_not_found(request: Request, exc: workspace.ProjectNotFound):
        name = str(exc.args[0]) if exc.args else ""
        return JSONResponse({"detail": f"project not found: {name}"}, status_code=404)

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

    @app.delete("/api/projects/{name}")
    def api_delete_project(name: str) -> dict:
        core(app.state.session_jobs.delete_project, load_config(), name)
        return {"deleted": name}

    # --------------------------------------------------------------- HTML pages

    @app.get("/", response_class=FileResponse)
    def main_screen() -> FileResponse:
        return FileResponse(APP_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get(chatgpt_auth.CALLBACK_PATH, response_class=HTMLResponse)
    def chatgpt_callback(request: Request) -> HTMLResponse:
        # OpenAI sends the browser back here after a ChatGPT sign-in started on settings.
        def done(status: int, title: str, message: str, ok: bool) -> HTMLResponse:
            return page(request, "chatgpt_login.html", status, title=title, message=message, ok=ok)

        try:
            result = core(chatgpt_auth.finish_login, dict(request.query_params))
        except chatgpt_auth.LoginError as exc:
            return done(400, t("web_chatgpt_failed_title"), str(exc), False)
        except HTTPException as exc:  # the sign-in server could not be reached
            return done(502, t("web_chatgpt_failed_title"), str(exc.detail), False)
        if not result["plan_usage"]:
            return done(200, t("web_chatgpt_done_title"), t("web_chatgpt_no_plan"), False)
        email = result["email"] or "ChatGPT"
        return done(200, t("web_chatgpt_done_title"), t("web_chatgpt_done", email=email), True)

    return app


def main(argv: list[str] | None = None) -> None:
    """python webapp.py: an application error is printed once and becomes the exit code."""
    try:
        serve(argv)
    except errors.SidaError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        raise SystemExit(exc.code) from None


def serve(argv: list[str] | None = None) -> None:
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
    telemetry.start_flusher()  # sends nothing unless this machine turned sending on
    uvicorn.run(create_app(), host=DEFAULT_HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
