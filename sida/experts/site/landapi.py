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


def _search(query: str, category: str, size: int, http_get: HttpGet | None) -> list[dict]:
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
            "query": query,
            "type": "address",
            "category": category,
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
    return (response.get("result") or {}).get("items") or []


def _region_of_road_address(road: str) -> str:
    """'경기도 군포시 공단로140번길 46 (당정동)' → '경기도 군포시' (everything before the road name)."""
    region = []
    for token in road.split():
        if any(ch.isdigit() for ch in token) or token.endswith(("로", "길")):
            break
        region.append(token)
    return " ".join(region)


def search_parcels(
    address: str, *, size: int = 10, http_get: HttpGet | None = None
) -> list[dict]:
    """
    Parcels matching an address, best match first. A lot-number address (지번 주소) is tried
    first; only when it matches nothing is the text tried as a road-name address (도로명 주소).
    Each: {"pnu", "address", "road_address", "building", "x", "y", "matched_by"} where
    matched_by is "parcel" or "road". Empty list when neither matches. Nothing is guessed or
    corrected: a misspelt address finds nothing.
    """
    query = " ".join(address.split())
    out: list[dict] = []
    seen: set[str] = set()
    for category in ("parcel", "road"):
        for item in _search(query, category, size, http_get):
            addr = item.get("address") or {}
            point = item.get("point") or {}
            pnu = str(item.get("id") or "")
            if len(pnu) != 19 or pnu in seen:
                continue
            seen.add(pnu)
            parcel, road = str(addr.get("parcel") or ""), str(addr.get("road") or "")
            if category == "road":
                # The road search matches loosely: "군포시 공단로 140" also returns 공단로 140 in
                # other cities. Keep a hit only if it has every 시·군·구 the designer typed.
                if any(token not in road for token in query.split() if token.endswith(("시", "군", "구"))):
                    continue
                # a road-name hit gives the lot number without its 시·군·구 (but with its 읍·면)
                region = _region_of_road_address(road).split()
                while region and region[-1] in parcel.split():
                    region.pop()
                parcel = " ".join([*region, parcel])
            out.append(
                {
                    "pnu": pnu,
                    "address": parcel,
                    "road_address": road,
                    "building": str(addr.get("bldnm") or ""),
                    "x": str(point.get("x") or ""),
                    "y": str(point.get("y") or ""),
                    "matched_by": category,
                }
            )
        if out:
            break
    return out


# ---------------------------------------------------------------------------
# Step-by-step address selection: 시·도 → 시·군·구 → 읍·면·동 (→ 리) → 지번
# ---------------------------------------------------------------------------

# parent code length → (VWorld layer, code field, name field) of its children
_REGION_LAYERS = {
    0: ("LT_C_ADSIDO_INFO", "ctprvn_cd", "ctp_kor_nm"),  # 시·도, 2-digit code
    2: ("LT_C_ADSIGG_INFO", "sig_cd", "sig_kor_nm"),  # 시·군·구, 5
    5: ("LT_C_ADEMD_INFO", "emd_cd", "emd_kor_nm"),  # 읍·면·동, 8
    8: ("LT_C_ADRI_INFO", "li_cd", "li_kor_nm"),  # 리, 10
}
REGION_LEVELS = {0: "sido", 2: "sigungu", 5: "emd", 8: "ri"}
KOREA_BOX = "BOX(124,33,132,39)"  # the 시·도 layer is asked by area: it has no parent code to filter on
PAGE_SIZE = 1000  # the data API's maximum

_region_cache: dict[str, list[dict]] = {}


def clear_cache() -> None:
    _region_cache.clear()


def _features(
    layer: str, http_get: HttpGet | None, *, attr_filter: str = "", geom_filter: str = ""
) -> list[dict]:
    """Attribute rows of a VWorld data-API layer (no geometry), every page."""
    key, domain = vworld_credentials()
    params = {
        "service": "data",
        "request": "GetFeature",
        "data": layer,
        "key": key,
        "domain": domain,
        "format": "json",
        "crs": "EPSG:4326",
        "geometry": "false",
        "attribute": "true",
        "size": PAGE_SIZE,
    }
    if attr_filter:
        params["attrFilter"] = attr_filter
    if geom_filter:
        params["geomFilter"] = geom_filter
    rows: list[dict] = []
    page = 1
    while True:
        data = (http_get or _http_get)(f"{VWORLD_URL}/req/data", {**params, "page": page})
        response = (data or {}).get("response") or {}
        status = str(response.get("status") or "")
        if status == "NOT_FOUND":
            return rows
        if status != "OK":
            error = response.get("error") or {}
            _raise_for_code(str(error.get("code") or status or "ERROR"), str(error.get("text") or ""))
        collection = (response.get("result") or {}).get("featureCollection") or {}
        rows += [f.get("properties") or {} for f in collection.get("features") or [] if isinstance(f, dict)]
        try:
            pages = int((response.get("page") or {}).get("total") or 1)
        except ValueError:
            pages = 1
        if page >= pages:
            return rows
        page += 1


