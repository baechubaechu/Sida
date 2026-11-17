"""LLM providers (OpenRouter, OpenAI, Anthropic, ChatGPT plan, Ollama, mock) behind one `chat()` call."""

from __future__ import annotations

import base64
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


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------
# A message's content list may hold pictures beside its text, in one shape (image_part) that
# every provider turns into its own. Only a user's message carries them. A provider says
# whether a model can look at one (sees_images); a model that refuses one raises
# ImagesUnsupported, and the caller sends the message again without it and says so. A picture
# is never dropped silently: an answer about a view the model did not see would mislead.


class ImagesUnsupported(LLMError):
    """This model takes no pictures; the caller sends the text alone and tells the user."""


# (provider name, model) pairs that refused a picture in this process.
_NO_IMAGES: set[tuple[str, str]] = set()


def image_part(data: bytes, media_type: str = "image/png") -> dict[str, str]:
    """A picture for a message's content list."""
    return {"type": "image", "media_type": media_type, "data": base64.b64encode(data).decode("ascii")}


def _is_image(part: Any) -> bool:
    return isinstance(part, dict) and part.get("type") == "image" and bool(part.get("data"))


def _images(message: dict[str, Any]) -> list[dict]:
    """The pictures a message carries (a user's message only)."""
    content = message.get("content")
    if str(message.get("role", "user")) != "user" or not isinstance(content, list):
        return []
    return [part for part in content if _is_image(part)]


def has_images(messages: list[dict[str, Any]]) -> bool:
    return any(_images(m) for m in messages)


def without_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same messages with their pictures taken out."""
    return [
        {**m, "content": [part for part in m["content"] if not _is_image(part)]} if isinstance(m.get("content"), list) else m
        for m in messages
    ]


def _data_url(part: dict) -> str:
    return f"data:{part.get('media_type') or 'image/png'};base64,{part['data']}"


def _chat_messages(messages: list[dict[str, Any]], *, flat: bool) -> list[dict[str, Any]]:
    """
    Messages for a chat-completions API with pictures as `image_url` parts. `flat` gives plain
    strings wherever there is no picture (OpenAI, which takes no cache markers); otherwise text
    parts stay as they are (OpenRouter).
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        pictures = _images(m)
        urls = [{"type": "image_url", "image_url": {"url": _data_url(p)}} for p in pictures]
        if flat:
            text = _flatten_content(m.get("content"))
            content: Any = ([{"type": "text", "text": text}] if text else []) + urls if pictures else text
            out.append({"role": str(m.get("role", "user")), "content": content})
        elif isinstance(m.get("content"), list):
            kept = [part for part in m["content"] if not _is_image(part)]
            out.append({**m, "content": kept + urls} if len(kept) != len(m["content"]) else m)
        else:
            out.append(m)
    return out


def _refuses_images(status: int, text: str) -> bool:
    low = text.lower()
    return status in {400, 404, 415, 422} and "image" in low and any(w in low for w in ("support", "vision", "modal"))


def sees_images(provider, model: str) -> bool:
    """Whether a picture may go to this model: its provider says so and it refused none in this process."""
    if (str(getattr(provider, "name", "")), model) in _NO_IMAGES:
        return False
    check = getattr(provider, "sees_images", None)
    return bool(check(model)) if callable(check) else False


