"""The height a 고도지구 sets on the site, read from the notice's table (data/height_districts.yaml).

The government's data says which notice set the 고도지구 a site lies in (VWorld LT_C_UQ123: dyear,
dnum) but not its height: that is only in the notice's own tables, and one notice sets several
heights by zone, drawn on its maps. So the tables are copied into the rules file once and checked
by a person (2026-11-17 지훈 "할때마다 읽어오는건 안돼"), and at run time:

1. the pieces under the site whose notice is in the file are taken, the newest notice first (old
   and unnumbered pieces lie on the same ground);
2. the piece is matched to a zone of that notice by its area (the table's area within
   AREA_TOLERANCE: the pieces are the zones as drawn), else by the site's 지번 named in a zone's
   location;
3. a zone measured from the ground with one figure (base "ground", max_m) gives the height; one
   from the road or the sea, or none matched, is shown as the notice says, with no figure.

The relaxed heights (완화) need a committee's review and are only shown. A notice whose
`verified` is null is shown but not used to cut the envelope.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache

import numpy as np
import shapely
from shapely.geometry import shape as to_shape

from sida import board
from sida.config import ROOT

TABLE_PATH = ROOT / "data" / "height_districts.yaml"
LAYER = "LT_C_UQ123"
AREA_TOLERANCE = 0.03  # the share a piece's area may differ from the table's and still match it
JIBUN = re.compile(r"^\d+(?:-\d+)?$")


@lru_cache(maxsize=1)
def load_table() -> dict:
    import yaml

    return yaml.safe_load(TABLE_PATH.read_text(encoding="utf-8"))


def piece_area(shape: dict) -> float:
    """The area (㎡) of a GeoJSON polygon in lon/lat, on a plane about its own middle."""
    geom = to_shape(shape)
    lat = geom.centroid.y
    k = math.pi / 180
    east, north = board.EARTH_RADIUS * k * math.cos(lat * k), board.EARTH_RADIUS * k
    return float(shapely.transform(geom, lambda xy: xy * np.array([east, north])).area)


def _places(location: str) -> set[tuple[str, str, str]]:
    """(구, 동, 지번) named in a zone's location: "중구 회현동1가 164, 신당동 432-1979, 432-1632 일대"
    names 회현동1가 164, 신당동 432-1979 and 신당동 432-1632, all in 중구."""
    out = set()
    gu = dong = ""
    for part in re.split(r"[,/]", location or ""):
        for word in part.replace("일대", " ").split():
            word = word.strip()
            if word.endswith("구") and len(word) > 1:
                gu, dong = word, ""
            elif re.search(r"(동|가|리)\d*$", word) or re.search(r"동\d+가$", word):
                m = re.match(r"^(.*?(?:동\d*가|동\d*|가|리))(\d+(?:-\d+)?)?$", word)
                dong = m.group(1) if m else word
                if m and m.group(2):
                    out.add((gu, dong, m.group(2)))
            elif JIBUN.match(word) and dong:
                out.add((gu, dong, word))
    return out


def _site_places(facts: dict) -> set[tuple[str, str, str]]:
    """(구, 동, 지번) of the site's parcels by their 지번 addresses ("서울특별시 중구 신당동 355-7")."""
    out = set()
    for p in facts.get("parcels") or []:
        words = (p.get("address") or "").split()
        gu = next((w for w in words if w.endswith("구")), "")
        if len(words) >= 2 and JIBUN.match(words[-1].removeprefix("산")):
            out.add((gu, words[-2], words[-1]))
    return out


def _zones(notice: dict) -> list[tuple[str, dict]]:
    return [(name, z) for name, d in notice["districts"].items() for z in d["zones"]]


def _label(name: str, zone: dict) -> str:
    return f"{name} {zone['number']}번 구역" if zone.get("number") is not None else name