def regions(parent: str = "", *, http_get: HttpGet | None = None) -> list[dict]:
    """
    The administrative areas directly under `parent`, by name:
      ""        → 시·도          "41"       → 시·군·구 of 경기도
      "41410"   → 읍·면·동 of 군포시  "41830250" → 리 of that 읍·면
    Each: {"code", "name", "full_name", "has_ri", "dong_code"}. `dong_code` is the 10-digit
    법정동 code a lot number is found under: a 동's own code + "00", a 리's code; empty for a
    시·도, 시·군·구, or 읍·면 (whose lots are under its 리, so `has_ri` is true). Lists are kept
    in memory for the life of the process. ValueError for a code that is not 0/2/5/8 digits.
    """
    parent = (parent or "").strip()
    if len(parent) not in _REGION_LAYERS or not (parent == "" or parent.isdigit()):
        raise ValueError(f"not a region code: {parent!r}")
    if parent in _region_cache:
        return [dict(r) for r in _region_cache[parent]]
    layer, code_field, name_field = _REGION_LAYERS[len(parent)]
    if parent:
        rows = _features(layer, http_get, attr_filter=f"{code_field}:like:{parent}")
    else:
        rows = _features(layer, http_get, geom_filter=KOREA_BOX)
    width = {0: 2, 2: 5, 5: 8, 8: 10}[len(parent)]
    out: dict[str, dict] = {}
    for row in rows:
        code, name = str(row.get(code_field) or ""), str(row.get(name_field) or "").strip()
        # `like` is a pattern match: keep only real children of the parent
        if len(code) != width or not code.startswith(parent) or not name or code in out:
            continue
        has_ri = width == 8 and name.endswith(("읍", "면"))
        out[code] = {
            "code": code,
            "name": name,
            "full_name": str(row.get("full_nm") or name).strip(),
            "has_ri": has_ri,
            "dong_code": "" if width < 8 or has_ri else code.ljust(10, "0"),
        }
    found = sorted(out.values(), key=lambda r: (r["name"], r["code"]))
    _region_cache[parent] = [dict(r) for r in found]
    return found


def _lot_rows(attr_filter: str, prefix: str, http_get: HttpGet | None) -> list[dict]:
    out: dict[str, dict] = {}
    for row in _features("LP_PA_CBND_BUBUN", http_get, attr_filter=attr_filter):
        pnu = str(row.get("pnu") or "")
        if len(pnu) == 19 and pnu.startswith(prefix):
            out[pnu] = {
                "pnu": pnu,
                "address": " ".join(str(row.get("addr") or "").split()),
                "road_address": "",
                "building": "",
                "matched_by": "lot",
            }
    return [out[p] for p in sorted(out)]


def find_lots(
    dong_code: str,
    main: int,
    sub: int | None = None,
    *,
    mountain: bool = False,
    http_get: HttpGet | None = None,
) -> list[dict]:
    """
    Parcels at a lot number in a 법정동 (10-digit `dong_code` from `regions`). The PNU is built
    from the parts (동 code + 1, or 2 for 산 + 본번 4 digits + 부번 4 digits), not searched for.
    Without `sub`, every parcel of that 본번 (689 → 689, 689-1, 689-14 …). Each: {"pnu",
    "address", "road_address", "building", "matched_by": "lot"} (no road address or building
    name: this layer has neither), by PNU. Empty when
    there is no such parcel. ValueError for parts out of range.
    """
    dong_code = (dong_code or "").strip()
    if len(dong_code) != 10 or not dong_code.isdigit():
        raise ValueError(f"not a 10-digit 법정동 code: {dong_code!r}")
    if not 1 <= main <= 9999 or (sub is not None and not 0 <= sub <= 9999):
        raise ValueError(f"lot number out of range: {main}-{sub}")
    prefix = f"{dong_code}{2 if mountain else 1}{main:04d}"
    if sub is None:
        return _lot_rows(f"pnu:like:{prefix}", prefix, http_get)
    pnu = f"{prefix}{sub:04d}"
    return _lot_rows(f"pnu:=:{pnu}", pnu, http_get)


def parcel_by_pnu(pnu: str, *, http_get: HttpGet | None = None) -> dict | None:
    """The parcel with this 19-digit PNU (same shape as `find_lots`), or None if there is none."""
    pnu = (pnu or "").strip()
    if len(pnu) != 19 or not pnu.isdigit():
        raise ValueError(f"not a 19-digit PNU: {pnu!r}")
    found = _lot_rows(f"pnu:=:{pnu}", pnu, http_get)
    return found[0] if found else None


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
