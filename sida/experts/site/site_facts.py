#!/usr/bin/env python3
"""Site facts: what government data says about the project's parcel(s).

An address is resolved to one or more parcels (a site may merge several), each parcel's
zoning and land characteristics are fetched, and the result is saved in the project as
site_facts.json. Experts then receive it as a SITE FACTS block, so zoning and statutory
limits come from data instead of model memory. `attach_ordinance` adds the municipality's
도시·군계획 조례 articles on 건폐율 and 용적률, quoted as written.

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

from sida.config import ROOT
from sida.experts.site import landapi
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


def attach_ordinance(facts: dict, *, http_get=None) -> dict:
    """
    Add facts["ordinance"]: the municipality's 도시·군계획 조례 and its 건폐율 / 용적률 articles.
    A failed lookup is kept as {"error": kind} so it shows as 미확인 instead of being guessed.
    """
    from sida.experts.regulation import ordinance  # the law.go.kr client lives with regulation

    body = facts["summary"].get("municipality")
    if not (body and facts["summary"]["zoning"]):
        facts.pop("ordinance", None)  # zoning unknown: an older site's ordinance must not linger
    else:
        found = ordinance.lookup(body, http_get=http_get)
        zone_table = load_limits()["zones"]
        found["values"] = {
            z["zone"]: ordinance.zone_values(found["articles"], z["zone"], zone_table[z["zone"]])
            for z in facts["summary"]["zoning"]
        }
        # what the designer hid stays hidden when the same ordinance is looked up again
        before = facts.get("ordinance") or {}
        labels = {r["label"] for r in found["related"]}
        for key in ("dismissed", "detailed"):
            found[key] = [
                x for x in before.get(key) or [] if before.get("name") == found["name"] and x in labels
            ]
        facts["ordinance"] = found
    return facts


GROUP_TITLES = {
    "site": "대지 위치로 정해지는 것",
    "design": "설계 내용으로 얻을 수 있는 완화",
    "admin": "행정이 따로 지정하는 것",
}
GROUP_NOTES = {
    "site": "대지가 그 지구·구역 안에 있으면 기본 수치보다 이 조문이 우선합니다.",
    "design": "조건을 갖추면 받을 수 있는 선택지입니다. 적용된 수치가 아닙니다. 검토할 조문을 고르면 전문가가 원문을 읽습니다.",
    "admin": "지자체가 구역을 지정했을 때만 적용됩니다. 지정 여부는 이 자료로 알 수 없으니 확인하세요.",
}


def _site_districts(facts: dict) -> list[str]:
    """Names of the 지구·구역 the site lies in (not merely next to), without the parentheses."""
    names = []
    for d in facts["summary"]["districts"]:
        if d["relation"] == "접함":
            continue
        name = re.sub(r"\(.*?\)", "", d["name"]).strip()
        if name and name not in names:
            names.append(name)
    return names


def _matched_districts(article_text: str, title: str, districts: list[str]) -> list[str]:
    """Which of the site's districts this article is about ("자연경관지구" also as "경관지구")."""
    haystack = re.sub(r"[\s·ㆍ]", "", title + article_text)
    matched = []
    for name in districts:
        squashed = re.sub(r"[\s·ㆍ]", "", name)
        short = re.sub(r"^(자연|시가지|특화|중심지미관|일반미관|역사문화미관)", "", squashed)
        if len(squashed) >= 4 and (squashed in haystack or (len(short) >= 4 and short in haystack)):
            matched.append(name)
    return matched


