#!/usr/bin/env python3
"""Client for the 법제처 국가법령정보 OPEN API (law.go.kr) — intelligent statute search.

`ai_search` takes a short Korean question and returns the statute articles (with full
text) or annex titles the service ranks as relevant. No printing, no project knowledge.

Raises LawApiError with a `kind`: no_key | denied | network | bad_response.
The OC value comes from .env (LAW_OPEN_API_OC). Tests pass `http_get`.

Notes from real calls (2026-10):
- Works on short questions ("직통계단 설치 기준"). A long project description returns
  nothing or noise, so callers must send focused queries.
- There is no relevance score and nonsense still returns results — rank is all we get.
- Annex results (scope 1) carry the title only, not the body.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable

import requests

from sida.harness import ROOT

ENV_PATH = ROOT / ".env"
SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
TIMEOUT = 30
ATTEMPTS = 2
MAX_QUERY_CHARS = 120

SCOPE_ARTICLES = 0  # 법령 조문 (본문 포함)
SCOPE_ANNEXES = 1  # 법령 별표·서식 (제목만)

HttpGet = Callable[[str, dict], str]  # (url, params) → response body text

_cache: dict[tuple[str, int, int], list[dict]] = {}


class LawApiError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def law_oc() -> str:
    """OC value from the environment / .env. Raises LawApiError('no_key')."""
    if ENV_PATH.exists():
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH, override=False)
    oc = os.environ.get("LAW_OPEN_API_OC", "").strip()
    if not oc:
        raise LawApiError("no_key", "LAW_OPEN_API_OC")
    return oc


def _http_get(url: str, params: dict) -> str:
    """GET text with one retry. Error text never includes the request URL (it carries the OC)."""
    last = "request failed"
    for attempt in range(ATTEMPTS):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.text
            last = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last = type(exc).__name__
        if attempt < ATTEMPTS - 1:
            time.sleep(1.0)
    raise LawApiError("network", last)


def article_label(number: str, branch: str = "") -> str:
    """('0034', '00') → '제34조'; ('0027', '02') → '제27조의2'."""
    label = f"제{int(number)}조" if str(number).isdigit() else str(number)
    if str(branch).isdigit() and int(branch):
        label += f"의{int(branch)}"
    return label


def tidy_article_text(text: str) -> str:
    """The API glues paragraphs together; put each 항(①②…) on its own line."""
    return re.sub(r"\s*([①-⑳])", r"\n\1", (text or "").strip()).strip()


def _date(stamp: str) -> str:
    stamp = str(stamp or "")
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 and stamp[:8].isdigit() else ""


def _parse(body: str, scope: int) -> list[dict]:
    try:
        data = json.loads(body)
    except ValueError as exc:
        if "미신청" in body:
            # HTML page: this OC has not applied for the intelligent-search API.
            raise LawApiError("denied", "not_applied") from exc
        raise LawApiError("bad_response", "not JSON") from exc
    if not isinstance(data, dict):
        raise LawApiError("bad_response", "unexpected shape")
    root = data.get("aiSearch")
    if not isinstance(root, dict):
        # {"result": "사용자 정보 검증에 실패하였습니다.", "msg": "..."}
        if data.get("result"):
            raise LawApiError("denied", str(data["result"]))
        raise LawApiError("bad_response", "no aiSearch")

    out: list[dict] = []
    if scope == SCOPE_ANNEXES:
        for it in root.get("법령별표서식") or []:
            number = str(it.get("별표서식번호") or "")
            label = str(it.get("별표서식구분명") or "별표")
            if number.isdigit():
                label += f" {int(number)}"
            branch = str(it.get("별표서식가지번호") or "")
            if branch.isdigit() and int(branch):
                label += f"의{int(branch)}"
            out.append(
                {
                    "kind": "annex",
                    "law": str(it.get("법령명") or ""),
                    "label": label,
                    "title": str(it.get("별표서식제목") or ""),
                    "text": "",
                    "effective": _date(it.get("시행일자")),
                }
            )
        return out
    for it in root.get("법령조문") or []:
        out.append(
            {
                "kind": "article",
                "law": str(it.get("법령명") or ""),
                "label": article_label(str(it.get("조문번호") or ""), str(it.get("조문가지번호") or "")),
                "title": str(it.get("조문제목") or ""),
                "text": tidy_article_text(str(it.get("조문내용") or "")),
                "effective": _date(it.get("시행일자")),
            }
        )
    return out


def ai_search(
    query: str,
    *,
    scope: int = SCOPE_ARTICLES,
    display: int = 5,
    http_get: HttpGet | None = None,
) -> list[dict]:
    """
    Statute articles (scope 0) or annex titles (scope 1) for a short Korean question, in
    the service's rank order. Each: {"kind", "law", "label", "title", "text", "effective"}.
    Identical calls are answered from memory for the life of the process.
    """
    query = " ".join((query or "").split())[:MAX_QUERY_CHARS]
    if not query:
        return []
    oc = law_oc()
    key = (query, scope, display)
    if key in _cache:
        return [dict(item) for item in _cache[key]]
    body = (http_get or _http_get)(
        SEARCH_URL,
        {"OC": oc, "target": "aiSearch", "type": "JSON", "search": scope, "query": query, "display": display},
    )
    items = _parse(body, scope)
    _cache[key] = [dict(item) for item in items]
    return items


def clear_cache() -> None:
    _cache.clear()
