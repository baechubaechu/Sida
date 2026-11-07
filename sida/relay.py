"""Sida's data server (중계 서버) for the government APIs, for installs without their own keys.

Each government API module (VWorld, data.go.kr, 법제처) calls the service directly when this
PC has its own key, as before. Without one, it calls the relay instead, when both its address
(SIDA_RELAY_URL) and this person's access key (SIDA_RELAY_TOKEN, sida_…, given by the team)
are set in .env from the settings screen. The relay adds the server's government key, calls the
service and passes the answer back unchanged. The app sends the relay no government key.

The relay server itself is in relay/ at the top of the repository (not part of this package).
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

ENV_NAME = "SIDA_RELAY_URL"
TOKEN_ENV = "SIDA_RELAY_TOKEN"
TOKEN_PARAM = "sida_token"  # map images: the browser can't send a header
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def valid_url(value: str) -> bool:
    """An https address, or http only for this PC (a relay run for testing)."""
    parts = urlsplit((value or "").strip())
    if not parts.hostname or parts.query or parts.fragment or parts.username or parts.password:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS)


def valid_token(value: str) -> bool:
    value = (value or "").strip()
    return value.startswith("sida_") and 10 < len(value) <= 100 and value.isascii() and " " not in value


def token() -> str:
    """This person's access key from the environment; "" when not set."""
    value = os.environ.get(TOKEN_ENV, "").strip()
    return value if valid_token(value) else ""


def base_url() -> str:
    """
    The relay address from the environment, without a trailing slash; "" when no address or no
    access key is set (or either is not valid). The API modules load .env before asking.
    """
    value = os.environ.get(ENV_NAME, "").strip().rstrip("/")
    return value if valid_url(value) and token() else ""


def headers(url: str) -> dict[str, str]:
    """The access key header for a request to `url` when it goes to the relay; {} otherwise."""
    base = base_url()
    if base and url.startswith(base + "/"):
        return {"Authorization": f"Bearer {token()}"}
    return {}
