"""LLM providers (OpenRouter, OpenAI, ChatGPT plan, Ollama, mock) behind one `chat()` call."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
CHATGPT_RESPONSES_URL = "https://api.openai.com/v1/responses"
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


class ToolsUnsupported(LLMError):
    """The provider or model refused function tools; the caller asks again without them."""


# Function tools are given as [{"name", "description", "parameters": <JSON schema>}].
# Providers that can call them have chat_tools(model, messages, tools, temperature,
# max_tokens) -> (text, calls, usage), with calls as [{"name", "arguments": dict}].


def _function_tools(tools: list[dict]) -> list[dict]:
    """Chat Completions shape (OpenRouter, Ollama)."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in tools
    ]


def _tool_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _function_calls(message: dict) -> list[dict]:
    """tool_calls of a Chat Completions (or Ollama) message → [{name, arguments}]."""
    calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict) and function.get("name"):
            calls.append(
                {"name": str(function["name"]), "arguments": _tool_arguments(function.get("arguments"))}
            )
    return calls


def _refuses_tools(status: int, text: str) -> bool:
    # OpenRouter answers 404 "No endpoints found that support tool use"; Ollama answers 400
    # "... does not support tools". Other 400s (too long, bad input) are not refusals.
    return status in {400, 404} and "tool" in text.lower()


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, api_key: str):
        if not api_key:
            raise LLMError("OpenRouter API key is missing. Enter it on the settings screen.")
        self.api_key = api_key

    def _post(self, body: dict[str, Any], *, tools: bool = False) -> tuple[dict, dict]:
        """One request → (first choice's message, usage)."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=120)
        except requests.Timeout as exc:
            raise _retryable(f"OpenRouter timeout: {exc}") from exc
        except requests.RequestException as exc:
            raise _retryable(f"OpenRouter request failed: {exc}") from exc

        if response.status_code != 200:
            message = f"OpenRouter error ({response.status_code}): {response.text[:300]}"
            if response.status_code in RETRY_STATUS:
                raise _retryable(message)
            if tools and _refuses_tools(response.status_code, response.text):
                raise ToolsUnsupported(message)
            raise LLMError(message)
        try:
            data = response.json()
            choice = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected OpenRouter response: {exc}") from exc
        if not isinstance(choice, dict):
            raise LLMError("Unexpected OpenRouter response: no message")
        return choice, data.get("usage") or {}

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        **_: Any,
    ) -> tuple[str, dict]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        def send():
            message, usage = self._post(body)
            content = message.get("content")
            if not content or not str(content).strip():
                raise _retryable("Empty LLM response")
            return str(content).strip(), usage

        return _with_retries(send)

    def chat_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict],
        temperature: float,
        max_tokens: int,
        **_: Any,
    ) -> tuple[str, list[dict], dict]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": _function_tools(tools),
        }

        def send():
            message, usage = self._post(body, tools=True)
            text = str(message.get("content") or "").strip()
            calls = _function_calls(message)
            if not text and not calls:
                raise _retryable("Empty LLM response")
            return text, calls, usage

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


def _sse_events(response) -> Any:
    """Parsed `data:` events of a server-sent event stream."""
    # Read bytes and decode here: the plan route sends no Content-Type charset, and then
    # iter_lines(decode_unicode=True) hands back bytes anyway.
    for raw in response.iter_lines():
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def _chatgpt_error(status: int, body: Any) -> LLMError:
    """An error from the ChatGPT plan route. Plan limits and eligibility are not retried."""
    body = body if isinstance(body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = str(error.get("code") or "")
    # Admission failures can come back as {"detail": "..."} with no error object.
    detail = str(error.get("message") or body.get("detail") or "")
    if code == "subscription_sharing_usage_limit_exceeded":
        return LLMError(
            "The ChatGPT plan's usage limit for Sida was reached. "
            "Check ChatGPT Settings → Usage, or switch the Conductor back to OpenRouter."
        )
    if code == "subscription_sharing_user_not_eligible":
        return LLMError("This ChatGPT account cannot use its plan in other apps (Go, Plus or Pro).")
    if code == "subscription_sharing_invalid_user":
        return LLMError("ChatGPT did not accept this sign-in. Sign in again on the settings screen.")
    message = f"ChatGPT error ({status}{', ' + code if code else ''}): {detail[:300]}"
    if code in {"subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable"}:
        return _retryable(message)
    if not code and status in {502, 503, 504}:
        return _retryable(message)
    return LLMError(message)


class ChatGPTProvider:
    """
    The signed-in user's ChatGPT plan (Sign in with ChatGPT, sida/chatgpt_auth.py) through
    the Responses API. This route takes no temperature or output cap and rejects system
    messages: system text goes in `instructions`, and every request streams with store off.
    """

    name = "chatgpt"

    def __init__(self, token):
        self.token = token  # () -> access token; refreshes as needed, raises LLMError

    @staticmethod
    def request_body(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        system = [m for m in _plain_messages(messages) if m["role"] == "system"]
        turns = [m for m in _plain_messages(messages) if m["role"] != "system" and m["content"]]
        body: dict[str, Any] = {
            "model": model,
            "input": [{"role": m["role"], "content": m["content"]} for m in turns],
            "store": False,
            "stream": True,
        }
        instructions = "\n\n".join(m["content"] for m in system if m["content"].strip())
        if instructions:
            body["instructions"] = instructions
        return body

    def _stream(self, body: dict[str, Any], *, tools: bool = False) -> tuple[str, list[dict], dict]:
        """One streamed request → (text, function calls, usage)."""
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                CHATGPT_RESPONSES_URL, headers=headers, json=body, stream=True, timeout=180
            )
        except requests.Timeout as exc:
            raise _retryable(f"ChatGPT timeout: {exc}") from exc
        except requests.RequestException as exc:
            raise _retryable(f"ChatGPT request failed: {exc}") from exc
        with response:
            if response.status_code != 200:
                try:
                    data = response.json()
                except ValueError:
                    data = {"detail": response.text[:300]}
                error = _chatgpt_error(response.status_code, data)
                if tools and _refuses_tools(response.status_code, str(error)):
                    raise ToolsUnsupported(str(error))
                raise error
            parts: list[str] = []
            calls: list[dict] = []
            for event in _sse_events(response):
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    parts.append(str(event.get("delta") or ""))
                elif kind == "response.output_item.done":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call" and item.get("name"):
                        calls.append(
                            {"name": str(item["name"]), "arguments": _tool_arguments(item.get("arguments"))}
                        )
                elif kind == "response.completed":
                    usage = (event.get("response") or {}).get("usage") or {}
                    return "".join(parts).strip(), calls, {
                        "prompt_tokens": usage.get("input_tokens"),
                        "completion_tokens": usage.get("output_tokens"),
                    }
                elif kind == "response.failed":
                    raise _chatgpt_error(200, event.get("response") or {})
                elif kind == "error":
                    raise _chatgpt_error(200, {"error": event})
                elif kind == "response.incomplete":
                    details = (event.get("response") or {}).get("incomplete_details") or {}
                    raise LLMError(
                        f"ChatGPT reply was cut off ({details.get('reason') or 'incomplete'})"
                    )
        raise _retryable("ChatGPT stream ended before the reply was complete")

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        **_: Any,
    ) -> tuple[str, dict]:
        body = self.request_body(model, messages)

        def send():
            text, _calls, usage = self._stream(body)
            if not text:
                raise _retryable("Empty LLM response")
            return text, usage

        return _with_retries(send)

    def chat_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict],
        temperature: float,
        max_tokens: int,
        **_: Any,
    ) -> tuple[str, list[dict], dict]:
        body = self.request_body(model, messages)
        body["tools"] = [
            {
                "type": "function",
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in tools
        ]

        def send():
            text, calls, usage = self._stream(body, tools=True)
            if not text and not calls:
                raise _retryable("Empty LLM response")
            return text, calls, usage

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

    def _body(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        *,
        json_mode: bool = False,
        think: bool | None = None,
    ) -> dict[str, Any]:
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
        return body

    def _post(self, body: dict[str, Any], *, tools: bool = False) -> dict:
        model = body["model"]
        try:
            response = requests.post(f"{self.base_url}/api/chat", json=body, timeout=300)
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
            raise LLMError(f"Ollama model '{model}' not found. Run: ollama pull {model}")
        if response.status_code != 200:
            message = f"Ollama error ({response.status_code}): {response.text[:300]}"
            if response.status_code in RETRY_STATUS:
                raise _retryable(message)
            if tools and _refuses_tools(response.status_code, response.text):
                raise ToolsUnsupported(message)  # e.g. "... does not support tools"
            raise LLMError(message)
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(f"Unexpected Ollama response: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError("Unexpected Ollama response: not an object")
        return data

    @staticmethod
    def _usage(data: dict) -> dict:
        return {
            "prompt_tokens": data.get("prompt_eval_count"),
            "completion_tokens": data.get("eval_count"),
        }

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
        body = self._body(
            model, messages, temperature, max_tokens, json_mode=json_mode, think=think
        )

        def send():
            data = self._post(body)
            msg = data.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if not content or not str(content).strip():
                thinking = str(msg.get("thinking") or msg.get("reasoning") or "") if isinstance(msg, dict) else ""
                reason = data.get("done_reason") or ""
                if thinking.strip():
                    raise _retryable(
                        "Empty LLM response (model spent the token budget on thinking; "
                        f"done_reason={reason or 'unknown'}). "
                        "Sida disables think by default — retry, or raise max_tokens."
                    )
                raise _retryable("Empty LLM response")
            return str(content).strip(), self._usage(data)

        # If think was on and we still get an empty answer, one silent retry with think off.
        try:
            return _with_retries(send)
        except LLMError as exc:
            if body.get("think") is True and "thinking" in str(exc).lower():
                body["think"] = False
                return _with_retries(send)
            raise

    def chat_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict],
        temperature: float,
        max_tokens: int,
        **_: Any,
    ) -> tuple[str, list[dict], dict]:
        body = self._body(model, messages, temperature, max_tokens)
        body["tools"] = _function_tools(tools)

        def send():
            data = self._post(body, tools=True)
            msg = data.get("message") or {}
            msg = msg if isinstance(msg, dict) else {}
            text = str(msg.get("content") or "").strip()
            calls = _function_calls(msg)
            if not text and not calls:
                raise _retryable("Empty LLM response")
            return text, calls, self._usage(data)

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
    if kind == "chatgpt":
        from sida import chatgpt_auth  # imports this module

        return ChatGPTProvider(chatgpt_auth.access_token)
    if kind == "mock":
        return MockProvider()
    raise LLMError(
        f"Unknown provider '{kind}'. Use openrouter | openai | chatgpt | ollama | mock."
    )


def provider_chat(provider, model, messages, temperature, max_tokens, **kw):
    """Call provider.chat with a busy spinner (TTY only).

    With `tools=[...]` it calls provider.chat_tools instead and returns (text, calls, usage).
    """
    from sida.console import ROLE_COLOR, busy_line
    from sida.i18n import t

    role = str(kw.get("role") or "model")
    status = kw.pop("status", None)
    color = kw.pop("color", None)
    tools = kw.pop("tools", None)
    if status is None:
        status = t("busy_role", role=role)
    if color is None:
        color = ROLE_COLOR.get(role)
    with busy_line(status, color=color):
        if tools is not None:
            return provider.chat_tools(model, messages, tools, temperature, max_tokens, **kw)
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
