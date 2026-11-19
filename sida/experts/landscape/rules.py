"""The 조경 and 공개 공지 a site asks for, read by rule from data/landscape_rules.yaml (2026-11-20 지훈
"조경 관련해서도 뭔가 넣으면 좋을듯").

Nothing is fetched or read by a model: the figures are the rules file's, copied from the 원문.
`requirement` works them out for one building (its 연면적 and use) on the site; `card_line` is
the site card's "조경" line, which knows no building yet and so names the ratio by 연면적.

Every result says how sure it is (`status`, as the site card's lines): "read" (by rule), "conditional"
(depends on what is not known yet, such as the 연면적), "none" (not asked, and why) and "check" (not
in the rules file; where to look).
"""

from __future__ import annotations

import math
from functools import lru_cache

import yaml

from sida.config import ROOT

RULES_PATH = ROOT / "data" / "landscape_rules.yaml"
PENDING = " (조문 원문 대조 전)"


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def _region(municipality: str, table: dict) -> str | None:
    return next((name for name in table if (municipality or "").startswith(name)), None)


def _pending(*parts: dict) -> str:
    return "" if all(p.get("verified") for p in parts) else PENDING


def _quote(text: str) -> str:
    return " ".join((text or "").split())


def _area(m2: float) -> str:
    return f"{m2:,.0f}㎡" if m2 >= 100 else f"{m2:,.1f}㎡"


def _tier(tiers: list, gross: float) -> float:
    return float(next(pct for least, pct in tiers if gross >= least))


def tiers_text(tiers: list) -> str:
    """"연면적 2,000㎡ 이상 15% · 1,000㎡ 이상 10% · 그 밖 5%"."""
    parts = [f"{least:,}㎡ 이상 {pct:g}%" if least else f"그 밖 {pct:g}%" for least, pct in tiers]
    return "연면적 " + " · ".join(parts)


def open_uses(municipality: str) -> list[str]:
    """The use keys that bring 공개 공지 where the site is: the region's ordinance's, else the statute's."""
    rules = load_rules()["open_space"]
    region = _region(municipality, rules["regions"])
    return list(rules["regions"][region]["uses"] if region else rules["statute_uses"])


def uses(municipality: str = "") -> list[dict]:
    """The uses the card offers (those that bring 공개 공지 there, then "그 밖"): [{"key", "label"}]."""
    labels = load_rules()["open_space"]["uses"]
    return [{"key": k, "label": labels[k]} for k in open_uses(municipality)] + [{"key": "other", "label": "그 밖의 용도"}]


def planting_per_m2(zone: str) -> dict:
    """{"trees", "shrubs"} per ㎡ of 조경면적 for the 용도지역 (조경기준)."""
    for word, counts in load_rules()["planting"]["per_m2"]:
        if word is None or word in (zone or ""):
            return dict(counts)
    return {"trees": 0.0, "shrubs": 0.0}


def _landscape(zone: str, municipality: str, site_area: float | None, gross: float | None) -> dict:
    """The 조경 asked: {"status", "ratio", "area_m2", "tiers", "detail", "quote", "source"}."""
    rules = load_rules()["landscape"]
    out = {"status": "check", "ratio": None, "area_m2": None, "tiers": None, "detail": "", "quote": _quote(rules["text"]),
           "source": rules["law"]}
    if not site_area:
        return {**out, "detail": "대지면적 미확인이라 조경면적을 셀 수 없음"}
    if site_area < rules["min_site_m2"]:
        return {**out, "status": "none", "detail": f"대지 {_area(site_area)}가 {rules['min_site_m2']}㎡ 미만이라 법 제42조의 조경 대상이 아님"}
    exempt = next((w for w in rules["exempt_zones"] if w in (zone or "")), None)
    if exempt:
        return {**out, "status": "none", "detail": f"{zone}: {rules['exempt_law']}에 따라 조경을 하지 않을 수 있음",
                "quote": _quote(rules["exempt_text"]), "source": rules["exempt_law"]}
    region = _region(municipality, rules["regions"])
    if not region:
        return {**out, "detail": f"{municipality or '이 지역'}의 건축 조례 조경 비율이 규칙 파일에 없음, 조례 원문 확인"}
    table = rules["regions"][region]
    pending = _pending(rules, table)
    out.update(quote=_quote(table["text"]), source=table["law"], tiers=table["tiers"])
    small = table.get("small_site")
    if small and site_area < small["below"]:  # a small site asks one ratio whatever its 연면적 (서울 제24조③)
        ratio = float(small["pct"])
        return {**out, "status": "read", "ratio": ratio, "area_m2": round(site_area * ratio / 100, 1), "tiers": [[0, ratio]],
                "detail": f"대지 {_area(site_area)}가 {small['below']}㎡ 미만이라 연면적과 관계없이 대지면적의 {ratio:g}% 이상{pending}"}
    if gross is None:
        return {**out, "status": "conditional", "detail": f"{tiers_text(table['tiers'])}{pending}"}
    ratio = _tier(table["tiers"], gross)
    area = site_area * ratio / 100
    detail = f"연면적 {_area(gross)} → 대지면적의 {ratio:g}% 이상{pending}"
    return {**out, "status": "read", "ratio": ratio, "area_m2": round(area, 1), "detail": detail}


