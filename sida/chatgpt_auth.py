"""Sign in with ChatGPT: run the Conductor on the user's own ChatGPT plan instead of an API key.

OpenAI's open-source / locally hosted flow (developers.openai.com/siwc/token-sharing-open-source):
OAuth 2 authorization code + PKCE in the user's browser, no client secret. The first sign-in
registers this PC as a client (`client_id=dynamic_agent_client`) and the callback returns an
issued client id, reused for every later sign-in. The callback is this web server's own
`/auth/callback` on 127.0.0.1 (only the port may change between sign-ins).

One ChatGPT account per PC. Tokens are kept in CREDENTIALS_PATH (outside the repository,
owner-only permissions) and never returned by the JSON API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import jwt
import requests

from sida.providers import LLMError

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
MODELS_URL = f"{RESOURCE}/models"
REGISTER_CLIENT_ID = "dynamic_agent_client"
AGENT_NAME = "Sida"
CALLBACK_PATH = "/auth/callback"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"
CREDENTIALS_PATH = Path.home() / "Sida" / "chatgpt_login.json"
PENDING_SECONDS = 600  # a sign-in started on the settings screen must finish within this
REFRESH_MARGIN = 120  # refresh this many seconds before the access token expires
# Refresh failures that mean the token set is gone for good: sign in again.
DEAD_REFRESH_ERRORS = frozenset(
    {
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    }
)

_pending: dict[str, dict] = {}  # state → one sign-in attempt waiting for its callback
_lock = threading.Lock()  # serializes refreshes and writes of CREDENTIALS_PATH


class LoginError(Exception):
    """A sign-in step failed. The message is shown on the callback page."""


# ---------------------------------------------------------------------------
# HTTP (tests replace these)
# ---------------------------------------------------------------------------


def _unreachable(message: str) -> LLMError:
    err = LLMError(message)
    err.retryable = True  # type: ignore[attr-defined]  # a network blip, not a dead sign-in
    return err


def _http_post_form(url: str, data: dict) -> tuple[int, dict]:
    try:
        response = requests.post(url, data=data, timeout=30)
    except requests.RequestException as exc:
        raise _unreachable(f"ChatGPT sign-in server unreachable: {exc}") from exc
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {"detail": response.text[:300]}
    return response.status_code, body if isinstance(body, dict) else {}


def _http_get_json(url: str, token: str | None = None) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise _unreachable(f"ChatGPT server unreachable: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:300]}
    return response.status_code, body if isinstance(body, dict) else {}


# ---------------------------------------------------------------------------
# Stored credentials
# ---------------------------------------------------------------------------


def _load() -> dict:
    try:
        data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    """Write atomically with owner-only permissions (0600 on Unix)."""
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CREDENTIALS_PATH.with_name(CREDENTIALS_PATH.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CREDENTIALS_PATH)


def host_id(data: dict) -> str:
    """This PC's opaque host identifier: a UUIDv4 made once and kept (not a user identifier)."""
    if not data.get("ext_agent_host_id"):
        data["ext_agent_host_id"] = f"urn:uuid:{uuid.uuid4()}"
    return str(data["ext_agent_host_id"])


def status() -> dict:
    """What the settings screen shows. No token values."""
    data = _load()
    session = data.get("session") or {}
    return {
        "signed_in": bool(session.get("refresh_token")),
        "email": session.get("email") or "",
        "plan_usage": PLAN_SCOPE in (session.get("scopes") or []),
        "registered": bool(data.get("client_id")),
    }


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------


def redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}{CALLBACK_PATH}"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def start_login(port: int, *, new_account: bool = False) -> dict:
    """
    Begin a sign-in; returns {authorize_url} for the screen to open in the browser.
    The first sign-in (or `new_account`) registers this PC; later ones reuse the issued
    client id and hint the account signed in before.
    """
    with _lock:
        data = _load()
        hid = host_id(data)
        _save(data)
    verifier = _b64url(secrets.token_bytes(32))
    state = _b64url(secrets.token_bytes(24))
    nonce = _b64url(secrets.token_bytes(24))
    client_id = "" if new_account else str(data.get("client_id") or "")
    params = {
        "client_id": client_id or REGISTER_CLIENT_ID,
        "ext_agent_host_id": hid,
        "response_type": "code",
        "redirect_uri": redirect_uri(port),
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
    }
    if client_id:
        last = data.get("last_login") or {}
        if last.get("id_token"):
            params["id_token_hint"] = last["id_token"]
        if last.get("email"):
            params["login_hint"] = last["email"]
    else:
        params["agent_name_hint"] = AGENT_NAME
    now = time.time()
    with _lock:
        for old in [s for s, p in _pending.items() if p["expires"] < now]:
            del _pending[old]
        _pending[state] = {
            "verifier": verifier,
            "nonce": nonce,
            "redirect_uri": params["redirect_uri"],
            "client_id": client_id,  # "" while registering
            "expires": now + PENDING_SECONDS,
        }
    return {"authorize_url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


def _discovery() -> dict:
    code, body = _http_get_json(DISCOVERY_URL)
    if code != 200:
        raise LoginError(f"OpenAI sign-in configuration unavailable (HTTP {code})")
    return body


def validate_id_token(id_token: str, *, client_id: str, nonce: str) -> dict:
    """Check the ID token's signature (OpenAI's JWKS), issuer, audience, expiry and nonce."""
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise LoginError(f"invalid ID token: {exc}") from exc
    code, jwks = _http_get_json(str(_discovery().get("jwks_uri") or ""))
    if code != 200:
        raise LoginError(f"OpenAI signing keys unavailable (HTTP {code})")
    match = [k for k in jwks.get("keys") or [] if k.get("kid") == header.get("kid")]
    if not match:
        raise LoginError("ID token signed with an unknown key")
    try:
        key = jwt.PyJWK(match[0]).key
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256", "ES256"],
            audience=client_id,
            issuer=ISSUER,
            leeway=5,
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise LoginError(f"invalid ID token: {exc}") from exc
    if claims.get("nonce") != nonce:
        raise LoginError("ID token nonce does not match this sign-in")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise LoginError("ID token has no subject")
    return claims


def _session(tokens: dict, *, email: str, subject: str) -> dict:
    scope = tokens.get("scope")
    scopes = sorted(str(scope).split()) if scope else []
    return {
        "email": email,
        "subject": subject,
        "access_token": str(tokens.get("access_token") or ""),
        "refresh_token": str(tokens.get("refresh_token") or ""),
        "expires_at": time.time() + float(tokens.get("expires_in") or 3600),
        "earliest_refresh_at": tokens.get("earliest_refresh_at"),
        "scopes": scopes,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def finish_login(params: dict[str, str]) -> dict:
    """Handle the browser's return to /auth/callback. Returns status(); raises LoginError."""
    state = params.get("state") or ""
    with _lock:
        pending = _pending.pop(state, None)
    if pending is None or pending["expires"] < time.time():
        raise LoginError("this sign-in expired or was already used; start again from settings")
    if params.get("error"):
        raise LoginError(f"sign-in was not completed ({params['error']})")
    issued = params.get("client_id") or ""
    client_id = pending["client_id"]
    if not client_id:  # registering this PC
        if not issued or issued == REGISTER_CLIENT_ID:
            raise LoginError("registration did not return a client id")
        client_id = issued
    elif issued and issued != client_id:
        raise LoginError("the callback named a different client id")
    if not params.get("code"):
        raise LoginError("the callback carried no authorization code")
    code, tokens = _http_post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": params["code"],
            "code_verifier": pending["verifier"],
            "redirect_uri": pending["redirect_uri"],
            "resource": RESOURCE,
        },
    )
    if code != 200 or not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise LoginError(f"token exchange failed (HTTP {code}): {_error_code(tokens)}")
    claims = validate_id_token(
        str(tokens.get("id_token") or ""), client_id=client_id, nonce=pending["nonce"]
    )
    email = str(claims.get("email") or "")
    with _lock:
        data = _load()
        data["client_id"] = client_id
        data["session"] = _session(tokens, email=email, subject=claims["sub"])
        data["last_login"] = {"id_token": tokens["id_token"], "email": email}
        _save(data)
    return status()