def ordinance_options(facts: dict | None) -> dict:
    """
    Everything the ordinance says about 건폐율 / 용적률 for this site, arranged for a designer:
    the base figures per zone, then every other article in three groups (GROUP_TITLES).
    Nothing is filtered out; an option the designer dismissed is marked, not removed.
    "detailed" marks the options whose full text the designer wants the experts to read
    (otherwise experts get the title only; see ordinance_text).
    """
    from sida.experts.regulation import ordinance

    o = (facts or {}).get("ordinance") or {}
    view = {
        "available": bool(o.get("articles")),
        "municipality": o.get("municipality", ""),
        "name": o.get("name", ""),
        "effective": o.get("effective", ""),
        "error": ORDINANCE_ERRORS.get(o.get("error") or "") if o.get("error") else None,
        "base": [],
        "articles": [],
        "groups": [],
    }
    if not facts or not o:
        return view
    for zone, values in (o.get("values") or {}).items():
        view["base"].append({"zone": zone, "bcr": values.get("bcr"), "far": values.get("far")})
    for a in o.get("articles") or []:
        annex = a.get("annex") or {}
        view["articles"].append(
            {
                "label": a["label"],
                "title": a["title"],
                "text": ordinance.readable(a["text"]),
                "annex": {"label": annex.get("label"), "text": "\n".join(annex.get("lines") or [])} if annex else None,
            }
        )
    districts = _site_districts(facts)
    dismissed = set(o.get("dismissed") or [])
    detailed = set(o.get("detailed") or [])
    for group in ordinance.GROUPS:
        items = []
        for r in o.get("related") or []:
            if r.get("group", ordinance.classify(r["title"])) != group:
                continue
            matched = _matched_districts(r.get("text", ""), r["title"], districts) if group == "site" else []
            items.append(
                {
                    "id": r["label"],
                    "label": r["label"],
                    "title": r["title"],
                    "text": ordinance.readable(r.get("text", "")),
                    # site: True / False from the site's districts; design, admin: not knowable here
                    "applies": bool(matched) if group == "site" else None,
                    "matched": matched,
                    "dismissed": r["label"] in dismissed,
                    "detailed": r["label"] in detailed and r["label"] not in dismissed,
                }
            )
        items.sort(key=lambda item: (item["applies"] is not True, item["dismissed"]))
        view["groups"].append(
            {"id": group, "title": GROUP_TITLES[group], "note": GROUP_NOTES[group], "items": items}
        )
    return view


def set_option(
    project_path: Path, option_id: str, *, dismissed: bool | None = None, detailed: bool | None = None
) -> dict:
    """
    The designer's choice for one related article: `dismissed` hides it (experts do not even
    get its title), `detailed` asks for its full text to be sent to the experts. None leaves a
    setting as it is. Returns the new options view.
    """
    facts = load_facts(project_path)
    o = (facts or {}).get("ordinance") or {}
    if option_id not in {r["label"] for r in o.get("related") or []}:
        raise ValueError(f"unknown ordinance article: {option_id}")
    for key, value in (("dismissed", dismissed), ("detailed", detailed)):
        if value is None:
            continue
        kept = [x for x in o.get(key) or [] if x != option_id]
        o[key] = [*kept, option_id] if value else kept
    save_facts(project_path, facts)
    return ordinance_options(facts)


def set_option_dismissed(project_path: Path, option_id: str, dismissed: bool) -> dict:
    """Hide or restore one related article for this project. Returns the new options view."""
    return set_option(project_path, option_id, dismissed=dismissed)


def describe_options(facts: dict) -> str:
    """The three groups as text, for the terminal ("" when there is no ordinance)."""
    view = ordinance_options(facts)
    if not view["available"]:
        return ""
    lines = [f"{view['name']} (시행 {view['effective']})"]
    for group in view["groups"]:
        lines.append(f"\n[{group['title']}] {group['note']}")
        if not group["items"]:
            lines.append("  (해당 조문 없음)")
        for item in group["items"]:
            mark = "숨김 " if item["dismissed"] else "원문 " if item["detailed"] else ""
            if item["applies"] is True:
                where = f" ← 이 대지 해당: {', '.join(item['matched'])}"
            elif item["applies"] is False:
                where = " (이 대지가 속한 지구·구역은 이 조문에 나오지 않음)"
            else:
                where = ""
            lines.append(f"  {mark}{item['label']} {item['title']}{where}")
    return "\n".join(lines)