def _open_space(zone: str, municipality: str, site_area: float | None, gross: float | None, use: str | None) -> dict:
    """The 공개 공지 asked: {"status", "ratio", "area_m2", "detail", "quote", "source"}."""
    rules = load_rules()["open_space"]
    out = {"status": "none", "ratio": None, "area_m2": None, "detail": "", "quote": _quote(rules["text"]), "source": rules["law"]}
    if not any(w in (zone or "") for w in rules["zones"]):
        return {**out, "detail": f"{zone or '용도지역 미확인'}: 공개 공지 대상 지역(일반주거·준주거·상업·준공업)이 아님"}
    if use not in open_uses(municipality):
        return {**out, "status": "conditional" if use is None else "none",
                "detail": "건물 용도를 고르면 공개 공지 대상인지 확인" if use is None else "공개 공지 대상 용도가 아님"}
    if gross is None:
        return {**out, "status": "conditional", "detail": f"{rules['uses'][use]} 바닥면적 {rules['min_floor_m2']:,}㎡ 이상이면 대상"}
    if gross < rules["min_floor_m2"]:
        return {**out, "detail": f"{rules['uses'][use]} {_area(gross)}로 {rules['min_floor_m2']:,}㎡ 미만"}
    region = _region(municipality, rules["regions"])
    if not region or not site_area:
        why = "대지면적 미확인" if not site_area else f"{municipality or '이 지역'}의 건축 조례 공개 공지 비율이 규칙 파일에 없음, 조례 원문 확인"
        return {**out, "status": "check", "detail": f"대상. {why} (법은 대지면적의 10% 이하에서 조례로 정함)"}
    table = rules["regions"][region]
    ratio = _tier(table["tiers"], gross)
    area = site_area * ratio / 100
    shape = ""
    if table.get("least_width_m"):
        shape = f". {table['least_piece_m2']:g}㎡ 이상 2곳 이내, 폭 {table['least_width_m']:g}m 이상, 가장 넓은 도로변"
    return {**out, "status": "read", "ratio": ratio, "area_m2": round(area, 1),
            "least_width_m": table.get("least_width_m"), "least_piece_m2": table.get("least_piece_m2"),
            "detail": f"{rules['uses'][use]} 바닥면적 {_area(gross)} → 대지면적의 {ratio:g}% 이상{shape}{_pending(rules, table)}",
            "quote": _quote(table["text"]), "source": table["law"]}


def requirement(zone: str, municipality: str, site_area: float | None, gross: float | None, use: str | None = None) -> dict:
    """
    What one building (its 연면적 `gross`, its `use` key or None) asks on the site: {"landscape",
    "open_space", "planting": {"trees", "shrubs", "trees_per_m2", "shrubs_per_m2", "detail", "quote",
    "source"}}. The planting counts are for the 조경면적 asked (none when it is not known).
    """
    landscape = _landscape(zone, municipality, site_area, gross)
    rules = load_rules()["planting"]
    per = planting_per_m2(zone)
    base = landscape["area_m2"]
    planting = {"trees_per_m2": per["trees"], "shrubs_per_m2": per["shrubs"],
                "trees": math.ceil(base * per["trees"] - 1e-9) if base else None,
                "shrubs": math.ceil(base * per["shrubs"] - 1e-9) if base else None,
                "planted_m2": round(base * rules["planted_share"] / 100, 1) if base else None,
                "least_side_m": rules["least_side_m"],
                "detail": f"조경면적 1㎡마다 교목 {per['trees']:g}주, 관목 {per['shrubs']:g}주 이상{_pending(rules)}",
                "quote": _quote(rules["text"]), "source": rules["law"],
                "share_detail": f"식재면적은 조경의무면적의 {rules['planted_share']}% 이상, 한 곳은 한 변 {rules['least_side_m']:g}m 이상",
                "share_quote": _quote(rules["share_text"]), "share_source": rules["share_law"],
                "weight_quote": _quote(rules["weight_text"])}
    return {"landscape": landscape, "open_space": _open_space(zone, municipality, site_area, gross, use), "planting": planting}


STATES = {"read": "규칙", "conditional": "조건", "none": "해당 없음", "check": "확인 필요"}


def card_line(zones: list[str], municipality: str, site_area: float | None) -> dict | None:
    """The site card's "조경" line (site_rules.card): the ratio by 연면적, as no building is known yet.
    Carries `tiers` and `min_site_m2` so the drafting table can set a scheme's 연면적 against them."""
    if len(zones) != 1:
        return None
    found = _landscape(zones[0], municipality, site_area, None)
    value = {"none": "해당 없음", "check": "미확인", "read": f"대지면적의 {found['ratio']:g}%" if found["ratio"] else ""}.get(found["status"], "")
    if found["status"] == "conditional":
        least = min(p for _, p in found["tiers"])
        top = max(p for _, p in found["tiers"])
        value = f"대지면적의 {least:g}~{top:g}%"
    return {"id": "landscape", "status": found["status"], "title": "조경", "value": value, "detail": found["detail"],
            "quote": found["quote"], "source": found["source"], "tiers": found["tiers"],
            "min_site_m2": load_rules()["landscape"]["min_site_m2"]}
