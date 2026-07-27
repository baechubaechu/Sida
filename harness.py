#!/usr/bin/env python3
"""Shared helpers for Sida (architectural reasoning CLI)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
WORKER_SYSTEM = (
    "You are an architectural reasoning assistant. "
    "Follow the agent role and output format exactly."
)


def fail(message: str, code: int = 1) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)


def load_env(*, interactive: bool = True) -> str:
    """Load API key; if missing, guide the user through setup."""
    from setup import ensure_api_key

    return ensure_api_key(interactive=interactive)


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        fail(f"Missing config file: {path}")
    try:
        with path.open(encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        fail(f"Invalid YAML in {path}: {exc}")
    if not isinstance(config, dict):
        fail(f"Invalid config format in {path}")
    return config


def get_agents(config: dict) -> list[dict]:
    agents = config.get("agents")
    if not isinstance(agents, list) or not agents:
        fail("No agents defined in config.yaml")
    return agents


def agent_by_id(agents: list[dict], agent_id: str) -> dict | None:
    for agent in agents:
        if agent.get("id") == agent_id:
            return agent
    return None


def resolve_agent(agents: list[dict], query: str) -> dict | None:
    """Resolve by id, output stem, or case-insensitive name substring."""
    q = query.strip().lower().replace(" ", "_").replace("-", "_")
    if not q:
        return None

    exact = agent_by_id(agents, q)
    if exact:
        return exact

    for agent in agents:
        aid = str(agent.get("id", "")).lower()
        name = str(agent.get("name", "")).lower().replace(" ", "_")
        output = str(agent.get("output", "")).lower().replace(".md", "")
        if q in {aid, name, output}:
            return agent
        if q in aid or q in name or q in output:
            return agent
    return None


def build_worker_prompt(agent_prompt: str, project_brief: str, previous_outputs: str) -> str:
    from i18n import get_language

    lang = get_language()
    language_rule = (
        "Write the entire Markdown output in Korean. Keep section headings exactly as specified in the agent output format."
        if lang == "ko"
        else "Write the entire Markdown output in English. Keep section headings exactly as specified in the agent output format."
    )
    return f"""AGENT PROMPT:
{agent_prompt}

ORIGINAL PROJECT BRIEF:
{project_brief}

PREVIOUS AGENT OUTPUTS:
{previous_outputs}

LANGUAGE:
{language_rule}

TASK:
Produce the output for this agent in Markdown.
Follow the output format defined in the agent prompt.
Do not invent project facts not included in the brief or previous outputs.
If information is missing, mark it as missing information.
"""


def call_openrouter(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    *,
    session_id: str | None = None,
    use_cache: bool = False,
    cache_ttl: str = "1h",
) -> tuple[str, dict]:
    """Call OpenRouter. Returns (content, usage_dict)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if session_id:
        body["session_id"] = session_id
    if use_cache:
        # Anthropic via OpenRouter: explicit cache opt-in
        body["cache_control"] = {"type": "ephemeral", "ttl": cache_ttl}

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=120)
    except requests.RequestException as exc:
        fail(f"API request failed: {exc}")

    if response.status_code != 200:
        fail(f"API error ({response.status_code}): {response.text}")

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        fail(f"Unexpected API response format: {exc}")

    if not content or not str(content).strip():
        fail("Empty LLM response")

    usage = data.get("usage") or {}
    return str(content).strip(), usage


def run_worker_agent(
    api_key: str,
    config: dict,
    agent: dict,
    project_brief: str,
    previous_blocks: list[str],
    output_dir: Path,
) -> str:
    worker = config.get("worker") or {}
    model = worker.get("model") or config.get("model", "openai/gpt-4o-mini")
    temperature = float(worker.get("temperature", config.get("temperature", 0.3)))
    max_tokens = int(worker.get("max_tokens", config.get("max_tokens", 2000)))

    prompt_rel = agent.get("file")
    output_name = agent.get("output")
    name = agent.get("name", agent.get("id", "agent"))
    if not prompt_rel or not output_name:
        fail(f"Agent '{name}' is missing 'file' or 'output' in config.yaml")

    prompt_path = ROOT / prompt_rel
    if not prompt_path.exists():
        fail(f"Missing agent prompt file: {prompt_path}")

    agent_prompt = prompt_path.read_text(encoding="utf-8")
    previous_outputs = "\n\n".join(previous_blocks) if previous_blocks else "(none yet)"
    full_prompt = build_worker_prompt(agent_prompt, project_brief, previous_outputs)

    messages = [
        {"role": "system", "content": WORKER_SYSTEM},
        {"role": "user", "content": full_prompt},
    ]
    result, _usage = call_openrouter(
        api_key,
        model,
        messages,
        temperature,
        max_tokens,
        use_cache=False,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name
    output_path.write_text(result + "\n", encoding="utf-8")
    return result


def format_usage(usage: dict) -> str:
    if not usage:
        return ""
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    prompt = usage.get("prompt_tokens", "?")
    completion = usage.get("completion_tokens", "?")
    parts = [f"in={prompt}", f"out={completion}"]
    if cached:
        parts.append(f"cached={cached}")
    return " | ".join(parts)
