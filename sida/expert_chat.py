"""Expert chat: the designer talks with one expert, apart from the Conductor conversation.

UI-agnostic like engine.py: nothing prints or reads input; progress goes out as
Session events. Each expert keeps its own history in chats/<expert id>.json. The expert
answers from its role prompt, the brief, project state and its current output. When the
designer asks for a change, the expert ends its reply with
```action {"type": "revise", "request": "..."}``` and the expert is rerun with that
request (engine.run_expert_command(..., revision=...)).

Experts with `chat: false` in config.yaml have no chat (e.g. site_reader, whose output is
government records: changes go through the site lookup, not a conversation).

Event kinds (besides the engine's run and state events):
  expert_reply      agent, text, usage
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sida import engine
from sida.conductor import parse_action
from sida.config import ROOT
from sida.i18n import get_language, t
from sida.providers import format_usage, provider_chat
from sida.runtime import resolve_worker_runtime
from sida.storage import atomic_write_text

CHAT_DIRNAME = "chats"
HISTORY_LIMIT = 20  # chat messages sent to the model; the file keeps everything
REVISED_PREFIX = "[revised] "

# Sent to the model — stays English regardless of UI language.
EXPERT_CHAT_SYSTEM = """You are one specialist expert in Sida, an architectural design reasoning tool.
The designer is talking with you directly about your own analysis, outside the main
Conductor conversation. Your role, the project brief, the project state and your current
output are given below.

- Answer questions about your output: explain the reasoning, point to the evidence, say
  what is uncertain or missing. Stay within your role; name another expert when a question
  belongs to them.
- Do not invent project facts, statutes or figures that are not in the material given.
- Keep replies short and conversational. Do not rewrite your output in the chat.
- When the designer asks you to change, add to or redo your output, say in one or two
  sentences what you will change, then end the reply with exactly one block:
```action
{"type": "revise", "request": "<the change, written as an instruction to yourself>"}
```
  Otherwise end with:
```action
{"type": "none"}
```"""


@dataclass
class ExpertReply:
    text: str
    revision: str | None = None  # the change request, when the expert agreed to revise
    run: engine.ExpertRun | None = None  # the revision run, when one happened


def chat_enabled(agent: dict) -> bool:
    return bool(agent.get("chat", True))


def chat_path(project_path: Path, agent: dict) -> Path:
    return project_path / CHAT_DIRNAME / f"{agent['id']}.json"


def load_chat(project_path: Path, agent: dict) -> list[dict]:
    try:
        data = json.loads(chat_path(project_path, agent).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [
        {"role": m["role"], "content": m["content"]}
        for m in data
        if isinstance(m, dict) and m.get("role") in {"user", "assistant"}
        and isinstance(m.get("content"), str)
    ]


def save_chat(project_path: Path, agent: dict, history: list[dict]) -> None:
    path = chat_path(project_path, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(history, ensure_ascii=False, indent=2) + "\n")


def chat_messages(history: list[dict]) -> list[dict]:
    """
    Stored chat as screen entries: {"role": "user" | "expert" | "system", "text"}.
    Action blocks are removed; a revision note becomes {"role": "system", "event": "revised"}.
    """
    messages: list[dict] = []
    for item in history:
        content = item["content"]
        if item["role"] == "user" and content.startswith(REVISED_PREFIX):
            messages.append({"role": "system", "event": "revised", "text": content})
        elif item["role"] == "assistant":
            messages.append({"role": "expert", "text": parse_action(content)[0]})
        else:
            messages.append({"role": "user", "text": content})
    return messages


def _context(session: engine.Session, agent: dict) -> str:
    role = (ROOT / agent["file"]).read_text(encoding="utf-8")
    output = session.project.read_module(agent["output"]) or "(not run yet)"
    state = session.project.read_state() or "(none)"
    language = "Korean" if get_language() == "ko" else "English"
    return (
        f"YOUR ROLE (expert id: {agent['id']}):\n{role}\n\n"
        f"PROJECT BRIEF:\n{session.project_brief}\n\n"
        f"PROJECT STATE:\n{state}\n\n"
        f"YOUR CURRENT OUTPUT (modules/{agent['output']}):\n{output}\n\n"
        f"Reply in {language}. Keep the action block keys in English."
    )


def expert_turn(session: engine.Session, agent: dict, user_text: str) -> ExpertReply:
    """One chat exchange. Raises LLMError; the chat file is untouched then."""
    history = load_chat(session.project.path, agent)
    rt = resolve_worker_runtime(session.config)
    messages = [
        {"role": "system", "content": EXPERT_CHAT_SYSTEM},
        {"role": "user", "content": _context(session, agent)},
        {"role": "assistant", "content": "Understood."},
        *history[-HISTORY_LIMIT:],
        {"role": "user", "content": user_text},
    ]
    raw, usage = provider_chat(
        session.w_provider,
        rt["model"],
        messages,
        rt["temperature"],
        rt["max_tokens"],
        role="expert_chat",
        status=t("busy_role", role=agent["id"]),
    )
    reply, action = parse_action(raw)
    history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": raw}]
    save_chat(session.project.path, agent, history)
    session.send("expert_reply", agent=agent, text=reply, usage=format_usage(usage))
    request = str(action.get("request") or "").strip()
    if str(action.get("type", "")).lower() == "revise" and request:
        return ExpertReply(reply, revision=request)
    return ExpertReply(reply)


def expert_chat(session: engine.Session, agent: dict, user_text: str) -> ExpertReply:
    """
    A chat exchange that carries out an agreed revision: the expert is rerun with the
    request, project_state.md is settled as after any run, and both the chat and the
    Conductor history note it. Raises ValueError for an expert without chat.
    """
    if not chat_enabled(agent):
        raise ValueError(f"chat is off for this expert: {agent['id']}")
    reply = expert_turn(session, agent, user_text)
    if reply.revision is None:
        return reply
    result = engine.run_expert_command(
        session, agent, f"/run {agent['id']} {reply.revision}", revision=reply.revision
    )
    reply.run = result
    if result.run is not None:
        history = load_chat(session.project.path, agent)
        history.append({
            "role": "user",
            "content": f"{REVISED_PREFIX}modules/{agent['output']} was rewritten: {reply.revision}",
        })
        save_chat(session.project.path, agent, history)
    return reply
