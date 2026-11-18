"""The ground and the 건축물대장 around a site from the Sida relay, for a PC without the packs.

A PC with terrain packs (terrain_pack.py) and ledger packs (ledger_pack.py) reads them, as
before. Without them, the surroundings ask the relay for just what one site needs
(relay/app.py), with this person's Sida access key (sida/relay.py):

- POST /relay/terrain/ground {lon, lat, radius}: the ground within ±radius m of the site's middle
  as context3d.shared_ground makes it on the server: metres from the site's middle and heights
  relative to the ground there, never lon/lat or heights above sea level (국토지리정보원
  보안관리규정 [별표 1]: no coordinates together with 1:5,000 contours or spot heights online).
  The app always asks for ASK_RADIUS m and cuts smaller ranges from it, so a change of range does
  not ask again. The answer is kept in <terrain folder>/cache (CACHE_BYTES at most, the least
  recently used goes first), so a site drawn once is drawn again without the internet.
- POST /relay/ledger/lookup {pnus}: 건축물대장 표제부 rows by PNU from the server's monthly packs
  ({"rows": {pnu: [row]}, "month"}); PNUs no pack covers are left out, as ledger_pack.lookup does.

Nothing here raises for a missing key, a refusal or no network: the caller goes on without
(flat ground, or data.go.kr live for the 대장).
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import requests

from sida import relay
from sida.experts.site import landapi, terrain_pack

GROUND_PATH = "/relay/terrain/ground"
LEDGER_PATH = "/relay/ledger/lookup"
FORMAT = 1
ASK_RADIUS = 500.0  # m: the app's largest range (context3d.MAX_RADIUS)
MAX_RADIUS = 1500.0  # m: the most the relay sends (a 3 km side)
MAX_PNUS = 2000  # PNUs per ledger lookup
TIMEOUT = 30
CACHE = "cache"
CACHE_BYTES = 500_000_000


class SiteRelayError(Exception):
    """kind: no_relay, refused (the relay refused the key), network, bad_response."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind, detail)
        self.kind = kind
        self.detail = detail


def _load_env() -> None:
    if landapi.ENV_PATH.exists():
        from dotenv import load_dotenv

        load_dotenv(landapi.ENV_PATH, override=False)


def _http_post(url: str, body: dict) -> dict:
    """The relay's JSON answer. Errors never carry the URL."""
    try:
        response = requests.post(url, json=body, timeout=TIMEOUT, headers=relay.headers(url))
    except requests.RequestException as exc:
        raise SiteRelayError("network", type(exc).__name__) from None
    if response.status_code in (401, 403):
        raise SiteRelayError("refused", f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise SiteRelayError("network", f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise SiteRelayError("bad_response", "not JSON") from None


def _ask(path: str, body: dict) -> dict:
    _load_env()
    base = relay.base_url()
    if not base:
        raise SiteRelayError("no_relay")
    return _http_post(base + path, body)


# ---------------------------------------------------------------------------
# Ground
# ---------------------------------------------------------------------------


def cache_dir(folder: Path | None = None) -> Path:
    return (terrain_pack.TERRAIN_DIR if folder is None else folder) / CACHE


def _cache_path(lon: float, lat: float, folder: Path | None) -> Path:
    return cache_dir(folder) / f"ground_{float(lon):.7f}_{float(lat):.7f}.json.gz"


def _usable(answer, radius: float) -> bool:
    return (isinstance(answer, dict) and answer.get("format") == FORMAT
            and float(answer.get("radius") or 0) >= radius and isinstance(answer.get("contours"), list))


def cached(lon: float, lat: float, radius: float, folder: Path | None = None) -> dict | None:
    """The relay's ground for this site middle kept from before, when it reaches `radius`."""
    path = _cache_path(lon, lat, folder)
    try:
        answer = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError, EOFError):
        return None
    if not _usable(answer, radius):
        return None
    try:
        os.utime(path)  # recently used: kept longest
    except OSError:
        pass
    return answer


def _keep(lon: float, lat: float, answer: dict, folder: Path | None) -> None:
    path = _cache_path(lon, lat, folder)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        part.write_bytes(gzip.compress(json.dumps(answer, separators=(",", ":")).encode()))
        part.replace(path)
        trim(path.parent)
    except OSError:
        pass  # a full disk only costs asking again


def trim(folder: Path, limit: int = CACHE_BYTES) -> None:
    """Delete the least recently used ground answers until the folder holds `limit` bytes or less."""
    files = sorted(folder.glob("ground_*.json.gz"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for path in files:
        if total <= limit:
            break
        total -= path.stat().st_size
        path.unlink(missing_ok=True)


def ground(lon: float, lat: float, radius: float, *, folder: Path | None = None) -> dict | None:
    """
    The relay's ground around this site middle reaching at least `radius` m (context3d.shared_ground),
    from the cache or asked for (ASK_RADIUS m, or more for a bigger range); None when there is
    none: no access key, no answer, or the relay has no ground packs here.
    """
    radius = float(radius)
    hit = cached(lon, lat, radius, folder)
    if hit is not None:
        return hit
    ask = min(max(radius, ASK_RADIUS), MAX_RADIUS)
    if ask < radius:
        return None
    try:
        answer = _ask(GROUND_PATH, {"lon": float(lon), "lat": float(lat), "radius": ask})
    except SiteRelayError:
        return None
    if not _usable(answer, radius):
        return None
    if not answer.get("sources"):  # nothing on the server here: ask again next time
        return None
    _keep(lon, lat, answer, folder)
    return answer


# ---------------------------------------------------------------------------
# 건축물대장
# ---------------------------------------------------------------------------


def ledger(pnus) -> tuple[dict[str, list[dict]], dict | None]:
    """
    ({pnu: rows} for the PNUs the relay's packs cover, {"month": …} or None), like
    ledger_pack.lookup; ({}, None) when the relay can't be asked.
    """
    wanted = sorted(set(pnus))
    asked = set(wanted)
    found: dict[str, list[dict]] = {}
    month = ""
    for k in range(0, len(wanted), MAX_PNUS):
        try:
            answer = _ask(LEDGER_PATH, {"pnus": wanted[k:k + MAX_PNUS]})
        except SiteRelayError:
            break
        rows = answer.get("rows") if isinstance(answer, dict) else None
        if not isinstance(rows, dict):
            break
        for pnu, got in rows.items():
            if pnu in asked and isinstance(got, list):
                found[pnu] = [r for r in got if isinstance(r, dict)]
        month = month or str(answer.get("month") or "")
    return found, ({"month": month, "relay": True} if found or month else None)
