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
  is then in the viewer's browser, as with any web map; it is a key of its own
  (VWORLD_3D_API_KEY) where one is set, and only the Sida app's own pages may frame the page.

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
from pydantic import BaseModel, ConfigDict, Field

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
    vworld3d: str = ""  # a key of its own for the 3D map, which ends up in viewers' browsers

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

    @property
    def webgl3d(self) -> str:
        """The key the 3D page carries: the 3D map's own, or else the server's VWorld key."""
        return self.vworld3d or self.vworld

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


def create_app(
    keys: Keys, store: TokenStore, *, fetch: Fetch | None = None, clock: Callable[[], float] = time.monotonic
) -> FastAPI:
    app = FastAPI(title="Sida relay", docs_url=None, redoc_url=None, openapi_url=None)
    get = fetch or _fetch
    calls_per_minute = MinuteLimit(CALLS_PER_MINUTE, clock)
    images_per_minute = MinuteLimit(IMAGES_PER_MINUTE, clock)
    address_per_minute = MinuteLimit(ADDRESS_PER_MINUTE, clock)
    requests_per_hour = MinuteLimit(REQUESTS_PER_HOUR, clock, window=3600)

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
                                         "law": bool(keys.law), "vworld3d": bool(keys.webgl3d)}}

    @app.get("/relay/vworld3d")
    def vworld3d_page(request: Request) -> Response:
        # Opened as a frame's address, so the access key comes as a parameter (like map images).
        # Not counted as an API call: VWorld's own viewer loads the map from here on.
        need(keys.webgl3d)
        access_key(request, image=True)
        return Response(content=webgl3d_page(keys.webgl3d), media_type="text/html; charset=utf-8", headers={
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

    return app


def from_env() -> FastAPI:
    return create_app(Keys.from_env(), TokenStore(os.environ.get("SIDA_RELAY_DB", "/data/relay.db")))
