#!/usr/bin/env python3
"""The 도시·군계획 조례 that applies to a site, and its 건폐율 / 용적률 articles.

국토계획법 leaves the actual building-coverage and floor-area ratios of each 용도지역 to the
ordinance of the 특별시·광역시·특별자치시·특별자치도·시·군. `lookup` finds that ordinance on
law.go.kr and returns the two articles as written. `zone_values` then reads the figure for
one 용도지역 out of that text by fixed rules ("100분의 60" → 60, "60퍼센트" → 60,
"1천300퍼센트" → 1300). It gives no figure when the item is not a single plain percentage
or when the result falls outside the statutory range; the quoted line is always kept.
When an article only says "별표 N과 같다", the annex file is downloaded and read the same way.

No printing. `lookup` never raises for an API failure — the failure is returned in "error".
"""

from __future__ import annotations

import re
from datetime import date

from sida.experts.regulation import hwp, lawapi

# Titles of the base articles vary only in spacing: "용도지역안에서의 건폐율",
# "용도지역 안에서의 용적률". Relaxation / tightening / district articles are listed, not quoted.
_NOT_BASE = ("완화", "강화", "지구단위", "특례")
KINDS = {"bcr": "건폐율", "far": "용적률"}


def _squash(text: str) -> str:
    return re.sub(r"[\s·ㆍ]", "", text or "")


def province_key(name: str) -> str:
    """'강원도' and '강원특별자치도' → '강원'; '전라북도' and '전북특별자치도' → '전북'."""
    name = (name or "").strip()
    if len(name) == 4 and name.endswith("도") and name[2] in "남북":
        return name[0] + name[2]
    return name[:2]


def same_body(org: str, municipality: str) -> bool:
    """Does the ordinance's 지자체기관명 name the same body as `municipality`?"""
    a, b = (org or "").replace("(구)", "").split(), (municipality or "").split()
    if not a or not b or len(a) != len(b):
        return False
    return province_key(a[0]) == province_key(b[0]) and a[1:] == b[1:]


def find_planning_ordinance(municipality: str, *, http_get=None, today: date | None = None) -> dict | None:
    """The body's own 도시계획 조례 / 군계획 조례 as a search hit, or None."""
    tokens = (municipality or "").split()
    if not tokens:
        return None
    hits = lawapi.search_ordinances(f"{tokens[-1]} 도시계획 조례", http_get=http_get)
    own = [
        h
        for h in hits
        if h["kind"] == "조례"
        and h["mst"]
        and same_body(h["org"], municipality)
        and _squash(h["name"]).endswith(("도시계획조례", "군계획조례"))
    ]
    if not own:
        return None
    now = (today or date.today()).isoformat()
    in_force = [h for h in own if h["effective"] and h["effective"] <= now]
    return max(in_force or own, key=lambda h: h["effective"])


# What decides whether a related article applies, checked in this order on the title.
#   admin  — the municipality designates an area (강화); the designer cannot choose it
#   site   — where the site is: a 지구 / 구역 it lies in
#   design — what is built or given: a relaxation the design can qualify for
GROUPS = ("site", "design", "admin")
_ADMIN_WORDS = ("강화",)
# "그 밖의 건폐율" (서울) lists the 지구·구역 rules without naming them in the title
_SITE_WORDS = ("지구", "구역", "성장관리", "그밖", "기타")


def classify(title: str) -> str:
    """Group of a related article: "site" | "design" | "admin"."""
    squashed = _squash(title)
    if any(word in squashed for word in _ADMIN_WORDS):
        return "admin"
    if any(word in squashed for word in _SITE_WORDS):
        return "site"
    return "design"


def readable(text: str) -> str:
    """Article text with each 항 and each 호 on its own line (the API glues them together)."""
    out: list[str] = []
    for part in re.split(r"\s*(?=[①-⑳])", (text or "").strip()):
        if not part:
            continue
        starts: list[int] = []
        pos, n = 0, 1
        while True:
            match = re.compile(rf"{n}\.\s*(?=[^\d\s.,)])").search(part, pos)
            if not match:
                break
            starts.append(match.start())
            pos = match.end()
            n += 1
        head = part[: starts[0]].strip() if starts else part.strip()
        if head:
            out.append(head)
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(part)
            out.append("  " + part[start:end].strip())
    return "\n".join(out)


