"""Clients for the land APIs on data.go.kr (공공데이터포털). No printing, no project knowledge.

- 토지이음 행위제한: which uses a zone allows (DTarLandUseInfo) and the use names it knows
  (DTsearchLunCd)
- 토지이음 건축제한 근거 조문: the statute and ordinance articles behind a zone's limits
  (DTluLawInfo)
- 건축물대장 표제부: buildings registered on a parcel (getBrTitleInfo)

Errors are DataGoError, a LandApiError (from landapi) with the same kinds: no_key | invalid_key |
over_limit | network | bad_response. The key is DATA_GO_KR_API_KEY (the decoded key) in
.env. Behaviour checked by real calls on 2026-10-16 (tests/fixtures/datago/):

- The 토지이음 services answer XML only, encoded in EUC-KR, whatever is asked for. Without
  an Accept header (and no type parameter) they refuse with returnReasonCode 04.
- 건축물대장 answers JSON with _type=json. An unknown key is HTTP 403 with code 30.
"""

from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

from sida.config import ROOT
from sida.experts.site.landapi import LandApiError

ENV_PATH = ROOT / ".env"
DATA_URL = "https://apis.data.go.kr/1613000"
TIMEOUT = 20
ATTEMPTS = 3
PAGE_ROWS = 100
MAX_PAGES = 10

# returnReasonCode of OpenAPI_ServiceResponse → error kind
_KEY_CODES = {"20", "30", "31", "32", "33"}
_LIMIT_CODES = {"22"}


class DataGoError(LandApiError):
    """A data.go.kr failure: same kinds as VWorld's, its own messages (datago_err_<kind>)."""

    MESSAGE_PREFIX = "datago_err_"


def credentials() -> str:
    """The data.go.kr service key. Raises DataGoError('no_key')."""
    if ENV_PATH.exists():
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH, override=False)
    key = os.environ.get("DATA_GO_KR_API_KEY", "").strip()
    if not key:
        raise DataGoError("no_key", "DATA_GO_KR_API_KEY")
    return key


def _http_get(url: str, params: dict) -> tuple[int, bytes]:
    """(HTTP status, body) with retries on 5xx and network errors. Errors never carry the URL."""
    last = "request failed"
    for attempt in range(ATTEMPTS):
        try:
            response = requests.get(
                url, params=params, timeout=TIMEOUT, headers={"Accept": "application/xml"}
            )
            if response.status_code < 500:
                return response.status_code, response.content
            last = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last = type(exc).__name__
        if attempt < ATTEMPTS - 1:
            time.sleep(1.0 * (attempt + 1))
    raise DataGoError("network", last)


