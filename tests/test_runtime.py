"""Runtime resolution: which roles need an OpenRouter key."""

from __future__ import annotations

import pytest

from sida.runtime import resolve_conductor_runtime


def test_load_env_without_a_key_fails_when_cloud(mock_config, monkeypatch, capsys):
    from sida import errors
    from sida.runtime import load_env

    mock_config["conductor"]["provider"] = "openrouter"
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    with pytest.raises(errors.SidaError) as info:
        load_env(config=mock_config)
    assert "설정 화면" in info.value.message  # points at the web settings, never a terminal prompt
    assert capsys.readouterr() == ("", "")


def test_cloud_runtime_untouched(mock_config):
    mock_config["conductor"]["provider"] = "openrouter"
    rt = resolve_conductor_runtime(mock_config)
    assert rt["provider"] == "openrouter"
    assert rt["num_ctx"] is None
