#!/usr/bin/env python3
"""Retrieval for specialist experts (regulation first).

Providers:
  - local_files — markdown under knowledge/<collection>/ (dev / offline)
  - http        — POST to a VPS RAG API (production); see docs/rag_api.md

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
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = self._session.post(self.url, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException:
            self.last_status = None
            return []
        self.last_status = r.status_code
        if r.status_code != 200:
            return []
        try:
            data = r.json()
        except ValueError:
            return []
        return parse_retrieve_response(data)


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
    if provider in {"local_files", "files", "markdown"}:
        return LocalFileRetriever(settings["knowledge_dir"])
    if provider in {"http", "api", "remote", "vps"}:
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
) -> str:
    """
    Return a formatted knowledge block for this agent, or "" if RAG is off /
    the agent has no collection / nothing matched.
    """
    settings = rag_settings(config)
    collection = collection_for_agent(settings, agent)
    if not collection or not settings["enabled"]:
        return ""
    top_k, max_chars, folder = collection_opts(settings, collection)
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
            agent_id=str(agent.get("id") or ""),
            project_brief=project_brief,
            project_state=project_state,
            expert_outputs=expert_outputs,
            lang=lang or "ko",
        )
    )
    if isinstance(engine, LocalFileRetriever):
        passages = engine.retrieve(
            collection, query, top_k=top_k, max_chars=max_chars, folder=folder
        )
    else:
        passages = engine.retrieve(collection, query, top_k=top_k, max_chars=max_chars)
    return format_passages(passages, collection=collection)
