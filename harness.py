#!/usr/bin/env python3
"""Shared helpers for Sida (architectural reasoning CLI)."""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
MODULE_HISTORY_DIRNAME = "_history"
WORKER_SYSTEM = (
    "You are an architectural reasoning assistant. "
    "Follow the agent role and output format exactly."
)

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """Recoverable LLM/provider failure. Callers decide whether to exit."""


def fail(message: str, code: int = 1) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)


def load_env(*, interactive: bool = True) -> str:
    """Load API key; if missing, guide the user through setup."""
    from setup_env import ensure_api_key

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


def get_paths(config: dict) -> dict[str, list[str]]:
    """Named suggested expert sequences (hints for the Conductor / run.py --path)."""
    raw = config.get("paths") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for name, ids in raw.items():
        if isinstance(ids, list) and ids:
            out[str(name)] = [str(i) for i in ids]
    return out


def agent_inputs(agent: dict) -> list[str] | str:
    """
    Which prior outputs this expert reads: a list of ids, "all", or "legacy"
    (key absent → caller passes every prior block, as before).
    """
    raw = agent.get("inputs")
    if raw is None:
        return "legacy"
    if isinstance(raw, str):
        return "all" if raw.strip().lower() == "all" else [raw]
    if isinstance(raw, list):
        return [str(i) for i in raw]
    return "legacy"


