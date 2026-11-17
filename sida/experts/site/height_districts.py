"""The height a 고도지구 sets on the site, read from the notice's table (data/height_districts.yaml).

The government's data says which notice set the 고도지구 a site lies in (VWorld LT_C_UQ123: dyear,
dnum) but not its height: that is only in the notice's own tables, and one notice sets several
heights by zone, drawn on its maps. So the tables are copied into the rules file once and checked
by a person (2026-11-17 지훈 "할때마다 읽어오는건 안돼"), and at run time:

1. the pieces under the site whose notice is in the file are taken, the newest notice first (old
   and unnumbered pieces lie on the same ground);
2. the piece is matched to a zone of that notice by its area (the table's area within
   AREA_TOLERANCE: the pieces are the zones as drawn), else by the site's 지번 named in a zone's
   location, else (zones split by 용도지역, 북한산) by the site's 용도지역 among the zones naming its
   구·동. Several zones left: the site's 용도지역 narrows them;
3. no piece of a known notice: a zone the notice left unchanged (`kept`, only its 기정 row) is
   still drawn by VWorld under its older notice number (2026-11-17 실제 대지로 확인: 이태원동
   137-23 is 2019-0362, 한남동 810 is 0000-0000), so the pieces of the notice's region are matched
   to its kept zones the same way;
4. a zone measured from the ground with one figure (base "ground", max_m) gives the height; one
   from the road or the sea, or none matched, is shown as the notice says, with no figure.

The 비고 of the zones (2026-11-17 지훈 "비고란 처리도 해"):
- 높이 산정 (height_rule): the height is to the top of the building; rooftop stair and lift towers
  and see-through railings within `rooftop_allowance_m` are left out, so they may stand that much
  above the envelope (said on the line and given as the envelope's rooftop allowance);
- 국·공유지 (public_land_max_m, 경복궁 주변 1번): the site's 소유구분 (landapi.land_owner) picks the
  height; unknown or mixed parcels give no figure;
- 완화 (relaxed_m): needs the committee's review, so it is used only when the designer turns on
  "완화 높이로 검토", and then said to need that review;
- the rest (지반고 6m, 정비사업 45m, 리모델링, 호텔, 조망선) is shown as written.

A notice whose `verified` is null is shown but not used to cut the envelope.
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


def _id(piece: dict) -> tuple[str, str]:
    return str(piece["properties"].get("dyear") or ""), str(piece["properties"].get("dnum") or "")


def _distinct(found: list[tuple[str, dict]]) -> set:
    return {(z.get("max_m"), z.get("base"), z["limit"]) for _n, z in found}


def _names_dong(location: str, gu: str, dong: str) -> bool:
    """Whether a zone's location names the site's 구 and 동, also as the notice shortens it
    ("종로구 효자, 창성, 통의, 적선동 일대" names 창성동; "수유1동" names 수유동)."""
    if gu not in location:
        return False
    stem = re.sub(r"동(\d+가)?$", "", dong)
    words = [w.strip() for w in re.split(r"[,/·\s]+", location.replace("일대", " "))]
    return dong in location or any(re.sub(r"\d*동(\d+가)?$", "", w) == stem for w in words if w)


def _fits_zoning(zone: dict, zoning: set[str]) -> bool:
    """Whether a zone split by 용도지역 (its `zoning`) is the site's; True when either is not known."""
    return not zone.get("zoning") or not zoning or bool(set(zone["zoning"]) & zoning)


def _match(zones: list[tuple[str, dict]], pieces: list[dict], site: set, zoning: set[str]) -> tuple[list, str]:
    """The zones the pieces are (by area, else the site's 지번, else its 용도지역) and how: (zones, how)."""
    found: list[tuple[str, dict]] = []
    for p in pieces:
        area = piece_area(p["shape"])
        sigg = str(p["properties"].get("sigg_name") or "")
        near = [(n, z) for n, z in zones if not sigg or sigg in z["location"]]  # VWorld cuts pieces at the 구
        found += [(n, z) for n, z in near if abs(area - z["area_m2"]) <= z["area_m2"] * AREA_TOLERANCE]
    how = "area"
    if not found:
        found, how = [(n, z) for n, z in zones if _places(z["location"]) & site], "location"
    if not found and zoning:  # zones told apart by 용도지역 only (북한산 주변: 1종 20m, 2종 이상 28m)
        found = [(n, z) for n, z in zones if z.get("zoning") and _fits_zoning(z, zoning)
                 and any(_names_dong(z["location"], gu, dong) for gu, dong, _j in site)]
        how = "zoning"
    if len(_distinct(found)) > 1:
        found = [(n, z) for n, z in found if _places(z["location"]) & site] or found
    if len(_distinct(found)) > 1 or any(not _fits_zoning(z, zoning) for _n, z in found):
        fitting = [(n, z) for n, z in found if _fits_zoning(z, zoning)]
        if not fitting:
            return found, "zoning_conflict"  # the zone found is for another 용도지역: not to be taken
        if len(_distinct(fitting)) == 1:
            found, how = fitting, f"{how}+zoning"
    return found, how