def images_refused(provider, model: str) -> None:
    """Remember that this model refused a picture, so none is sent to it again."""
    _NO_IMAGES.add((str(getattr(provider, "name", "")), model))


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

    @staticmethod
    def sees_images(model: str) -> bool:
        return True  # most models here do; one that does not refuses (ImagesUnsupported)

    def _post(self, body: dict[str, Any], *, tools: bool = False) -> tuple[dict, dict]:
        """One request → (first choice's message, usage)."""
        images = has_images(body["messages"])
        body = {**body, "messages": _chat_messages(body["messages"], flat=False)}
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
            if images and _refuses_images(response.status_code, response.text):
                raise ImagesUnsupported(message)
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
    """Official OpenAI Chat Completions API."""

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

    @staticmethod
    def sees_images(model: str) -> bool:
        return True  # a model that does not refuses (ImagesUnsupported)

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
        images = has_images(messages)
        body: dict[str, Any] = {
            "model": model,
            "messages": _chat_messages(messages, flat=True),
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
                message = f"OpenAI error ({response.status_code}): {response.text[:300]}"
                if images and _refuses_images(response.status_code, response.text):
                    raise ImagesUnsupported(message)
                raise LLMError(message)
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
    if not detail and body:  # an unexpected shape: show it rather than an empty reason
        detail = json.dumps(body, ensure_ascii=False)
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
    def sees_images(model: str) -> bool:
        return True  # the plan's models take pictures (checked 2026-11-17); one that does not refuses

    @staticmethod
    def request_body(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        system: list[str] = []
        turns: list[dict[str, Any]] = []
        for m in messages:
            role = str(m.get("role", "user"))
            text = _flatten_content(m.get("content"))
            if role == "system":
                system.append(text)
                continue
            pictures = _images(m)
            if pictures:
                parts: list[dict[str, Any]] = [{"type": "input_text", "text": text}] if text else []
                parts += [{"type": "input_image", "image_url": _data_url(p)} for p in pictures]
                turns.append({"role": role, "content": parts})
            elif text:
                turns.append({"role": role, "content": text})
        body: dict[str, Any] = {
            "model": model,
            "input": turns,
            "store": False,
            "stream": True,
        }
        instructions = "\n\n".join(text for text in system if text.strip())
        if instructions:
            body["instructions"] = instructions
        return body

    def _stream(self, body: dict[str, Any], *, tools: bool = False) -> tuple[str, list[dict], dict]:
        """One streamed request → (text, function calls, usage)."""
        images = any(isinstance(turn.get("content"), list) for turn in body.get("input") or [])
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
                if images and _refuses_images(response.status_code, str(error)):
                    raise ImagesUnsupported(str(error))
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
                elif kind in {"response.failed", "error"}:
                    if kind == "response.failed":
                        body = event.get("response") or {}
                    else:  # {"type": "error", "message"...} or {"type": "error", "error": {...}}
                        body = event if isinstance(event.get("error"), dict) else {"error": event}
                    error = _chatgpt_error(200, body)
                    if tools and _refuses_tools(400, str(error)):
                        raise ToolsUnsupported(str(error))
                    if images and _refuses_images(400, str(error)):
                        raise ImagesUnsupported(str(error))
                    raise error
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
        self._vision: dict[str, bool] = {}  # model → whether its card says it sees pictures

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
        turns = []
        for m, plain in zip(messages, _plain_messages(messages), strict=True):
            pictures = _images(m)
            turns.append({**plain, "images": [p["data"] for p in pictures]} if pictures else plain)
        body: dict[str, Any] = {
            "model": model,
            "messages": turns,
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

    def sees_images(self, model: str) -> bool:
        """Ollama gives a model that cannot see a picture no error, so the model's card is asked (`capabilities`)."""
        if model not in self._vision:
            try:
                response = requests.post(f"{self.base_url}/api/show", json={"model": model}, timeout=10)
                able = response.json().get("capabilities") if response.status_code == 200 else None
            except (requests.RequestException, ValueError, AttributeError):
                able = None
            self._vision[model] = isinstance(able, list) and "vision" in able
        return self._vision[model]

    def _post(self, body: dict[str, Any], *, tools: bool = False) -> dict:
        model = body["model"]
        images = any(turn.get("images") for turn in body.get("messages") or [])
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
            if images and _refuses_images(response.status_code, response.text):
                raise ImagesUnsupported(message)
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


# ---------------------------------------------------------------------------
# Anthropic (Claude API, the user's own API key)
# ---------------------------------------------------------------------------
# Billed by use on the key's account. The Claude plans (Pro, Max) are not used here: Anthropic's
# terms do not allow third-party apps to sign in with them.

# Models whose declined requests the API re-runs on the model Anthropic picks for that kind of
# refusal (server-side fallback), inside the same call.
ANTHROPIC_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"}
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Thinking is always on in the current models and counts against max_tokens, so the role's own
# limit (1,400-2,500, sized for a reply alone) would cut it: this is the least a request asks for.
ANTHROPIC_MIN_TOKENS = 16000
ANTHROPIC_CACHE_MARKERS = 4  # the API takes at most this many cache_control markers a request


def _anthropic_parts(content: Any, *, role: str) -> list[dict]:
    """A message's content → Messages API blocks (text keeps its cache marker; a user's pictures go as base64)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else []
    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}] if content is not None and str(content).strip() else []
    out: list[dict] = []
    for part in content:
        if isinstance(part, str):
            if part.strip():
                out.append({"type": "text", "text": part})
        elif _is_image(part):
            if role == "user":
                out.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": part.get("media_type") or "image/png", "data": part["data"]},
                })
        elif isinstance(part, dict) and part.get("type") == "text" and str(part.get("text", "")).strip():
            block = {"type": "text", "text": str(part["text"])}
            if part.get("cache_control"):
                block["cache_control"] = dict(part["cache_control"])
            out.append(block)
    return out


def _anthropic_request(messages: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """
    Sida's messages → (system blocks, messages) for the Messages API. The leading system messages
    become `system`; a later one goes in as the user's text (the API has no system turn there).
    Turns of the same role next to each other are joined, and cache markers past the API's limit
    are dropped from the end.
    """
    system: list[dict] = []
    turns: list[dict] = []
    for m in messages:
        role = str(m.get("role", "user"))
        if role == "system" and not turns:
            system.extend(_anthropic_parts(m.get("content"), role="system"))
            continue
        role = "assistant" if role == "assistant" else "user"
        parts = _anthropic_parts(m.get("content"), role=role)
        if not parts:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(parts)
        else:
            turns.append({"role": role, "content": parts})
    seen = 0
    for block in [*system, *(b for t in turns for b in t["content"])]:
        if "cache_control" in block:
            seen += 1
            if seen > ANTHROPIC_CACHE_MARKERS:
                del block["cache_control"]
    return system, turns


def _anthropic_usage(usage: Any) -> dict:
    """The Messages API's usage → the chat-completions shape format_usage reads."""
    if usage is None:
        return {}
    fresh = int(getattr(usage, "input_tokens", 0) or 0)
    read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    return {
        "prompt_tokens": fresh + read + written,
        "completion_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "prompt_tokens_details": {"cached_tokens": read},
    }


class AnthropicProvider:
    """Claude through the Messages API with the official SDK (`anthropic`), streamed."""

    name = "anthropic"

    def __init__(self, api_key: str):
        if not api_key:
            raise LLMError("Anthropic API key is missing. Enter it on the settings screen.")
        try:
            import anthropic
        except ImportError as exc:  # an install from before the dependency was added
            raise LLMError("The anthropic package is missing. Run: pip install -e .") from exc
        self._sdk = anthropic
        # Retries are ours (_with_retries), as for the other providers.
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=600)

    @staticmethod
    def sees_images(model: str) -> bool:
        return True  # every current Claude model reads pictures

    def _send(self, model: str, messages: list[dict[str, Any]], max_tokens: int, tools: list[dict] | None = None):
        """One streamed request → the final message. Raises LLMError (retryable where it helps)."""
        sdk = self._sdk
        system, turns = _anthropic_request(messages)
        if not turns:
            raise LLMError("Nothing to send: no user message")
        # No temperature: the current models take only their default sampling.
        request: dict[str, Any] = {"model": model, "max_tokens": max(int(max_tokens or 0), ANTHROPIC_MIN_TOKENS), "messages": turns}
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools
            ]
        if model in ANTHROPIC_FALLBACK_MODELS:
            request["betas"] = [ANTHROPIC_FALLBACK_BETA]
            request["fallbacks"] = "default"
        try:
            with self._client.beta.messages.stream(**request) as stream:
                message = stream.get_final_message()
        except sdk.AuthenticationError as exc:
            raise LLMError("Anthropic refused the API key (401). Check it on the settings screen.") from exc
        except sdk.APIStatusError as exc:
            status = int(getattr(exc, "status_code", 0) or 0)
            text = str(getattr(exc, "message", "") or exc)
            msg = f"Anthropic error ({status}): {text[:300]}"
            if status in RETRY_STATUS or status >= 500:
                raise _retryable(msg) from exc
            if tools and _refuses_tools(status, text):
                raise ToolsUnsupported(msg) from exc
            if has_images(messages) and _refuses_images(status, text):
                raise ImagesUnsupported(msg) from exc
            raise LLMError(msg) from exc
        except sdk.APIConnectionError as exc:  # also the timeout
            raise _retryable(f"Anthropic request failed: {exc}") from exc
        if getattr(message, "stop_reason", None) == "refusal":
            raise LLMError("Claude declined this request (refusal).")
        return message

    @staticmethod
    def _reply(message) -> tuple[str, list[dict]]:
        texts: list[str] = []
        calls: list[dict] = []
        for block in getattr(message, "content", None) or []:
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(str(getattr(block, "text", "") or ""))
            elif kind == "tool_use" and getattr(block, "name", None):
                calls.append({"name": str(block.name), "arguments": _tool_arguments(getattr(block, "input", None))})
        return "".join(texts).strip(), calls

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        **_: Any,
    ) -> tuple[str, dict]:
        def send():
            message = self._send(model, messages, max_tokens)
            text, _calls = self._reply(message)
            if not text:
                if getattr(message, "stop_reason", None) == "max_tokens":
                    raise LLMError("Claude used up max_tokens before replying.")
                raise _retryable("Empty LLM response")
            return text, _anthropic_usage(getattr(message, "usage", None))

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
        def send():
            message = self._send(model, messages, max_tokens, tools=tools)
            text, calls = self._reply(message)
            if not text and not calls:
                if getattr(message, "stop_reason", None) == "max_tokens":
                    raise LLMError("Claude used up max_tokens before replying.")
                raise _retryable("Empty LLM response")
            return text, calls, _anthropic_usage(getattr(message, "usage", None))

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
    if kind == "anthropic":
        return AnthropicProvider(api_key)
    if kind == "chatgpt":
        from sida import chatgpt_auth  # imports this module

        return ChatGPTProvider(chatgpt_auth.access_token)
    if kind == "mock":
        return MockProvider()
    raise LLMError(
        f"Unknown provider '{kind}'. Use openrouter | openai | anthropic | chatgpt | ollama | mock."
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
