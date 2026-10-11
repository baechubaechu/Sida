#!/usr/bin/env python3
"""
Record the VWorld data-API replies that tests/experts/site use for the step-by-step address
selection (시·도 → 시·군·구 → 읍·면·동 → 리 → 지번) into tests/fixtures/landapi/data_*.json.

Needs VWORLD_API_KEY (and VWORLD_DOMAIN) in .env. Run from the repository root:

    python scripts/record_landapi_regions.py

It calls the real API about ten times, overwrites the fixtures, and prints what it found so
the assumptions in landapi.regions / find_lots can be checked against the real service.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sida.console import configure_stdio  # noqa: E402
from sida.experts.site import landapi  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "landapi"


def fixture_name(params: dict) -> str:
    """Same naming as the fake_vworld fixture in tests/conftest.py."""
    value = str(params.get("attrFilter") or "").rsplit(":", 1)[-1]
    return f"data_{params['data']}{'_' + value if value else ''}.json"


def record(params: dict, name: str | None = None) -> dict:
    key, domain = landapi.vworld_credentials()
    full = {
        "service": "data", "request": "GetFeature", "key": key, "domain": domain, "format": "json",
        "crs": "EPSG:4326", "geometry": "false", "attribute": "true", "size": landapi.PAGE_SIZE, "page": 1,
        **params,
    }
    data = landapi._http_get(f"{landapi.VWORLD_URL}/req/data", full)
    path = OUT / (name or fixture_name(params))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    response = data.get("response") or {}
    features = ((response.get("result") or {}).get("featureCollection") or {}).get("features") or []
    print(f"{path.name}: status={response.get('status')} record={response.get('record')} "
          f"page={response.get('page')} rows={len(features)}")
    if features:
        print("   first row:", json.dumps(features[0].get("properties"), ensure_ascii=False))
    if response.get("error"):
        print("   error:", json.dumps(response["error"], ensure_ascii=False))
    return data


def rows(data: dict) -> list[dict]:
    response = data.get("response") or {}
    features = ((response.get("result") or {}).get("featureCollection") or {}).get("features") or []
    return [f.get("properties") or {} for f in features]


def main() -> None:
    configure_stdio()
    record({"data": "LT_C_ADSIDO_INFO", "geomFilter": landapi.KOREA_BOX})
    sigungu = rows(record({"data": "LT_C_ADSIGG_INFO", "attrFilter": "sig_cd:like:41"}))
    print("   codes not starting with 41:", [r.get("sig_cd") for r in sigungu if not str(r.get("sig_cd")).startswith("41")])
    record({"data": "LT_C_ADEMD_INFO", "attrFilter": "emd_cd:like:41410"})  # 군포시
    emd = rows(record({"data": "LT_C_ADEMD_INFO", "attrFilter": "emd_cd:like:41830"}))  # 양평군
    towns = sorted(str(r.get("emd_cd")) for r in emd if str(r.get("emd_kor_nm") or "").endswith(("읍", "면")))
    if towns:
        record({"data": "LT_C_ADRI_INFO", "attrFilter": f"li_cd:like:{towns[0]}"})
    record({"data": "LP_PA_CBND_BUBUN", "attrFilter": "pnu:like:414101050010689"})  # 금정동 689 전부
    record({"data": "LP_PA_CBND_BUBUN", "attrFilter": "pnu:=:4141010500106890014"})  # 금정동 689-14
    record({"data": "LP_PA_CBND_BUBUN", "attrFilter": "pnu:=:4141010500106890015"})  # 금정동 689-15
    record({"data": "LP_PA_CBND_BUBUN", "attrFilter": "pnu:=:4141010500199999999"}, "data_not_found.json")
    landapi_key = landapi.vworld_credentials

    def bad_key() -> tuple[str, str]:
        return "not-a-registered-key", landapi_key()[1]

    landapi.vworld_credentials = bad_key
    record({"data": "LT_C_ADSIGG_INFO", "attrFilter": "sig_cd:like:41"}, "data_bad_key.json")


if __name__ == "__main__":
    main()
