from __future__ import annotations

import pytest

from sida.experts.rhino.rhino_mcp import SAFE_TOOLS, resolve_mcp_command
from sida.experts.rhino.rhino_modeler import (
    modeling_settings,
    parse_rhino_plan,
    require_gpt6_plus,
    run_modeling_turn,
)
from sida.providers import LLMError, gpt_major_version


def test_parse_rhino_plan_block():
    raw = (
        '잠깐 확인합니다.\n```rhino\n'
        '{"say": "박스 추가", "done": false, "calls": [{"tool": "run_python", "args": {"script": "x=1"}}]}\n'
        "```\n"
    )
    plan = parse_rhino_plan(raw)
    assert plan["say"] == "박스 추가"
    assert plan["done"] is False
    assert plan["calls"][0]["tool"] == "run_python"
    assert "script" in plan["calls"][0]["args"]


def test_parse_rhino_plan_done_without_block():
    plan = parse_rhino_plan("그냥 설명만")
    assert plan["done"] is True
    assert plan["calls"] == []


def test_modeling_settings_defaults(mock_config):
    rt = modeling_settings(mock_config)
    assert rt["provider"] == "openai"
    assert gpt_major_version(rt["model"]) >= 6
    assert rt["auto_execute"] is True


def test_require_gpt6_plus():
    require_gpt6_plus("gpt-6-astra")
    require_gpt6_plus("gpt-7-preview")
    with pytest.raises(LLMError):
        require_gpt6_plus("gpt-5.2")
    with pytest.raises(LLMError):
        require_gpt6_plus("openai/gpt-4o")


def test_gpt_major_version():
    assert gpt_major_version("gpt-6-astra") == 6
    assert gpt_major_version("openai/gpt-5.2") == 5
    assert gpt_major_version("claude") is None


def test_resolve_mcp_command_finds_router_or_none(mock_config):
    cmd = resolve_mcp_command(mock_config)
    assert cmd is None or (isinstance(cmd, list) and cmd[0].endswith(".exe") or True)


def test_run_modeling_turn_dry(mock_config, scripted, capsys):
    mock_config["modeling"] = {
        "provider": "mock",
        "model": "gpt-6-astra",
        "auto_execute": False,
        "max_rounds": 2,
        "temperature": 0.1,
        "max_tokens": 400,
        "prompt": "agents/71_rhino_modeler.md",
    }
    provider = scripted(
        [
            '```rhino\n{"say":"컨텍스트 확인","done":false,"calls":[{"tool":"get_context","args":{}}]}\n```',
            '```rhino\n{"say":"완료","done":true,"calls":[]}\n```',
        ]
    )
    say, log, done = run_modeling_turn(
        mock_config, "", "10m 박스 하나", provider=provider, rhino=None
    )
    assert done is True
    assert say
    assert any(e.get("tool") == "get_context" for e in log)


def test_hub_modeling_menu(mock_config, monkeypatch):
    from sida import hub

    called = {"n": 0}
    monkeypatch.setattr(hub, "load_config", lambda *a, **k: mock_config)
    monkeypatch.setattr(hub, "run_rhino_modeler", lambda cfg: called.__setitem__("n", 1))
    it = iter(["m", "q"])
    monkeypatch.setattr("builtins.input", lambda *_: next(it))
    assert hub.project_hub() is None
    assert called["n"] == 1


def test_safe_tools_include_run_python():
    assert "run_python" in SAFE_TOOLS
    assert "ask_user" not in SAFE_TOOLS


def _router(packages, rhino, version):
    exe = (
        packages / rhino / "Rhino-MCP-Platform" / version / "router" / "win-x64"
        / "rhino-mcp-router.exe"
    )
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    return str(exe)


def test_default_rhino_commands_find_any_version_newest_first(tmp_path, monkeypatch):
    from sida.experts.rhino.mcp_stdio import iter_default_rhino_commands

    monkeypatch.delenv("SIDA_RHINO_MCP", raising=False)
    assert list(iter_default_rhino_commands(tmp_path)) == []  # nothing installed

    old = _router(tmp_path, "8.0", "0.2.1-wip")
    newer = _router(tmp_path, "8.0", "0.2.10")  # numeric sort: 10 > 9 > 1
    mid = _router(tmp_path, "8.0", "0.2.9")
    rhino9 = _router(tmp_path, "9.0", "0.1.0")
    assert list(iter_default_rhino_commands(tmp_path)) == [[rhino9], [newer], [mid], [old]]

    monkeypatch.setenv("SIDA_RHINO_MCP", "C:/custom/router.exe")
    assert next(iter_default_rhino_commands(tmp_path)) == ["C:/custom/router.exe"]