def render_conductor_prompt(template: str, config: dict) -> str:
    """Fill {{MODULES}} and {{PATHS}} from config so the expert list lives in one place."""
    agents = get_agents(config)
    by_phase: dict[str, list[dict]] = {}
    for a in agents:
        by_phase.setdefault(str(a.get("phase") or "other"), []).append(a)
    lines: list[str] = []
    for phase, items in by_phase.items():
        lines.append(f"**{phase}**")
        for a in items:
            desc = str(a.get("desc") or a.get("name") or "").strip()
            inputs = agent_inputs(a)
            if inputs == "all":
                dep = "reads all completed outputs"
            elif isinstance(inputs, list) and inputs:
                dep = "reads: " + ", ".join(inputs)
            else:
                dep = "standalone"
            lines.append(f"- `{a.get('id')}` — {desc}  ({dep})")
        lines.append("")
    modules = "\n".join(lines).rstrip()

    paths = get_paths(config)
    path_lines = [f"- {name}: " + " → ".join(ids) for name, ids in paths.items()]
    paths_text = "\n".join(path_lines) if path_lines else "- (none defined)"

    return template.replace("{{MODULES}}", modules).replace("{{PATHS}}", paths_text)


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


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def _flatten_content(content: Any) -> str:
    """Anthropic-style content arrays → plain string (for non-OpenRouter providers)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n\n".join(p for p in parts if p)
    return str(content)


def _plain_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"role": str(m.get("role", "user")), "content": _flatten_content(m.get("content"))}
        for m in messages
    ]


def _with_retries(send, *, attempts: int = 3, base_delay: float = 1.5):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return send()
        except LLMError as exc:
            last = exc
            if not getattr(exc, "retryable", False) or i == attempts - 1:
                raise
            time.sleep(base_delay * (2**i))
    assert last is not None
    raise last


def _retryable(msg: str) -> LLMError:
    err = LLMError(msg)
    err.retryable = True  # type: ignore[attr-defined]
    return err


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, api_key: str):
        if not api_key:
            raise LLMError("OpenRouter API key is missing. Run: python setup_env.py")
        self.api_key = api_key

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        **_: Any,
    ) -> tuple[str, dict]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        def send():
            try:
                response = requests.post(
                    OPENROUTER_URL, headers=headers, json=body, timeout=120
                )
            except requests.Timeout as exc:
                raise _retryable(f"OpenRouter timeout: {exc}") from exc
            except requests.RequestException as exc:
                raise _retryable(f"OpenRouter request failed: {exc}") from exc

            if response.status_code in RETRY_STATUS:
                raise _retryable(
                    f"OpenRouter error ({response.status_code}): {response.text[:300]}"
                )
            if response.status_code != 200:
                raise LLMError(
                    f"OpenRouter error ({response.status_code}): {response.text[:300]}"
                )
            try:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"Unexpected OpenRouter response: {exc}") from exc
            if not content or not str(content).strip():
                raise _retryable("Empty LLM response")
            return str(content).strip(), data.get("usage") or {}

        return _with_retries(send)


class OllamaProvider:
    """Local Ollama via native /api/chat (supports num_ctx)."""

    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        num_ctx: int | None = None,
        keep_alive: str | None = "30m",
    ):
        url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
        if url.endswith("/v1"):
            url = url[: -len("/v1")]
        self.base_url = url
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        *,
        json_mode: bool = False,
        **_: Any,
    ) -> tuple[str, dict]:
        options: dict[str, Any] = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        if self.num_ctx:
            options["num_ctx"] = int(self.num_ctx)
        body: dict[str, Any] = {
            "model": model,
            "messages": _plain_messages(messages),
            "stream": False,
            "options": options,
        }
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        if json_mode:
            body["format"] = "json"

        def send():
            try:
                response = requests.post(
                    f"{self.base_url}/api/chat", json=body, timeout=300
                )
            except requests.ConnectionError as exc:
                raise LLMError(
                    f"Cannot reach Ollama at {self.base_url}. "
                    "Start it with `ollama serve` (or open the Ollama app)."
                ) from exc
            except requests.Timeout as exc:
                raise _retryable(f"Ollama timeout: {exc}") from exc
            except requests.RequestException as exc:
                raise _retryable(f"Ollama request failed: {exc}") from exc

            if response.status_code == 404:
                raise LLMError(
                    f"Ollama model '{model}' not found. Run: ollama pull {model}"
                )
            if response.status_code in RETRY_STATUS:
                raise _retryable(
                    f"Ollama error ({response.status_code}): {response.text[:300]}"
                )
            if response.status_code != 200:
                raise LLMError(
                    f"Ollama error ({response.status_code}): {response.text[:300]}"
                )
            try:
                data = response.json()
                content = data["message"]["content"]
            except (ValueError, KeyError, TypeError) as exc:
                raise LLMError(f"Unexpected Ollama response: {exc}") from exc
            if not content or not str(content).strip():
                raise _retryable("Empty LLM response")
            usage = {
                "prompt_tokens": data.get("prompt_eval_count"),
                "completion_tokens": data.get("eval_count"),
            }
            return str(content).strip(), usage

        return _with_retries(send)


class MockProvider:
    """Offline provider for demos/tests. Returns deterministic placeholder text."""

    name = "mock"

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        *,
        role: str = "conductor",
        **_: Any,
    ) -> tuple[str, dict]:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = _flatten_content(m.get("content"))
                break
        if role == "worker":
            agent_part = last_user.split("ORIGINAL PROJECT BRIEF:", 1)[0]
            headers = expected_headers(agent_part)
            body = "\n\n".join(f"## {h}\n- (mock) placeholder" for h in headers)
            return f"# Mock Output\n\n{body}".strip(), {}
        if role == "state_update":
            m = re.search(r"MODULE ID:\s*(\S+)", last_user)
            mod = m.group(1) if m else "module"
            return (
                '{"module_status": {"status": "done", "key_takeaway": "(mock) takeaway"}, '
                '"sections": {"Recent Notes": ["(mock) ' + mod + ' completed"]}}'
            ), {}
        if role == "action_recovery":
            return '{"type": "none"}', {}
        return (
            "(mock) Conductor reply. No model was called.\n\n"
            '```action\n{"type": "none"}\n```'
        ), {}


def make_provider(
    kind: str,
    *,
    api_key: str = "",
    base_url: str | None = None,
    num_ctx: int | None = None,
    keep_alive: str | None = "30m",
):
    kind = (kind or "openrouter").lower()
    if kind == "openrouter":
        return OpenRouterProvider(api_key)
    if kind in {"ollama", "local"}:
        return OllamaProvider(base_url=base_url, num_ctx=num_ctx, keep_alive=keep_alive)
    if kind == "mock":
        return MockProvider()
    raise LLMError(f"Unknown provider '{kind}'. Use openrouter | ollama | mock.")


def call_openrouter(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    **_: Any,
) -> tuple[str, dict]:
    """Backward-compatible wrapper. Raises LLMError."""
    return OpenRouterProvider(api_key).chat(model, messages, temperature, max_tokens)


# ---------------------------------------------------------------------------
# Runtime config
# ---------------------------------------------------------------------------


def resolve_local_profile(config: dict) -> dict | None:
    """Return the active local_profiles entry when Conductor uses ollama."""
    conductor = config.get("conductor") or {}
    provider = str(conductor.get("provider") or config.get("provider") or "openrouter")
    if provider.lower() not in {"ollama", "local"}:
        return None
    profiles = config.get("local_profiles") or {}
    name = str(conductor.get("local_profile") or "local")
    profile = profiles.get(name)
    if not isinstance(profile, dict):
        fail(
            f"Unknown conductor.local_profile '{name}'. "
            f"Define it under local_profiles in config.yaml "
            f"(available: {', '.join(profiles) or 'none'})."
        )
    return profile


def resolve_conductor_runtime(config: dict) -> dict:
    """Effective Conductor settings after applying local_profile overlays."""
    conductor = dict(config.get("conductor") or {})
    provider = str(conductor.get("provider") or config.get("provider") or "openrouter")
    runtime = {
        "provider": provider.lower(),
        "model": conductor.get("model", "anthropic/claude-haiku-4.5"),
        "temperature": float(conductor.get("temperature", 0.4)),
        "max_tokens": int(conductor.get("max_tokens", 700)),
        "cache_ttl": str(conductor.get("cache_ttl", "1h")),
        "prompt": conductor.get("prompt", "agents/00_conductor.md"),
        "base_url": conductor.get("base_url"),
        "local_profile": conductor.get("local_profile"),
        "num_ctx": None,
        "history_window": int((conductor.get("context") or {}).get("history_window", 12)),
        "action_recovery": str(conductor.get("action_recovery", "auto")).lower(),
        "keep_alive": str(conductor.get("ollama_keep_alive", "30m")),
    }

    profile = resolve_local_profile(config)
    if profile:
        if profile.get("model"):
            runtime["model"] = profile["model"]
        if "temperature" in profile:
            runtime["temperature"] = float(profile["temperature"])
        if "max_tokens" in profile:
            runtime["max_tokens"] = int(profile["max_tokens"])
        if "history_window" in profile:
            runtime["history_window"] = int(profile["history_window"])
        if "num_ctx" in profile:
            runtime["num_ctx"] = int(profile["num_ctx"])
        if profile.get("base_url"):
            runtime["base_url"] = profile["base_url"]
        elif not runtime["base_url"]:
            runtime["base_url"] = DEFAULT_OLLAMA_URL

    return runtime


def resolve_worker_runtime(config: dict) -> dict:
    worker = config.get("worker") or {}
    return {
        "provider": str(worker.get("provider") or config.get("provider") or "openrouter").lower(),
        "model": worker.get("model") or config.get("model", "openai/gpt-4o-mini"),
        "temperature": float(worker.get("temperature", config.get("temperature", 0.3))),
        "max_tokens": int(worker.get("max_tokens", config.get("max_tokens", 2000))),
        "base_url": worker.get("base_url"),
        "num_ctx": worker.get("num_ctx"),
    }


def conductor_provider(config: dict, api_key: str):
    rt = resolve_conductor_runtime(config)
    return make_provider(
        rt["provider"],
        api_key=api_key,
        base_url=rt.get("base_url"),
        num_ctx=rt.get("num_ctx"),
        keep_alive=rt.get("keep_alive"),
    )


def worker_provider(config: dict, api_key: str):
    rt = resolve_worker_runtime(config)
    return make_provider(
        rt["provider"], api_key=api_key, base_url=rt.get("base_url"), num_ctx=rt.get("num_ctx")
    )


# ---------------------------------------------------------------------------
# Worker agents
# ---------------------------------------------------------------------------


def build_worker_prompt(
    agent_prompt: str,
    project_brief: str,
    previous_outputs: str,
    *,
    project_state: str | None = None,
    other_completed: list[str] | None = None,
    knowledge_block: str | None = None,
) -> str:
    from i18n import get_language

    lang = get_language()
    language_rule = (
        "Write the entire Markdown output in Korean. Keep section headings exactly as specified in the agent output format. In the Handoff section, keep expert ids in English (e.g. → regulation_checker)."
        if lang == "ko"
        else "Write the entire Markdown output in English. Keep section headings exactly as specified in the agent output format."
    )
    state_block = ""
    if project_state and project_state.strip():
        state_block = f"""
