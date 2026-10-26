#!/usr/bin/env python3
"""Conductor turn: message assembly, expert tools or action parsing, one LLM call."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sida.conductor_context import prepare_conductor_context
from sida.runtime import conductor_provider, resolve_conductor_runtime

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


# ---------------------------------------------------------------------------
# Function tools: the Conductor calls experts through the provider's tool calling.
# The ```action``` block stays the fallback for providers or models without tools.
# ---------------------------------------------------------------------------

RUN_TOOL = "run_expert"
READ_TOOL = "read_expert_output"
BOARD_TOOL = "read_board"  # a cloud Conductor reads drafting-table papers (sida/board.py)
PROPOSE_TOOL = "propose_paper"  # ... and puts new ones in the table's AI section
ACTION_SECTION = "## Action block (required)"
TOOLS_SECTION = "## Expert tools"

# (provider name, model) pairs that refused tools in this process; they stay in text mode.
_NO_TOOLS: set[tuple[str, str]] = set()


def uses_tools(runtime: dict, provider, model: str) -> bool:
    mode = str(runtime.get("tool_calls", "auto")).lower()
    if mode in {"off", "false", "0", "never"}:
        return False
    if not callable(getattr(provider, "chat_tools", None)):
        return False
    return (str(getattr(provider, "name", "")), model) not in _NO_TOOLS


def conductor_tools(agents: list[dict], *, board: bool = False) -> list[dict]:
    ids = [str(a.get("id")) for a in agents]
    target = {
        "type": "object",
        "properties": {"agent": {"type": "string", "enum": ids, "description": "Expert id."}},
        "required": ["agent"],
        "additionalProperties": False,
    }
    return [
        {
            "name": RUN_TOOL,
            "description": (
                "Run one expert now. Its output document is saved and shown to you afterwards. "
                "Call it at most once per reply, only when the designer wants that expert now "
                "or the next step is obvious and useful."
            ),
            "parameters": target,
        },
        {
            "name": READ_TOOL,
            "description": (
                "Open the full output document of a completed expert when PROJECT STATE does not "
                "hold enough detail to answer. Only for experts listed as completed."
            ),
            "parameters": target,
        },
    ] + ([read_board_spec(), propose_paper_spec()] if board else [])


def read_board_spec() -> dict:
    return {
        "name": BOARD_TOOL,
        "description": (
            "Open one paper on the drawing table (a massing scheme with its figures, a note, the "
            "site, a tracing sheet) by its id from the DRAWING TABLE index, when the designer "
            "talks about a paper that is not shown in full."
        ),
        "parameters": {
            "type": "object",
            "properties": {"paper": {"type": "string", "description": "Paper id."}},
            "required": ["paper"],
            "additionalProperties": False,
        },
    }


def propose_paper_spec() -> dict:
    block = {
        "type": "object",
        "properties": {
            "u": {"type": "number", "description": "Block centre along the site's long side, m from the site's middle."},
            "v": {"type": "number", "description": "Block centre across it, m from the middle."},
            "w": {"type": "number", "description": "Length, m."},
            "d": {"type": "number", "description": "Depth, m."},
            "floors": {"type": "integer"},
        },
        "required": ["w", "d", "floors"],
    }
    return {
        "name": PROPOSE_TOOL,
        "description": (
            "Put a new massing scheme or note in the AI section next to the drawing table; the "
            "designer moves it onto the table if they like it. To change a scheme on the table, "
            "send the whole changed scheme with based_on = its id (the original stays). Only when "
            "the designer asks for a scheme or a note, or a concrete alternative clearly helps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["mass", "note"]},
                "title": {"type": "string", "description": "Short name, in the designer's language."},
                "text": {"type": "string", "description": "The note (kind note)."},
                "blocks": {"type": "array", "items": block, "description": "The blocks (kind mass)."},
                "based_on": {"type": "string", "description": "Id of the scheme this changes."},
                "reason": {"type": "string", "description": "One line: why this scheme or note."},
            },
            "required": ["kind", "reason"],
        },
    }


def action_from_tool_calls(calls: list[dict]) -> dict:
    """The first known tool call → an action dict like parse_action's."""
    for call in calls:
        arguments = call.get("arguments") or {}
        if call.get("name") == BOARD_TOOL and str(arguments.get("paper") or "").strip():
            return {"type": "read_board", "paper": str(arguments["paper"]).strip()}
        if call.get("name") == PROPOSE_TOOL and isinstance(arguments, dict):
            return {"type": "propose_paper", "paper": arguments}
        agent = str(arguments.get("agent") or "").strip()
        if call.get("name") == RUN_TOOL and agent:
            return {"type": "run", "agent": agent}
        if call.get("name") == READ_TOOL and agent:
            return {"type": "read", "module": agent}
    return {"type": "none"}


def prompt_for_mode(prompt: str, *, tools: bool) -> str:
    """Keep the section for the mode in use: expert tools, or the action block.
    A prompt without an expert tools section keeps its action block in both modes."""
    parts = re.split(r"(?m)^(?=## )", prompt)
    if tools and not any(p.startswith(TOOLS_SECTION) for p in parts):
        return prompt.strip()
    drop = ACTION_SECTION if tools else TOOLS_SECTION
    return "".join(p for p in parts if not p.startswith(drop)).strip()


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
        from sida.config import resolve_agent

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
        from sida.i18n import t
        from sida.providers import provider_chat

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
    table_context: str = "",
) -> list[dict]:
    """
    system → brief → [state] → module snapshot → [drawing table] → history.
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
    if table_context.strip():
        # Not cached: the selection changes with every message.
        messages.append({"role": "user", "content": [{"type": "text", "text": table_context.strip()}]})

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
    table_context: str = "",
    board_tool: bool = False,
) -> tuple[str, dict, dict]:
    """
    One Conductor turn. Raises LLMError on provider failure (history is left
    unchanged in that case so the user can retry).

    ephemeral=True sends `user_text` without storing it in history
    (session openings, system nudges).
    extra_messages are appended after history for this call only
    (module file injected for a `read` action).
    table_context is the drawing table for this call only (sida/board.py); board_tool adds
    the read_board tool.
    """
    from sida.i18n import get_language

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

    def messages_for(tools: bool) -> list[dict]:
        prompt = prompt_for_mode(conductor_prompt.strip(), tools=tools)
        return build_conductor_messages(
            f"{prompt}\n\n## Language\n\n{language_rule(get_language())}",
            project_brief,
            project_state=state_text,
            module_context=module_context,
            history=api_history,
            cache_ttl=cache_ttl,
            history_truncated=truncated,
            table_context=table_context,
        )

    from sida.i18n import t
    from sida.providers import ToolsUnsupported, provider_chat

    raw = None
    if agents and uses_tools(runtime, provider, model):
        try:
            text, calls, usage = provider_chat(
                provider,
                model,
                messages_for(True),
                temperature,
                max_tokens,
                role="conductor",
                status=t("busy_conductor"),
                tools=conductor_tools(agents, board=board_tool),
            )
        except ToolsUnsupported:
            _NO_TOOLS.add((str(getattr(provider, "name", "")), model))
        else:
            reply, action = parse_action(text)  # a model may still write the block
            if action.get("type") == "none":
                action = action_from_tool_calls(calls)
            # Stored as an action block so later turns (in either mode) read what happened.
            if action.get("type") != "none":
                raw = f"{reply}\n\n```action\n{json.dumps(action)}\n```".strip()
            elif reply:
                raw = reply
            # Neither text nor a known tool call: ask again in text mode below.

    if raw is None:
        raw, usage = provider_chat(
            provider,
            model,
            messages_for(False),
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
