"""Sida's data server (중계 서버) for the government APIs, for installs without their own keys.

Each government API module (VWorld, data.go.kr, 법제처) calls the service directly when this
PC has its own key, as before. Without one, it calls the relay instead, when this person has an
access key (SIDA_RELAY_TOKEN, sida_…): asked for from the settings screen (sida/relay_key.py) or
given by the team. The relay is the team's server (DEFAULT_URL) unless SIDA_RELAY_URL names
another. The relay adds the server's government key, calls the service and passes the answer
back unchanged. The app sends the relay no government key.

The relay server itself is in relay/ at the top of the repository (not part of this package).
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

ENV_NAME = "SIDA_RELAY_URL"
TOKEN_ENV = "SIDA_RELAY_TOKEN"
TOKEN_PARAM = "sida_token"  # map images: the browser can't send a header
DEFAULT_URL = "https://sida-kr.duckdns.org"  # the team's server (a real domain before the CBT)
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


def server_url() -> str:
    """
    The relay address without a trailing slash: SIDA_RELAY_URL, or the team's server when it is
    not set; "" when it is set but not valid.
    """
    value = os.environ.get(ENV_NAME, "").strip().rstrip("/")
    if not value:
        return DEFAULT_URL
    return value if valid_url(value) else ""


def base_url() -> str:
    """
    The relay address the API modules call; "" when there is no access key (or no valid address).
    The API modules load .env before asking.
    """
    return server_url() if token() else ""


def headers(url: str) -> dict[str, str]:
    """The access key header for a request to `url` when it goes to the relay; {} otherwise."""
    base = base_url()
    if base and url.startswith(base + "/"):
        return {"Authorization": f"Bearer {token()}"}
    return {}
