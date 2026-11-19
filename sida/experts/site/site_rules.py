"""What applies to the site, in at most five lines (2026-11-17 지훈: "대지 정보가 정확한 건 알겠는데
사용자 입장에서 체감이 안 돼. 뭘 적용해야 하는지 간결하게 알려 줄 방법").

The site card puts these above the full facts, in this order:

1. 용적률 and 2. 건폐율 of the site's one 용도지역: the ordinance's figure read by rule, with its
   proviso applied when it names a 지구·구역 the site lies in (site_facts.site_figure), and what it
   allows on this site's area (area × ratio). Several 용도지역: one line saying so.
3. 높이: the site's 지역·지구 whose names bring a height limit of their own (data/site_rules.yaml
   height_words), named as the government names them.
4. 정북일조: whether 건축법 제61조제1항 applies, by the 용도지역's name.
   조경: the 대지의 조경 the ordinance asks, by 연면적 (sida/experts/landscape/rules.py card_line;
   it carries the ratio `tiers` so the table can set a scheme's 연면적 against them).
5. 따로 정한 계획: areas whose own plan may override the base figures (plan_words), to check.

Every line says how sure it is (`status`): "read" (read by rule), "conditional" (holds, with a
condition or a proviso left to the 원문), "none" (does not apply, and why), "check" (not known
from the facts; where to look). A figure always comes with the line it was read from. Lines 3 and
5 appear only when a district is named; their absence does not mean there is no limit.
"""

from __future__ import annotations

from functools import lru_cache

import yaml

from sida.config import ROOT
from sida.experts.landscape import rules as landscape_rules
from sida.experts.site import eum, site_facts

RULES_PATH = ROOT / "data" / "site_rules.yaml"
WORDS = {"bcr": "건폐율", "far": "용적률"}
AMOUNTS = {"bcr": "건축면적", "far": "연면적"}
STATUSES = ("read", "conditional", "none", "check")


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def _line(id_: str, status: str, title: str, value: str, detail: str = "", quote: str = "", source: str = "") -> dict:
    return {"id": id_, "status": status, "title": title, "value": value, "detail": detail, "quote": quote, "source": source}


def _area(m2: float) -> str:
    return f"{m2:,.0f}㎡" if m2 >= 100 else f"{m2:,.1f}㎡"


def ratio_line(facts: dict, zone: dict, kind: str) -> dict:
    """The coverage or FAR line of the site's one zone."""
    word, statutory = WORDS[kind], zone["bcr_max"] if kind == "bcr" else zone["far_max"]
    s = facts["summary"]
    area = s["total_area_m2"] if s.get("area_complete") else None
    o = facts.get("ordinance") or {}
    figure = site_facts.site_figure(facts, zone["zone"], kind)
    if not o.get("articles") or figure is None:
        why = site_facts.ORDINANCE_ERRORS.get(o.get("error") or "", "") if o else "조례를 조회하지 않음"
        detail = f"조례값 미확인{f'({why})' if why else ''}. 법정 상한이며 조례가 이보다 낮게 정할 수 있음"
        return _line(kind, "check", word, f"법정 상한 {statutory}%", detail)
    quote, label = figure.get("quote", ""), figure.get("label", "")
    value = site_facts.ruling_value(figure)
    if value is None:
        applied = figure.get("applied")
        if applied:
            detail = f"대지가 {applied['where']} 안이라 단서가 걸리지만 한 가지 수치로 읽히지 않음, 원문 확인"
        elif figure.get("out_of_range"):
            detail = "읽은 값이 법정 범위를 벗어나 수치를 내지 않음, 원문 확인"
        else:
            detail = "한 가지 수치로 읽히지 않음, 원문 확인"
        return _line(kind, "check", word, "미확인", detail, quote, label)
    allowed = f"{AMOUNTS[kind]} 최대 {_area(area * value / 100)}" if area else f"{AMOUNTS[kind]}은 대지면적 미확인"
    applied = figure.get("applied")
    if applied:
        reason = f"{zone['zone']} 기본 {applied['base']:,}%, 대지가 {applied['where']} 안이라 단서의 {value:,}%"
        return _line(kind, "read", word, f"{value:,}%", f"{allowed}. {reason}", quote, label)
    if figure.get("conditional"):
        return _line(kind, "conditional", word, f"{value:,}%", f"{allowed}. 단서·예외가 붙어 있음, 원문 확인", quote, label)
    return _line(kind, "read", word, f"{value:,}%", allowed, quote, label)


def _named(facts: dict, words: list[str], skip: set[str]) -> list[str]:
    """The site's districts (as the government names them) whose names contain one of `words`."""
    out = []
    for d in facts["summary"]["districts"]:
        name = d["name"]
        if d.get("relation") == "접함" or name in skip or name in out:
            continue
        if any(w in name for w in words):
            out.append(name)
    return out


def height_districts(facts: dict) -> list[str]:
    """The site's districts that set a height of their own (height_words: 고도지구 and the like), as
    the government names them."""
    return _named(facts, load_rules()["height_words"], set())


def _topic(word: str) -> str:
    """은 or 는 after `word` (지역 → 은)."""
    last = word[-1:]
    return "은" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "는"


def sunlight_line(facts: dict) -> dict | None:
    rule = load_rules()["north_sunlight"]
    zones = [z["zone"] for z in facts["summary"]["zoning"]]
    if not zones:
        return None
    hit = [z for z in zones if z in rule["zones"]]
    pending = "" if rule.get("verified") else " (조문 원문 대조 전)"
    if hit:
        return _line("sunlight", "read", "정북일조", "적용", f"{rule['summary']}{pending}", " ".join(rule["text"].split()), rule["law"])
    where = ", ".join(zones)
    return _line("sunlight", "none", "정북일조", "해당 없음", f"{where}{_topic(where)} 전용·일반주거지역이 아님", "", rule["law"])


def card(facts: dict | None) -> list[dict]:
    """The lines of "이 대지에 걸리는 것" (module docstring). [] without a site or zoning."""
    if not facts or not facts["summary"]["zoning"]:
        return []
    zoning = facts["summary"]["zoning"]
    lines = []
    if len(zoning) == 1:
        lines += [ratio_line(facts, zoning[0], "far"), ratio_line(facts, zoning[0], "bcr")]
    else:
        names = ", ".join(z["zone"] for z in zoning)
        lines.append(_line("zones", "check", "용도지역 여러 개", names, "필지마다 건폐율·용적률 한도가 달라 면적 비율로 나눠 봐야 함"))
    rules = load_rules()
    heights = _named(facts, rules["height_words"], set())
    if heights:
        height = _line("height", "conditional", "높이", ", ".join(heights), "이 지역·지구가 높이를 따로 정함, 지정 내용과 원문 확인")
        # 토지이음의 이 필지 토지이용계획: 지역·지구 목록이 고도지구의 높이를 함께 적음("고도지구(28m이하)")
        page = eum.land_use_page((facts.get("parcels") or [{}])[0].get("pnu", ""))
        lines.append({**height, "links": [page] if page else []})
    sunlight = sunlight_line(facts)
    if sunlight:
        lines.append(sunlight)
    s = facts["summary"]
    green = landscape_rules.card_line([z["zone"] for z in zoning], s.get("municipality") or "",
                                      s["total_area_m2"] if s.get("area_complete") else None)
    if green:
        lines.append(green)
    plans = _named(facts, rules["plan_words"], set(heights))
    if plans:
        lines.append(_line("plan", "check", "따로 정한 계획", ", ".join(plans), "구역의 계획이 높이·용적률·건축선을 따로 정했을 수 있음, 계획 내용 확인"))
    return lines
