#!/usr/bin/env python3
"""Hub-level Rhino modeling assistant (OpenAI GPT-6+ + Rhino MCP)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from console import ROLE_COLOR, paint, prompt_line
from harness import (
    ROOT,
    LLMError,
    gpt_major_version,
    make_provider,
    provider_chat,
)
from i18n import get_language, t
from mcp_stdio import McpError
from rhino_mcp import SAFE_TOOLS, open_rhino_mcp, resolve_mcp_command

RHINO_BLOCK = re.compile(r"```rhino\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
DEFAULT_MODEL = "gpt-6-astra"
MIN_GPT_MAJOR = 6


def modeling_settings(config: dict) -> dict:
    raw = dict(config.get("modeling") or {})
    provider = str(raw.get("provider") or "openai").lower()
    if provider in {"openrouter", "cloud", "ollama", "local"}:
        # Modeling is OpenAI-only (or mock in tests).
        provider = "openai"
    return {
        "provider": provider,
        "model": str(raw.get("model") or DEFAULT_MODEL),
        "min_major": int(raw.get("min_major") or MIN_GPT_MAJOR),
        "temperature": float(raw.get("temperature", 0.2)),
        "max_tokens": int(raw.get("max_tokens", 2500)),
        "max_rounds": int(raw.get("max_rounds", 8)),
        "auto_execute": bool(raw.get("auto_execute", True)),
        "prompt": str(raw.get("prompt") or "agents/71_rhino_modeler.md"),
        "base_url": raw.get("base_url"),
    }


def require_gpt6_plus(model: str, *, min_major: int = MIN_GPT_MAJOR) -> None:
    major = gpt_major_version(model)
    if major is None or major < min_major:
        raise LLMError(
            t(
                "modeling_model_too_old",
                model=model,
                min_major=min_major,
                example=DEFAULT_MODEL,
            )
        )


def load_modeler_prompt(config: dict) -> str:
    rel = modeling_settings(config)["prompt"]
    path = ROOT / rel if not Path(rel).is_absolute() else Path(rel)
    text = path.read_text(encoding="utf-8") if path.exists() else "# Rhino Modeler\n"
    tools = ", ".join(sorted(SAFE_TOOLS))
    lang = get_language()
    lang_line = (
        "Reply to the user in Korean in the `say` field."
        if lang == "ko"
        else "Reply to the user in English in the `say` field."
    )
    return (
        f"{text.strip()}\n\n## Allowed tools\n{tools}\n\n## Language\n{lang_line}\n"
    )


def modeling_provider(config: dict, api_key: str):
    rt = modeling_settings(config)
    if rt["provider"] in {"mock"}:
        return make_provider("mock")
    require_gpt6_plus(rt["model"], min_major=rt["min_major"])
    return make_provider("openai", api_key=api_key, base_url=rt.get("base_url"))


def parse_rhino_plan(raw: str) -> dict[str, Any]:
    """Extract {say, done, calls} from model output."""
    text = (raw or "").strip()
    m = RHINO_BLOCK.search(text)
    blob = m.group(1) if m else None
    if blob is None:
        if text.startswith("{") and text.endswith("}"):
            blob = text
    if not blob:
        return {"say": text or "(empty)", "done": True, "calls": []}
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {"say": text, "done": True, "calls": []}
    if not isinstance(data, dict):
        return {"say": text, "done": True, "calls": []}
    calls = data.get("calls") or []
    if not isinstance(calls, list):
        calls = []
    clean: list[dict[str, Any]] = []
    for item in calls[:3]:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        if tool:
            clean.append({"tool": tool, "args": args})
    return {
        "say": str(data.get("say") or "").strip() or "(…)",
        "done": bool(data.get("done")),
        "calls": clean,
    }


def _clip(obj: Any, limit: int = 4000) -> str:
    try:
        text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    except TypeError:
        text = str(obj)
    if len(text) > limit:
        return text[: limit - 20] + "\n…[truncated]"
    return text


def run_modeling_turn(
    config: dict,
    api_key: str,
    user_text: str,
    *,
    history: list[dict[str, str]] | None = None,
    provider=None,
    rhino=None,
) -> tuple[str, list[dict[str, Any]], bool]:
    """
    One user request → up to max_rounds of (LLM plan → MCP tools).
    Returns (final_say, tool_log, done).
    """
    rt = modeling_settings(config)
    if provider is None:
        require_gpt6_plus(rt["model"], min_major=rt["min_major"])
        provider = modeling_provider(config, api_key)
    system = load_modeler_prompt(config)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for turn in history or []:
        if turn.get("role") in {"user", "assistant"} and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_text.strip()})

    tool_log: list[dict[str, Any]] = []
    last_say = ""
    accent = ROLE_COLOR.get("modeling", "bright_cyan")

    for _round in range(int(rt["max_rounds"])):
        raw, _ = provider_chat(
            provider,
            rt["model"],
            messages,
            rt["temperature"],
            rt["max_tokens"],
            role="modeling",
            status=t("busy_modeling"),
            color=accent,
        )
        plan = parse_rhino_plan(raw)
        last_say = plan["say"]
        if last_say:
            print(paint(t("modeling_label"), accent, bold=True) + last_say)

        if plan["done"] or not plan["calls"]:
            return last_say, tool_log, True

        if not rt["auto_execute"] or rhino is None:
            for call in plan["calls"]:
                tool_log.append({**call, "result": "(dry-run — MCP not connected)"})
                print(t("modeling_dry_call", tool=call["tool"]))
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "MCP is not connected (dry-run). Summarize the intended script "
                        "changes and set done=true with empty calls."
                    ),
                }
            )
            continue

        results: list[dict[str, Any]] = []
        for call in plan["calls"]:
            tool = call["tool"]
            args = call["args"]
            print(paint(t("modeling_calling", tool=tool), accent))
            try:
                result = rhino.call(tool, args)
                entry = {"tool": tool, "args": args, "result": result}
                tool_log.append(entry)
                results.append({"tool": tool, "ok": True, "result": _clip(result)})
            except McpError as exc:
                entry = {"tool": tool, "args": args, "error": str(exc)}
                tool_log.append(entry)
                results.append({"tool": tool, "ok": False, "error": str(exc)})

        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": "TOOL RESULTS:\n" + _clip(results, 6000),
            }
        )

    return last_say or t("modeling_round_limit"), tool_log, False


def run_rhino_modeler(config: dict) -> None:
    """Interactive modeling loop from the project hub (OpenAI GPT-6+ only)."""
    rt = modeling_settings(config)
    accent = ROLE_COLOR.get("modeling", "bright_cyan")
    print()
    print("=" * 40)
    print(paint(f"  {t('modeling_title')}", accent, bold=True))
    print("=" * 40)
    print(t("modeling_intro", model=rt["model"]))
    print(t("modeling_hint"))
    print()

    try:
        require_gpt6_plus(rt["model"], min_major=rt["min_major"])
    except LLMError as exc:
        print(t("modeling_boot_failed", reason=str(exc)))
        return

    cmd = resolve_mcp_command(config)
    rhino = None
    if cmd and rt["auto_execute"]:
        try:
            rhino = open_rhino_mcp(config)
            print(t("modeling_mcp_ok", cmd=cmd[0]))
            try:
                slots = rhino.call("list_slots", {})
                print(t("modeling_slots", detail=_clip(slots, 500)))
            except McpError as exc:
                print(t("modeling_slots_fail", reason=str(exc)))
        except McpError as exc:
            print(t("modeling_mcp_fail", reason=str(exc)))
            print(t("modeling_dry_mode"))
            rhino = None
    else:
        print(t("modeling_dry_mode"))

    try:
        from setup_env import ensure_openai_api_key

        api_key = ensure_openai_api_key(interactive=True)
        provider = modeling_provider(config, api_key)
    except LLMError as exc:
        print(t("modeling_boot_failed", reason=str(exc)))
        if rhino:
            rhino.close()
        return

    history: list[dict[str, str]] = []
    try:
        while True:
            q = prompt_line(t("modeling_prompt"))
            if q is None:
                print()
                return
            low = q.lower()
            if not q or low in {"/back", "/hub", "q", "quit", "exit", "뒤로"}:
                print(t("modeling_bye"))
                return
            if low in {"/clear", "clear"}:
                history.clear()
                print(t("modeling_cleared"))
                continue
            if low in {"/ctx", "/context"}:
                if rhino is None:
                    print(t("modeling_dry_mode"))
                    continue
                try:
                    ctx = rhino.call("get_context", {})
                    print(_clip(ctx, 2000))
                except McpError as exc:
                    print(t("modeling_failed", reason=str(exc)))
                continue

            try:
                say, _log, _done = run_modeling_turn(
                    config,
                    api_key,
                    q,
                    history=history[-8:],
                    provider=provider,
                    rhino=rhino,
                )
            except LLMError as exc:
                print(t("modeling_failed", reason=str(exc)))
                continue

            history.append({"role": "user", "content": q})
            history.append({"role": "assistant", "content": say})
            print()
    finally:
        if rhino is not None:
            rhino.close()
