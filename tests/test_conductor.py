from __future__ import annotations

import pytest

from sida.conductor import ask_conductor, build_conductor_messages, parse_action
from sida.providers import LLMError, MockProvider


def test_parse_action_variants():
    assert parse_action("hi") == ("hi", {"type": "none"})
    reply, action = parse_action('hello\n\n```action\n{"type": "run", "agent": "site_reader"}\n```')
    assert reply == "hello" and action == {"type": "run", "agent": "site_reader"}
    reply, action = parse_action("a\n```action\n{bad json}\n```\nb")
    assert reply == "a\n\nb" and action["type"] == "none"
    _, action = parse_action("```ACTION\n[1,2]\n```")
    assert action == {"type": "none"}


def test_messages_without_state_send_full_modules():
    msgs = build_conductor_messages(
        "sys", "brief", project_state=None, module_context="### Site Reader\n\nfull", history=[], cache_ttl="1h"
    )
    assert [m["role"] for m in msgs] == ["system", "user", "user"]
    text = msgs[2]["content"][0]["text"]
    assert text.startswith("KNOWN MODULE OUTPUTS:") and "full" in text


def test_messages_with_state_add_state_block_and_snapshot():
    hist = [{"role": "user", "content": "q"}]
    msgs = build_conductor_messages(
        "sys", "brief", project_state="# State", module_context="(none)", history=hist, cache_ttl="1h", history_truncated=True
    )
    assert [m["role"] for m in msgs] == ["system", "user", "user", "user", "user"]
    state_text = msgs[2]["content"][0]["text"]
    assert state_text.startswith("PROJECT STATE:") and "Older conversation turns are omitted" in state_text
    assert msgs[3]["content"][0]["text"].startswith("MODULE SNAPSHOT:")
    assert msgs[-1] == hist[0]


def test_ask_conductor_ephemeral_and_error_semantics(mock_config, agents, project, conductor_prompt):
    history: list[dict] = []
    reply, action, usage = ask_conductor(
        "", mock_config, conductor_prompt, project.read_brief(), [], history, project.session_id,
        user_text="OPENING", project=project, agents=agents, output_dir=project.modules_dir,
        provider=MockProvider(), ephemeral=True,
    )
    assert action["type"] == "none"
    assert all(m["content"] != "OPENING" for m in history)
    assert history[-1]["role"] == "assistant"

    class Boom:
        name = "boom"

        def chat(self, *a, **k):
            raise LLMError("down")

    n = len(history)
    with pytest.raises(LLMError):
        ask_conductor(
            "", mock_config, conductor_prompt, project.read_brief(), [], history, project.session_id,
            user_text="hello", project=project, agents=agents, output_dir=project.modules_dir, provider=Boom(),
        )
    assert len(history) == n  # failed turn is not recorded
    assert project.load_history() == history


def test_ask_conductor_stores_user_turn_when_not_ephemeral(mock_config, agents, project, conductor_prompt):
    history: list[dict] = []
    ask_conductor(
        "", mock_config, conductor_prompt, project.read_brief(), [], history, project.session_id,
        user_text="hello", project=project, agents=agents, output_dir=project.modules_dir, provider=MockProvider(),
    )
    assert [m["role"] for m in history] == ["user", "assistant"]


RUN_REPLY = "네, 지금 Site Reader 모듈을 실행합니다."  # no action block


def _local(cfg, mode="auto"):
    cfg["conductor"]["provider"] = "ollama"
    cfg["conductor"]["action_recovery"] = mode
    return cfg


def test_recovery_runs_when_block_missing_on_local(mock_config, agents, project, conductor_prompt, scripted):
    cfg = _local(mock_config)
    provider = scripted([RUN_REPLY, '{"type": "run", "agent": "site_reader"}'])
    history: list[dict] = []
    reply, action, _ = ask_conductor(
        "", cfg, conductor_prompt, project.read_brief(), [], history, project.session_id,
        user_text="go", project=project, agents=agents, output_dir=project.modules_dir, provider=provider,
    )
    assert action == {"type": "run", "agent": "site_reader", "recovered": True}
    assert len(provider.calls) == 2
    assert provider.calls[1]["kw"].get("json_mode") is True
    assert provider.calls[1]["kw"].get("role") == "action_recovery"
    # stored raw now contains a well-formed block; visible reply unchanged
    assert reply == RUN_REPLY
    assert history[-1]["content"].endswith('```action\n{"type": "run", "agent": "site_reader"}\n```')
    assert "recovered" not in history[-1]["content"]


def test_recovery_rejects_agent_not_mentioned(mock_config, agents, project, conductor_prompt, scripted):
    cfg = _local(mock_config)
    provider = scripted(["좋은 질문입니다. 먼저 사이트를 더 보죠.", '{"type": "run", "agent": "design_critic"}'])
    _, action, _ = ask_conductor(
        "", cfg, conductor_prompt, project.read_brief(), [], [], project.session_id,
        user_text="x", project=project, agents=agents, output_dir=project.modules_dir, provider=provider,
    )
    assert action == {"type": "none"}