def pick(pieces: list[dict], facts: dict) -> dict:
    """
    What the 고도지구 pieces under the site say: {"status": "matched" | "candidates" | "unknown_notice"
    | "none" (or "error" from the caller when the lookup failed), "notice", "verified", "district",
    "zone", "matched_by" ("area" | "location" | "zoning", "+zoning" when the 용도지역 narrowed it),
    "kept_as" (the other numbers VWorld draws the zone with), "drawn_as" ("kept": an unchanged zone under
    its older number; "alias": a number the table's vworld_also gives the notice), "candidates", "notices_seen"}.
    """
    table = load_table()["notices"]
    seen = sorted({_id(p) for p in pieces})
    out = {"status": "none", "notice": None, "verified": None, "district": "", "zone": None, "matched_by": "",
           "kept_as": [], "drawn_as": "", "candidates": [], "notices_seen": [f"{y}-{n}" for y, n in seen]}
    if not pieces:
        return out
    site = _site_places(facts)
    zoning = {z["zone"] for z in (facts.get("summary") or {}).get("zoning") or []}
    known = [n for n in table if (n["vworld"]["dyear"], n["vworld"]["dnum"]) in seen]
    aliased = [(n, a) for n in table for a in n.get("vworld_also") or [] if (a["dyear"], a["dnum"]) in seen]
    if known:
        notice = max(known, key=lambda n: (n["vworld"]["dyear"], n["vworld"]["dnum"]))
        mine = [p for p in pieces if _id(p) == (notice["vworld"]["dyear"], notice["vworld"]["dnum"])]
        zones = _zones(notice)
        found, how = _match(zones, mine, site, zoning)
    elif aliased:
        # pieces VWorld draws under another number for some districts of a notice (its vworld_also)
        notice, alias = aliased[0]
        mine = [p for p in pieces if _id(p) == (alias["dyear"], alias["dnum"])]
        zones = [(n, z) for n, z in _zones(notice) if n in alias["districts"]]
        found, how = _match(zones, mine, site, zoning)
        out.update(kept_as=[f"{alias['dyear']}-{alias['dnum']}"], drawn_as="alias")
    else:
        # an unchanged zone drawn under its older number: the kept zones of a notice of the pieces' region
        regions = {str(p["properties"].get("sido_name") or "") for p in pieces}
        found, how, notice, zones = [], "", None, []
        for candidate in sorted(table, key=lambda n: (n["vworld"]["dyear"], n["vworld"]["dnum"]), reverse=True):
            if candidate.get("region") not in regions:
                continue
            kept = [(n, z) for n, z in _zones(candidate) if z.get("kept")]
            found, how = _match(kept, pieces, site, zoning)
            if found:
                notice, zones = candidate, kept
                out.update(kept_as=out["notices_seen"], drawn_as="kept")
                break
        if notice is None:
            out["status"] = "unknown_notice"
            return out
    out.update(notice=notice["notice"], verified=notice.get("verified"))
    if len(_distinct(found)) == 1 and how != "zoning_conflict":
        name, zone = found[0]
        out.update(status="matched", district=name, zone=zone, matched_by=how)
        return out
    # not one zone: the zones of the site's 구·동 (or those matched) as candidates
    if not found:
        found = [(n, z) for n, z in zones if any(_names_dong(z["location"], gu, dong) for gu, dong, _j in site)]
    out.update(status="candidates", candidates=[{"district": n, "number": z.get("number"), "limit": z["limit"]} for n, z in found])
    return out


