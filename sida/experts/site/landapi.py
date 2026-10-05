#!/usr/bin/env python3
"""Clients for the Korean government land APIs (VWorld). No printing, no project knowledge.

Each function returns plain data or raises LandApiError with a `kind` the caller can
turn into a message:
  no_key | invalid_key | over_limit | network | bad_response

Keys come from .env: VWORLD_API_KEY and VWORLD_DOMAIN (the service URL registered with
the key). Tests pass `http_get` to avoid the network.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import requests

from sida.config import ROOT

ENV_PATH = ROOT / ".env"
VWORLD_URL = "https://api.vworld.kr"
TIMEOUT = 20
ATTEMPTS = 3  # the NED endpoints time out now and then; a retry usually succeeds

HttpGet = Callable[[str, dict], Any]  # (url, params) → parsed JSON


class LandApiError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def vworld_credentials() -> tuple[str, str]:
    """(key, domain) from the environment / .env. Raises LandApiError('no_key')."""
    if ENV_PATH.exists():
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH, override=False)
    key = os.environ.get("VWORLD_API_KEY", "").strip()
    if not key:
        raise LandApiError("no_key", "VWORLD_API_KEY")
    return key, os.environ.get("VWORLD_DOMAIN", "").strip()


def _http_get(url: str, params: dict) -> Any:
    """GET JSON with retries. Error text never includes the request URL (it carries the key)."""
    last = "request failed"
    for attempt in range(ATTEMPTS):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT)
            if response.status_code >= 500:
                last = f"HTTP {response.status_code}"
            elif response.status_code != 200:
                raise LandApiError("bad_response", f"HTTP {response.status_code}")
            else:
                try:
                    return response.json()
                except ValueError as exc:
                    raise LandApiError("bad_response", "not JSON") from exc
        except requests.RequestException as exc:
            last = type(exc).__name__
        if attempt < ATTEMPTS - 1:
            time.sleep(1.0 * (attempt + 1))
    raise LandApiError("network", last)


def _raise_for_code(code: str, message: str) -> None:
    code = (code or "").upper()
    if not code:
        return
    if "KEY" in code or "DOMAIN" in code or "INCORRECT" in code:
        raise LandApiError("invalid_key", message or code)
    if "LIMIT" in code:
        raise LandApiError("over_limit", message or code)
    raise LandApiError("bad_response", message or code)


def search_parcels(
    address: str, *, size: int = 10, http_get: HttpGet | None = None
) -> list[dict]:
    """
    Parcels matching a lot-number address (지번 주소), best match first.
    Each: {"pnu", "address", "road_address", "building", "x", "y"}. Empty list when none.
    """
    key, _domain = vworld_credentials()
    data = (http_get or _http_get)(
        f"{VWORLD_URL}/req/search",
        {
            "service": "search",
            "request": "search",
            "version": "2.0",
            "crs": "EPSG:4326",
            "size": size,
            "page": 1,
            "query": address.strip(),
            "type": "address",
            "category": "parcel",
            "format": "json",
            "key": key,
        },
    )
    response = (data or {}).get("response") or {}
    status = str(response.get("status") or "")
    if status == "NOT_FOUND":
        return []
    if status != "OK":
        error = response.get("error") or {}
        _raise_for_code(str(error.get("code") or status or "ERROR"), str(error.get("text") or ""))
    out = []
    for item in (response.get("result") or {}).get("items") or []:
        addr = item.get("address") or {}
        point = item.get("point") or {}
        pnu = str(item.get("id") or "")
        if len(pnu) != 19:
            continue
        out.append(
            {
                "pnu": pnu,
                "address": str(addr.get("parcel") or ""),
                "road_address": str(addr.get("road") or ""),
                "building": str(addr.get("bldnm") or ""),
                "x": str(point.get("x") or ""),
                "y": str(point.get("y") or ""),
            }
        )
    return out


def _ned(operation: str, root_key: str, pnu: str, http_get: HttpGet | None) -> list[dict]:
    key, domain = vworld_credentials()
    data = (http_get or _http_get)(
        f"{VWORLD_URL}/ned/data/{operation}",
        {"key": key, "domain": domain, "pnu": pnu, "format": "json", "numOfRows": 100, "pageNo": 1},
    )
    body = (data or {}).get(root_key)
    if body is None:
        # Unknown parcel: {"response": {"totalCount": "0", ...}} with no data root.
        fallback = (data or {}).get("response") or {}
        _raise_for_code(str(fallback.get("resultCode") or ""), str(fallback.get("resultMsg") or ""))
        return []
    _raise_for_code(str(body.get("resultCode") or ""), str(body.get("resultMsg") or ""))
    fields = body.get("field") or []
    return [f for f in fields if isinstance(f, dict)]


def land_use(pnu: str, *, http_get: HttpGet | None = None) -> list[dict]:
    """
    토지이용계획: zones and districts on a parcel, duplicates removed, API order kept.
    Each: {"name", "code", "relation" (포함 | 저촉 | 접함), "updated"}.
    """
    seen: set[tuple[str, str]] = set()
    out = []
    for f in _ned("getLandUseAttr", "landUses", pnu, http_get):
        name = str(f.get("prposAreaDstrcCodeNm") or "").strip()
        relation = str(f.get("cnflcAtNm") or "").strip()
        if not name or (name, relation) in seen:
            continue
        seen.add((name, relation))
        out.append(
            {
                "name": name,
                "code": str(f.get("prposAreaDstrcCode") or ""),
                "relation": relation,
                "updated": str(f.get("lastUpdtDt") or ""),
            }
        )
    return out


def land_characteristics(pnu: str, *, http_get: HttpGet | None = None) -> dict | None:
    """
    토지특성 for the most recent base year, or None when the parcel has no record.
    {"year", "land_category", "area_m2", "zone1", "zone2", "use", "terrain_height",
     "terrain_shape", "road_side", "official_price", "updated"}
    """
    rows = _ned("getLandCharacteristics", "landCharacteristicss", pnu, http_get)
    if not rows:
        return None
    latest = max(rows, key=lambda f: (str(f.get("stdrYear") or ""), str(f.get("stdrMt") or "")))

    def number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def named(value: Any) -> str:
        text = str(value or "").strip()
        return "" if text == "지정되지않음" else text

    return {
        "year": str(latest.get("stdrYear") or ""),
        "land_category": named(latest.get("lndcgrCodeNm")),
        "area_m2": number(latest.get("lndpclAr")),
        "zone1": named(latest.get("prposArea1Nm")),
        "zone2": named(latest.get("prposArea2Nm")),
        "use": named(latest.get("ladUseSittnNm")),
        "terrain_height": named(latest.get("tpgrphHgCodeNm")),
        "terrain_shape": named(latest.get("tpgrphFrmCodeNm")),
        "road_side": named(latest.get("roadSideCodeNm")),
        "official_price": number(latest.get("pblntfPclnd")),
        "updated": str(latest.get("lastUpdtDt") or ""),
    }
