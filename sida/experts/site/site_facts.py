#!/usr/bin/env python3
"""Site facts: what government data says about the project's parcel(s).

An address is resolved to one or more parcels (a site may merge several), each parcel's
zoning and land characteristics are fetched, and the result is saved in the project as
site_facts.json. Experts then receive it as a SITE FACTS block, so zoning and statutory
limits come from data instead of model memory.

UI-agnostic like engine.py: no printing, no input. Looking facts up never raises for a
single failed call — the failure is recorded on the parcel and shown as "미확인".
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from sida.experts.site import landapi
from sida.harness import ROOT
from sida.storage import atomic_write_text

FACTS_FILE = "site_facts.json"
FACTS_VERSION = 1
LIMITS_PATH = ROOT / "data" / "zoning_limits.yaml"

# Which block an expert receives. Config can override via site_facts.agents.
DEFAULT_AGENT_BLOCKS: dict[str, str] = {
    "site_reader": "physical",
    "regulation_checker": "regulatory",
}

# 도시계획시설 도로: 광로/대로/중로/소로 + 류
_ROAD_RE = re.compile(r"^(광로|대로|중로|소로)\d류")


@lru_cache(maxsize=1)
def load_limits() -> dict:
    with LIMITS_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        "source": data.get("source") or {},
        "zones": data.get("zones") or {},
        "umbrella": set(data.get("umbrella") or []),
        "verify": [v for v in (data.get("verify") or []) if v.get("keyword")],
    }


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def lookup_parcel(candidate: dict, *, http_get=None) -> dict:
    """Fetch zoning and characteristics for one parcel. Failed calls are recorded, not raised."""
    parcel = {
        "pnu": candidate["pnu"],
        "address": candidate.get("address", ""),
        "road_address": candidate.get("road_address", ""),
        "building": candidate.get("building", ""),
        "zones": [],
        "characteristics": None,
        "errors": [],
    }
    try:
        parcel["zones"] = landapi.land_use(parcel["pnu"], http_get=http_get)
    except landapi.LandApiError as exc:
        parcel["errors"].append({"what": "land_use", "kind": exc.kind})
    try:
        parcel["characteristics"] = landapi.land_characteristics(parcel["pnu"], http_get=http_get)
    except landapi.LandApiError as exc:
        parcel["errors"].append({"what": "characteristics", "kind": exc.kind})
    return parcel


def build_facts(query: str, candidates: list[dict], *, http_get=None, now: datetime | None = None) -> dict:
    """Look up every chosen parcel and summarize them as one site."""
    parcels = [lookup_parcel(c, http_get=http_get) for c in candidates]
    stamp = (now or datetime.now().astimezone()).replace(microsecond=0)
    return {
        "version": FACTS_VERSION,
        "query": query.strip(),
        "fetched_at": stamp.isoformat(),
        "parcels": parcels,
        "summary": summarize(parcels),
    }


def parcel_zoning(parcel: dict, zone_names) -> list[str]:
    """용도지역 of a parcel (zones this parcel lies in that have statutory limits)."""
    names = [z["name"] for z in parcel["zones"] if z["name"] in zone_names and z["relation"] != "접함"]
    if not names and not parcel["zones"]:
        # Zoning call failed: fall back to what the land-characteristics record says.
        ch = parcel.get("characteristics") or {}
        names = [n for n in (ch.get("zone1"), ch.get("zone2")) if n in zone_names]
    return list(dict.fromkeys(names))


def municipality(address: str) -> str:
    """
    The body whose 도시계획조례 applies: '경기도 군포시 금정동 689-14' → '경기도 군포시',
    '서울특별시 종로구 …' → '서울특별시' (구는 도시계획조례를 따로 두지 않음).
    """
    tokens = address.split()
    if not tokens:
        return ""
    if tokens[0].endswith("시"):  # 특별시·광역시·특별자치시
        return tokens[0]
    if len(tokens) > 1 and tokens[1].endswith(("시", "군")):
        return " ".join(tokens[:2])
    return tokens[0]


def summarize(parcels: list[dict]) -> dict:
    limits = load_limits()
    zone_table = limits["zones"]

    areas = [(p.get("characteristics") or {}).get("area_m2") for p in parcels]
    known = [a for a in areas if a]
    total_area = round(sum(known), 1) if known else None

    zoning: dict[str, dict] = {}
    for p in parcels:
        area = (p.get("characteristics") or {}).get("area_m2")
        names = parcel_zoning(p, zone_table)
        for name in names:
            entry = zoning.setdefault(
                name, {"zone": name, "pnus": [], "area_m2": 0.0, "partial": False, **zone_table[name]}
            )
            entry["pnus"].append(p["pnu"])
            if len(names) > 1:
                # One parcel split between zones: the API does not say how much lies in each.
                entry["partial"] = True
            elif area:
                entry["area_m2"] = round(entry["area_m2"] + area, 1)

    districts: dict[tuple[str, str], dict] = {}
    roads: dict[tuple[str, str], dict] = {}
    for p in parcels:
        for z in p["zones"]:
            name, relation = z["name"], z["relation"]
            if name in zone_table or name in limits["umbrella"]:
                continue
            target = roads if _ROAD_RE.match(name) else districts
            target.setdefault((name, relation), {"name": name, "relation": relation})

    flags: list[str] = []
    if len(parcels) > 1:
        flags.append(
            f"필지 {len(parcels)}개를 하나의 대지로 본 값임 — 합병 또는 하나의 대지로 건축 가능한지 확인"
        )
    if len(zoning) > 1:
        flags.append(
            "둘 이상의 용도지역에 걸침 — 건폐율·용적률·건축제한의 적용 기준(국토계획법 제84조) 확인"
        )
    for d in districts.values():
        if d["relation"] == "접함":
            continue  # next to the district, not in it
        for rule in limits["verify"]:
            if rule["keyword"] in d["name"]:
                flags.append(f"{d['name']}: {rule['note']}")
                break
    for r in roads.values():
        if r["relation"] == "저촉":
            flags.append(f"{r['name']}: 도시계획시설 도로에 대지 일부가 저촉됨 — 건축 가능 범위 확인")

    missing = []
    for p in parcels:
        for err in p["errors"]:
            missing.append({"pnu": p["pnu"], "address": p["address"], **err})
    if total_area is not None and len(known) < len(parcels):
        flags.append("일부 필지의 면적을 가져오지 못해 합계 면적이 실제보다 작음")

    updated = sorted({z["updated"] for p in parcels for z in p["zones"] if z.get("updated")})
    return {
        "parcel_count": len(parcels),
        "municipality": municipality(parcels[0]["address"]) if parcels else "",
        "total_area_m2": total_area,
        "area_complete": len(known) == len(parcels),
        "zoning": list(zoning.values()),
        "districts": list(districts.values()),
        "roads": list(roads.values()),
        "flags": flags,
        "missing": missing,
        "zoning_updated": updated[-1] if updated else "",
    }


def parse_selection(text: str, count: int) -> list[int] | None:
    """'1,3' → [0, 2] (zero-based, in the order typed, no repeats). None if anything is invalid."""
    picks: list[int] = []
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        if not part.isdigit() or not 1 <= int(part) <= count:
            return None
        if int(part) - 1 not in picks:
            picks.append(int(part) - 1)
    return picks or None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def facts_path(project_path: Path) -> Path:
    return Path(project_path) / FACTS_FILE


def save_facts(project_path: Path, facts: dict) -> Path:
    path = facts_path(project_path)
    atomic_write_text(path, json.dumps(facts, ensure_ascii=False, indent=2) + "\n")
    return path


def load_facts(project_path: Path) -> dict | None:
    path = facts_path(project_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("parcels"):
        return None
    return data


# ---------------------------------------------------------------------------
# Rendering (Korean: these lines go to the designer and into expert prompts)
# ---------------------------------------------------------------------------


def _area(value) -> str:
    return f"{value:,.1f}㎡" if value else "면적 미확인"


def _parcel_line(index: int, parcel: dict) -> str:
    ch = parcel.get("characteristics")
    head = f"필지 {index}: {parcel['address'] or parcel['pnu']}"
    if not ch:
        return f"{head} — 토지 특성 미확인"
    parts = [_area(ch.get("area_m2"))]
    if ch.get("land_category"):
        parts.append(f"지목 {ch['land_category']}")
    terrain = "·".join(x for x in (ch.get("terrain_height"), ch.get("terrain_shape")) if x)
    if terrain:
        parts.append(f"지형 {terrain}")
    if ch.get("road_side"):
        parts.append(f"도로접면 {ch['road_side']}")
    if ch.get("use"):
        parts.append(f"이용상황 {ch['use']}")
    line = f"{head} — " + ", ".join(parts)
    if ch.get("year"):
        line += f" (토지특성 기준연도 {ch['year']})"
    if parcel.get("building"):
        line += f"; 현재 건물: {parcel['building']}"
    return line


def _site_line(facts: dict) -> str:
    s = facts["summary"]
    if s["parcel_count"] == 1:
        return f"대지: 필지 1개, 면적 {_area(s['total_area_m2'])}"
    note = "" if s["area_complete"] else " (일부 필지 면적 미확인)"
    return f"대지: 필지 {s['parcel_count']}개를 하나의 대지로 봄, 합계 면적 {_area(s['total_area_m2'])}{note}"


def _roads_line(facts: dict) -> str | None:
    roads = facts["summary"]["roads"]
    if not roads:
        return None
    return "도시계획 도로: " + ", ".join(f"{r['name']} {r['relation']}" for r in roads)


def _missing_lines(facts: dict) -> list[str]:
    labels = {"land_use": "토지이용계획(용도지역·지구)", "characteristics": "토지 특성"}
    return [
        f"조회 실패(미확인): {m['address'] or m['pnu']}의 {labels.get(m['what'], m['what'])}"
        for m in facts["summary"]["missing"]
    ]


def physical_lines(facts: dict) -> list[str]:
    lines = [_site_line(facts)]
    lines += [_parcel_line(i, p) for i, p in enumerate(facts["parcels"], start=1)]
    road = _roads_line(facts)
    if road:
        lines.append(road)
    lines += [m for m in _missing_lines(facts) if "토지 특성" in m]
    return lines


def regulatory_lines(facts: dict) -> list[str]:
    s = facts["summary"]
    source = load_limits()["source"]
    lines = [_site_line(facts)]
    if not s["zoning"]:
        lines.append("용도지역: 미확인")
    for z in s["zoning"]:
        if z.get("partial"):
            where = "필지 일부에 걸침, 면적 비율 미확인"
        elif len(z["pnus"]) == s["parcel_count"]:
            where = "전 필지"
        else:
            where = f"필지 {len(z['pnus'])}개, {_area(z['area_m2'])}"
        lines.append(
            f"용도지역: {z['zone']} ({where}) — 건폐율 법정 상한 {z['bcr_max']}%, "
            f"용적률 법정 범위 {z['far_min']}~{z['far_max']}%"
        )
    if s["zoning"]:
        body = s["municipality"] or "해당 지자체"
        lines.append(
            f"위 수치는 법정 범위임({source.get('bcr', '')}, {source.get('far', '')}). "
            f"실제 적용값은 {body} 도시계획조례가 이 범위 안에서 정하므로 verify."
        )
    if s["districts"]:
        lines.append(
            "그 밖의 지역·지구: " + ", ".join(f"{d['name']}({d['relation']})" for d in s["districts"])
        )
    road = _roads_line(facts)
    if road:
        lines.append(road)
    lines += [f"확인 필요: {flag}" for flag in s["flags"]]
    lines += [m for m in _missing_lines(facts) if "토지이용계획" in m]
    return lines


def facts_block(facts: dict, kind: str) -> str:
    """SITE FACTS block for an expert prompt. kind: "physical" | "regulatory"."""
    lines = regulatory_lines(facts) if kind == "regulatory" else physical_lines(facts)
    s = facts["summary"]
    stamp = facts.get("fetched_at", "")[:10]
    updated = f", 토지이용계획 갱신일 {s['zoning_updated']}" if s.get("zoning_updated") else ""
    header = (
        f"SITE FACTS ({kind}) — government land data (VWorld), 조회일 {stamp}{updated}. "
        "Treat these as given facts and cite them as \"site facts\". Do not restate them as your "
        "own analysis and do not invent values for items marked 미확인 — list those as missing."
    )
    return header + "\n" + "\n".join(f"- {line}" for line in lines)


def block_for_agent(config: dict, agent: dict, project_path: Path) -> str:
    """The SITE FACTS block this expert should receive, or "" (no facts / not mapped)."""
    mapping = ((config.get("site_facts") or {}).get("agents")) or DEFAULT_AGENT_BLOCKS
    kind = mapping.get(str(agent.get("id") or ""))
    if not kind:
        return ""
    facts = load_facts(project_path)
    if not facts:
        return ""
    return facts_block(facts, kind)


def describe(facts: dict) -> str:
    """Everything, for showing to the designer."""
    seen: set[str] = set()
    lines = []
    for line in physical_lines(facts) + regulatory_lines(facts)[1:]:
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return "\n".join(f"- {line}" for line in lines)