def _text(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp949", errors="replace")  # EUC-KR, as 토지이음 sends it


def _service_error(code: str, message: str) -> DataGoError:
    if code in _KEY_CODES:
        return DataGoError("invalid_key", message or code)
    if code in _LIMIT_CODES:
        return DataGoError("over_limit", message or code)
    return DataGoError("bad_response", message or code)


def _get(path: str, params: dict) -> tuple[int, str]:
    status, body = _http_get(f"{DATA_URL}/{path}", {"serviceKey": credentials(), **params})
    return status, _text(body)


def _xml_items(path: str, params: dict) -> tuple[ET.Element, list[ET.Element], int | None]:
    """The <items> element, its <item> children and totalCount of a 토지이음 reply."""
    status, text = _get(path, params)
    stripped = text.lstrip()
    if stripped.startswith("{"):  # a gateway error comes back as JSON even here
        _raise_json_error(stripped, status)
    try:
        root = ET.fromstring(stripped)
    except ET.ParseError as exc:
        raise DataGoError("bad_response", f"HTTP {status}, not XML") from exc
    if root.tag == "OpenAPI_ServiceResponse":
        header = root.find("cmmMsgHeader")
        code = (header.findtext("returnReasonCode") if header is not None else "") or ""
        message = (header.findtext("errMsg") if header is not None else "") or ""
        raise _service_error(code.strip(), message.strip())
    result = (root.findtext("header/resultCode") or "").strip()
    if result not in {"0", "00"}:
        raise DataGoError("bad_response", root.findtext("header/resultMsg") or result or "no header")
    total = _int(root.findtext("body/totalCount"))
    items = root.find("body/items")
    if items is None:
        return ET.Element("items"), [], total
    return items, items.findall("item"), total


def _raise_json_error(text: str, status: int) -> None:
    try:
        header = json.loads(text)["OpenAPI_ServiceResponse"]["cmmMsgHeader"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DataGoError("bad_response", f"HTTP {status}") from exc
    raise _service_error(
        str(header.get("returnReasonCode") or "").strip(), str(header.get("errMsg") or "").strip()
    )


def _value(element: ET.Element, tag: str) -> str:
    return " ".join((element.findtext(tag) or "").split())


# ---------------------------------------------------------------------------
# 토지이음 행위제한
# ---------------------------------------------------------------------------


def search_uses(name: str) -> list[dict]:
    """Use names 토지이음 knows that contain `name` (up to 100): [{"name", "code"}]."""
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("use name is required")
    _items, items, _total = _xml_items(
        "arLandUseInfoService/DTsearchLunCd",
        {"landUseNm": name, "pageNum": 1, "numOfRows": PAGE_ROWS},
    )
    out = []
    for item in items:
        use = _value(item, "LUN_NM")
        if use:
            out.append({"name": use, "code": _value(item, "LUN_CD")})
    # The exact name first, then the shorter (broader) names.
    return sorted(out, key=lambda u: (u["name"] != name, len(u["name"])))


def use_rules(area_code: str, zone_codes: list[str], use: str) -> list[dict]:
    """
    Whether `use` (an exact 토지이음 use name) may be built in each zone or district:
    [{"zone", "code", "zone_law", "acts": [{"act", "result", "conditions", "uses"}]}]
    where result is the API's word (가능 | 금지 | …), conditions the attached provisos as
    written, and uses [{"name", "law", "definition"}] the use as defined in law.
    """
    if not zone_codes:
        return []
    items_el, items, _total = _xml_items(
        "arLandUseInfoService/DTarLandUseInfo",
        {"areaCd": area_code, "ucodeList": ",".join(zone_codes), "landUseNm": use},
    )
    conditions = {
        _value(c, "RNUM"): _value(c, "QNODE_DESC") for c in items_el.findall("QnodeCond")
    }
    zones = []
    for item in items:
        acts = []
        for act in item.findall("actRegList"):
            refs = [_value(r, ".") for r in act.findall("QNODE_CONDS/RNUM")]
            acts.append({
                "act": _value(act, "ACT_NM"),
                "result": _value(act, "REG_NM"),
                "conditions": [conditions[r] for r in refs if conditions.get(r)],
                "uses": [
                    {
                        "name": _value(u, "NODE_DESC"),
                        "law": _value(u, "LU_REF_LAW_NM1"),
                        "definition": _value(u, "DEF_REF"),
                    }
                    for u in act.findall("luInfoList")
                ],
            })
        zones.append({
            "zone": _value(item, "UNAME"),
            "code": _value(item, "UCODE"),
            "zone_law": _value(item, "UCODE_REF_LAW_NM"),
            "acts": acts,
        })
    return zones


# ---------------------------------------------------------------------------
# 토지이음 건축제한 근거 조문
# ---------------------------------------------------------------------------


def zone_laws(area_code: str, zone_codes: list[str]) -> list[dict]:
    """
    The articles behind the building limits of these zones, duplicates merged, API order kept:
    [{"text", "law_code", "local", "zones"}]. `local` is True for the municipality's own
    ordinance (its law code starts with the area code). The reply names no law, only the
    article ("제71조(용도지역안에서의 건축제한)") and sometimes its first sentence.
    """
    if not zone_codes:
        return []
    merged: dict[str, dict] = {}
    for page in range(1, MAX_PAGES + 1):
        _items, items, total = _xml_items(
            "LuLawInfoService/DTluLawInfo",
            {"areaCd": area_code, "ucodeList": ",".join(zone_codes), "pageNo": page, "numOfRows": PAGE_ROWS},
        )
        for item in items:
            text = _value(item, "LAW_CONTENTS")
            code = _value(item, "LAW_FULL_CD")
            if not text:
                continue
            entry = merged.setdefault(
                code or text,
                {"text": text, "law_code": code, "local": code.startswith(area_code), "zones": []},
            )
            zone = _value(item, "UNAME")
            if zone and zone not in entry["zones"]:
                entry["zones"].append(zone)
        if len(items) < PAGE_ROWS or (total is not None and page * PAGE_ROWS >= total):
            break
    return list(merged.values())


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 건축물대장
# ---------------------------------------------------------------------------

_BUILDING_FIELDS = {
    "name": "bldNm",
    "dong": "dongNm",
    "main_or_annex": "mainAtchGbCdNm",
    "register_kind": "regstrKindCdNm",
    "purpose": "mainPurpsCdNm",
    "purpose_detail": "etcPurps",
    "structure": "strctCdNm",
    "road_address": "newPlatPlc",
    "approved": "useAprDay",
}
_BUILDING_NUMBERS = {
    "plat_area_m2": "platArea",
    "building_area_m2": "archArea",
    "total_floor_area_m2": "totArea",
    "bcr": "bcRat",
    "far": "vlRat",
    "floors_above": "grndFlrCnt",
    "floors_below": "ugrndFlrCnt",
    "height_m": "heit",
}


def lot_params(pnu: str) -> dict:
    """건축물대장 lot parameters from a 19-digit PNU (산 → platGbCd 1)."""
    return {
        "sigunguCd": pnu[:5],
        "bjdongCd": pnu[5:10],
        "platGbCd": "1" if pnu[10] == "2" else "0",
        "bun": pnu[11:15],
        "ji": pnu[15:19],
    }


def buildings(pnu: str) -> list[dict]:
    """
    Buildings on the 건축물대장 표제부 of this parcel ([] when none is registered). Numbers
    are as registered (0 is a real value there; a missing value is None).
    """
    rows: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        status, text = _get(
            "BldRgstHubService/getBrTitleInfo",
            {**lot_params(pnu), "_type": "json", "numOfRows": PAGE_ROWS, "pageNo": page},
        )
        try:
            data = json.loads(text)
        except ValueError:
            if text.lstrip().startswith("<"):  # a gateway error in XML
                _xml_error(text, status)
            raise DataGoError("bad_response", f"HTTP {status}, not JSON") from None
        if "OpenAPI_ServiceResponse" in data:
            _raise_json_error(text, status)
        try:
            response = data["response"]
            result = str(response["header"]["resultCode"])
            body = response["body"]
        except (KeyError, TypeError) as exc:
            raise DataGoError("bad_response", f"HTTP {status}") from exc
        if result not in {"0", "00"}:
            raise DataGoError("bad_response", str(response["header"].get("resultMsg") or result))
        items = (body.get("items") or {}) if isinstance(body.get("items"), dict) else {}
        found = items.get("item") or []
        if isinstance(found, dict):  # a single row is sometimes not wrapped in a list
            found = [found]
        rows += found
        total = _int(body.get("totalCount"))
        if len(found) < PAGE_ROWS or (total is not None and page * PAGE_ROWS >= total):
            break
    return [_building(row) for row in rows]


def _xml_error(text: str, status: int) -> None:
    try:
        root = ET.fromstring(text.lstrip())
    except ET.ParseError as exc:
        raise DataGoError("bad_response", f"HTTP {status}") from exc
    raise _service_error(
        (root.findtext("cmmMsgHeader/returnReasonCode") or "").strip(),
        (root.findtext("cmmMsgHeader/errMsg") or "").strip(),
    )


def _building(row: dict) -> dict:
    out: dict[str, Any] = {}
    for key, field in _BUILDING_FIELDS.items():
        out[key] = " ".join(str(row.get(field) or "").split())
    for key, field in _BUILDING_NUMBERS.items():
        value = row.get(field)
        try:
            out[key] = float(value) if value not in (None, "", " ") else None
        except (TypeError, ValueError):
            out[key] = None
    for key in ("floors_above", "floors_below"):
        if out[key] is not None:
            out[key] = int(out[key])
    return out
