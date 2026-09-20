#!/usr/bin/env python3
"""Hub-level building-regulation Q&A (RAG + LLM). No project required."""

from __future__ import annotations

import re
from typing import Any

from console import ROLE_COLOR, paint, prompt_line
from harness import (
    LLMError,
    conductor_provider,
    load_env,
    provider_chat,
    resolve_conductor_runtime,
)
from i18n import get_language, t
from rag import Passage, format_passages, rag_settings, retrieve_passages

LAW_SYSTEM_KO = """당신은 한국 건축·도시계획 법령 정보 도우미입니다.
프로젝트나 사이트 브리프 없이, 사용자가 물어본 법령·기준만 설명합니다.

규칙:
- 숫자·조문·조례 문구는 RETRIEVED KNOWLEDGE에 있을 때만 확정하고 source를 인용하세요.
- 지식에 관련 조가 일부만 있으면, 있는 문장을 인용한 뒤 「검색된 구간에 해당 호/목/수치가 없음」이라고 하세요.
- 검색 결과에 없다고 해서 「그 조항이 법령에 존재하지 않는다」고 단정하지 마세요.
  (인덱스가 조문 앞부분만 잘랐을 수 있습니다.) 대신 「이번 검색 결과에 없음」+ 어디서 더 볼지 안내하세요.
- 법률 자문이 아니며, 설계안을 제안하지 마세요.
- 답변은 한국어로, 간결하게."""

LAW_SYSTEM_EN = """You are a building- and planning-regulation information assistant.
There is no project brief — answer only the user's legal/code question.

Rules:
- State numbers and article text only when present in RETRIEVED KNOWLEDGE; cite sources.
- If a related article is only partially retrieved, quote what is there and say the
  specific item/number is missing from the retrieved span — do NOT claim the statute
  itself does not exist (chunks may be truncated).
- This is not legal advice. Do not propose a building design.
- Respond in English, briefly."""

_ARTICLE_RE = re.compile(
    r"제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*제\s*\d+\s*항)?(?:\s*[가-힣]\s*목)?"
)
_STATUTE_HINT_RE = re.compile(
    r"(건축법|주차장법|국토의\s*계획|주차장법\s*시행규칙|주차장법\s*시행령|"
    r"건축법\s*시행령|건축법\s*시행규칙)[^\n]{0,40}"
)


def default_collection(config: dict) -> str:
    settings = rag_settings(config)
    return str(settings["agents"].get("regulation_checker") or "regulation")


def law_search_opts(config: dict) -> dict:
    rag = config.get("rag") or {}
    raw = dict(rag.get("law_search") or {})
    return {
        "top_k": int(raw.get("top_k") or rag.get("top_k") or 12),
        "max_chars": int(raw.get("max_chars") or rag.get("max_chars") or 14000),
        "multi_query": bool(raw.get("multi_query", True)),
    }


def build_law_queries(
    question: str,
    history: list[dict[str, str]] | None = None,
) -> list[str]:
    """
    Retrieval queries for the current question only.

    Prior turns are intentionally excluded (context budget / clear scope).
    `history` is accepted for API compatibility but ignored.
    """
    del history  # not used — each question is self-contained for retrieval
    q = (question or "").strip()
    if not q:
        return []

    out: list[str] = [q]

    statutes = [m.group(0).strip() for m in _STATUTE_HINT_RE.finditer(q)]
    articles = [re.sub(r"\s+", "", m) for m in _ARTICLE_RE.findall(q)]
    if statutes or articles:
        head = statutes[-1] if statutes else ""
        art = " ".join(articles[-2:]) if articles else ""
        focused = " ".join(x for x in (head, art, q) if x).strip()
        if focused and focused not in out:
            out.append(focused)

    if any(w in q for w in ("경사", "구배", "기울기", "경사로")):
        syn = f"{q}\n종단경사도 구배 경사로 차로 기울기"
        if syn not in out:
            out.append(syn)

    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(key)
    return uniq[:4]


def merge_passages(groups: list[list[Passage]], *, limit: int) -> list[Passage]:
    best: dict[str, Passage] = {}
    order: list[str] = []
    for group in groups:
        for p in group:
            key = p.source or f"{p.title}:{p.text[:40]}"
            prev = best.get(key)
            if prev is None:
                best[key] = p
                order.append(key)
            elif (p.score, len(p.text)) > (prev.score, len(prev.text)):
                best[key] = p
    ranked = sorted(best.values(), key=lambda p: (-p.score, -len(p.text)))
    # Prefer stable order among equal scores: first-seen then score
    return ranked[:limit]


