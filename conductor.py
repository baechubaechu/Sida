#!/usr/bin/env python3
"""Conductor turn: message assembly, action parsing, one LLM call."""

from __future__ import annotations

import json
import re
from pathlib import Path

from harness import (
    conductor_provider,
    prepare_conductor_context,
    resolve_conductor_runtime,
)

ACTION_RE = re.compile(r"```action\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def parse_action(raw: str) -> tuple[str, dict]:
    """Split the visible reply from the trailing ```action``` block."""
    match = ACTION_RE.search(raw)
    if not match:
        return raw.strip(), {"type": "none"}
    reply = (raw[: match.start()] + raw[match.end() :]).strip()
    try:
        action = json.loads(match.group(1))
        if not isinstance(action, dict):
            action = {"type": "none"}
    except json.JSONDecodeError:
        action = {"type": "none"}
    action.setdefault("type", "none")
    return reply, action


ACTION_TYPES = ("none", "run", "read", "exit")


def should_recover_action(runtime: dict) -> bool:
    mode = str(runtime.get("action_recovery", "auto")).lower()
    if mode in {"off", "false", "0", "never"}:
        return False
    if mode in {"always", "true", "1"}:
        return True
    return runtime.get("provider") in {"ollama", "local"}


def _recovery_messages(reply: str, agents: list[dict]) -> list[dict]:
    ids = ", ".join(str(a.get("id")) for a in agents)
    system = (
        "You extract a single JSON action from an assistant reply. "
        "Output JSON only, no prose, no code fence. Schema: "
        '{"type": "none" | "run" | "read" | "exit", "agent": "<agent_id or omitted>"}.\n'
        f"Valid agent ids: {ids}.\n"
        "Rules:\n"
        "- run: only if the reply clearly states it is running / starting a module NOW "
        "(not merely suggesting or asking permission).\n"
        "- read: only if the reply says it will look at / open a completed module file.\n"
        "- exit: only if the reply clearly ends the session (goodbye, closing).\n"
        "- Otherwise: none. When unsure, none."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"ASSISTANT REPLY:\n\n{reply.strip()}\n\nJSON:"},
    ]


def _parse_recovered(raw: str, agents: list[dict]) -> dict:
    text = raw.strip()
    fenced = re.search(r"\{.*\}", text, re.DOTALL)
    if fenced:
        text = fenced.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"type": "none"}
    if not isinstance(data, dict):
        return {"type": "none"}
    kind = str(data.get("type", "none")).lower()
    if kind not in ACTION_TYPES:
        return {"type": "none"}
    if kind in {"run", "read"}:
        from harness import resolve_agent

        agent = resolve_agent(agents, str(data.get("agent") or data.get("module") or ""))
        if not agent:
            return {"type": "none"}
        key = "agent" if kind == "run" else "module"
        return {"type": kind, key: agent["id"], "recovered": True}
    return {"type": kind, "recovered": True}


def _reply_mentions_agent(reply: str, agents: list[dict], agent_id: str) -> bool:
    agent = next((a for a in agents if a.get("id") == agent_id), None)
    if not agent:
        return False
    low = reply.lower()
    candidates = {
        str(agent.get("id", "")).lower(),
        str(agent.get("id", "")).lower().replace("_", " "),
        str(agent.get("name", "")).lower(),
        str(agent.get("output", "")).lower().replace(".md", ""),
    }
    return any(c and c in low for c in candidates)


def recover_action(provider, model: str, reply: str, agents: list[dict]) -> dict:
    """
    Second, JSON-only call to extract the action a small model forgot to emit.
    Never raises: any failure yields {"type": "none"}. `run`/`read` are accepted
    only if the reply text actually mentions that module.
    """
    if not reply.strip():
        return {"type": "none"}
    try:
        from harness import provider_chat
        from i18n import t

        raw, _ = provider_chat(
            provider,
            model,
            _recovery_messages(reply, agents),
            0.0,
            120,
            role="action_recovery",
            json_mode=True,
            status=t("busy_recovery"),
        )
    except Exception:
        return {"type": "none"}
    action = _parse_recovered(raw, agents)
    target = action.get("agent") or action.get("module")
    if target and not _reply_mentions_agent(reply, agents, str(target)):
        return {"type": "none"}
    return action


def language_rule(lang: str) -> str:
    if lang == "ko":
        return (
            "CRITICAL: You must respond to the user entirely in Korean. "
            "Do not use English for the visible reply. "
            "Keep action JSON keys and agent ids in English only."
        )
    return "Respond to the user in English. Keep action JSON keys and agent ids in English."