def refresh(
    project_path: Path, query: str, candidates: list[dict], *, http_get=None, progress=None
) -> dict:
    """
    Look the chosen parcels up as one site, add the ordinance, save and return the facts.
    The designer's earlier choices about ordinance articles are carried over. Used by the
    terminal (/site) and the web API alike. `progress(municipality)` is called before the
    ordinance lookup, which is the slow part.
    """
    facts = build_facts(query, candidates, http_get=http_get)
    previous = load_facts(project_path)
    if previous and previous.get("ordinance"):
        facts["ordinance"] = previous["ordinance"]
    if progress and facts["summary"]["zoning"]:
        progress(facts["summary"]["municipality"])
    attach_ordinance(facts)
    save_facts(project_path, facts)
    return facts


def pick_candidates(candidates: list[dict], pnus: list[str]) -> list[dict]:
    """The candidates with these PNUs, in the order asked. ValueError if one is not among them."""
    by_pnu = {c["pnu"]: c for c in candidates}
    wanted = list(dict.fromkeys(str(p) for p in pnus))
    missing = [p for p in wanted if p not in by_pnu]
    if not wanted or missing:
        raise ValueError(f"parcel not among the search results: {', '.join(missing) or '(none given)'}")
    return [by_pnu[p] for p in wanted]