def build_law_messages(
    question: str,
    knowledge: str,
    *,
    history: list[dict[str, str]] | None = None,
    lang: str | None = None,
) -> list[dict[str, str]]:
    lang = lang or get_language()
    system = LAW_SYSTEM_KO if lang == "ko" else LAW_SYSTEM_EN
    block = knowledge.strip() if knowledge.strip() else "(no passages retrieved)"
    user = (
        f"RETRIEVED KNOWLEDGE:\n\n{block}\n\n"
        f"QUESTION:\n{question.strip()}\n\n"
        "Answer using the knowledge above. Cite sources when you use a number or article. "
        "If the answer seems missing, say it is missing from the retrieved span — "
        "do not assert that the statute does not exist."
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user})
    return messages


def answer_law_question(
    config: dict,
    api_key: str,
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
    provider: Any = None,
    collection: str | None = None,
) -> tuple[str, list]:
    """
    Retrieve regulation passages, then ask the Conductor model.
    Returns (reply_text, passages). Raises LLMError on provider failure.

    Prior user turns are not included in retrieval or the LLM prompt
    (`history` is ignored — kept only for call-site compatibility).
    """
    del history
    coll = collection or default_collection(config)
    opts = law_search_opts(config)
    queries = build_law_queries(question) if opts["multi_query"] else [question]
    if not queries:
        queries = [question]

    groups: list[list[Passage]] = []
    for i, query in enumerate(queries):
        groups.append(
            retrieve_passages(
                config,
                coll,
                query,
                agent_id="law_search",
                lang=get_language(),
                top_k=opts["top_k"],
                max_chars=opts["max_chars"],
                # Other phrasings of *this* question only (not prior user turns).
                project_brief=queries[0] if i > 0 else None,
                expert_outputs="\n".join(queries[:i]) if i > 0 else None,
            )
        )
    passages = merge_passages(groups, limit=opts["top_k"])
    knowledge = format_passages(passages, collection=coll)
    rt = resolve_conductor_runtime(config)
    provider = provider or conductor_provider(config, api_key)
    messages = build_law_messages(question, knowledge, history=None)
    reply, _ = provider_chat(
        provider,
        rt["model"],
        messages,
        rt["temperature"],
        max(int(rt["max_tokens"]), 2000),
        role="law_search",
        status=t("busy_law"),
        color=ROLE_COLOR.get("rag", "yellow"),
    )
    return reply.strip(), passages


def _print_sources(passages: list) -> None:
    if not passages:
        print(t("law_no_passages"))
        return
    print(t("law_sources"))
    truncated = False
    for i, p in enumerate(passages, start=1):
        title = getattr(p, "title", "") or getattr(p, "source", "")
        source = getattr(p, "source", "")
        text = getattr(p, "text", "") or ""
        print(f"  [{i}] {title}  ({source})")
        if len(text) >= 900 or text.rstrip().endswith("[...]"):
            truncated = True
    if truncated:
        print(t("law_chunk_truncated"))


def run_law_search(config: dict) -> None:
    """Interactive regulation Q&A loop. Returns to hub when the user exits."""
    settings = rag_settings(config)
    print()
    print("=" * 40)
    print(f"  {t('law_title')}")
    print("=" * 40)
    print(t("law_intro"))
    if not settings["enabled"]:
        print(t("law_rag_off"))
    print(t("law_hint"))
    print()

    try:
        from ollama_boot import ensure_ollama_ready

        ensure_ollama_ready(config)
    except LLMError as exc:
        print(t("law_boot_failed", reason=str(exc)))
        return
    except Exception:
        pass

    api_key = load_env(config=config)
    try:
        provider = conductor_provider(config, api_key)
    except LLMError as exc:
        print(t("law_boot_failed", reason=str(exc)))
        return

    accent = ROLE_COLOR.get("rag", "yellow")

    while True:
        q = prompt_line(t("law_prompt"))
        if q is None:
            print()
            return
        low = q.lower()
        if not q or low in {"/back", "/hub", "q", "quit", "exit", "뒤로"}:
            print(t("law_bye"))
            return
        if low in {"/clear", "clear"}:
            print(t("law_no_session_context"))
            continue

        try:
            reply, passages = answer_law_question(
                config, api_key, q, provider=provider
            )
        except LLMError as exc:
            print(t("law_failed", reason=str(exc)))
            continue

        print()
        print(paint(t("law_label"), accent, bold=True) + reply)
        print()
        _print_sources(passages)
        print()
