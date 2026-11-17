"""Sida relay: the government API calls of Sida apps that have no keys of their own.

Runs on the Korean server (Naver Cloud, /opt/sida-kr) behind Caddy. The app (sida/relay.py)
calls the same paths it would call on VWorld, data.go.kr and law.go.kr, under /relay/<service>/,
with no government key; this server adds its own key, calls the service and passes the answer
back as it came (status, content type, body).

- Each person gets an access key (sida_…, relay/tokens.py, made with relay/admin.py). The app
  sends it as "Authorization: Bearer sida_…"; map images, which the browser loads itself, carry
  it as the sida_token parameter. No key or an unknown one → 401, a revoked or expired one → 403.
- Each key has a daily limit for API calls (kept in SQLite, so a restart does not reset it) and
  per-minute limits; each sending address has a per-minute limit too.
- Only the paths Sida uses are open, so this is not a general proxy for the keys.
- Nothing is kept of the answers: no cache (VWorld 이용약관 제19조) and no query log. Usage is
  counted per key, day and service only.
- A government key never leaves the server: one the client sends is dropped, and an answer that
  echoes the server's key has it masked.
- Someone without a key asks for one from the app's settings (POST /relay/requests: a name and
  how to reach them). The admin approves it with relay/admin.py, and the app collects the key
  with the request's claim code (POST /relay/requests/claim). Each sending address can ask a few
  times an hour.
- VWorld's WebGL 3D map can't be relayed: the browser loads VWorld's script with a key, and
  VWorld checks the key against the page's address. So this server serves the app's 3D page
  itself (GET /relay/vworld3d, a copy of webui/app/vworld3d.html in relay/static/) with the 3D
  script address filled in. The app shows it in a frame and drives it by postMessage. The 3D key
  is then in the viewer's browser, as with any web map, so it is a key of its own with only the
  3D map on it (VWORLD_3D_API_KEY; no 3D page without it), and only the Sida app's own pages may
  frame the page.

Run: uvicorn relay.app:from_env --factory (see relay/README.md).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from relay.shares import LimitReached, Limits, ShareError, ShareStore
from relay.tokens import MAX_CONTACT, Token, TokenStore

VWORLD_URL = "https://api.vworld.kr"
DATAGO_URL = "https://apis.data.go.kr/1613000"
LAW_URL = "https://www.law.go.kr/DRF"
TIMEOUT = 20

TOKEN_PARAM = "sida_token"  # map images: the browser can't send a header
CALLS_PER_MINUTE = 120  # API calls per key per minute
IMAGES_PER_MINUTE = 600  # map images per key per minute (a map view loads a few dozen)
ADDRESS_PER_MINUTE = 1500  # requests per sending address per minute (a school shares one)
REQUESTS_PER_HOUR = 5  # key requests per sending address per hour
MAX_PARAMS = 30
MAX_PARAM_CHARS = 4000  # attrFilter / geomFilter can be long polygons

# Client parameters never forwarded: the server sets its own (any case).
_DROPPED_PARAMS = {"key", "domain", "apikey", "servicekey", "oc", TOKEN_PARAM}

# Paths open on each service, as the app calls them.
_VWORLD_DATA = re.compile(r"^(req/search|req/data|ned/data/[A-Za-z]{3,40})$")
_VWORLD_WMS = "req/wms"
_VWORLD_TILE = re.compile(r"^req/wmts/1\.0\.0/Base/(\d{1,2})/(\d{1,7})/(\d{1,7})\.png$")
_DATAGO_PATHS = {
    "arLandUseInfoService/DTarLandUseInfo",
    "arLandUseInfoService/DTsearchLunCd",
    "LuLawInfoService/DTluLawInfo",
    "BldRgstHubService/getBrTitleInfo",
}
_LAW_PATHS = {"lawSearch.do", "lawService.do"}
_LAW_TARGETS = {"aiSearch", "ordin"}
# 건축물대장 packs made on this server each month (relay/ledger/ledger_pull.py), for the apps to download.
LEDGER_MANIFEST = "manifest.json"
_LEDGER_FILE = re.compile(r"^[a-z0-9_-]{1,40}-\d{4}-\d{2}\.ledger\.sqlite\.gz$")

# Shares (공유, relay/shares.py): the viewer page and the files it loads, from the app's own screen
# files (webui/app, mounted on the server at SIDA_VIEWER_DIR). Only these are served.
VIEWER_PAGE = "share.html"
VIEWER_FILES = {
    "share.html", "share-view.js", "share-model.js", "share.css", "board-model.js", "model.js", "icons.js",
    "vendor/three.js",
}
COMMENTS_PER_MINUTE = 6  # new comments per link and sending address per minute
PARCELS_PER_MINUTE = 30  # parcel boundaries asked of VWorld per link per minute (a page asks once)
AROUND_PER_MINUTE = 30  # VWorld 3D pages opened per link per minute (the surroundings in the viewer)
UPLOAD_SLACK = 1024 * 1024  # a request body may be this much over a share's limit before it is read
# The viewer's page: its own files and the share's data only, never another site's.
VIEWER_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)

# The app's VWorld 3D page and its script (copies of webui/app/, kept identical by a test).
STATIC = Path(__file__).parent / "static"
WEBGL3D_SCRIPT = "https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey={key}"
# Who may show the 3D page in a frame: the Sida app on its own PC (any port), and this server.
WEBGL3D_FRAME_ANCESTORS = "'self' http://localhost:* http://127.0.0.1:*"


@dataclass(frozen=True)
class Keys:
    vworld: str = ""
    vworld_domain: str = ""  # the service address the VWorld key was issued for
    datago: str = ""
    law: str = ""
    # The 3D map's own key (only VWorld's 3D map API on it), which ends up in viewers' browsers.
    # Never the server's other VWorld key: without this one there is no 3D page.
    vworld3d: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Keys:
        env = dict(os.environ if env is None else env)
        return cls(
            vworld=env.get("VWORLD_API_KEY", "").strip(),
            vworld_domain=env.get("VWORLD_DOMAIN", "").strip(),
            datago=env.get("DATA_GO_KR_API_KEY", "").strip(),
            law=env.get("LAW_OPEN_API_OC", "").strip(),
            vworld3d=env.get("VWORLD_3D_API_KEY", "").strip(),
        )

    def secrets(self) -> list[str]:
        return [k for k in (self.vworld, self.datago, self.law) if len(k) >= 6]


def webgl3d_page(key: str) -> str:
    """The app's 3D page with VWorld's script address (and so the 3D key) filled in."""
    page = (STATIC / "vworld3d.html").read_text(encoding="utf-8")
    script = json.dumps(WEBGL3D_SCRIPT.replace("{key}", key)).replace("<", "\\u003c")
    fill = f"<script>window.SIDA_VWORLD_SCRIPT = {script};</script>\n  "
    head = "<script>"
    at = page.index(head)  # before the page's own script, which loads VWorld's
    return page[:at] + fill + page[at:]


@dataclass
class Upstream:
    status: int
    content_type: str
    body: bytes


# (url, params, headers) → the service's answer. Tests pass a fake.
Fetch = Callable[[str, dict, dict], Upstream]


def _fetch(url: str, params: dict, headers: dict) -> Upstream:
    try:
        r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"upstream {type(exc).__name__}") from exc
    return Upstream(r.status_code, r.headers.get("content-type", "application/octet-stream"), r.content)


class MinuteLimit:
    """At most `limit` requests per key within the last `window` seconds (in memory)."""

    def __init__(self, limit: int, clock: Callable[[], float], window: float = 60):
        self.limit = limit
        self.clock = clock
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def take(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


class KeyRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    contact: str = Field(default="", max_length=MAX_CONTACT)


class ClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=100)


def _client_params(request: Request) -> dict[str, str]:
    items = list(request.query_params.multi_items())
    if len(items) > MAX_PARAMS or any(len(v) > MAX_PARAM_CHARS for _k, v in items):
        raise HTTPException(status_code=400, detail="too many or too long parameters")
    return {k: v for k, v in items if k.lower() not in _DROPPED_PARAMS}


def _mask(answer: Upstream, secrets: list[str]) -> Upstream:
    if answer.content_type.startswith("image/"):
        return answer
    body = answer.body
    for secret in secrets:
        body = body.replace(secret.encode("utf-8"), b"***")
    return Upstream(answer.status, answer.content_type, body)


class ShareChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comments_open: bool | None = None
    new_links: bool = False


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved: bool


def create_app(
    keys: Keys, store: TokenStore, *, fetch: Fetch | None = None, clock: Callable[[], float] = time.monotonic,
    ledger_dir: Path | None = None, shares: ShareStore | None = None, viewer_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Sida relay", docs_url=None, redoc_url=None, openapi_url=None)
    get = fetch or _fetch
    calls_per_minute = MinuteLimit(CALLS_PER_MINUTE, clock)
    images_per_minute = MinuteLimit(IMAGES_PER_MINUTE, clock)
    address_per_minute = MinuteLimit(ADDRESS_PER_MINUTE, clock)
    requests_per_hour = MinuteLimit(REQUESTS_PER_HOUR, clock, window=3600)
    comments_per_minute = MinuteLimit(COMMENTS_PER_MINUTE, clock)
    parcels_per_minute = MinuteLimit(PARCELS_PER_MINUTE, clock)
    around_per_minute = MinuteLimit(AROUND_PER_MINUTE, clock)

    def address(request: Request) -> str:
        # Behind Caddy the sender is the first X-Forwarded-For address.
        forwarded = request.headers.get("x-forwarded-for", "")
        return forwarded.split(",")[0].strip() or (request.client.host if request.client else "")

    def access_key(request: Request, *, image: bool) -> Token:
        if not address_per_minute.take(address(request)):
            raise HTTPException(status_code=429, detail="too many requests")
        sent = request.headers.get("authorization", "")
        value = sent[7:].strip() if sent.lower().startswith("bearer ") else ""
        if not value and image:
            value = request.query_params.get(TOKEN_PARAM, "")
        token = store.find(value) if value else None
        if token is None:
            raise HTTPException(status_code=401, detail="Sida access key missing or unknown")
        if not token.usable(store.now().date()):
            raise HTTPException(status_code=403, detail="Sida access key revoked or expired")
        if image:
            if not images_per_minute.take(token.id):
                raise HTTPException(status_code=429, detail="too many map images")
        elif not calls_per_minute.take(token.id) or not store.take(token):
            raise HTTPException(status_code=429, detail="limit reached for this access key")
        return token

    def need(key: str) -> None:
        if not key:
            raise HTTPException(status_code=503, detail="this service is not set up on the relay")

    def answer(url: str, params: dict, headers: dict | None = None) -> Response:
        got = _mask(get(url, params, headers or {}), keys.secrets())
        return Response(content=got.body, status_code=got.status, media_type=got.content_type,
                        headers={"Cache-Control": "no-store"})

    def counted(token: Token, service: str, call: Callable[[], Response]) -> Response:
        ok = False
        try:
            response = call()
            ok = response.status_code < 400
            return response
        finally:
            store.record(token.id, service, ok)

    @app.get("/relay/health")
    def health() -> dict:
        return {"ok": True, "services": {"vworld": bool(keys.vworld), "datago": bool(keys.datago),
                                         "law": bool(keys.law), "vworld3d": bool(keys.vworld3d)}}

    @app.get("/relay/vworld3d")
    def vworld3d_page(request: Request) -> Response:
        # Opened as a frame's address, so the access key comes as a parameter (like map images).
        # Not counted as an API call: VWorld's own viewer loads the map from here on.
        if not keys.vworld3d:
            raise HTTPException(status_code=503, detail="3D map is not set up on the relay")
        access_key(request, image=True)
        return Response(content=webgl3d_page(keys.vworld3d), media_type="text/html; charset=utf-8", headers={
            "Cache-Control": "no-store",
            # VWorld sees only this server's address, never the access key in this page's address
            "Referrer-Policy": "origin",
            "Content-Security-Policy": f"frame-ancestors {WEBGL3D_FRAME_ANCESTORS}",
        })

    @app.get("/relay/vworld3d-frame.js")
    def vworld3d_script() -> Response:
        return Response(content=(STATIC / "vworld3d-frame.js").read_bytes(),
                        media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "no-cache"})

    def private(answer: dict, status: int = 200) -> Response:
        return Response(content=json.dumps(answer), status_code=status, media_type="application/json",
                        headers={"Cache-Control": "no-store"})

    @app.post("/relay/requests", status_code=201)
    def request_key(body: KeyRequestBody, request: Request) -> Response:
        sender = address(request)
        if not address_per_minute.take(sender) or not requests_per_hour.take(sender):
            raise HTTPException(status_code=429, detail="too many key requests")
        try:
            claim, record = store.request(body.name, body.contact)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return private({"id": record.id, "claim": claim, "state": record.state}, 201)

    @app.post("/relay/requests/claim")
    def claim_key(body: ClaimBody, request: Request) -> Response:
        if not address_per_minute.take(address(request)):
            raise HTTPException(status_code=429, detail="too many requests")
        found = store.collect(body.claim)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown key request")
        record, token = found
        answer = {"id": record.id, "state": record.state}
        if token:
            answer["key"] = token
        return private(answer)

    @app.get("/relay/vworld/{path:path}")
    def vworld(path: str, request: Request) -> Response:
        tile = _VWORLD_TILE.match(path)
        image = bool(tile) or path == _VWORLD_WMS
        if not (image or _VWORLD_DATA.match(path)):
            raise HTTPException(status_code=404, detail="not a relayed path")
        params = _client_params(request)
        need(keys.vworld)
        token = access_key(request, image=image)
        if tile:
            z, y, x = tile.groups()
            return answer(f"{VWORLD_URL}/req/wmts/1.0.0/{keys.vworld}/Base/{z}/{y}/{x}.png", {})
        if image:
            return answer(f"{VWORLD_URL}/{path}", {**params, "key": keys.vworld, "domain": keys.vworld_domain})
        auth = {"key": keys.vworld} if path == "req/search" else {"key": keys.vworld, "domain": keys.vworld_domain}
        return counted(token, "vworld", lambda: answer(f"{VWORLD_URL}/{path}", {**params, **auth}))

    @app.get("/relay/datago/{path:path}")
    def datago(path: str, request: Request) -> Response:
        if path not in _DATAGO_PATHS:
            raise HTTPException(status_code=404, detail="not a relayed path")
        params = _client_params(request)
        need(keys.datago)
        token = access_key(request, image=False)
        # 토지이음 refuses a call without an Accept header (sida/experts/site/datago.py).
        accept = {"Accept": request.headers.get("accept", "application/xml")}
        return counted(token, "datago",
                       lambda: answer(f"{DATAGO_URL}/{path}", {"serviceKey": keys.datago, **params}, accept))

    @app.get("/relay/law/DRF/{path}")
    def law(path: str, request: Request) -> Response:
        params = _client_params(request)
        if path not in _LAW_PATHS or params.get("target") not in _LAW_TARGETS:
            raise HTTPException(status_code=404, detail="not a relayed path")
        need(keys.law)
        token = access_key(request, image=False)
        return counted(token, "law", lambda: answer(f"{LAW_URL}/{path}", {"OC": keys.law, **params}))

    def ledger_listed() -> set[str]:
        try:
            manifest = json.loads((ledger_dir / LEDGER_MANIFEST).read_text(encoding="utf-8"))
            return {p["file"] for p in manifest["packs"]}
        except (OSError, ValueError, KeyError, TypeError):
            return set()

    @app.get("/relay/ledger/manifest.json")
    def ledger_manifest(request: Request) -> Response:
        token = access_key(request, image=False)
        path = ledger_dir / LEDGER_MANIFEST if ledger_dir else None
        if path is None or not path.is_file():
            raise HTTPException(status_code=503, detail="건축물대장 packs are not set up on the relay")
        store.record(token.id, "ledger", True)
        return Response(content=path.read_bytes(), media_type="application/json", headers={"Cache-Control": "no-cache"})

    @app.get("/relay/ledger/{name}")
    def ledger_file(name: str, request: Request) -> Response:
        if not _LEDGER_FILE.match(name):
            raise HTTPException(status_code=404, detail="not a relayed path")
        token = access_key(request, image=False)
        if not ledger_dir or name not in ledger_listed() or not (ledger_dir / name).is_file():
            raise HTTPException(status_code=404, detail="no such pack")
        store.record(token.id, "ledger", True)
        return FileResponse(ledger_dir / name, media_type="application/gzip", filename=name)

    # ------------------------------------------------------------ shares (공유)

    def share_store() -> ShareStore:
        if shares is None:
            raise HTTPException(status_code=503, detail="sharing is not set up on the relay")
        return shares

    def owner_key(request: Request) -> Token:
        """The designer's access key; managing shares is not counted as an API call."""
        if not address_per_minute.take(address(request)):
            raise HTTPException(status_code=429, detail="too many requests")
        sent = request.headers.get("authorization", "")
        value = sent[7:].strip() if sent.lower().startswith("bearer ") else ""
        token = store.find(value) if value else None
        if token is None:
            raise HTTPException(status_code=401, detail="Sida access key missing or unknown")
        if not token.usable(store.now().date()):
            raise HTTPException(status_code=403, detail="Sida access key revoked or expired")
        return token

    def owned(share_id: str, token: Token):
        share = share_store().owned(share_id, token.id)
        if share is None:
            raise HTTPException(status_code=404, detail="no such share")
        return share

    async def upload_body(request: Request) -> bytes:
        limit = share_store().limits.share_bytes + UPLOAD_SLACK
        try:
            sent = int(request.headers.get("content-length") or 0)
        except ValueError:
            sent = 0
        if sent > limit:
            raise HTTPException(status_code=413, detail="snapshot too large")
        body = await request.body()
        if len(body) > limit:
            raise HTTPException(status_code=413, detail="snapshot too large")
        return body

    def refused(exc: Exception) -> HTTPException:
        if isinstance(exc, LimitReached):
            return HTTPException(status_code=429, detail={"code": exc.code, "message": str(exc)})
        return HTTPException(status_code=400, detail=str(exc))

    def owner_view(share) -> dict:
        return share_store().describe(share, owner=True)

    @app.get("/relay/shares")
    def list_shares(request: Request) -> Response:
        token = owner_key(request)
        found = share_store()
        return private({"shares": [owner_view(s) for s in found.owner_shares(token.id)], "usage": found.usage(token.id)})

    @app.post("/relay/shares", status_code=201)
    async def create_share(request: Request) -> Response:
        token = owner_key(request)
        body = await upload_body(request)
        try:
            share = share_store().create(token.id, body)
        except (ShareError, LimitReached) as exc:
            raise refused(exc) from exc
        return private({**owner_view(share), "usage": share_store().usage(token.id)}, 201)

    @app.get("/relay/shares/{share_id}")
    def get_share(share_id: str, request: Request) -> Response:
        return private(owner_view(owned(share_id, owner_key(request))))

    @app.put("/relay/shares/{share_id}")
    async def new_version(share_id: str, request: Request) -> Response:
        token = owner_key(request)
        share = owned(share_id, token)
        body = await upload_body(request)
        try:
            share_store().add_version(share, body)
        except (ShareError, LimitReached) as exc:
            raise refused(exc) from exc
        return private({**owner_view(share_store().get(share.id)), "usage": share_store().usage(token.id)})

    @app.patch("/relay/shares/{share_id}")
    def change_share(share_id: str, body: ShareChange, request: Request) -> Response:
        share = owned(share_id, owner_key(request))
        return private(owner_view(share_store().change(share, comments_open=body.comments_open, new_links=body.new_links)))

    @app.delete("/relay/shares/{share_id}")
    def delete_share(share_id: str, request: Request) -> Response:
        share = owned(share_id, owner_key(request))
        share_store().delete(share.id)
        return private({"deleted": share.id})

    @app.get("/relay/shares/{share_id}/comments")
    def owner_comments(share_id: str, request: Request) -> Response:
        share = owned(share_id, owner_key(request))
        return private({"comments": share_store().comments(share.id)})

    @app.post("/relay/shares/{share_id}/comments", status_code=201)
    def owner_reply(share_id: str, body: dict, request: Request) -> Response:
        share = owned(share_id, owner_key(request))
        if not body.get("parent"):
            raise HTTPException(status_code=400, detail="the designer answers a comment (parent)")
        try:
            comment = share_store().add_comment(share, body, by_owner=True)
        except (ShareError, LimitReached) as exc:
            raise refused(exc) from exc
        return private(comment, 201)

    @app.patch("/relay/shares/{share_id}/comments/{comment_id}")
    def resolve_comment(share_id: str, comment_id: str, body: ResolveBody, request: Request) -> Response:
        share = owned(share_id, owner_key(request))
        if not share_store().resolve(share, comment_id, body.resolved):
            raise HTTPException(status_code=404, detail="no such comment")
        return private({"id": comment_id, "resolved": body.resolved})

    @app.delete("/relay/shares/{share_id}/comments/{comment_id}")
    def delete_comment(share_id: str, comment_id: str, request: Request) -> Response:
        share = owned(share_id, owner_key(request))
        if not share_store().delete_comment(share, comment_id):
            raise HTTPException(status_code=404, detail="no such comment")
        return private({"deleted": comment_id})

    # The viewer: /s/<link> is the page, the rest is what it reads. No access key; the link is the key.

    def viewer_file(name: str) -> Response:
        if viewer_dir is None or name not in VIEWER_FILES or not (viewer_dir / name).is_file():
            raise HTTPException(status_code=404, detail="not found")
        media = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
                 "html": "text/html; charset=utf-8"}[name.rsplit(".", 1)[-1]]
        return Response(content=(viewer_dir / name).read_bytes(), media_type=media,
                        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

    def opened(link: str, request: Request):
        if not address_per_minute.take(address(request)):
            raise HTTPException(status_code=429, detail="too many requests")
        found = share_store().by_link(link)
        if found is None:
            raise HTTPException(status_code=404, detail="this share is gone or the link was changed")
        return found

    def public(answer: dict, status: int = 200) -> Response:
        return Response(content=json.dumps(answer), status_code=status, media_type="application/json",
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    @app.get("/s/vendor/three.js")
    def viewer_three() -> Response:
        return viewer_file("vendor/three.js")

    @app.get("/s/{link}")
    def viewer_page(link: str, request: Request) -> Response:
        if link in VIEWER_FILES:
            return viewer_file(link)
        opened(link, request)
        page = viewer_file(VIEWER_PAGE)
        page.headers.update({
            "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": VIEWER_CSP,
        })
        return page

    @app.get("/s/{link}/info")
    def viewer_info(link: str, request: Request) -> Response:
        share, can_comment = opened(link, request)
        return public({**share_store().describe(share, owner=False), "can_comment": can_comment,
                       "around": bool(keys.vworld3d)})

    @app.get("/s/{link}/v/{version}/{name:path}")
    def viewer_data(link: str, version: int, name: str, request: Request) -> Response:
        share, _ = opened(link, request)
        path = share_store().file(share, version, name)
        if path is None:
            raise HTTPException(status_code=404, detail="not in this share")
        media = "application/json" if name.endswith(".json") else ("image/png" if name.endswith(".png") else "image/jpeg")
        # A version never changes once uploaded, but the link may be turned off: the browser
        # keeps it only for this visit.
        return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=600",
                                                              "X-Robots-Tag": "noindex"})

    @app.get("/s/{link}/parcels")
    def viewer_parcels(link: str, request: Request) -> Response:
        """
        The site's parcel boundaries, asked of VWorld now: VWorld's data may not be stored
        (이용약관 제19조), so a snapshot holds only the parcel numbers. Nothing is kept here either.
        """
        share, _ = opened(link, request)
        need(keys.vworld)
        if not parcels_per_minute.take(link):
            raise HTTPException(status_code=429, detail="too many requests")
        pnus = share_store().parcel_numbers(share)
        found = []
        for pnu in pnus:
            got = get(f"{VWORLD_URL}/req/data", {
                "service": "data", "request": "GetFeature", "data": "LP_PA_CBND_BUBUN", "key": keys.vworld,
                "domain": keys.vworld_domain, "format": "json", "crs": "EPSG:4326", "geometry": "true",
                "attribute": "true", "size": 10, "attrFilter": f"pnu:=:{pnu}",
            }, {})
            try:
                data = json.loads(got.body)
                features = data["response"]["result"]["featureCollection"]["features"]
            except (ValueError, KeyError, TypeError):
                continue
            for feature in features:
                if str((feature.get("properties") or {}).get("pnu") or "") == pnu and feature.get("geometry"):
                    found.append({"pnu": pnu, "shape": feature["geometry"]})
                    break
        return public({"parcels": found})

    @app.get("/s/{link}/around")
    def viewer_around(link: str, request: Request) -> Response:
        """
        VWorld's 3D map around the site for the viewer (the app's 3D page with the server's 3D key,
        shown as a one-colour model by the viewer). Only the viewer page on this server may frame
        it; nothing of VWorld's passes through or is kept here.
        """
        opened(link, request)
        if not keys.vworld3d:
            raise HTTPException(status_code=503, detail="3D map is not set up on the relay")
        if not around_per_minute.take(link):
            raise HTTPException(status_code=429, detail="too many requests")
        return Response(content=webgl3d_page(keys.vworld3d), media_type="text/html; charset=utf-8", headers={
            "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "origin",  # VWorld checks the key against this server's address only
            "Content-Security-Policy": "frame-ancestors 'self'",
        })

    @app.get("/s/{link}/vworld3d-frame.js")
    def viewer_around_script(link: str) -> Response:
        return vworld3d_script()

    @app.get("/s/{link}/comments")
    def viewer_comments(link: str, request: Request) -> Response:
        share, _ = opened(link, request)
        return public({"comments": share_store().comments(share.id)})

    @app.post("/s/{link}/comments", status_code=201)
    def viewer_comment(link: str, body: dict, request: Request) -> Response:
        share, can_comment = opened(link, request)
        if not can_comment:
            raise HTTPException(status_code=403, detail="this link is for looking only")
        if not share.comments_open:
            raise HTTPException(status_code=403, detail="the designer is not taking new comments")
        if not comments_per_minute.take(f"{link}|{address(request)}"):
            raise HTTPException(status_code=429, detail="too many comments; wait a minute")
        try:
            comment = share_store().add_comment(share, body)
        except (ShareError, LimitReached) as exc:
            raise refused(exc) from exc
        return public(comment, 201)

    return app


def from_env() -> FastAPI:
    share_dir = os.environ.get("SIDA_SHARE_DIR", "").strip()
    viewer_dir = os.environ.get("SIDA_VIEWER_DIR", "").strip()
    return create_app(Keys.from_env(), TokenStore(os.environ.get("SIDA_RELAY_DB", "/data/relay.db")),
                      ledger_dir=Path(os.environ.get("SIDA_LEDGER_DIR", "/ledger")),
                      shares=ShareStore(share_dir, limits=Limits.from_env()) if share_dir else None,
                      viewer_dir=Path(viewer_dir) if viewer_dir else None)
