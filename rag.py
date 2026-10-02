#!/usr/bin/env python3
"""Retrieval for specialist experts (regulation first).

Providers:
  - lawgokr     — 법제처 국가법령정보 지능형 검색 (law.go.kr); the default. See lawapi.py
  - http        — POST to a self-hosted RAG API; see docs/rag_api.md
  - local_files — markdown under knowledge/<collection>/ (offline)

When `rag.enabled` is false, nothing is injected.
`retrieve_for_agent(config, agent, query, ...)` is the only worker call site.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

from harness import ROOT

# Agents that may receive a knowledge block. Config can override via
# rag.agents: { regulation_checker: regulation, ... }.
DEFAULT_AGENT_COLLECTIONS: dict[str, str] = {
    "regulation_checker": "regulation",
}

API_VERSION = "sida.rag.v1"


@dataclass(frozen=True)
class Passage:
    source: str  # relative path or citation id
    title: str
    text: str
    score: float = 0.0


class Retriever(Protocol):
    def retrieve(self, collection: str, query: str, *, top_k: int, max_chars: int) -> list[Passage]:
        ...


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def rag_settings(config: dict) -> dict:
    raw = dict(config.get("rag") or {})
    agents = raw.get("agents") or {}
    if not isinstance(agents, dict):
        agents = {}
    collections = raw.get("collections") or {}
    if not isinstance(collections, dict):
        collections = {}
    knowledge = Path(str(raw.get("knowledge_dir") or "knowledge"))
    if not knowledge.is_absolute():
        knowledge = ROOT / knowledge

    # URL: config.base_url → env SIDA_RAG_URL → empty
    base_url = str(raw.get("base_url") or os.environ.get("SIDA_RAG_URL") or "").rstrip("/")
    key_env = str(raw.get("api_key_env") or "SIDA_RAG_API_KEY")
    api_key = str(raw.get("api_key") or os.environ.get(key_env) or "")
    path = str(raw.get("path") or "/v1/retrieve")
    if not path.startswith("/"):
        path = "/" + path

    return {
        "enabled": bool(raw.get("enabled", False)),
        "provider": str(raw.get("provider") or "local_files").lower(),
        "knowledge_dir": knowledge,
        "agents": {str(k): str(v) for k, v in agents.items()} or dict(DEFAULT_AGENT_COLLECTIONS),
        "collections": collections,
        "default_top_k": int(raw.get("top_k", 6)),
        "default_max_chars": int(raw.get("max_chars", 6000)),
        "base_url": base_url,
        "api_key": api_key,
        "api_key_env": key_env,
        "path": path,
        "timeout": float(raw.get("timeout", 30)),
    }


def collection_for_agent(settings: dict, agent: dict) -> str | None:
    aid = str(agent.get("id") or "")
    return settings["agents"].get(aid)


def collection_opts(settings: dict, collection: str) -> tuple[int, int, Path]:
    meta = settings["collections"].get(collection) or {}
    if not isinstance(meta, dict):
        meta = {}
    top_k = int(meta.get("top_k", settings["default_top_k"]))
    max_chars = int(meta.get("max_chars", settings["default_max_chars"]))
    sub = str(meta.get("path") or collection)
    return top_k, max_chars, settings["knowledge_dir"] / sub


# ---------------------------------------------------------------------------
# Query building + HTTP request body (what the VPS receives)
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def build_retrieval_query(
    project_brief: str,
    *,
    project_state: str | None = None,
    expert_outputs: str | None = None,
    max_chars: int = 2500,
) -> str:
    """Compact query text — brief + state + prior experts (also sent as context.*)."""
    parts: list[str] = []
    if project_brief and project_brief.strip():
        parts.append(project_brief.strip())
    if project_state and project_state.strip():
        parts.append(project_state.strip())
    if expert_outputs and expert_outputs.strip() and expert_outputs.strip() != "(none yet)":
        parts.append(expert_outputs.strip())
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _clip(text: str | None, limit: int) -> str:
    if not text or not str(text).strip() or str(text).strip() == "(none yet)":
        return ""
    t = str(text).strip()
    return t if len(t) <= limit else t[: limit - 20] + "\n[... truncated ...]"


def build_retrieve_request(
    *,
    collection: str,
    query: str,
    top_k: int,
    max_chars: int,
    agent_id: str,
    project_brief: str | None = None,
    project_state: str | None = None,
    expert_outputs: str | None = None,
    lang: str = "ko",
) -> dict[str, Any]:
    """
    JSON body POSTed to the VPS. Keep this stable — VPS logs/debug against this schema.
    See docs/rag_api.md and examples/rag_retrieve_request.json.
    """
    return {
        "api_version": API_VERSION,
        "collection": collection,
        "agent_id": agent_id,
        "query": query,
        "top_k": top_k,
        "max_chars": max_chars,
        "lang": lang,
        "context": {
            "brief": _clip(project_brief, 4000),
            "project_state": _clip(project_state, 3000),
            "expert_outputs": _clip(expert_outputs, 4000),
        },
    }


def parse_retrieve_response(data: Any) -> list[Passage]:
    """Accept {passages:[...]} or a bare list. Unknown shapes → []."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("passages") or data.get("results") or data.get("chunks") or []
    else:
        return []
    out: list[Passage] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if not text:
            continue
        source = str(item.get("source") or item.get("id") or item.get("path") or "unknown")
        title = str(item.get("title") or source)
        try:
            score = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        out.append(Passage(source=source, title=title, text=text, score=score))
    return out


