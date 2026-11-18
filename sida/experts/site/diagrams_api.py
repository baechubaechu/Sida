"""JSON API of the site analysis diagrams (site_diagrams.py, drawn by site_sheet.py); the routes only adapt it.

    GET /api/projects/{name}/site/diagrams              the kinds, whether each can be drawn here, and the saved choices
    GET /api/projects/{name}/site/diagrams/{kind}       one diagram: ?range=small|default|large&hour=9..15|all&format=svg|json
    PUT /api/projects/{name}/site/diagrams/{kind}       keep its range (and the shadow's hour): {range, hour}
    GET /api/projects/{name}/site/diagrams/export       every diagram drawable here at its kept choice, as SVGs in a zip

Without `range` or `hour` the saved choice is drawn. Each kind has a range that suits it, one
step under it and one over it ("small", "default", "large"), in the shape the designer picked for
주변 3D. The surroundings are read straight from the map packs (site_diagrams.gather), not built.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from sida import workspace
from sida.experts.site import site_diagrams, site_sheet
from sida.i18n import t


def _hour(raw: str | None, saved: int | None) -> int | None:
    """The shadow's hour as asked: none given keeps the saved one, "all" (or empty) layers them all."""
    if raw is None:
        return saved
    if raw in ("", "all"):
        return None
    if not raw.isdigit() or int(raw) not in site_diagrams.SHADOW_HOURS:
        raise HTTPException(status_code=400, detail="hour must be 9~15 or all")
    return int(raw)


def create_router(load_config, core, land) -> APIRouter:
    """`land` calls the government API and turns its failures into HTTP errors (api._land)."""
    router = APIRouter(prefix="/api/projects/{name}/site/diagrams")

    def mats(name: str):
        path = core(workspace.find_project, load_config(), name)
        try:
            got = land(site_diagrams.materials, path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if got is None:
            raise HTTPException(status_code=404, detail=t("web_site_none"))
        return path, got

    @router.get("")
    def list_all(name: str) -> dict:
        """[{kind, title, ready, reason, range, hour, ranges: {small|default|large: {side, words}}}], the shape and the shadow's hours."""
        path, got = mats(name)
        saved = site_diagrams.choices(path)
        around = got["around"]
        return {
            "diagrams": [{**a, **saved[a["kind"]], "ranges": site_diagrams.ranges(around, a["kind"], got["plan"])}
                         for a in site_diagrams.available(around)],
            "shape": got["around"].get("shape") or "square",
            "hours": list(site_diagrams.SHADOW_HOURS),
            "source": got["around"].get("building_source", {}).get("name", ""),
        }

    @router.get("/export")
    def export(name: str) -> Response:
        """Every diagram that can be drawn here, each at its kept range and hour, as SVG files in one zip."""
        path, got = mats(name)
        try:
            data, _names = site_sheet.bundle(got, site_diagrams.choices(path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filename = f"{path.name}_대지분석_다이어그램.zip"
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                                 "Cache-Control": "no-store"})

    @router.get("/{kind}")
    def one(name: str, kind: str, range: str | None = None, hour: str | None = None, format: str = "svg"):  # noqa: A002
        """One diagram as SVG (or its drawing instruction with format=json)."""
        if format not in ("svg", "json"):
            raise HTTPException(status_code=400, detail="format must be svg or json")
        if kind not in site_diagrams.KINDS:
            raise HTTPException(status_code=404, detail="kind must be one of " + ", ".join(site_diagrams.KINDS))
        path, got = mats(name)
        saved = site_diagrams.choices(path)[kind]
        try:
            drawing = site_diagrams.drawing(kind, got, range or saved["range"], hour=_hour(hour, saved["hour"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if format == "json":
            return {"drawing": drawing}
        return Response(site_sheet.to_svg(drawing), media_type="image/svg+xml",
                        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(drawing['title'])}.svg",
                                 "Cache-Control": "no-store"})

    @router.put("/{kind}")
    def keep(name: str, kind: str, body: dict) -> dict:
        """Keep a diagram's range ("small", "default" or "large") and, for the shadow, its hour (9~15, or null for all)."""
        path = core(workspace.find_project, load_config(), name)
        hour = body.get("hour")
        try:
            return site_diagrams.save_choice(path, kind, str(body.get("range") or "default"), hour)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

