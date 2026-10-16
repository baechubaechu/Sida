"""expert_chat.py — the designer's own chat with one expert, apart from the Conductor."""

from __future__ import annotations

import pytest

from sida import config as sida_config
from sida import expert_chat
from sida.providers import LLMError, MockProvider

REVISE = '북측 도로 부분을 보강하겠습니다\n```action\n{"type":"revise","request":"북측 도로를 더 자세히"}\n```'
ANSWER = '소음 때문입니다\n```action\n{"type":"none"}\n```'


class ChatProvider(MockProvider):
    """Scripted replies for the expert chat; everything else (runs, state) stays mock."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, model, messages, temperature, max_tokens, *, role="conductor", **kw):
        self.calls.append({"role": role, "messages": messages})
        if role != "expert_chat":
            return super().chat(model, messages, temperature, max_tokens, role=role, **kw)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {}


@pytest.fixture
def chat_session(make_session):
    def _make(replies):
        provider = ChatProvider(replies)
        s = make_session(w_provider=provider)
        s.events = []
        s.emit = lambda kind, data: s.events.append((kind, data))
        return s, provider

    return _make


def agent(s, agent_id="program_analyst"):
    return sida_config.agent_by_id(s.agents, agent_id)


def test_answer_is_saved_to_the_expert_chat_only(chat_session):
    s, provider = chat_session([ANSWER])
    a = agent(s)
    reply = expert_chat.expert_chat(s, a, "왜 이렇게 배치했어?")
    assert reply.text == "소음 때문입니다" and reply.revision is None and reply.run is None
    assert [k for k, _ in s.events] == ["expert_reply"]
    assert s.history == []  # the Conductor conversation is untouched
    messages = expert_chat.chat_messages(expert_chat.load_chat(s.project.path, a))
    assert messages == [
        {"role": "user", "text": "왜 이렇게 배치했어?"},
        {"role": "expert", "text": "소음 때문입니다"},
    ]
    context = provider.calls[0]["messages"][1]["content"]
    assert "YOUR ROLE (expert id: program_analyst)" in context and "(not run yet)" in context


def test_agreed_revision_reruns_the_expert_and_tells_the_conductor(chat_session):
    s, provider = chat_session([REVISE])
    a = agent(s)
    (s.output_dir / a["output"]).write_text("## Users\n- 이전 결과\n", encoding="utf-8")
    reply = expert_chat.expert_chat(s, a, "북측 도로를 더 자세히 봐 줘")
    assert reply.revision == "북측 도로를 더 자세히" and reply.run.run is not None
    assert [k for k, _ in s.events][:3] == ["expert_reply", "module_started", "module_saved"]
    worker_prompt = next(c for c in provider.calls if c["role"] == "worker")["messages"][-1]["content"]
    assert "북측 도로를 더 자세히" in worker_prompt and "이전 결과" in worker_prompt
    assert s.history[-1]["content"].startswith("[module completed] program_analyst")
    messages = expert_chat.chat_messages(expert_chat.load_chat(s.project.path, a))
    assert messages[-1]["role"] == "system" and messages[-1]["event"] == "revised"


def test_chat_is_refused_for_an_expert_without_chat(chat_session):
    s, provider = chat_session([ANSWER])
    site = agent(s, "site_reader")
    assert expert_chat.chat_enabled(site) is False
    with pytest.raises(ValueError):
        expert_chat.expert_chat(s, site, "안녕")
    assert provider.calls == []


def test_model_error_leaves_the_chat_file_untouched(chat_session):
    s, _provider = chat_session([ANSWER, LLMError("down")])
    a = agent(s)
    expert_chat.expert_chat(s, a, "하나")
    before = expert_chat.chat_path(s.project.path, a).read_bytes()
    with pytest.raises(LLMError):
        expert_chat.expert_chat(s, a, "둘")
    assert expert_chat.chat_path(s.project.path, a).read_bytes() == before
