#!/usr/bin/env python3
"""
Record the VWorld replies that the map API tests use (parcel boundary shapes and finding a
parcel by a map click) into tests/fixtures/landapi/data_*_geom.json, and check the map tile
and cadastral-line image addresses the browser will call.

Needs VWORLD_API_KEY (and VWORLD_DOMAIN) in .env. Run from the repository root:

    python scripts/record_landapi_map.py

It calls the real API about ten times, overwrites those fixtures, and prints what it found so
the assumptions in landapi.parcel_shapes / parcel_at can be checked against the real service.
The key is never printed: image addresses are shown with {key}.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sida.console import configure_stdio  # noqa: E402
from sida.experts.site import landapi  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "landapi"

P14, P15 = "4141010500106890014", "4141010500106890015"  # 군포시 금정동 689-14, 689-15
INSIDE_P14 = (126.945978, 37.37025)  # the address-search point of 689-14
SEA = (125.0, 34.0)  # no parcel


def fixture_name(params: dict) -> str:
    """Same naming as the fake_vworld fixture in tests/conftest.py."""
    value = str(params.get("attrFilter") or "").rsplit(":", 1)[-1]
    geom = str(params.get("geomFilter") or "")
    if not value and geom.startswith("POINT("):
        value = "at_" + "_".join(geom[6:-1].split())
    suffix = "_geom" if params.get("geometry") == "true" else ""
    return f"data_{params['data']}{'_' + value if value else ''}{suffix}.json"


def record(params: dict) -> dict:
    key, domain = landapi.vworld_credentials()
    full = {
        "service": "data", "request": "GetFeature", "key": key, "domain": domain, "format": "json",
        "crs": "EPSG:4326", "geometry": "true", "attribute": "true", "size": landapi.PAGE_SIZE, "page": 1,
        **params,
    }
    data = landapi._http_get(f"{landapi.VWORLD_URL}/req/data", full)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if key in text:
        raise SystemExit("the reply contains the key; not saved")
    path = OUT / fixture_name(full)
    path.write_text(text + "\n", encoding="utf-8")
    response = data.get("response") or {}
    features = ((response.get("result") or {}).get("featureCollection") or {}).get("features") or []
    print(f"{path.name}: status={response.get('status')} record={response.get('record')} rows={len(features)}")
    for feature in features[:3]:
        geometry = feature.get("geometry") or {}
        coords = json.dumps(geometry.get("coordinates"))
        print("   pnu:", (feature.get("properties") or {}).get("pnu"), "| addr:",
              (feature.get("properties") or {}).get("addr"), "| geometry:", geometry.get("type"),
              f"({len(coords)} chars) {coords[:80]}…")
    if response.get("error"):
        print("   error:", json.dumps(response["error"], ensure_ascii=False))
    return data


def probe_image(label: str, url: str, params: dict | None = None) -> None:
    """GET an image address as the browser would (Referer localhost); print status and type only."""
    key, domain = landapi.vworld_credentials()
    filled = url.replace("{key}", key)
    query = {k: str(v).replace("{key}", key).replace("{domain}", domain) for k, v in (params or {}).items()}
    try:
        r = requests.get(filled, params=query, timeout=30, headers={"Referer": "http://localhost:8000/"})
        body = r.content[:120].decode("utf-8", "replace").replace(key, "{key}") if "image" not in r.headers.get(
            "Content-Type", "") else ""
        print(f"{label}: HTTP {r.status_code} {r.headers.get('Content-Type')} {len(r.content)} bytes {body!r}")
    except requests.RequestException as exc:
        print(f"{label}: {type(exc).__name__}")
    shown = url + ("?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()) if params else "")
    print("   address:", shown)


def main() -> None:
    configure_stdio()
    record({"data": "LP_PA_CBND_BUBUN", "attrFilter": f"pnu:=:{P14}"})
    record({"data": "LP_PA_CBND_BUBUN", "attrFilter": f"pnu:=:{P15}"})
    for x, y in (INSIDE_P14, SEA):
        record({"data": "LP_PA_CBND_BUBUN", "geomFilter": f"POINT({x} {y})"})

    # map images the browser calls directly (zoom 17 tile over 금정동, and the cadastral lines there)
    z, tx, ty = 17, 111755, 50847
    probe_image("WMTS Base", f"https://api.vworld.kr/req/wmts/1.0.0/{{key}}/Base/{z}/{ty}/{tx}.png")
    probe_image("WMTS Satellite", f"https://api.vworld.kr/req/wmts/1.0.0/{{key}}/Satellite/{z}/{ty}/{tx}.jpeg")
    bbox = "14131412,4490691,14131712,4490991"  # EPSG:3857, 300 m around 금정동 689-14
    probe_image("WMS lp_pa_cbnd_bubun", "https://api.vworld.kr/req/wms", {
        "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0", "LAYERS": "lp_pa_cbnd_bubun",
        "STYLES": "lp_pa_cbnd_bubun", "CRS": "EPSG:3857", "BBOX": bbox, "WIDTH": 256, "HEIGHT": 256,
        "FORMAT": "image/png", "TRANSPARENT": "true", "KEY": "{key}", "DOMAIN": "{domain}",
    })


if __name__ == "__main__":
    main()