# ---------------------------------------------------------------------------
# Local markdown corpus
# ---------------------------------------------------------------------------


def _split_chunks(text: str, *, max_len: int = 900) -> list[str]:
    """Split on ## headers first, then by length."""
    text = text.strip()
    if not text:
        return []
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    chunks: list[str] = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) <= max_len:
            chunks.append(sec)
            continue
        paras = re.split(r"\n\s*\n", sec)
        buf = ""
        for p in paras:
            if buf and len(buf) + len(p) + 2 > max_len:
                chunks.append(buf.strip())
                buf = p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
        if buf.strip():
            chunks.append(buf.strip())
    return chunks


def _title_from_chunk(chunk: str, fallback: str) -> str:
    m = re.match(r"^#+\s+(.+)$", chunk, re.MULTILINE)
    if m:
        return m.group(1).strip()[:120]
    return fallback


def load_markdown_corpus(folder: Path) -> list[tuple[str, str, str]]:
    """Return (relpath, title, chunk_text) for every .md under folder."""
    if not folder.is_dir():
        return []
    out: list[tuple[str, str, str]] = []
    for path in sorted(folder.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.relative_to(folder).as_posix()
        for i, chunk in enumerate(_split_chunks(raw)):
            title = _title_from_chunk(chunk, path.stem)
            label = rel if i == 0 else f"{rel}#{i + 1}"
            out.append((label, title, chunk))
    return out


class LocalFileRetriever:
    """Keyword-overlap retriever over knowledge/<collection>/*.md — no embeddings."""

    name = "local_files"

    def __init__(self, knowledge_dir: Path):
        self.knowledge_dir = knowledge_dir
        self._cache: dict[str, list[tuple[str, str, str]]] = {}

    def _corpus(self, collection_path: Path) -> list[tuple[str, str, str]]:
        key = str(collection_path)
        if key not in self._cache:
            self._cache[key] = load_markdown_corpus(collection_path)
        return self._cache[key]

    def retrieve(
        self, collection: str, query: str, *, top_k: int, max_chars: int, folder: Path | None = None
    ) -> list[Passage]:
        folder = folder or (self.knowledge_dir / collection)
        qtoks = tokenize(query)
        if not qtoks:
            return []
        scored: list[Passage] = []
        for rel, title, chunk in self._corpus(folder):
            ctoks = tokenize(chunk)
            if not ctoks:
                continue
            overlap = len(qtoks & ctoks)
            if overlap == 0:
                continue
            score = overlap / (len(qtoks) ** 0.5)
            scored.append(Passage(source=rel, title=title, text=chunk, score=score))
        scored.sort(key=lambda p: p.score, reverse=True)

        selected: list[Passage] = []
        used = 0
        for p in scored:
            if len(selected) >= top_k:
                break
            room = max_chars - used
            if room < 80:
                break
            text = p.text if len(p.text) <= room else p.text[: room - 20] + "\n[...]"
            selected.append(Passage(source=p.source, title=p.title, text=text, score=p.score))
            used += len(text)
        return selected


class HttpApiRetriever:
    """POST JSON to a remote RAG service (VPS)."""

    name = "http"

    def __init__(
        self,
        base_url: str,
        *,
        path: str = "/v1/retrieve",
        api_key: str = "",
        timeout: float = 30.0,
        agent_id: str = "",
        project_brief: str | None = None,
        project_state: str | None = None,
        expert_outputs: str | None = None,
        lang: str = "ko",
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.path = path if path.startswith("/") else f"/{path}"
        self.api_key = api_key
        self.timeout = timeout
        self.agent_id = agent_id
        self.project_brief = project_brief
        self.project_state = project_state
        self.expert_outputs = expert_outputs
        self.lang = lang
        self._session = session or requests.Session()
        self.last_request: dict[str, Any] | None = None
        self.last_status: int | None = None
        self.last_error: str | None = None  # unreachable | http | bad_response

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.path}"

    def retrieve(self, collection: str, query: str, *, top_k: int, max_chars: int) -> list[Passage]:
        body = build_retrieve_request(
            collection=collection,
            query=query,
            top_k=top_k,
            max_chars=max_chars,
            agent_id=self.agent_id,
            project_brief=self.project_brief,
            project_state=self.project_state,
            expert_outputs=self.expert_outputs,
            lang=self.lang,
        )
        self.last_request = body
        self.last_error = None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            from console import ROLE_COLOR, busy_line
            from i18n import t

            with busy_line(t("busy_rag"), color=ROLE_COLOR["rag"]):
                r = self._session.post(self.url, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException:
            self.last_status = None
            self.last_error = "unreachable"
            return []
        self.last_status = r.status_code
        if r.status_code != 200:
            self.last_error = "http"
            return []
        try:
            data = r.json()
        except ValueError:
            self.last_error = "bad_response"
            return []
        return parse_retrieve_response(data)


LAW_PROVIDERS = frozenset({"lawgokr", "law_api", "law.go.kr"})
HTTP_PROVIDERS = frozenset({"http", "api", "remote", "vps"})
LAW_PASSAGE_CHARS = 1800
LAW_MAX_QUERIES = 5
# The service gives rank only (no score) and its tail is noisy, so keep the head of each list.
LAW_PER_QUERY = 3
LAW_SINGLE_QUERY = 6
_PAREN_RE = re.compile(r"[(（].*$")


class LawSearchRetriever:
    """법제처 지능형 검색. Takes short focused questions, never a whole project description."""

    name = "lawgokr"
    url = "law.go.kr"

    def __init__(self, *, http_get=None):
        self._http_get = http_get
        self.last_error: str | None = None  # no_key | denied | unreachable | bad_response
        self.last_detail = ""

    def retrieve(
        self,
        collection: str,
        query: str,
        *,
        top_k: int,
        max_chars: int,
        queries: list[str] | None = None,
    ) -> list[Passage]:
        import lawapi
        from console import ROLE_COLOR, busy_line
        from i18n import t

        self.last_error, self.last_detail = None, ""
        asked = [q for q in (queries if queries is not None else [query]) if q and q.strip()]
        asked = asked[:LAW_MAX_QUERIES]
        if not asked:
            return []
        per_query = LAW_PER_QUERY if len(asked) > 1 else min(top_k, LAW_SINGLE_QUERY)
        ranked: list[list[dict]] = []
        try:
            with busy_line(t("busy_rag"), color=ROLE_COLOR["rag"]):
                for q in asked:
                    ranked.append(lawapi.ai_search(q, display=per_query, http_get=self._http_get))
        except lawapi.LawApiError as exc:
            self.last_error = "unreachable" if exc.kind == "network" else exc.kind
            self.last_detail = exc.detail
            return []

        # Round-robin across queries so one question does not crowd out the others.
        merged: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for rank in range(per_query):
            for results in ranked:
                if rank < len(results):
                    item = results[rank]
                    key = (item["law"], item["label"])
                    if key not in seen:
                        seen.add(key)
                        merged.append(item)

        # Articles only: annex search returns titles without bodies and is too noisy to inject.
        passages: list[Passage] = []
        used = 0
        for item in merged[:top_k]:
            text = item["text"]
            if len(text) > LAW_PASSAGE_CHARS:
                text = text[: LAW_PASSAGE_CHARS - 20].rstrip() + "\n[... 조문 일부 생략 ...]"
            if used + len(text) > max_chars and passages:
                break
            name = f"{item['law']} {item['label']}"
            title = f"{name} ({item['title']})" if item["title"] else name
            if item.get("effective"):
                title += f" [시행 {item['effective']}]"
            passages.append(
                Passage(
                    source=f"law.go.kr/{name}",
                    title=title,
                    text=text,
                    score=round(max(0.1, 1.0 - 0.03 * len(passages)), 2),
                )
            )
            used += len(text)
        return passages


def focus_queries(project_brief: str | None, site_facts: dict | None) -> list[str]:
    """
    Short statute questions for a project, built from what is known for certain: the
    zoning and districts in site facts, then Korean one-liners in the brief. The statute
    search needs focused questions — a whole brief returns nothing useful.
    """
    queries: list[str] = []
    if site_facts:
        summary = site_facts.get("summary") or {}
        zones = [z["zone"] for z in summary.get("zoning") or []]
        for zone in zones[:2]:
            queries.append(f"{zone}에서 건축할 수 있는 건축물")
        if zones:
            queries.append(f"{zones[0]} 건폐율 용적률")
        try:
            from site_facts import load_limits

            keywords = [r["keyword"] for r in load_limits()["verify"]]
        except Exception:
            keywords = []
        for d in summary.get("districts") or []:
            name = str(d.get("name") or "")
            if d.get("relation") == "접함" or "토지거래" in name:
                continue
            if any(k in name for k in keywords):
                queries.append(f"{_PAREN_RE.sub('', name).strip()} 건축 제한")
    if project_brief:
        from project import section_body

        for heading, suffix in (("Project Type", " 건축 기준"), ("Core Problem", "")):
            line = " ".join(section_body(project_brief, heading).split()).lstrip("- ").strip()
            if 2 <= len(line) <= 60 and re.search(r"[가-힣]", line):
                queries.append(line + suffix)
    unique = list(dict.fromkeys(q for q in queries if q.strip()))
    return unique[:LAW_MAX_QUERIES]


class NullRetriever:
    name = "null"

    def retrieve(self, collection: str, query: str, *, top_k: int, max_chars: int) -> list[Passage]:
        return []


def make_retriever(
    settings: dict,
    *,
    agent_id: str = "",
    project_brief: str | None = None,
    project_state: str | None = None,
    expert_outputs: str | None = None,
    lang: str = "ko",
) -> Retriever:
    if not settings["enabled"]:
        return NullRetriever()
    provider = settings["provider"]
    if provider in LAW_PROVIDERS:
        return LawSearchRetriever()
    if provider in {"local_files", "files", "markdown"}:
        return LocalFileRetriever(settings["knowledge_dir"])
    if provider in HTTP_PROVIDERS:
        if not settings["base_url"]:
            return NullRetriever()
        return HttpApiRetriever(
            settings["base_url"],
            path=settings["path"],
            api_key=settings["api_key"],
            timeout=settings["timeout"],
            agent_id=agent_id,
            project_brief=project_brief,
            project_state=project_state,
            expert_outputs=expert_outputs,
            lang=lang,
        )
    return NullRetriever()


# ---------------------------------------------------------------------------
# Diagnostics — why the last retrieval gave nothing (retrieval itself never raises)
# ---------------------------------------------------------------------------

_last_problem: tuple[str, dict[str, Any]] | None = None


def diagnose_retrieval(
    settings: dict, engine: Retriever, passages: list[Passage]
) -> tuple[str, dict[str, Any]] | None:
    """(i18n key, format args) when RAG is on but produced nothing; None when it worked."""
    if passages:
        return None
    if isinstance(engine, NullRetriever):
        if settings["provider"] in HTTP_PROVIDERS and not settings["base_url"]:
            return "rag_warn_no_url", {}
        return "rag_warn_provider", {"provider": settings["provider"]}
    error = getattr(engine, "last_error", None)
    if error == "no_key":
        return "rag_warn_no_oc", {}
    if error == "denied":
        detail = getattr(engine, "last_detail", "")
        if detail == "not_applied":
            return "rag_warn_law_not_applied", {}
        return "rag_warn_law_denied", {"detail": detail}
    if error == "unreachable":
        return "rag_warn_unreachable", {"url": getattr(engine, "url", "")}
    if error == "http":
        return "rag_warn_http", {"status": getattr(engine, "last_status", "?")}
    if error == "bad_response":
        return "rag_warn_bad_response", {}
    return "rag_warn_no_hits", {}


def last_retrieval_warning() -> str | None:
    """Localized one-line warning for the most recent retrieval, or None if it worked / RAG is off."""
    if _last_problem is None:
        return None
    from i18n import t

    key, args = _last_problem
    return t(key, **args)


def url_missing(settings: dict) -> bool:
    """RAG is on with the HTTP provider but no server URL is configured."""
    return bool(
        settings["enabled"] and settings["provider"] in HTTP_PROVIDERS and not settings["base_url"]
    )


def key_missing(settings: dict) -> bool:
    """RAG is on with the 법제처 provider but LAW_OPEN_API_OC is not set."""
    if not settings["enabled"] or settings["provider"] not in LAW_PROVIDERS:
        return False
    import lawapi

    try:
        lawapi.law_oc()
    except lawapi.LawApiError:
        return True
    return False


# ---------------------------------------------------------------------------
# Format + public API
# ---------------------------------------------------------------------------


def format_passages(passages: list[Passage], *, collection: str) -> str:
    if not passages:
        return ""
    lines = [
        f"RETRIEVED KNOWLEDGE ({collection}) — cite source paths; do not invent numbers "
        "not present here. Prefer these passages over model memory for numeric limits.",
        "",
    ]
    for i, p in enumerate(passages, start=1):
        lines.append(f"### [{i}] {p.title}")
        lines.append(f"source: {p.source}")
        lines.append("")
        lines.append(p.text.strip())
        lines.append("")
    return "\n".join(lines).rstrip()


def retrieve_for_agent(
    config: dict,
    agent: dict,
    query: str,
    *,
    retriever: Retriever | None = None,
    project_brief: str | None = None,
    project_state: str | None = None,
    expert_outputs: str | None = None,
    lang: str | None = None,
    site_facts: dict | None = None,
) -> str:
    """
    Return a formatted knowledge block for this agent, or "" if RAG is off /
    the agent has no collection / nothing matched.

    With the 법제처 provider the long `query` is not used: focused questions are built
    from `site_facts` and the brief instead (see focus_queries).
    """
    global _last_problem
    _last_problem = None
    settings = rag_settings(config)
    collection = collection_for_agent(settings, agent)
    if not collection or not settings["enabled"]:
        return ""
    queries = None
    if settings["provider"] in LAW_PROVIDERS and retriever is None:
        queries = focus_queries(project_brief, site_facts)
        if not queries:
            _last_problem = ("rag_warn_no_query", {})
            return ""
    passages = retrieve_passages(
        config,
        collection,
        query,
        queries=queries,
        retriever=retriever,
        agent_id=str(agent.get("id") or ""),
        project_brief=project_brief,
        project_state=project_state,
        expert_outputs=expert_outputs,
        lang=lang,
    )
    return format_passages(passages, collection=collection)


def retrieve_passages(
    config: dict,
    collection: str,
    query: str,
    *,
    retriever: Retriever | None = None,
    agent_id: str = "law_search",
    project_brief: str | None = None,
    project_state: str | None = None,
    expert_outputs: str | None = None,
    lang: str | None = None,
    top_k: int | None = None,
    max_chars: int | None = None,
    queries: list[str] | None = None,
) -> list[Passage]:
    """
    Retrieve raw passages for any collection (hub law search or workers).
    Returns [] when RAG is off / provider unavailable / nothing matched;
    `last_retrieval_warning()` then says why.
    """
    global _last_problem
    _last_problem = None
    settings = rag_settings(config)
    if not settings["enabled"] or not collection:
        return []
    default_k, default_chars, folder = collection_opts(settings, collection)
    use_k = int(top_k) if top_k is not None else default_k
    use_chars = int(max_chars) if max_chars is not None else default_chars
    if lang is None:
        try:
            from i18n import get_language

            lang = get_language()
        except Exception:
            lang = "ko"
    engine = (
        retriever
        if retriever is not None
        else make_retriever(
            settings,
            agent_id=agent_id,
            project_brief=project_brief,
            project_state=project_state,
            expert_outputs=expert_outputs,
            lang=lang or "ko",
        )
    )
    if isinstance(engine, LawSearchRetriever):
        passages = engine.retrieve(
            collection, query, top_k=use_k, max_chars=use_chars, queries=queries
        )
    elif isinstance(engine, LocalFileRetriever):
        passages = engine.retrieve(
            collection, query, top_k=use_k, max_chars=use_chars, folder=folder
        )
    else:
        passages = engine.retrieve(collection, query, top_k=use_k, max_chars=use_chars)
    _last_problem = diagnose_retrieval(settings, engine, passages)
    return passages