PROJECT STATE (designer-curated memory — decisions, open questions, expert status):
{project_state.strip()}
"""
    others_block = ""
    if other_completed:
        others_block = (
            "\nOTHER COMPLETED EXPERTS (not included above; ask via Handoff if needed): "
            + ", ".join(other_completed)
            + "\n"
        )
    knowledge = ""
    if knowledge_block and knowledge_block.strip():
        knowledge = f"""
{knowledge_block.strip()}
"""
    return f"""AGENT PROMPT:
{agent_prompt}

ORIGINAL PROJECT BRIEF:
{project_brief}
{state_block}
RELEVANT EXPERT OUTPUTS:
{previous_outputs}
{others_block}{knowledge}
LANGUAGE:
{language_rule}

TASK:
Produce the output for this expert in Markdown.
Follow the output format defined in the agent prompt, every header, in order.
Do not invent project facts not included in the brief, project state, expert outputs, or retrieved knowledge.
When RETRIEVED KNOWLEDGE is present, prefer it for numeric limits and cite `source:` paths; still mark uncertain items as verify.
If information is missing, mark it as missing information.
End with the Handoff section: name which experts should look next and what they should check.
"""


def select_input_blocks(
    agents: list[dict], agent: dict, output_dir: Path
) -> tuple[list[str], list[str]] | None:
    """
    Pick which completed outputs this expert receives, per its `inputs` declaration.
    Returns (blocks, other_completed_names) or None for legacy agents (no `inputs` key).
    """
    wanted = agent_inputs(agent)
    if wanted == "legacy":
        return None
    blocks: list[str] = []
    others: list[str] = []
    for other in agents:
        if other.get("id") == agent.get("id"):
            continue
        path = output_dir / str(other.get("output", ""))
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        label = str(other.get("name", other.get("id")))
        if wanted == "all" or other.get("id") in wanted:
            blocks.append(f"### {label} ({other.get('id')})\n\n{text}")
        else:
            others.append(str(other.get("id")))
    return blocks, others


def expected_headers(agent_prompt: str) -> list[str]:
    """`## ...` headers listed under the agent's `## Output Format` section."""
    match = re.search(r"^## Output Format\s*$", agent_prompt, flags=re.MULTILINE)
    if not match:
        return []
    tail = agent_prompt[match.end():]
    return [h.strip() for h in re.findall(r"^## (.+)$", tail, flags=re.MULTILINE)]