def excerpt_for_zones(text: str, zones: list[str], all_zones: list[str]) -> str:
    """
    `readable(text)` without the 호 that are about some other 용도지역. Everything else stays:
    headings, the 호 of the site's own zones, and any 호 that is not a zone line at all.
    """
    mine = [_squash(z) for z in zones]
    others = [_squash(z) for z in all_zones if _squash(z) not in mine]
    kept: list[str] = []
    dropped = 0
    for line in readable(text).split("\n"):
        item = re.match(r"\s+\d+\.\s*(.*)", line)
        head = _squash(item.group(1)) if item else ""
        if item and any(head.startswith(z) for z in others) and not any(head.startswith(z) for z in mine):
            dropped += 1
            continue
        kept.append(line)
    if dropped:
        kept.append(f"  (다른 용도지역의 호 {dropped}개 생략)")
    return "\n".join(kept)


def ratio_paragraphs(text: str) -> str:
    """The 항 of an article that mention 건폐율 or 용적률 (the whole article if it has no 항)."""
    parts = re.split(r"\n(?=[①-⑳])", readable(text))
    if len(parts) < 2:
        return parts[0]
    kept = [p for p in parts[1:] if any(word in p for word in KINDS.values())]
    if not kept or len(kept) == len(parts) - 1:
        return "\n".join(parts)
    return "\n".join([parts[0], *kept, "(건폐율·용적률을 다루지 않는 항은 생략)"])


