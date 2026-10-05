"""LLM providers (OpenRouter, OpenAI, Ollama, mock) behind one `chat()` call, with retries."""

from __future__ import annotations

import re
import time
from typing import Any

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """Recoverable LLM/provider failure. Callers decide whether to exit."""


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


def gpt_major_version(model: str) -> int | None:
    """Return GPT major version from a model id (gpt-6-astra → 6), else None."""
    m = re.search(r"(?:^|/)gpt-(\d+)\b", str(model or "").lower())
    return int(m.group(1)) if m else None


class OpenAIProvider:
    """Official OpenAI Chat Completions API (used by Rhino modeling mode)."""

    name = "openai"

    def __init__(self, api_key: str, *, base_url: str | None = None):
        if not api_key:
            raise LLMError("OpenAI API key is missing. Set OPENAI_API_KEY or enter it in the hub.")
        self.api_key = api_key
        self.base_url = (base_url or OPENAI_URL).rstrip("/")
        if self.base_url.endswith("/chat/completions"):
            pass
        elif self.base_url.endswith("/v1"):
            self.base_url = self.base_url + "/chat/completions"
        else:
            self.base_url = self.base_url.rstrip("/") + "/chat/completions"

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
            "messages": _plain_messages(messages),
            "max_completion_tokens": int(max_tokens),
        }
        # GPT-6+ rejects custom temperature / top_p.
        major = gpt_major_version(model)
        if major is not None and major < 6:
            body["temperature"] = float(temperature)

        def send():
            try:
                response = requests.post(self.base_url, headers=headers, json=body, timeout=180)
            except requests.Timeout as exc:
                raise _retryable(f"OpenAI timeout: {exc}") from exc
            except requests.RequestException as exc:
                raise _retryable(f"OpenAI request failed: {exc}") from exc

            if response.status_code in RETRY_STATUS:
                raise _retryable(
                    f"OpenAI error ({response.status_code}): {response.text[:300]}"
                )
            if response.status_code != 200:
                raise LLMError(
                    f"OpenAI error ({response.status_code}): {response.text[:300]}"
                )
            try:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"Unexpected OpenAI response: {exc}") from exc
            if content is None or not str(content).strip():
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
        *,
        think: bool | None = False,
    ):
        url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
        if url.endswith("/v1"):
            url = url[: -len("/v1")]
        self.base_url = url
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        # Qwen3+ etc. may fill num_predict with chain-of-thought and leave content empty.
        # Default False so visible answers fit in the token budget.
        self.think = think

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        *,
        json_mode: bool = False,
        think: bool | None = None,
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
        use_think = self.think if think is None else think
        if use_think is not None:
            body["think"] = bool(use_think)

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
                msg = data.get("message") or {}
                content = msg.get("content")
            except (ValueError, KeyError, TypeError) as exc:
                raise LLMError(f"Unexpected Ollama response: {exc}") from exc
            if not content or not str(content).strip():
                thinking = str(msg.get("thinking") or msg.get("reasoning") or "")
                reason = data.get("done_reason") or ""
                if thinking.strip():
                    raise _retryable(
                        "Empty LLM response (model spent the token budget on thinking; "
                        f"done_reason={reason or 'unknown'}). "
                        "Sida disables think by default — retry, or raise max_tokens."
                    )
                raise _retryable("Empty LLM response")
            usage = {
                "prompt_tokens": data.get("prompt_eval_count"),
                "completion_tokens": data.get("eval_count"),
            }
            return str(content).strip(), usage

        # If think was on and we still get an empty answer, one silent retry with think off.
        try:
            return _with_retries(send)
        except LLMError as exc:
            if use_think is True and "thinking" in str(exc).lower():
                body["think"] = False
                return _with_retries(send)
            raise


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
            from sida.worker import expected_headers  # worker.py imports this module

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
    think: bool | None = False,
):
    kind = (kind or "openrouter").lower()
    if kind == "openrouter":
        return OpenRouterProvider(api_key)
    if kind in {"openai", "openai_api"}:
        return OpenAIProvider(api_key, base_url=base_url)
    if kind in {"ollama", "local"}:
        return OllamaProvider(
            base_url=base_url, num_ctx=num_ctx, keep_alive=keep_alive, think=think
        )
    if kind == "mock":
        return MockProvider()
    raise LLMError(f"Unknown provider '{kind}'. Use openrouter | openai | ollama | mock.")


def provider_chat(provider, model, messages, temperature, max_tokens, **kw):
    """Call provider.chat with a busy spinner (TTY only)."""
    from sida.console import ROLE_COLOR, busy_line
    from sida.i18n import t

    role = str(kw.get("role") or "model")
    status = kw.pop("status", None)
    color = kw.pop("color", None)
    if status is None:
        status = t("busy_role", role=role)
    if color is None:
        color = ROLE_COLOR.get(role)
    with busy_line(status, color=color):
        return provider.chat(model, messages, temperature, max_tokens, **kw)


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
