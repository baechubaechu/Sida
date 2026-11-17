"""LLM providers: construction, retries, the mock provider."""

from __future__ import annotations

import json
import time

import pytest

from sida import providers, worker
from sida.providers import (
    ChatGPTProvider,
    LLMError,
    MockProvider,
    _flatten_content,
    _plain_messages,
    _retryable,
    _with_retries,
    make_provider,
)
from sida.worker import expected_headers, missing_headers
from tests.conftest import ROOT


def test_make_provider_kinds():
    assert make_provider("openrouter", api_key="k").name == "openrouter"
    assert make_provider("mock").name == "mock"
    assert make_provider("chatgpt").name == "chatgpt"  # no key: the sign-in is checked per call


def test_make_provider_errors():
    with pytest.raises(LLMError):
        make_provider("openrouter", api_key="")
    with pytest.raises(LLMError):
        make_provider("nope")


def test_flatten_content_and_plain_messages():
    flat = _flatten_content([{"type": "text", "text": "a", "cache_control": {}}, {"type": "text", "text": "b"}])
    assert flat == "a\n\nb"
    assert _plain_messages([{"role": "system", "content": [{"type": "text", "text": "s"}]}]) == [
        {"role": "system", "content": "s"}
    ]


def test_retry_then_success(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _retryable("boom")
        return "ok"

    assert _with_retries(flaky) == "ok"
    assert calls["n"] == 3


def test_non_retryable_raises_immediately(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def hard():
        calls["n"] += 1
        raise LLMError("fatal")

    with pytest.raises(LLMError):
        _with_retries(hard)
    assert calls["n"] == 1


def test_mock_worker_matches_output_format():
    prompt = (ROOT / "agents" / "41_spatial_reviewer.md").read_text(encoding="utf-8")
    full = worker.build_worker_prompt(prompt, "## Site\nbrief has headers too", "(none yet)")
    out, _ = MockProvider().chat("m", [{"role": "user", "content": full}], 0, 10, role="worker")
    assert missing_headers(out, expected_headers(prompt)) == []


# ---------------------------------------------------------------------------
# ChatGPT plan (Responses API, streamed)
# ---------------------------------------------------------------------------


class FakeStream:
    def __init__(self, events=(), status=200, body=None):
        self.status_code = status
        self.lines = [f"data: {json.dumps(e)}" for e in events]
        self.body = body or {}
        self.text = json.dumps(self.body)

    def iter_lines(self, decode_unicode=False):
        # The real route sends no charset, so requests yields bytes even with decode_unicode.
        for line in self.lines:
            yield line.encode("utf-8")

    def json(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def chatgpt_post(monkeypatch, *replies):
    calls = []
    queue = list(replies)

    def post(url, headers=None, json=None, stream=False, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "stream": stream})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(providers.requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    return calls


def test_chatgpt_request_moves_system_text_to_instructions():
    body = ChatGPTProvider.request_body(
        "gpt-6.1-sol",
        [
            {"role": "system", "content": [{"type": "text", "text": "Be the Conductor.", "cache_control": {}}]},
            {"role": "user", "content": [{"type": "text", "text": "PROJECT BRIEF:\n\nx"}]},
            {"role": "assistant", "content": "earlier reply"},
            {"role": "user", "content": "next"},
        ],
    )
    assert body == {
        "model": "gpt-6.1-sol",
        "instructions": "Be the Conductor.",
        "input": [
            {"role": "user", "content": "PROJECT BRIEF:\n\nx"},
            {"role": "assistant", "content": "earlier reply"},
            {"role": "user", "content": "next"},
        ],
        "store": False,
        "stream": True,
    }
    # The plan route rejects these, so they are never sent.
    assert not {"temperature", "max_output_tokens", "top_p"} & set(body)


def test_chatgpt_reads_the_stream_until_completed(monkeypatch):
    calls = chatgpt_post(
        monkeypatch,
        FakeStream([
            {"type": "response.created"},
            {"type": "response.output_text.delta", "delta": "안녕, "},
            {"type": "response.output_text.delta", "delta": "world!"},
            {"type": "response.completed", "response": {"usage": {"input_tokens": 12, "output_tokens": 3}}},
        ]),
    )
    p = ChatGPTProvider(lambda: "at-1")
    text, usage = p.chat("gpt-6.1-sol", [{"role": "user", "content": "hi"}], 0.4, 700)
    assert text == "안녕, world!"
    assert usage == {"prompt_tokens": 12, "completion_tokens": 3}
    assert calls[0]["url"] == "https://api.openai.com/v1/responses"
    assert calls[0]["headers"]["Authorization"] == "Bearer at-1" and calls[0]["stream"] is True


def test_chatgpt_stream_without_completed_is_not_a_reply(monkeypatch):
    chatgpt_post(monkeypatch, FakeStream([{"type": "response.output_text.delta", "delta": "Hal"}]))
    with pytest.raises(LLMError, match="ended before"):
        ChatGPTProvider(lambda: "t").chat("m", [{"role": "user", "content": "hi"}], 0, 1)


def test_chatgpt_usage_limit_stops_without_retrying(monkeypatch):
    calls = chatgpt_post(
        monkeypatch,
        FakeStream([
            {"type": "response.output_text.delta", "delta": "par"},
            {"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}},
        ]),
    )
    with pytest.raises(LLMError, match="usage limit"):
        ChatGPTProvider(lambda: "t").chat("m", [{"role": "user", "content": "hi"}], 0, 1)
    assert len(calls) == 1


def test_chatgpt_http_errors(monkeypatch):
    chatgpt_post(
        monkeypatch,
        FakeStream(status=403, body={"error": {"code": "subscription_sharing_user_not_eligible"}}),
    )
    with pytest.raises(LLMError, match="Go, Plus or Pro"):
        ChatGPTProvider(lambda: "t").chat("m", [{"role": "user", "content": "hi"}], 0, 1)
    # A temporary outage is retried; admission errors may carry only {"detail": ...}.
    calls = chatgpt_post(
        monkeypatch,
        FakeStream(status=503, body={"detail": "direct routing unavailable"}),
        FakeStream([
            {"type": "response.output_text.delta", "delta": "ok"},
            {"type": "response.completed", "response": {}},
        ]),
    )
    assert ChatGPTProvider(lambda: "t").chat("m", [{"role": "user", "content": "hi"}], 0, 1)[0] == "ok"
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Function tools (Conductor calls experts)
# ---------------------------------------------------------------------------

TOOLS = [{"name": "run_expert", "description": "Run one expert.", "parameters": {"type": "object"}}]


class FakeJson:
    def __init__(self, data, status=200, text=""):
        self.status_code = status
        self.data = data
        self.text = text or json.dumps(data)

    def json(self):
        return self.data


def json_post(monkeypatch, response):
    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append(json)
        return response

    monkeypatch.setattr(providers.requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    return sent


def test_openrouter_sends_tools_and_reads_calls(monkeypatch):
    message = {
        "content": None,
        "tool_calls": [{"type": "function", "function": {"name": "run_expert", "arguments": '{"agent": "site_reader"}'}}],
    }
    sent = json_post(monkeypatch, FakeJson({"choices": [{"message": message}], "usage": {"prompt_tokens": 3}}))
    text, calls, usage = providers.OpenRouterProvider("k").chat_tools(
        "m", [{"role": "user", "content": "hi"}], TOOLS, 0.2, 100
    )
    assert (text, calls, usage) == ("", [{"name": "run_expert", "arguments": {"agent": "site_reader"}}], {"prompt_tokens": 3})
    assert sent[0]["tools"] == [
        {"type": "function", "function": {"name": "run_expert", "description": "Run one expert.", "parameters": {"type": "object"}}}
    ]


@pytest.mark.parametrize(
    ("make", "response"),
    [
        (lambda: providers.OpenRouterProvider("k"), FakeJson({}, status=404, text="No endpoints found that support tool use")),
    ],
)
def test_a_model_without_tools_raises_tools_unsupported(monkeypatch, make, response):
    json_post(monkeypatch, response)
    with pytest.raises(providers.ToolsUnsupported):
        make().chat_tools("m", [{"role": "user", "content": "hi"}], TOOLS, 0.2, 100)


def test_chatgpt_sends_tools_and_reads_function_call_items(monkeypatch):
    calls = chatgpt_post(
        monkeypatch,
        FakeStream([
            {"type": "response.output_text.delta", "delta": "실행합니다"},
            {"type": "response.output_item.done", "item": {"type": "message"}},
            {"type": "response.output_item.done", "item": {"type": "function_call", "name": "run_expert", "arguments": '{"agent":"site_reader"}'}},
            {"type": "response.completed", "response": {}},
        ]),
    )
    text, found, _ = ChatGPTProvider(lambda: "t").chat_tools("m", [{"role": "user", "content": "hi"}], TOOLS, 0, 1)
    assert text == "실행합니다" and found == [{"name": "run_expert", "arguments": {"agent": "site_reader"}}]
    assert calls[0]["json"]["tools"] == [
        {"type": "function", "name": "run_expert", "description": "Run one expert.", "parameters": {"type": "object"}}
    ]
    chatgpt_post(monkeypatch, FakeStream(status=400, body={"detail": "tools are not supported"}))
    with pytest.raises(providers.ToolsUnsupported):
        ChatGPTProvider(lambda: "t").chat_tools("m", [{"role": "user", "content": "hi"}], TOOLS, 0, 1)
    # Any other bad request stays an ordinary error, so tools are not switched off for it.
    chatgpt_post(monkeypatch, FakeStream(status=400, body={"detail": "input is too long"}))
    with pytest.raises(LLMError) as raised:
        ChatGPTProvider(lambda: "t").chat_tools("m", [{"role": "user", "content": "hi"}], TOOLS, 0, 1)
    assert not isinstance(raised.value, providers.ToolsUnsupported)


def test_provider_chat_uses_chat_tools_only_when_tools_are_given():
    class Both:
        def chat(self, *a, **k):
            return "text", {}

        def chat_tools(self, model, messages, tools, temperature, max_tokens, **k):
            return "tools", [], {"n": len(tools)}

    assert providers.provider_chat(Both(), "m", [], 0, 1, role="conductor") == ("text", {})
    assert providers.provider_chat(Both(), "m", [], 0, 1, role="conductor", tools=TOOLS) == ("tools", [], {"n": 1})


def test_chatgpt_stream_errors_always_carry_a_reason(monkeypatch):
    nested = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad schema"}}
    chatgpt_post(monkeypatch, FakeStream([nested]))
    with pytest.raises(LLMError, match="bad schema"):
        ChatGPTProvider(lambda: "t").chat("m", [{"role": "user", "content": "hi"}], 0, 1)
    # The plan's usage limit arrives in this nested shape too and must read as the limit.
    limit = {"type": "error", "error": {
        "type": "invalid_request_error", "code": "subscription_sharing_usage_limit_exceeded",
        "message": "The ChatGPT user has reached their Subscription Sharing usage limit.",
    }}
    calls = chatgpt_post(monkeypatch, FakeStream([limit]))
    with pytest.raises(LLMError, match="usage limit for Sida was reached"):
        ChatGPTProvider(lambda: "t").chat_tools("m", [{"role": "user", "content": "hi"}], TOOLS, 0, 1)
    assert len(calls) == 1  # not retried, and not taken for a tools refusal
    # No message at all: the event itself is shown instead of "ChatGPT error (200): ".
    chatgpt_post(monkeypatch, FakeStream([{"type": "response.failed", "response": {"status": "failed", "error": None}}]))
    with pytest.raises(LLMError, match='"status": "failed"'):
        ChatGPTProvider(lambda: "t").chat("m", [{"role": "user", "content": "hi"}], 0, 1)
    # A refusal of the tools inside the stream lets the Conductor fall back to the action block.
    refusal = {"type": "error", "message": "Tool calling is not supported for this model"}
    chatgpt_post(monkeypatch, FakeStream([refusal]))
    with pytest.raises(providers.ToolsUnsupported):
        ChatGPTProvider(lambda: "t").chat_tools("m", [{"role": "user", "content": "hi"}], TOOLS, 0, 1)


def test_chatgpt_reply_cut_off_is_an_error_not_a_short_document(monkeypatch):
    # The plan route takes no output cap, so a long expert document can end incomplete.
    calls = chatgpt_post(
        monkeypatch,
        FakeStream([
            {"type": "response.output_text.delta", "delta": "## 대지 개요\n…"},
            {"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}}},
        ]),
    )
    with pytest.raises(LLMError, match="cut off.*max_output_tokens"):
        ChatGPTProvider(lambda: "t").chat("m", [{"role": "user", "content": "hi"}], 0, 1)
    assert len(calls) == 1


# --- pictures ---------------------------------------------------------------

PICTURE = providers.image_part(b"\x89PNG-not-really")
SEEN = [
    {"role": "system", "content": [{"type": "text", "text": "Be brief."}]},
    {"role": "user", "content": [{"type": "text", "text": "What is this?", "cache_control": {"type": "ephemeral"}}, PICTURE]},
    {"role": "assistant", "content": [{"type": "text", "text": "A box."}, PICTURE]},  # only a user's message carries one
]
URL = "data:image/png;base64," + PICTURE["data"]


def test_a_picture_goes_to_each_provider_in_its_own_shape(monkeypatch):
    assert providers.has_images(SEEN) and not providers.has_images(providers.without_images(SEEN))
    assert providers.without_images(SEEN)[1]["content"] == [SEEN[1]["content"][0]]

    sent = json_post(monkeypatch, FakeJson({"choices": [{"message": {"content": "ok"}}]}))
    providers.OpenRouterProvider("key").chat("m", SEEN, 0.2, 100)
    user, assistant = sent[0]["messages"][1:]
    assert user["content"] == [SEEN[1]["content"][0], {"type": "image_url", "image_url": {"url": URL}}]  # cache marker kept
    assert assistant["content"] == [{"type": "text", "text": "A box."}]

    providers.OpenAIProvider("key").chat("gpt-6-astra", SEEN, 0.2, 100)
    assert sent[1]["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": [{"type": "text", "text": "What is this?"}, {"type": "image_url", "image_url": {"url": URL}}]},
        {"role": "assistant", "content": "A box."},
    ]

    body = providers.ChatGPTProvider.request_body("gpt-6-luna", SEEN)
    assert body["instructions"] == "Be brief." and body["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "What is this?"}, {"type": "input_image", "image_url": URL}]},
        {"role": "assistant", "content": "A box."},
    ]

    ollama = providers.OllamaProvider()._body("llava", SEEN, 0.2, 100)["messages"]
    assert ollama[1] == {"role": "user", "content": "What is this?", "images": [PICTURE["data"]]} and "images" not in ollama[2]


def test_messages_without_a_picture_go_out_as_they_always_did(monkeypatch):
    plain = providers.without_images(SEEN)
    sent = json_post(monkeypatch, FakeJson({"choices": [{"message": {"content": "ok"}}]}))
    providers.OpenRouterProvider("key").chat("m", plain, 0.2, 100)
    assert sent[0]["messages"] == plain
    assert providers.ChatGPTProvider.request_body("m", plain)["input"][0] == {"role": "user", "content": "What is this?"}
    assert providers.OllamaProvider()._body("m", plain, 0.2, 100)["messages"] == providers._plain_messages(plain)


def test_a_model_that_refuses_a_picture_says_so_and_is_not_sent_another(monkeypatch):
    monkeypatch.setattr(providers, "_NO_IMAGES", set())
    refusal = FakeJson({}, status=404, text="No endpoints found that support image input")
    json_post(monkeypatch, refusal)
    router = providers.OpenRouterProvider("key")
    assert providers.sees_images(router, "text-only")
    with pytest.raises(providers.ImagesUnsupported):
        router.chat("text-only", SEEN, 0.2, 100)
    with pytest.raises(providers.LLMError) as plain:  # the same answer to a message without one is an ordinary error
        router.chat("text-only", providers.without_images(SEEN), 0.2, 100)
    assert not isinstance(plain.value, providers.ImagesUnsupported)
    providers.images_refused(router, "text-only")
    assert not providers.sees_images(router, "text-only") and providers.sees_images(router, "other")
    assert not providers.sees_images(providers.MockProvider(), "mock")  # says nothing about pictures: none is sent

    chatgpt_post(monkeypatch, FakeStream(status=400, body={"error": {"message": "This model does not support image inputs."}}))
    with pytest.raises(providers.ImagesUnsupported):
        providers.ChatGPTProvider(lambda: "token").chat("m", SEEN, 0.2, 100)


def test_ollama_asks_the_models_card_whether_it_sees_pictures_once(monkeypatch):
    asked = []
    cards = {"llava": {"capabilities": ["completion", "vision"]}, "qwen": {"capabilities": ["completion", "tools"]}, "old": {}}

    def post(url, json=None, timeout=None):
        asked.append((url.rsplit("/", 1)[1], json["model"]))
        return FakeJson(cards[json["model"]])

    monkeypatch.setattr(providers.requests, "post", post)
    ollama = providers.OllamaProvider()
    assert [ollama.sees_images(m) for m in ("llava", "qwen", "old", "llava")] == [True, False, False, True]
    assert asked == [("show", "llava"), ("show", "qwen"), ("show", "old")]

    def down(url, json=None, timeout=None):
        raise providers.requests.ConnectionError("no ollama")

    monkeypatch.setattr(providers.requests, "post", down)
    assert providers.OllamaProvider().sees_images("llava") is False


# ---------------------------------------------------------------------------
# Anthropic (Claude API key, official SDK, streamed)
# ---------------------------------------------------------------------------


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _claude_message(*blocks, stop="end_turn", usage=None):
    usage = usage or _Obj(input_tokens=10, output_tokens=5, cache_read_input_tokens=100, cache_creation_input_tokens=20)
    return _Obj(content=list(blocks), stop_reason=stop, usage=usage)


class FakeClaude:
    """Stands in for anthropic.Anthropic: records each request, answers from a queue (an exception is raised)."""

    def __init__(self, *replies):
        self.requests = []
        self.replies = list(replies)
        self.beta = _Obj(messages=_Obj(stream=self._stream))

    def _stream(self, **request):
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return _Stream(reply)


class _Stream:
    def __init__(self, reply):
        self.reply = reply

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.reply


def claude(monkeypatch, *replies):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    provider = make_provider("anthropic", api_key="sk-ant-test")
    fake = FakeClaude(*replies)
    provider._client = fake
    return provider, fake


def _status_error(status, text="bad"):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request, json={"error": {"message": text}})
    cls = {401: anthropic.AuthenticationError, 400: anthropic.BadRequestError, 429: anthropic.RateLimitError}.get(
        status, anthropic.APIStatusError
    )
    return cls(text, response=response, body={"error": {"message": text}})


SYSTEM_CACHED = [
    {"role": "system", "content": [{"type": "text", "text": "rules", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]},
    {"role": "user", "content": [
        {"type": "text", "text": "brief", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "state", "cache_control": {"type": "ephemeral"}},
    ]},
    {"role": "assistant", "content": "earlier answer"},
    {"role": "user", "content": "now this"},
]


def test_make_provider_anthropic_needs_a_key():
    assert make_provider("anthropic", api_key="sk-ant-x").name == "anthropic"
    with pytest.raises(LLMError, match="Anthropic API key"):
        make_provider("anthropic", api_key="")


def test_claude_request_moves_system_out_keeps_cache_marks_and_sends_no_temperature(monkeypatch):
    provider, fake = claude(monkeypatch, _claude_message(_Obj(type="thinking"), _Obj(type="text", text=" hi ")))
    text, usage = provider.chat("claude-opus-5-5", SYSTEM_CACHED, 0.2, 2000)
    assert text == "hi"
    req = fake.requests[0]
    assert req["system"] == [{"type": "text", "text": "rules", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert [m["role"] for m in req["messages"]] == ["user", "assistant", "user"]
    assert req["messages"][0]["content"][1]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in req
    assert req["max_tokens"] == providers.ANTHROPIC_MIN_TOKENS  # room for the model's thinking
    # Refusals are re-run server-side on the model Anthropic picks for that kind of refusal.
    assert req["fallbacks"] == "default" and req["betas"] == [providers.ANTHROPIC_FALLBACK_BETA]
    assert usage == {"prompt_tokens": 130, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 100}}


def test_claude_request_drops_cache_marks_past_four_and_joins_same_role_turns(monkeypatch):
    provider, fake = claude(monkeypatch, _claude_message(_Obj(type="text", text="ok")))
    marked = {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}
    messages = [
        {"role": "system", "content": [dict(marked), dict(marked)]},
        {"role": "user", "content": [dict(marked), dict(marked), dict(marked)]},
        {"role": "system", "content": "late note"},
    ]
    provider.chat("claude-haiku-5-5", messages, 0, 100)
    req = fake.requests[0]
    blocks = [*req["system"], *(b for m in req["messages"] for b in m["content"])]
    assert sum("cache_control" in b for b in blocks) == 4
    assert len(req["messages"]) == 1 and req["messages"][0]["content"][-1] == {"type": "text", "text": "late note"}
    assert "fallbacks" not in req and "betas" not in req  # no server-side fallback for this model


def test_claude_pictures_go_as_base64_images(monkeypatch):
    provider, fake = claude(monkeypatch, _claude_message(_Obj(type="text", text="I see it")))
    picture = providers.image_part(b"png-bytes", "image/png")
    provider.chat("claude-opus-5-5", [{"role": "user", "content": [{"type": "text", "text": "look"}, picture]}], 0, 100)
    part = fake.requests[0]["messages"][0]["content"][1]
    assert part == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": picture["data"]}}
    assert providers.sees_images(provider, "claude-opus-5-5")


def test_claude_tools_are_sent_as_input_schema_and_calls_come_back(monkeypatch):
    reply = _claude_message(
        _Obj(type="text", text="Asking the site analyst."),
        _Obj(type="tool_use", name="run_expert", input={"expert": "site_analyst"}),
        stop="tool_use",
    )
    provider, fake = claude(monkeypatch, reply)
    tools = [{"name": "run_expert", "description": "Run one expert", "parameters": {"type": "object"}}]
    text, calls, _ = provider.chat_tools("claude-opus-5-5", [{"role": "user", "content": "go"}], tools, 0.2, 100)
    assert fake.requests[0]["tools"] == [{"name": "run_expert", "description": "Run one expert", "input_schema": {"type": "object"}}]
    assert "tool_choice" not in fake.requests[0]
    assert text == "Asking the site analyst."
    assert calls == [{"name": "run_expert", "arguments": {"expert": "site_analyst"}}]


def test_claude_refusal_is_an_error_not_an_empty_reply(monkeypatch):
    provider, _ = claude(monkeypatch, _claude_message(stop="refusal"))
    with pytest.raises(LLMError, match="declined"):
        provider.chat("claude-opus-5-5", [{"role": "user", "content": "x"}], 0, 100)


def test_claude_errors_retry_on_busy_and_stop_on_a_bad_key(monkeypatch):
    provider, fake = claude(monkeypatch, _status_error(529, "overloaded"), _claude_message(_Obj(type="text", text="ok")))
    assert provider.chat("claude-opus-5-5", [{"role": "user", "content": "x"}], 0, 100)[0] == "ok"
    assert len(fake.requests) == 2

    provider, fake = claude(monkeypatch, _status_error(401, "invalid x-api-key"))
    with pytest.raises(LLMError, match="refused the API key"):
        provider.chat("claude-opus-5-5", [{"role": "user", "content": "x"}], 0, 100)
    assert len(fake.requests) == 1


def test_claude_image_refusal_is_images_unsupported(monkeypatch):
    provider, _ = claude(monkeypatch, _status_error(400, "This model does not support image input"))
    picture = providers.image_part(b"x")
    with pytest.raises(providers.ImagesUnsupported):
        provider.chat("claude-x", [{"role": "user", "content": [{"type": "text", "text": "a"}, picture]}], 0, 100)


# ---------------------------------------------------------------------------
# Google Gemini (Gemini API key, REST)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.body = body or {}
        self.text = json.dumps(self.body)

    def json(self):
        return self.body


def gemini(monkeypatch, *replies):
    calls = []
    queue = list(replies)

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(providers.requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    return make_provider("google", api_key="AIza-test"), calls


def _gemini_reply(*parts, finish="STOP"):
    return FakeResponse(body={
        "candidates": [{"content": {"role": "model", "parts": list(parts)}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 7, "thoughtsTokenCount": 30,
                          "cachedContentTokenCount": 100},
    })


def test_make_provider_google_needs_a_key():
    assert make_provider("google", api_key="AIza-x").name == "google"
    with pytest.raises(LLMError, match="Gemini API key"):
        make_provider("google", api_key="")


def test_gemini_request_shape_and_reply(monkeypatch):
    provider, calls = gemini(monkeypatch, _gemini_reply({"text": "thinking…", "thought": True}, {"text": " hi "}))
    text, usage = provider.chat("gemini-4-hydrogen", SYSTEM_CACHED, 0.2, 2000)
    assert text == "hi"  # thought parts are left out
    sent = calls[0]
    assert sent["url"].endswith("/models/gemini-4-hydrogen:generateContent")
    assert sent["headers"]["x-goog-api-key"] == "AIza-test"
    body = sent["json"]
    assert body["systemInstruction"] == {"parts": [{"text": "rules"}]}
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][0]["parts"] == [{"text": "brief"}, {"text": "state"}]
    assert "temperature" not in body["generationConfig"]
    assert body["generationConfig"]["maxOutputTokens"] == providers.GEMINI_MIN_TOKENS
    assert usage == {"prompt_tokens": 120, "completion_tokens": 37, "prompt_tokens_details": {"cached_tokens": 100}}


def test_gemini_pictures_and_tools(monkeypatch):
    reply = _gemini_reply({"text": "Asking."}, {"functionCall": {"name": "run_expert", "args": {"expert": "site_analyst"}}})
    provider, calls = gemini(monkeypatch, reply)
    picture = providers.image_part(b"png", "image/png")
    tools = [{"name": "run_expert", "description": "Run one expert", "parameters": {
        "type": "object", "properties": {"expert": {"type": "string"}}, "additionalProperties": False}}]
    text, found, _ = provider.chat_tools("gemini-4-hydrogen", [{"role": "user", "content": [{"type": "text", "text": "go"}, picture]}],
                                         tools, 0.2, 100)
    body = calls[0]["json"]
    assert body["contents"][0]["parts"][1] == {"inlineData": {"mimeType": "image/png", "data": picture["data"]}}
    declared = body["tools"][0]["functionDeclarations"][0]
    assert declared["parameters"] == {"type": "object", "properties": {"expert": {"type": "string"}}}  # no additionalProperties
    assert text == "Asking." and found == [{"name": "run_expert", "arguments": {"expert": "site_analyst"}}]


def test_gemini_blocked_cut_and_errors(monkeypatch):
    provider, _ = gemini(monkeypatch, FakeResponse(body={"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(LLMError, match="declined"):
        provider.chat("gemini-4-hydrogen", [{"role": "user", "content": "x"}], 0, 100)

    provider, _ = gemini(monkeypatch, _gemini_reply(finish="MAX_TOKENS"))
    with pytest.raises(LLMError, match="maxOutputTokens"):
        provider.chat("gemini-4-hydrogen", [{"role": "user", "content": "x"}], 0, 100)

    provider, calls = gemini(monkeypatch, FakeResponse(503, {"error": "busy"}), _gemini_reply({"text": "ok"}))
    assert provider.chat("gemini-4-hydrogen", [{"role": "user", "content": "x"}], 0, 100)[0] == "ok"
    assert len(calls) == 2

    provider, calls = gemini(monkeypatch, FakeResponse(400, {"error": {"message": "API key not valid. Please pass a valid API key."}}))
    with pytest.raises(LLMError, match="refused the Gemini API key"):
        provider.chat("gemini-4-hydrogen", [{"role": "user", "content": "x"}], 0, 100)
    assert len(calls) == 1
