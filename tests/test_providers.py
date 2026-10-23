"""LLM providers: construction, retries, Ollama request details, the mock provider."""

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
    assert make_provider("ollama", base_url="http://h:1/v1").base_url == "http://h:1"
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


def test_ollama_unreachable_is_llmerror():
    p = make_provider("ollama", base_url="http://127.0.0.1:9")  # closed port
    with pytest.raises(LLMError):
        p.chat("m", [{"role": "user", "content": "hi"}], 0.1, 5)


def test_ollama_sends_think_false_by_default(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"message": {"role": "assistant", "content": "ok"}, "eval_count": 1}

    def fake_post(url, json=None, timeout=None):
        captured["body"] = json
        return FakeResp()

    monkeypatch.setattr("sida.providers.requests.post", fake_post)
    p = make_provider("ollama", base_url="http://127.0.0.1:11434")
    out, _ = p.chat("qwen3.5:9b", [{"role": "user", "content": "hi"}], 0.2, 100)
    assert out == "ok"
    assert captured["body"]["think"] is False


def test_ollama_empty_content_with_thinking_is_retryable(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "message": {"role": "assistant", "content": "", "thinking": "…"},
                "done_reason": "length",
                "eval_count": 700,
            }

    monkeypatch.setattr("sida.providers.requests.post", lambda *a, **k: FakeResp())
    p = make_provider("ollama", base_url="http://h", think=True)
    with pytest.raises(LLMError) as ei:
        p.chat("m", [{"role": "user", "content": "hi"}], 0.1, 50)
    assert "thinking" in str(ei.value).lower()


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


def test_ollama_tool_arguments_arrive_as_an_object(monkeypatch):
    data = {"message": {"content": "대지부터", "tool_calls": [{"function": {"name": "run_expert", "arguments": {"agent": "site_reader"}}}]}}
    sent = json_post(monkeypatch, FakeJson(data))
    text, calls, _ = providers.OllamaProvider().chat_tools("qwen3.5:9b", [{"role": "user", "content": "hi"}], TOOLS, 0.2, 100)
    assert text == "대지부터" and calls == [{"name": "run_expert", "arguments": {"agent": "site_reader"}}]
    assert sent[0]["tools"][0]["function"]["name"] == "run_expert" and sent[0]["think"] is False


@pytest.mark.parametrize(
    ("make", "response"),
    [
        (lambda: providers.OllamaProvider(), FakeJson({"error": "x does not support tools"}, status=400)),
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