def test_recovery_handles_bad_json_and_exceptions(mock_config, agents, project, conductor_prompt, scripted):
    cfg = _local(mock_config)
    provider = scripted([RUN_REPLY, "not json at all"])
    _, action, _ = ask_conductor(
        "", cfg, conductor_prompt, project.read_brief(), [], [], project.session_id,
        user_text="x", project=project, agents=agents, output_dir=project.modules_dir, provider=provider,
    )
    assert action == {"type": "none"}
    provider = scripted([RUN_REPLY, LLMError("down")])
    _, action, _ = ask_conductor(
        "", cfg, conductor_prompt, project.read_brief(), [], [], project.session_id,
        user_text="x", project=project, agents=agents, output_dir=project.modules_dir, provider=provider,
    )
    assert action == {"type": "none"}


def test_recovery_skipped_when_block_present_or_cloud_or_off(mock_config, agents, project, conductor_prompt, scripted):
    # explicit none block -> no second call
    cfg = _local(mock_config)
    provider = scripted(['ok\n```action\n{"type":"none"}\n```'])
    ask_conductor("", cfg, conductor_prompt, project.read_brief(), [], [], project.session_id,
                  user_text="x", project=project, agents=agents, output_dir=project.modules_dir, provider=provider)
    assert len(provider.calls) == 1
    # cloud + auto -> no second call
    mock_config["conductor"]["provider"] = "openrouter"
    provider = scripted([RUN_REPLY])
    _, action, _ = ask_conductor("", mock_config, conductor_prompt, project.read_brief(), [], [], project.session_id,
                                 user_text="x", project=project, agents=agents, output_dir=project.modules_dir, provider=provider)
    assert len(provider.calls) == 1 and action == {"type": "none"}
    # cloud + always -> second call
    mock_config["conductor"]["action_recovery"] = "always"
    provider = scripted([RUN_REPLY, '{"type":"run","agent":"site_reader"}'])
    _, action, _ = ask_conductor("", mock_config, conductor_prompt, project.read_brief(), [], [], project.session_id,
                                 user_text="x", project=project, agents=agents, output_dir=project.modules_dir, provider=provider)
    assert action["type"] == "run"
    # local + off -> no second call
    cfg = _local(mock_config, "off")
    provider = scripted([RUN_REPLY])
    ask_conductor("", cfg, conductor_prompt, project.read_brief(), [], [], project.session_id,
                  user_text="x", project=project, agents=agents, output_dir=project.modules_dir, provider=provider)
    assert len(provider.calls) == 1


def test_recovery_exit_and_read_paths(mock_config, agents, project, conductor_prompt, scripted):
    from sida.conductor import _parse_recovered, recover_action

    assert _parse_recovered('{"type":"exit"}', agents) == {"type": "exit", "recovered": True}
    assert _parse_recovered('{"type":"read","module":"spatial reviewer"}', agents) == {
        "type": "read", "module": "spatial_reviewer", "recovered": True}
    assert _parse_recovered('{"type":"teleport"}', agents) == {"type": "none"}
    assert _parse_recovered("[1]", agents) == {"type": "none"}
    # exit needs no agent mention
    provider = scripted(['{"type":"exit"}'])
    assert recover_action(provider, "m", "오늘은 여기까지 하겠습니다. 안녕히.", agents)["type"] == "exit"
    assert recover_action(provider, "m", "   ", agents) == {"type": "none"}


def test_language_rule_injected(mock_config, agents, project, conductor_prompt, scripted):
    from sida import i18n

    i18n.set_language("ko")
    provider = scripted(['ok\n```action\n{"type":"none"}\n```'])
    ask_conductor(
        "", mock_config, conductor_prompt, project.read_brief(), [], [], project.session_id,
        user_text="x", project=project, agents=agents, output_dir=project.modules_dir, provider=provider,
    )
    system_text = provider.calls[0]["messages"][0]["content"][0]["text"]
    assert "entirely in Korean" in system_text


# ---------------------------------------------------------------------------
# Expert tools (function calling), with the action block as fallback
# ---------------------------------------------------------------------------


class ToolProvider:
    """chat_tools returns queued (text, calls); chat returns queued text. Records calls."""

    name = "tooly"

    def __init__(self, tool_replies, text_replies=()):
        self.tool_replies = list(tool_replies)
        self.text_replies = list(text_replies)
        self.calls = []

    def chat_tools(self, model, messages, tools, temperature, max_tokens, **kw):
        self.calls.append({"mode": "tools", "messages": messages, "tools": tools})
        item = self.tool_replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item[0], item[1], {}

    def chat(self, model, messages, temperature, max_tokens, **kw):
        self.calls.append({"mode": "text", "messages": messages, "kw": kw})
        return self.text_replies.pop(0), {}


