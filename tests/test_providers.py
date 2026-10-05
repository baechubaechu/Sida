"""LLM providers: construction, retries, Ollama request details, the mock provider."""

from __future__ import annotations

import time

import pytest

from sida import worker
from sida.providers import (
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
    prompt = (ROOT / "agents" / "31_constraint_mapper.md").read_text(encoding="utf-8")
    full = worker.build_worker_prompt(prompt, "## Site\nbrief has headers too", "(none yet)")
    out, _ = MockProvider().chat("m", [{"role": "user", "content": full}], 0, 10, role="worker")
    assert missing_headers(out, expected_headers(prompt)) == []