def build_conductor_messages(
    conductor_prompt: str,
    project_brief: str,
    *,
    project_state: str | None,
    module_context: str,
    history: list[dict],
    cache_ttl: str,
    history_truncated: bool = False,
) -> list[dict]:
    """
    system → brief → [state] → module snapshot → history.
    cache_control markers are for Anthropic-via-OpenRouter; other providers
    flatten and ignore them.
    """
    system_content = [
        {
            "type": "text",
            "text": conductor_prompt.strip(),
            "cache_control": {"type": "ephemeral", "ttl": cache_ttl},
        }
    ]
    brief_block = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": f"PROJECT BRIEF:\n\n{project_brief.strip()}",
                "cache_control": {"type": "ephemeral", "ttl": cache_ttl},
            }
        ],
    }

    messages: list[dict] = [
        {"role": "system", "content": system_content},
        brief_block,
    ]

    if project_state:
        state_note = (
            "Treat PROJECT STATE as the rolling project memory. "
            "Prefer it over older chat turns for decisions, open questions, and module status."
        )
        if history_truncated:
            state_note += (
                " Older conversation turns are omitted from this request; "
                "use Recent Notes in PROJECT STATE for earlier context."
            )
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"PROJECT STATE:\n\n{project_state.strip()}\n\n{state_note}",
                        "cache_control": {"type": "ephemeral", "ttl": cache_ttl},
                    }
                ],
            }
        )

    module_header = "MODULE SNAPSHOT:" if project_state else "KNOWN MODULE OUTPUTS:"
    module_rules = (
        "Use module status from PROJECT STATE. Do not invent missing module outputs."
        if project_state
        else "Treat this as the current project state. Do not invent missing module outputs."
    )
    body = module_context.strip() if module_context.strip() else "(none yet)"
    messages.append(
        {
            "role": "user",
            "content": [{"type": "text", "text": f"{module_header}\n\n{body}\n\n{module_rules}"}],
        }
    )

    return messages + history


def ask_conductor(
    api_key: str,
    config: dict,
    conductor_prompt: str,
    project_brief: str,
    previous_blocks: list[str],
    history: list[dict],
    session_id: str,
    user_text: str | None = None,
    *,
    project=None,
    agents: list[dict] | None = None,
    output_dir: Path | None = None,
    provider=None,
    ephemeral: bool = False,
    extra_messages: list[dict] | None = None,
) -> tuple[str, dict, dict]:
    """
    One Conductor turn. Raises LLMError on provider failure (history is left
    unchanged in that case so the user can retry).

    ephemeral=True sends `user_text` without storing it in history
    (session openings, system nudges).
    extra_messages are appended after history for this call only
    (module file injected for a `read` action).
    """
    from i18n import get_language

    runtime = resolve_conductor_runtime(config)
    model = runtime["model"]
    temperature = float(runtime["temperature"])
    max_tokens = int(runtime["max_tokens"])
    cache_ttl = str(runtime["cache_ttl"])
    provider = provider or conductor_provider(config, api_key)

    project_state = project.read_state() if project is not None else None
    state_path = project.state_path if project is not None else None

    working_history = list(history)
    if user_text is not None:
        working_history.append({"role": "user", "content": user_text})

    if agents is not None and output_dir is not None:
        state_text, module_context, api_history, truncated = prepare_conductor_context(
            config,
            agents,
            output_dir,
            previous_blocks,
            working_history,
            project_state,
            state_path=state_path,
        )
    else:
        state_text = project_state
        module_context = "\n\n".join(previous_blocks) if previous_blocks else "(none yet)"
        api_history = working_history
        truncated = False

    if extra_messages:
        api_history = list(api_history) + list(extra_messages)

    messages = build_conductor_messages(
        f"{conductor_prompt.strip()}\n\n## Language\n\n{language_rule(get_language())}",
        project_brief,
        project_state=state_text,
        module_context=module_context,
        history=api_history,
        cache_ttl=cache_ttl,
        history_truncated=truncated,
    )

    from harness import provider_chat
    from i18n import t

    raw, usage = provider_chat(
        provider,
        model,
        messages,
        temperature,
        max_tokens,
        role="conductor",
        status=t("busy_conductor"),
    )
    reply, action = parse_action(raw)

    if (
        action.get("type") == "none"
        and ACTION_RE.search(raw) is None
        and agents is not None
        and should_recover_action(runtime)
    ):
        recovered = recover_action(provider, model, reply, agents)
        if recovered.get("type") != "none":
            action = recovered
            stored = {k: v for k, v in recovered.items() if k != "recovered"}
            # Store the block so later turns see a well-formed example.
            raw = f"{reply}\n\n```action\n{json.dumps(stored)}\n```"

    # Commit to history only after a successful call.
    if user_text is not None and not ephemeral:
        history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": raw})
    if project is not None:
        project.save_history(history)
    return reply, action, usage