def missing_headers(output: str, headers: list[str]) -> list[str]:
    present = {h.strip().lower() for h in re.findall(r"^## (.+)$", output, flags=re.MULTILINE)}
    return [h for h in headers if h.lower() not in present]


def archive_module_output(output_path: Path) -> Path | None:
    """Move an existing module file into modules/_history before overwrite."""
    if not output_path.exists():
        return None
    hist = output_path.parent / MODULE_HISTORY_DIRNAME
    hist.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(output_path.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
    target = hist / f"{output_path.stem}.{stamp}{output_path.suffix}"
    counter = 1
    while target.exists():
        target = hist / f"{output_path.stem}.{stamp}-{counter}{output_path.suffix}"
        counter += 1
    output_path.replace(target)
    return target


def run_worker_agent(
    api_key: str,
    config: dict,
    agent: dict,
    project_brief: str,
    previous_blocks: list[str],
    output_dir: Path,
    *,
    provider=None,
    project_state: str | None = None,
) -> str:
    """Run one expert. Raises LLMError on provider failure.

    Experts with an `inputs` declaration receive only the listed completed outputs
    (read from output_dir); other completed experts are named but not included.
    Legacy agents (no `inputs`) receive `previous_blocks` unchanged.
    """
    rt = resolve_worker_runtime(config)
    provider = provider or worker_provider(config, api_key)

    prompt_rel = agent.get("file")
    output_name = agent.get("output")
    name = agent.get("name", agent.get("id", "agent"))
    if not prompt_rel or not output_name:
        fail(f"Agent '{name}' is missing 'file' or 'output' in config.yaml")

    prompt_path = ROOT / prompt_rel
    if not prompt_path.exists():
        fail(f"Missing agent prompt file: {prompt_path}")

    agent_prompt = prompt_path.read_text(encoding="utf-8")

    selected = select_input_blocks(get_agents(config), agent, output_dir)
    other_completed: list[str] | None = None
    if selected is None:
        blocks = previous_blocks
    else:
        blocks, other_completed = selected
    previous_outputs = "\n\n".join(blocks) if blocks else "(none yet)"
    knowledge_block = ""
    try:
        from rag import build_retrieval_query, retrieve_for_agent

        query = build_retrieval_query(
            project_brief, project_state=project_state, expert_outputs=previous_outputs
        )
        knowledge_block = retrieve_for_agent(
            config,
            agent,
            query,
            project_brief=project_brief,
            project_state=project_state,
            expert_outputs=previous_outputs,
        )
    except Exception:
        knowledge_block = ""
    full_prompt = build_worker_prompt(
        agent_prompt,
        project_brief,
        previous_outputs,
        project_state=project_state,
        other_completed=other_completed,
        knowledge_block=knowledge_block or None,
    )

    messages = [
        {"role": "system", "content": WORKER_SYSTEM},
        {"role": "user", "content": full_prompt},
    ]
    result, _usage = provider.chat(
        rt["model"], messages, rt["temperature"], rt["max_tokens"], role="worker"
    )

    headers = expected_headers(agent_prompt)
    missing = missing_headers(result, headers)
    if missing:
        fix = (
            "Your previous output was missing these required section headers: "
            + ", ".join(f"'## {h}'" for h in missing)
            + ". Rewrite the full output with every header from the Output Format, in order."
        )
        retry_messages = messages + [
            {"role": "assistant", "content": result},
            {"role": "user", "content": fix},
        ]
        retried, _ = provider.chat(
            rt["model"], retry_messages, rt["temperature"], rt["max_tokens"], role="worker"
        )
        if len(missing_headers(retried, headers)) < len(missing):
            result = retried
        still = missing_headers(result, headers)
        if still:
            from i18n import t

            print(
                t("module_missing_headers", name=name, headers=", ".join(still)),
                file=sys.stderr,
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name
    archived = archive_module_output(output_path)
    if archived:
        from i18n import t

        print(t("module_archived", path=archived.relative_to(output_dir).as_posix()))
    output_path.write_text(result + "\n", encoding="utf-8")
    return result


def format_usage(usage: dict) -> str:
    if not usage:
        return ""
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if prompt is None and completion is None:
        return ""
    parts = [f"in={prompt if prompt is not None else '?'}", f"out={completion if completion is not None else '?'}"]
    if cached:
        parts.append(f"cached={cached}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Conductor context
# ---------------------------------------------------------------------------


def get_conductor_context_settings(config: dict) -> dict:
    ctx = (config.get("conductor") or {}).get("context") or {}
    runtime = resolve_conductor_runtime(config)
    return {
        "state_file": str(ctx.get("state_file") or "project_state.md"),
        "history_window": max(0, int(runtime["history_window"])),
        "prefer_state_over_modules": bool(ctx.get("prefer_state_over_modules", True)),
        "provider": runtime["provider"],
        "local_profile": runtime.get("local_profile"),
        "num_ctx": runtime.get("num_ctx"),
    }


def slice_history(history: list[dict], window: int) -> tuple[list[dict], bool]:
    """
    Return recent history for the API and whether older turns were omitted.
    The slice is aligned to start on a user message so pairs are not split.
    """
    if window <= 0 or len(history) <= window:
        return list(history), False
    start = len(history) - window
    while start < len(history) and history[start].get("role") != "user":
        start += 1
    if start >= len(history):
        start = len(history) - window
    return history[start:], True


def modules_newer_than_state(
    agents: list[dict], output_dir: Path, state_path: Path | None
) -> list[dict]:
    """Modules whose output file changed after project_state.md was last saved."""
    if state_path is None or not state_path.exists():
        return []
    state_mtime = state_path.stat().st_mtime
    fresh = []
    for agent in agents:
        path = output_dir / agent["output"]
        if path.exists() and path.stat().st_mtime > state_mtime:
            fresh.append(agent)
    return fresh


def build_module_snapshot(
    agents: list[dict], output_dir: Path, fresh: list[dict] | None = None
) -> str:
    """Compact module index; full text only for modules newer than the state file."""
    fresh_ids = {a.get("id") for a in (fresh or [])}
    lines = ["Completed module files (see PROJECT STATE for takeaways):", ""]
    any_done = False
    fresh_blocks: list[str] = []
    for agent in agents:
        path = output_dir / agent["output"]
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        any_done = True
        marker = "  (UPDATED after PROJECT STATE — full text below)" if agent.get("id") in fresh_ids else ""
        lines.append(f"- {agent.get('id')} → modules/{agent['output']}{marker}")
        if agent.get("id") in fresh_ids:
            fresh_blocks.append(f"### {agent.get('name', agent.get('id'))} (not yet reflected in PROJECT STATE)\n\n{text}")
    if not any_done:
        return "(no completed modules yet)"
    lines.extend(
        [
            "",
            "Use PROJECT STATE for module status. Do not invent outputs for modules not listed.",
        ]
    )
    if fresh_blocks:
        lines.extend(["", *fresh_blocks])
        lines.append(
            "\nRemind the designer to fold the updated module(s) into project_state.md."
        )
    return "\n".join(lines)


def prepare_conductor_context(
    config: dict,
    agents: list[dict],
    output_dir: Path,
    previous_blocks: list[str],
    history: list[dict],
    project_state: str | None,
    *,
    state_path: Path | None = None,
) -> tuple[str | None, str, list[dict], bool]:
    """
    Build Conductor context blocks.

    Returns: (project_state text or None, module context, history slice, truncated?)
    """
    settings = get_conductor_context_settings(config)
    sliced_history, truncated = slice_history(history, settings["history_window"])

    state_text = project_state.strip() if project_state else None
    prefer_state = settings["prefer_state_over_modules"]

    if state_text and prefer_state:
        fresh = modules_newer_than_state(agents, output_dir, state_path)
        module_context = build_module_snapshot(agents, output_dir, fresh)
    else:
        module_context = "\n\n".join(previous_blocks) if previous_blocks else "(none yet)"

    return state_text, module_context, sliced_history, truncated