def pick_articles(articles: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    (the base 건폐율 and 용적률 articles, every other article about either). The others
    carry their text and a "group" (see classify): relaxations, district rules, tightening.
    """
    base: dict[str, dict] = {}
    related: list[dict] = []
    for article in articles:
        article = {**article, "title": re.sub(r"\s*<[^>]*>", "", article["title"]).strip()}
        title = _squash(article["title"])
        kinds = [kind for kind, word in KINDS.items() if word in title]
        if not kinds:
            # "자연경관지구 안에서의 건축제한" (서울): a district's article that sets a ratio
            # in its text without saying so in its title
            in_district = ("지구" in title or "구역" in title) and ("안에서" in title or "에서의" in title)
            if in_district and any(word in article["text"] for word in KINDS.values()):
                related.append({"label": article["label"], "title": article["title"], "group": "site", "text": article["text"]})
            continue
        kind = kinds[0]
        # "용도지역안에서의 건폐율", also "용도구역·지역·지구안에서의 건폐율" (여수시)
        zones = "용도지역" in title or (title.startswith("용도") and "지역" in title)
        is_base = zones and not any(word in title for word in _NOT_BASE)
        if is_base and len(kinds) == 2 and "both" not in base and article["text"]:
            base["both"] = {"kind": "both", **article}  # one article for both ratios
        elif is_base and len(kinds) == 1 and kind not in base and article["text"]:
            base[kind] = {"kind": kind, **article}
        else:
            related.append(
                {
                    "label": article["label"],
                    "title": article["title"],
                    "group": classify(article["title"]),
                    "text": article["text"],
                }
            )
    return [base[k] for k in (*KINDS, "both") if k in base], related


def lookup(municipality: str, *, http_get=None, today: date | None = None) -> dict:
    """
    {"municipality", "name", "effective", "mst", "articles", "related", "error"}.
    error: None, a LawApiError kind, "not_found" (no such ordinance listed) or
    "no_articles" (ordinance found, but neither base article recognized).
    """
    result = {
        "municipality": municipality,
        "name": "",
        "effective": "",
        "mst": "",
        "articles": [],
        "related": [],
        "error": None,
    }
    try:
        hit = find_planning_ordinance(municipality, http_get=http_get, today=today)
        if hit is None:
            result["error"] = "not_found"
            return result
        result.update(name=hit["name"], effective=hit["effective"], mst=hit["mst"])
        body = lawapi.ordinance_articles(hit["mst"], http_get=http_get)
    except lawapi.LawApiError as exc:
        result["error"] = exc.kind
        return result
    result["name"] = body["name"] or result["name"]
    result["effective"] = body["effective"] or result["effective"]
    result["articles"], result["related"] = pick_articles(body["articles"])
    if not result["articles"]:
        result["error"] = "no_articles"
    result["articles"] = [follow_annex(a, body.get("annexes") or []) for a in result["articles"]]
    return result


_ANNEX_REF = re.compile(r"별표\s*(\d+)(?:의\s*(\d+))?")


def follow_annex(article: dict, annexes: list[dict]) -> dict:
    """
    An article that lists no zones itself and points at an annex ("…은 별표 27과 같다") gets
    that annex's text: article["annex"] = {"label", "title", "lines"} or {"label", "error"}.
    """
    text = _TAG.sub("", article["text"])
    ref = _ANNEX_REF.search(text)
    if not ref or list_items(text):
        return article
    label = f"별표 {int(ref.group(1))}" + (f"의{int(ref.group(2))}" if ref.group(2) else "")
    annex = next((x for x in annexes if x["label"] == label), None)
    if annex is None:
        return {**article, "annex": {"label": label, "error": "not_listed"}}
    try:
        if annex["format"] != "hwp":
            raise hwp.HwpError(f"unsupported format {annex['format'] or '?'}")
        lines = hwp.paragraphs(lawapi.download_annex(annex["url"]))
    except lawapi.LawApiError as exc:
        return {**article, "annex": {"label": label, "title": annex["title"], "error": exc.kind}}
    except hwp.HwpError:
        return {**article, "annex": {"label": label, "title": annex["title"], "error": "unreadable"}}
    return {**article, "annex": {"label": label, "title": annex["title"], "lines": lines}}


# ---------------------------------------------------------------------------
# Reading the figure for one zone out of a quoted article
# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^<>]{0,80}>|[(\[](?:제목\s*)?(?:개정|신설|전문개정|본조신설|삭제)[^()\[\]]{0,80}[)\]]")
_NUMBER = re.compile(r"100분의\s*([\d,]+)|((?:\d+천)?[\d,]*\d|\d+천)\s*(?:퍼센트|%)")
# Figures are read as whole numbers. "62.5퍼센트" must not be read as 5 (or "100분의 62.5" as
# 62): a decimal gives no figure and the line is shown instead. "60.0" is simply 60.
_WHOLE_DECIMAL = re.compile(r"(?<=\d)\.0+(?!\d)")
# Only a decimal that is part of the figure itself; a date left in the line ("2013.01.01.") is not one.
_DECIMAL = re.compile(r"\d\.\d+\s*(?:퍼센트|%)|100분의\s*[\d,]+\.\d")
_SUBITEM = re.compile(r"가\.\s*\S")  # 목 (가. 나. 다.) always start at 가; glued like "이하가. 아파트"


def _number(match: re.Match) -> int | None:
    raw = (match.group(1) or match.group(2) or "").replace(",", "")
    if "천" in raw:
        thousands, rest = raw.split("천", 1)
        raw = str(int(thousands or 1) * 1000 + int(rest or 0))
    return int(raw) if raw.isdigit() else None


def list_items(text: str) -> list[str]:
    """
    The numbered 호 of an article, in order, without their numbers. The API glues them
    together ("…100분의 402. 제2종…" is 40 followed by item 2), so items are found by
    counting: item n+1 starts at the next "n+1." that is followed by text.
    """
    items: list[str] = []
    start = None
    pos, n = 0, 1
    while True:
        match = re.compile(rf"{n}\.\s*(?=[^\d\s.,)])").search(text, pos)
        if not match:
            break
        if start is not None:
            items.append(text[start : match.start()])
        start = pos = match.end()
        n += 1
    if start is not None:
        tail = text[start:]
        cut = re.search(r"\s*[②-⑳]", tail)  # the last 호 runs into the next 항
        items.append(tail[: cut.start()] if cut else tail)
    return items


def zone_figure(article_text: str, zone: str) -> dict | None:
    """
    The 호 of `article_text` that names `zone`, and the percentage it states.
    {"value": int | None, "quote": str, "conditional": bool} — value is None when the item
    does not state exactly one readable base figure (sub-items, several figures before any
    proviso, a decimal figure, no figure). None when the zone is not listed at all.
    """
    text = _TAG.sub("", article_text or "")
    name = r"\s*".join(map(re.escape, zone))
    for item in list_items(text):
        match = re.match(name + r"(?![가-힣])", item)
        if not match:
            continue
        rest = item[match.end() :]
        base = _WHOLE_DECIMAL.sub("", re.split(r"다만|단,|\(", rest, maxsplit=1)[0])
        figures = [_number(m) for m in _NUMBER.finditer(base)]
        clear = len(figures) == 1 and not _SUBITEM.search(base) and not _DECIMAL.search(base)
        value = figures[0] if clear else None
        return {
            "value": value,
            "quote": " ".join(item.split()),
            "conditional": base != rest or bool(_SUBITEM.search(rest)),
        }
    return None


_PLAIN_NUMBER = re.compile(r"^((?:\d+천)?[\d,]*\d|\d+천)(\.\d+)?\s*(?:퍼센트|%)?\s*(?:이하)?$")


def table_figures(lines: list[str], zone: str) -> dict[str, dict]:
    """
    Figures for `zone` from an annex laid out as a table (one cell per line): the header
    cells "건폐율(%)" / "용적률(%)" give the column order, and the cells right after the
    zone's name give the values. {} when the table is not shaped like that. A decimal cell
    gives no figure for that cell (value None), with the row still quoted.
    """
    order: list[str] = []
    for line in lines:
        cell = _squash(line)
        for kind, word in KINDS.items():
            if cell.startswith(word) and len(cell) <= len(word) + 6 and kind not in order:
                order.append(kind)
        if len(order) == len(KINDS):
            break
    if not order:
        return {}
    wanted = _squash(zone)
    for index, line in enumerate(lines):
        if _squash(line) != wanted:
            continue
        cells = []
        for following in lines[index + 1 : index + 1 + len(order)]:
            match = _PLAIN_NUMBER.match(following.strip())
            if not match:
                break
            raw = match.group(1).replace(",", "")
            if "천" in raw:
                thousands, rest = raw.split("천", 1)
                raw = str(int(thousands or 1) * 1000 + int(rest or 0))
            decimal = bool(match.group(2)) and bool(match.group(2).strip(".0"))
            cells.append((None if decimal else int(raw), following.strip()))
        if len(cells) != len(order):
            return {}
        header = ", ".join(KINDS[k] for k in order)
        quote = f"{line.strip()} | " + " | ".join(c[1] for c in cells) + f" (표의 열: {header})"
        return {
            kind: {"value": value, "quote": quote, "conditional": False}
            for kind, (value, _cell) in zip(order, cells, strict=True)
        }
    return {}


def _figures(article: dict, zone: str) -> dict[str, dict]:
    """{kind: figure} read from one article, or from the annex it points at."""
    annex = article.get("annex") or {}
    if annex.get("lines"):
        found = table_figures(annex["lines"], zone)
        if not found and article["kind"] in KINDS:
            figure = zone_figure("\n".join(annex["lines"]), zone)
            found = {article["kind"]: figure} if figure else {}
        return {k: {**f, "label": f"{article['label']} {annex['label']}"} for k, f in found.items()}
    if article["kind"] not in KINDS:
        return {}  # a combined article states two figures per zone: quoted, not read
    figure = zone_figure(article["text"], zone)
    return {article["kind"]: {**figure, "label": article["label"]}} if figure else {}


def zone_values(articles: list[dict], zone: str, limits: dict) -> dict:
    """
    {"bcr": figure | None, "far": figure | None} for one zone, each figure as zone_figure
    returns it. A value outside the statutory range in `limits` (bcr_max, far_min, far_max)
    is dropped (value None, "out_of_range": True): it was misread or needs a human.
    """
    out: dict[str, dict | None] = {"bcr": None, "far": None}
    for article in articles:
        for kind, figure in _figures(article, zone).items():
            if kind not in out or (article["kind"] in KINDS and kind != article["kind"]):
                continue
            value = figure["value"]
            if value is not None:
                if kind == "bcr":
                    ok = 0 < value <= limits["bcr_max"]
                else:
                    ok = limits["far_min"] <= value <= limits["far_max"]
                if not ok:
                    figure = {**figure, "value": None, "out_of_range": True}
            out[kind] = figure
    return out