def pick(pieces: list[dict], facts: dict) -> dict:
    """
    What the 고도지구 pieces under the site say: {"status": "matched" | "candidates" | "unknown_notice"
    | "none" (or "error" from the caller when the lookup failed), "notice", "verified", "district", "zone", "matched_by", "candidates", "notices_seen"}.
    """
    table = load_table()["notices"]
    seen = sorted({(str(p["properties"].get("dyear") or ""), str(p["properties"].get("dnum") or "")) for p in pieces})
    out = {"status": "none", "notice": None, "verified": None, "district": "", "zone": None, "matched_by": "",
           "candidates": [], "notices_seen": [f"{y}-{n}" for y, n in seen]}
    if not pieces:
        return out
    known = [n for n in table if (n["vworld"]["dyear"], n["vworld"]["dnum"]) in seen]
    if not known:
        out["status"] = "unknown_notice"
        return out
    notice = max(known, key=lambda n: (n["vworld"]["dyear"], n["vworld"]["dnum"]))
    out.update(notice=notice["notice"], verified=notice.get("verified"))
    mine = [p for p in pieces if (str(p["properties"].get("dyear") or ""), str(p["properties"].get("dnum") or ""))
            == (notice["vworld"]["dyear"], notice["vworld"]["dnum"])]
    zones = _zones(notice)
    found: list[tuple[str, dict]] = []
    site = _site_places(facts)
    for p in mine:
        area = piece_area(p["shape"])
        sigg = str(p["properties"].get("sigg_name") or "")
        near = [(n, z) for n, z in zones if not sigg or sigg in z["location"]]  # VWorld cuts pieces at the 구
        found += [(n, z) for n, z in near if abs(area - z["area_m2"]) <= z["area_m2"] * AREA_TOLERANCE]
    how = "area"
    if len({(z.get("max_m"), z.get("base"), z["limit"]) for _n, z in found}) > 1:
        by_place = [(n, z) for n, z in found if _places(z["location"]) & site]
        found = by_place or found
    if not found:
        found = [(n, z) for n, z in zones if _places(z["location"]) & site]
        how = "location"
    distinct = {(z.get("max_m"), z.get("base"), z["limit"]) for _n, z in found}
    if len(distinct) == 1:
        name, zone = found[0]
        out.update(status="matched", district=name, zone=zone, matched_by=how)
        return out
    # not one zone: the zones of the site's 구·동 (or those the area matched) as candidates
    if not found:
        found = [(n, z) for n, z in zones if any(gu in z["location"] and dong in z["location"] for gu, dong, _j in site)]
    out.update(status="candidates", candidates=[{"district": n, "number": z.get("number"), "limit": z["limit"]} for n, z in found])
    return out


def line(found: dict, *, entered: float | None) -> tuple[dict | None, float | None]:
    """The card's height line for what pick() found and the height it cuts the envelope to (or
    None): (line, height). `entered`: the height the designer typed, which wins."""
    notice = found.get("notice") or ""
    zone = found.get("zone")
    where = _label(found["district"], zone) if zone else ""
    if entered:
        detail = "설계자가 넣은 고시 높이로 볼륨을 자름"
        if zone:
            detail += f". 고시 표에서 찾은 구역: {where}({zone['limit']})"
        return _line("read", f"{entered:g}m", detail, "", "사용자 입력"), entered
    if found["status"] == "none":
        return None, None
    if found["status"] == "error":
        return _line("check", "입력 필요", "고도지구 조각을 받지 못함(연결 실패). 고시에서 높이를 찾아 입력하거나 다시 열기"), None
    rule = " ".join((_notice(notice) or {}).get("height_rule", "").split())
    if found["status"] == "unknown_notice":
        return _line("check", "입력 필요", f"고도지구 고시({', '.join(found['notices_seen'])})의 높이 표가 아직 없음. 고시에서 높이를 찾아 입력"), None
    if found["status"] == "candidates":
        names = ", ".join(f"{_label(c['district'], c)}({c['limit']})" for c in found["candidates"]) or "없음"
        return _line("check", "미확인", f"{notice}의 어느 구역인지 정하지 못함. 후보: {names}. 맞는 높이를 입력", "", notice), None
    how = "고도지구 조각 넓이가 고시 표의 면적과 맞음" if found["matched_by"] == "area" else "대지 지번이 고시 표의 위치에 있음"
    relaxed = f". 완화시 {zone['relaxed_m']:g}m는 위원회 심의가 필요해 쓰지 않음" if zone.get("relaxed_m") else ""
    note = f". {zone['note']}" if zone.get("note") else ""
    quote = f"{where}: {zone['limit']}" + (f" — 높이 산정: {rule}" if rule else "")
    if zone.get("base") != "ground" or not zone.get("max_m"):
        return _line("check", zone["limit"], f"{where}({how}). 도로면·해발 기준이라 한 가지 높이로 쓰지 않음, 원문 확인{note}",
                     quote, notice), None
    if not found.get("verified"):
        return _line("check", f"{zone['max_m']:g}m (대조 전)", f"{where}({how}){relaxed}{note}. 고시 표를 사람이 원문과 대조하기 전이라 "
                     "볼륨을 자르지 않음. 맞으면 높이 칸에 넣기", quote, notice), None
    return _line("read", f"{zone['max_m']:g}m", f"{where}({how}){relaxed}{note}", quote, notice), float(zone["max_m"])


def _notice(name: str) -> dict | None:
    return next((n for n in load_table()["notices"] if n["notice"] == name), None)


def _line(status: str, value: str, detail: str, quote: str = "", source: str = "") -> dict:
    return {"id": "height", "status": status, "title": "높이 한도", "value": value, "detail": detail, "quote": quote,
            "source": source}
