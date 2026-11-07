"""Asking the Sida relay for an access key from the settings screen (요청 후 승인).

Someone with no government keys and no Sida key sends a key request (a name and how to reach
them) to the relay (sida/relay.py, relay/app.py). The relay answers with a claim code, which is
kept on this PC outside the repository (REQUEST_PATH, like the ChatGPT sign-in). The team
approves the request on the server (relay/admin.py); the next check from the settings screen
then collects the key with the claim code and saves it to .env as SIDA_RELAY_TOKEN. Neither the
claim code nor the key is ever returned by the JSON API.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from sida import relay, settings

REQUEST_PATH = Path.home() / "Sida" / "relay_request.json"
TIMEOUT = 20
MAX_NAME = 80
MAX_CONTACT = 120


class RelayUnreachable(Exception):
    """The relay did not answer, or answered with something other than what it sends."""


class RelayBusy(Exception):
    """The relay refused for now: too many requests from this address, or too many waiting."""


def _http_post(url: str, body: dict) -> tuple[int, dict]:
    try:
        response = requests.post(url, json=body, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise RelayUnreachable(f"Sida relay unreachable: {type(exc).__name__}") from exc
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    return response.status_code, data if isinstance(data, dict) else {}


def _load() -> dict:
    try:
        data = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("claim") else {}


def _save(data: dict) -> None:
    """Write atomically with owner-only permissions (0600 on Unix): the claim code is a secret."""
    REQUEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REQUEST_PATH.with_name(REQUEST_PATH.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REQUEST_PATH)


def _forget() -> None:
    REQUEST_PATH.unlink(missing_ok=True)


def _view(data: dict, state: str, **extra) -> dict:
    return {"state": state, "name": data.get("name", ""), "requested": data.get("requested", ""), **extra}


def status() -> dict:
    """The key request waiting on this PC, without asking the relay: state "none" or "pending"."""
    data = _load()
    return _view(data, "pending") if data else {"state": "none"}


def ask(name: str, contact: str = "") -> dict:
    """Send a key request to the relay and keep its claim code. ValueError on a bad name or contact."""
    name, contact = " ".join((name or "").split()), " ".join((contact or "").split())
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"name must be 1-{MAX_NAME} characters")
    if len(contact) > MAX_CONTACT:
        raise ValueError(f"contact must be at most {MAX_CONTACT} characters")
    server = relay.server_url()
    if not server:
        raise ValueError("relay_url must be an https address")
    code, body = _http_post(f"{server}/relay/requests", {"name": name, "contact": contact})
    if code == 429:
        raise RelayBusy("too many key requests; try again in an hour")
    if code != 201 or not str(body.get("claim", "")).startswith("sidareq_"):
        raise RelayUnreachable(f"Sida relay answered HTTP {code}")
    data = {
        "server": server,
        "id": str(body.get("id", "")),
        "claim": body["claim"],
        "name": name,
        "requested": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save(data)
    return status()


def check() -> dict:
    """
    Ask the relay about the waiting request. "approved": the key was collected and saved (the
    request is then forgotten); "refused" and "unknown" (the relay no longer knows it) forget it
    too; "pending" stays, with `unreachable` when the relay did not answer.
    """
    data = _load()
    if not data:
        return {"state": "none"}
    try:
        code, body = _http_post(f"{data['server']}/relay/requests/claim", {"claim": data["claim"]})
    except RelayUnreachable:
        return _view(data, "pending", unreachable=True)
    if code == 404:
        _forget()
        return _view(data, "unknown")
    if code != 200:
        return _view(data, "pending", unreachable=True)
    state = body.get("state")
    if state == "pending":
        return _view(data, "pending")
    if state == "refused":
        _forget()
        return _view(data, "refused")
    key = str(body.get("key", ""))
    if state == "delivered" and relay.valid_token(key):
        if data["server"] != relay.server_url():
            settings.set_key("relay_url", data["server"])
        settings.set_key("relay_token", key)
        _forget()
        return _view(data, "approved", key=settings.key_status("relay_token"))
    # Collected before (another check got it) or an answer we don't know: ask again from scratch.
    _forget()
    return _view(data, "unknown")


def cancel() -> dict:
    """Forget the waiting request on this PC (the relay keeps it until the team answers)."""
    _forget()
    return {"state": "none"}