def site_view(facts: dict | None) -> dict:
    """Saved site facts arranged for a screen: parcels, zoning with statutory limits, flags."""
    if not facts:
        return {"available": False, "query": "", "fetched_at": "", "parcels": [], "summary": None, "lines": []}
    parcels = []
    for p in facts["parcels"]:
        ch = p.get("characteristics") or {}
        parcels.append(
            {
                "pnu": p["pnu"],
                "address": p.get("address", ""),
                "road_address": p.get("road_address", ""),
                "building": p.get("building", ""),
                "area_m2": ch.get("area_m2"),
                "land_category": ch.get("land_category", ""),
                "use": ch.get("use", ""),
                "road_side": ch.get("road_side", ""),
                "errors": [e["what"] for e in p.get("errors") or []],
            }
        )
    return {
        "available": True,
        "query": facts.get("query", ""),
        "fetched_at": facts.get("fetched_at", ""),
        "parcels": parcels,
        "summary": facts["summary"],
        "lines": describe(facts).replace("\n- ", "\n").removeprefix("- ").split("\n"),
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
    '서울특별시 종로구 …' → '서울특별시' (구·광역시의 군은 건폐율·용적률을 정하지 않음),
    '제주특별자치도 제주시 …' → '제주특별자치도'.
    """
    tokens = address.split()
    if not tokens:
        return ""
    if tokens[0] == "전남광주통합특별시" and len(tokens) > 1:
        # Merged in 2026; the ordinances are still those of the former bodies. A 구 is the
        # former 광주광역시 (listed on law.go.kr as "(구)광주광역시"); a 시·군 keeps its own.
        return "광주광역시" if tokens[1].endswith("구") else " ".join(tokens[:2])
    if tokens[0].endswith("시") or tokens[0].startswith("제주"):
        # 특별시·광역시·특별자치시, and 제주 (its 시 are not ordinance-making bodies)
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
            f"실제 적용값은 {body} 도시계획조례가 이 범위 안에서 정함."
        )
        lines.append(_ordinance_line(facts, body))
        lines += _ordinance_value_lines(facts)
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


ORDINANCE_ERRORS = {
    "not_found": "법제처 자치법규에서 도시·군계획 조례를 찾지 못함",
    "no_articles": "조례는 찾았으나 건폐율·용적률 조문을 가려내지 못함",
    "no_key": "법제처 인증값(LAW_OPEN_API_OC) 없음",
    "denied": "법제처가 요청을 거부함",
    "network": "법제처 연결 실패",
    "bad_response": "법제처 응답이 예상과 다름",
}


def _ordinance_line(facts: dict, body: str) -> str:
    o = facts.get("ordinance")
    if not o:
        return f"조례 조문: 조회하지 않음(미확인) — {body} 도시계획조례에서 직접 verify."
    if not o.get("articles"):
        why = ORDINANCE_ERRORS.get(o.get("error") or "", "조회 실패")
        name = f"{o['name']} " if o.get("name") else ""
        return f"조례 조문: {name}미확인({why}) — 수치를 추정하지 말고 verify 항목으로 둘 것."
    cited = ", ".join(f"{a['label']}({a['title']})" for a in o["articles"])
    kinds = {a["kind"] for a in o["articles"]}
    missing = [w for k, w in (("bcr", "건폐율"), ("far", "용적률")) if k not in kinds and "both" not in kinds]
    gap = f" {'·'.join(missing)} 조문은 가려내지 못함(미확인)." if missing else ""
    return (
        f"적용 조례: {o['name']} (시행 {o['effective'] or '시행일 미확인'}) — {cited}. 원문은 "
        f"조례 블록에 있음.{gap} 지구단위계획·용도지구·완화 조문에 따라 달라질 수 있으므로 verify."
    )


def _figure_text(word: str, figure: dict | None) -> str:
    """One ratio of one zone, as read from the ordinance, always next to the quoted line."""
    if figure is None:
        return f"{word} — 조문과 별표에서 이 용도지역의 줄을 찾지 못함, 미확인"
    quote = figure["quote"] if len(figure["quote"]) <= 110 else figure["quote"][:110] + "…"
    cited = f"{figure['label']} 「{quote}」"
    if figure.get("out_of_range"):
        return f"{word} — 읽은 값이 법정 범위를 벗어나 표시하지 않음, 원문 확인: {cited}"
    if figure["value"] is None:
        return f"{word} — 수치를 규칙으로 읽지 못함(여러 수치, 소수 등), 원문 확인: {cited}"
    note = " (단서·예외가 붙어 있음 — 원문 확인)" if figure["conditional"] else ""
    return f"{word} {figure['value']:,}% 이하{note}: {cited}"


def _ordinance_value_lines(facts: dict) -> list[str]:
    o = facts.get("ordinance") or {}
    if not o.get("articles"):
        return []
    lines = []
    for zone, values in (o.get("values") or {}).items():
        if any(a["kind"] == "both" for a in o["articles"]) and not any(values.values()):
            lines.append(f"조례값({zone}): 건폐율·용적률을 한 조문(또는 별표)에서 정함 — 수치를 읽지 못함, 원문 확인")
            continue
        lines.append(
            f"조례값({zone}): " + "; ".join(_figure_text(word, values.get(kind)) for kind, word in (("bcr", "건폐율"), ("far", "용적률")))
        )
    return lines


def ordinance_text(facts: dict) -> str:
    """
    What the experts receive of the ordinance — only what concerns this site ("" if none):
      - the base articles without the 호 of other 용도지역 (a table annex: the zone's row)
      - the articles of districts the site lies in, cut to the 항 about 건폐율 / 용적률
      - relaxations and tightening: titles, plus the full text of the ones the designer
        marked "detailed". Dismissed ones are left out altogether.
    The designer's own view (ordinance_options, /site 조례) always has every article in full.
    """
    from sida.experts.regulation import ordinance

    o = facts.get("ordinance") or {}
    if not o.get("articles"):
        return ""
    zones = [z["zone"] for z in facts["summary"]["zoning"]]
    all_zones = list(load_limits()["zones"])
    parts = []
    for a in o["articles"]:
        body = ordinance.excerpt_for_zones(a["text"], zones, all_zones)
        parts.append(f"source: {o['name']} {a['label']} (시행 {o['effective']})\n{body}")
        annex = a.get("annex") or {}
        if annex.get("lines"):
            rows = {
                f["quote"]
                for values in (o.get("values") or {}).values()
                for f in values.values()
                if f and "표의 열" in f["quote"] and annex["label"] in f.get("label", "")
            }
            body = "\n".join(sorted(rows)) if rows else ordinance.excerpt_for_zones(
                "\n".join(annex["lines"]), zones, all_zones
            )
            parts.append(f"source: {o['name']} {annex['label']} (시행 {o['effective']})\n{body}")
        elif annex:
            parts.append(f"{annex['label']}: 파일을 읽지 못함(미확인) — 조례 원문에서 직접 확인")

    view = ordinance_options(facts)
    groups = {g["id"]: [i for i in g["items"] if not i["dismissed"]] for g in view["groups"]}
    raw = {r["label"]: r.get("text", "") for r in o.get("related") or []}

    applied = [i for i in groups["site"] if i["applies"]]
    if applied:
        body = "\n\n".join(
            f"source: {o['name']} {i['label']} ({i['title']}) — 해당: {', '.join(i['matched'])}\n"
            + ordinance.ratio_paragraphs(raw[i["label"]])
            for i in applied
        )
        parts.append(f"[이 대지가 속한 지구·구역의 조문 — 기본 수치보다 우선함]\n{body}")

    for group, heading, rule in (
        ("design", "설계로 얻을 수 있는 완화(선택지)", "조건을 갖출 때만 가능. 적용된 것으로 계산하지 말 것"),
        ("admin", "지자체가 구역을 지정했을 때만 적용", "지정 여부를 verify 항목으로 둘 것"),
    ):
        items = groups[group]
        if not items:
            continue
        titles = ", ".join(f"{i['label']}({i['title']})" for i in items)
        lines = [f"[{heading} — {rule}]", f"조문 목록: {titles}"]
        full = [i for i in items if i["detailed"]]
        if full:
            lines.append("설계자가 검토를 요청한 조문의 원문:")
            lines += [f"source: {o['name']} {i['label']} ({i['title']})\n{i['text']}" for i in full]
        else:
            lines.append("원문은 포함하지 않음. 조건을 추정하지 말고, 해당할 만한 조문은 번호로 가리켜 verify로 둘 것.")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def ordinance_block(facts: dict) -> str:
    """RETRIEVED KNOWLEDGE block with the ordinance articles as written, or ""."""
    text = ordinance_text(facts)
    if not text:
        return ""
    o = facts["ordinance"]
    zones = ", ".join(z["zone"] for z in facts["summary"]["zoning"])
    header = (
        f"RETRIEVED KNOWLEDGE (local ordinance) — {o['municipality']}의 도시·군계획 조례 조문 원문 "
        f"(법제처 자치법규, 조회일 {facts.get('fetched_at', '')[:10]}). 이 대지의 용도지역: {zones}. "
        "Quote the line for that zone and cite the `source:`. The text is the ordinance as written. "
        "SITE FACTS lists the figure read from it (조례값); where the two differ, the text wins. "
        "Do not apply a relaxation clause unless the project clearly meets its condition."
    )
    return header + "\n\n" + text


def block_kind(config: dict, agent: dict) -> str | None:
    """Which SITE FACTS block this expert is mapped to ("physical" | "regulatory" | None)."""
    mapping = ((config.get("site_facts") or {}).get("agents")) or DEFAULT_AGENT_BLOCKS
    return mapping.get(str(agent.get("id") or ""))


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
    kind = block_kind(config, agent)
    if not kind:
        return ""
    facts = load_facts(project_path)
    if not facts:
        return ""
    return facts_block(facts, kind)


def ordinance_block_for_agent(config: dict, agent: dict, project_path: Path) -> str:
    """The ordinance articles for experts that get the regulatory block, or ""."""
    if block_kind(config, agent) != "regulatory":
        return ""
    facts = load_facts(project_path)
    return ordinance_block(facts) if facts else ""


def describe(facts: dict) -> str:
    """Everything, for showing to the designer."""
    seen: set[str] = set()
    lines = []
    for line in physical_lines(facts) + regulatory_lines(facts)[1:]:
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return "\n".join(f"- {line}" for line in lines)