def _error_code(body: dict) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or error.get("type") or error.get("message") or "error")
    return str(error or body.get("detail") or "unknown error")


# ---------------------------------------------------------------------------
# Using the session
# ---------------------------------------------------------------------------


def access_token() -> str:
    """A valid access token, refreshed when it is about to expire. Raises LLMError."""
    with _lock:
        data = _load()
        session = data.get("session") or {}
        if not session.get("refresh_token"):
            raise LLMError("ChatGPT is not signed in. Sign in on the settings screen.")
        if PLAN_SCOPE not in (session.get("scopes") or []):
            raise LLMError(
                "This ChatGPT sign-in does not allow using the plan in Sida. Sign in again "
                "and approve plan usage, or check that the plan is Go, Plus or Pro."
            )
        now = time.time()
        expires = float(session.get("expires_at") or 0)
        earliest = float(session.get("earliest_refresh_at") or 0)
        if now < expires - REFRESH_MARGIN or now < min(earliest, expires):
            return str(session["access_token"])
        code, tokens = _http_post_form(
            TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "client_id": data.get("client_id") or "",
                "refresh_token": session["refresh_token"],
                "resource": RESOURCE,
            },
        )
        if code == 200 and tokens.get("access_token"):
            fresh = _session(
                {
                    "scope": " ".join(session.get("scopes") or []),
                    "refresh_token": session["refresh_token"],
                    **tokens,
                },
                email=session.get("email") or "",
                subject=session.get("subject") or "",
            )
            data["session"] = fresh
            _save(data)
            return fresh["access_token"]
        reason = _error_code(tokens)
        if reason in DEAD_REFRESH_ERRORS:
            data.pop("session", None)  # the issued client id stays for the next sign-in
            _save(data)
            raise LLMError("ChatGPT sign-in has expired. Sign in again on the settings screen.")
        if code >= 500:
            raise _unreachable(f"ChatGPT sign-in server error (HTTP {code}); try again shortly.")
        raise LLMError(f"ChatGPT token refresh failed (HTTP {code}): {reason}")


def list_models() -> list[dict]:
    """Models this ChatGPT account can use, in the server's order: [{slug, display_name}]."""
    code, body = _http_get_json(MODELS_URL, access_token())
    if code != 200:
        raise LLMError(f"ChatGPT model list failed (HTTP {code}): {_error_code(body)}")
    return [
        {"slug": str(m["slug"]), "display_name": str(m.get("display_name") or m["slug"])}
        for m in body.get("models") or []
        if isinstance(m, dict) and m.get("visibility") == "list" and m.get("slug")
    ]


def sign_out() -> dict:
    """
    Revoke the refresh token and forget the session (the issued client id is kept).
    Returns {revoked}; false means the user should also disconnect Sida in ChatGPT settings.
    """
    with _lock:
        data = _load()
        session = data.pop("session", None) or {}
        _save(data)
    token = session.get("refresh_token")
    if not token:
        return {"revoked": True}
    try:
        endpoint = str(_discovery().get("revocation_endpoint") or "")
        code, _ = _http_post_form(
            endpoint,
            {
                "token": token,
                "token_type_hint": "refresh_token",
                "client_id": data.get("client_id") or "",
            },
        )
    except (LLMError, LoginError):
        return {"revoked": False}
    return {"revoked": code == 200}


def reset_pending() -> None:
    """Forget sign-ins in progress (tests)."""
    with _lock:
        _pending.clear()