HOW = {"area": "고도지구 조각 넓이가 고시 표의 면적과 맞음", "location": "대지 지번이 고시 표의 위치에 있음",
       "zoning": "대지의 용도지역이 고시 표의 구역과 맞음"}


def rooftop_allowance(notice_name: str | None) -> float | None:
    """How far rooftop stair and lift towers and see-through railings may stand above the notice's
    height (its height_rule leaves them out), or None."""
    value = (_notice(notice_name or "") or {}).get("rooftop_allowance_m")
    return float(value) if value else None


def line(found: dict, *, entered: float | None, use_relaxed: bool = False,
         public_land: bool | None = None) -> tuple[dict | None, float | None]:
    """The card's height line for what pick() found and the height it cuts the envelope to (or
    None): (line, height). `entered`: the height the designer typed, which wins. `use_relaxed`: the
    designer looks at the relaxed height (완화, needs the committee's review). `public_land`: whether
    the site's parcels are 국·공유지 (all True / all False; None when unknown or mixed)."""
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
    base_how, _plus, narrowed = found["matched_by"].partition("+")
    how = HOW.get(base_how, "")
    if narrowed:
        how += ", 용도지역으로 구역을 가림"
    if found.get("drawn_as") == "alias":
        how += f". 브이월드 조각 번호({', '.join(found['kept_as'])})는 이 고시의 {found['district']} 구역으로 봄(높이 표의 vworld_also)"
    elif found.get("kept_as"):
        how += f". 브이월드 조각은 예전 고시 번호({', '.join(found['kept_as'])})로 그려져 있으나 이 고시에서 바뀌지 않은 구역"
    note = f". {zone['note']}" if zone.get("note") else ""
    quote = f"{where}: {zone['limit']}" + (f" — 높이 산정: {rule}" if rule else "")
    if zone.get("base") != "ground" or not zone.get("max_m"):
        return _line("check", zone["limit"], f"{where}({how}). 도로면·해발 기준이라 한 가지 높이로 쓰지 않음, 원문 확인{note}",
                     quote, notice), None
    height, extra = float(zone["max_m"]), ""
    if zone.get("public_land_max_m"):  # 경복궁 주변 1번: "단, 국·공유지는 12m이하로 함"
        if public_land is None:
            return _line("check", f"{zone['max_m']:g}m 또는 {zone['public_land_max_m']:g}m", f"{where}({how}). 국·공유지는 "
                         f"{zone['public_land_max_m']:g}m인데 대지의 소유구분을 확인하지 못함(또는 필지마다 다름). 맞는 높이를 입력",
                         quote, notice), None
        if public_land:
            height = float(zone["public_land_max_m"])
            extra = f". 대지가 국·공유지(토지소유정보)라 {height:g}m"
        else:
            extra = ". 대지가 국·공유지가 아님(토지소유정보)"
    status, value = "read", f"{height:g}m"
    if zone.get("relaxed_m"):
        if use_relaxed:
            height, status, value = float(zone["relaxed_m"]), "conditional", f"{zone['relaxed_m']:g}m (완화)"
            extra += (f". 완화 높이 {zone['relaxed_m']:g}m로 검토 중: 도시계획위원회 심의 등을 거쳐야 하는 높이"
                      f"(기본 {zone['max_m']:g}m)")
        else:
            extra += f". 완화시 {zone['relaxed_m']:g}m는 위원회 심의가 필요해 기본 높이로 자름(완화 높이로 검토를 켜면 그 높이로 봄)"
    roof = rooftop_allowance(notice)
    if roof:
        extra += f". 옥상 승강기탑·계단탑·투시형 난간은 {roof:g}m 이내면 높이에 넣지 않음(볼륨 위로 {roof:g}m까지)"
    if not found.get("verified"):
        return _line("check", f"{value} (대조 전)", f"{where}({how}){extra}{note}. 고시 표를 사람이 원문과 대조하기 전이라 "
                     "볼륨을 자르지 않음. 맞으면 높이 칸에 넣기", quote, notice), None
    return _line(status, value, f"{where}({how}){extra}{note}", quote, notice), height


def _notice(name: str) -> dict | None:
    return next((n for n in load_table()["notices"] if n["notice"] == name), None)


def _line(status: str, value: str, detail: str, quote: str = "", source: str = "") -> dict:
    return {"id": "height", "status": status, "title": "높이 한도", "value": value, "detail": detail, "quote": quote,
            "source": source}