@pytest.fixture
def no_tools_cache(monkeypatch):
    from sida import conductor

    monkeypatch.setattr(conductor, "_NO_TOOLS", set())
    return conductor


def _ask(cfg, project, agents, conductor_prompt, provider, history=None):
    history = [] if history is None else history
    reply, action, _ = ask_conductor(
        "", cfg, conductor_prompt, project.read_brief(), [], history, project.session_id,
        user_text="go", project=project, agents=agents, output_dir=project.modules_dir, provider=provider,
    )
    return reply, action, history


def test_tool_call_becomes_a_run_action(mock_config, agents, project, conductor_prompt, no_tools_cache):
    provider = ToolProvider([("대지부터 보겠습니다", [{"name": "run_expert", "arguments": {"agent": "site_reader"}}])])
    reply, action, history = _ask(mock_config, project, agents, conductor_prompt, provider)
    assert (reply, action) == ("대지부터 보겠습니다", {"type": "run", "agent": "site_reader"})
    # Stored as an action block, so the screen and a later text-mode turn read the same history.
    assert history[-1]["content"] == '대지부터 보겠습니다\n\n```action\n{"type": "run", "agent": "site_reader"}\n```'
    call = provider.calls[0]
    system = call["messages"][0]["content"][0]["text"]
    assert "## Expert tools" in system and "## Action block" not in system
    assert [t["name"] for t in call["tools"]] == ["run_expert", "read_expert_output"]
    assert call["tools"][0]["parameters"]["properties"]["agent"]["enum"] == [a["id"] for a in agents]


def test_run_tool_carries_the_site_address(mock_config, agents, project, conductor_prompt, no_tools_cache):
    arguments = {"agent": "site_reader", "address": " 대구광역시 서구 국채보상로81안길 3 "}
    provider = ToolProvider([("대지부터 보겠습니다", [{"name": "run_expert", "arguments": arguments}])])
    reply, action, history = _ask(mock_config, project, agents, conductor_prompt, provider)
    assert action == {"type": "run", "agent": "site_reader", "address": "대구광역시 서구 국채보상로81안길 3"}
    assert parse_action(history[-1]["content"])[1] == action  # a later turn reads it back
    run, read = provider.calls[0]["tools"]
    assert "address" in run["parameters"]["properties"]
    assert "address" not in read["parameters"]["properties"]


def test_read_tool_and_tool_only_reply(mock_config, agents, project, conductor_prompt, no_tools_cache):
    provider = ToolProvider([("", [{"name": "read_expert_output", "arguments": {"agent": "site_reader"}}])])
    reply, action, history = _ask(mock_config, project, agents, conductor_prompt, provider)
    assert (reply, action) == ("", {"type": "read", "module": "site_reader"})
    assert history[-1]["content"] == '```action\n{"type": "read", "module": "site_reader"}\n```'


def test_model_without_tools_falls_back_to_the_action_block(mock_config, agents, project, conductor_prompt, no_tools_cache):
    from sida.providers import ToolsUnsupported

    provider = ToolProvider(
        [ToolsUnsupported("does not support tools")],
        [RUN_REPLY + '\n```action\n{"type":"run","agent":"site_reader"}\n```', 'ok\n```action\n{"type":"none"}\n```'],
    )
    _, action, _ = _ask(mock_config, project, agents, conductor_prompt, provider)
    assert action == {"type": "run", "agent": "site_reader"}
    assert [c["mode"] for c in provider.calls] == ["tools", "text"]
    system = provider.calls[1]["messages"][0]["content"][0]["text"]
    assert "## Action block" in system and "## Expert tools" not in system
    # Remembered: the next turn goes straight to text mode.
    _ask(mock_config, project, agents, conductor_prompt, provider)
    assert [c["mode"] for c in provider.calls] == ["tools", "text", "text"]


def test_tool_mode_off_and_written_block_and_empty_reply(mock_config, agents, project, conductor_prompt, no_tools_cache):
    mock_config["conductor"]["tool_calls"] = "off"
    provider = ToolProvider([], ['ok\n```action\n{"type":"none"}\n```'])
    _ask(mock_config, project, agents, conductor_prompt, provider)
    assert [c["mode"] for c in provider.calls] == ["text"]

    mock_config["conductor"]["tool_calls"] = "auto"
    written = ToolProvider([('보겠습니다\n```action\n{"type":"run","agent":"site_reader"}\n```', [])])
    assert _ask(mock_config, project, agents, conductor_prompt, written)[1] == {"type": "run", "agent": "site_reader"}

    # No text and no known tool: asked again without tools rather than storing an empty reply.
    empty = ToolProvider([("", [{"name": "something_else", "arguments": {}}])], ['ok\n```action\n{"type":"none"}\n```'])
    reply, _, history = _ask(mock_config, project, agents, conductor_prompt, empty)
    assert reply == "ok" and [c["mode"] for c in empty.calls] == ["tools", "text"]
    assert history[-1]["content"].startswith("ok")
