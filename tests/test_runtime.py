"""Runtime resolution: local profiles, and which roles need an OpenRouter key."""

from __future__ import annotations

from sida.runtime import resolve_conductor_runtime


def test_local_profiles_overlay(mock_config):
    cfg = mock_config
    cfg["conductor"]["provider"] = "ollama"
    cfg["conductor"]["local_profile"] = "local"
    rt = resolve_conductor_runtime(cfg)
    assert rt["model"] == "qwen2.5:7b" and rt["num_ctx"] == 8192 and rt["history_window"] == 12
    cfg["conductor"]["local_profile"] = "local_plus"
    rt = resolve_conductor_runtime(cfg)
    assert rt["model"] == "qwen3.5:9b" and rt["num_ctx"] == 16384 and rt["history_window"] == 16


def test_worker_ollama_uses_local_profile_model(mock_config):
    from sida.runtime import resolve_worker_runtime

    cfg = mock_config
    cfg["conductor"]["provider"] = "ollama"
    cfg["conductor"]["local_profile"] = "local_plus"
    cfg["worker"]["provider"] = "ollama"
    cfg["worker"]["model"] = "openai/gpt-4o-mini"  # cloud id must be replaced
    rt = resolve_worker_runtime(cfg)
    assert rt["provider"] == "ollama"
    assert rt["model"] == "qwen3.5:9b"
    assert rt["num_ctx"] == 16384
    assert rt["base_url"]


def test_needs_openrouter_false_when_fully_local(mock_config):
    from sida.runtime import needs_openrouter

    cfg = mock_config
    cfg["conductor"]["provider"] = "ollama"
    cfg["worker"]["provider"] = "ollama"
    cfg["state_update"] = {"mode": "ask", "provider": "conductor"}
    assert needs_openrouter(cfg) is False
    cfg["worker"]["provider"] = "openrouter"
    assert needs_openrouter(cfg) is True
    cfg["worker"]["provider"] = "ollama"
    cfg["state_update"] = {"mode": "ask", "provider": "worker"}
    # worker is ollama → still local
    assert needs_openrouter(cfg) is False
    cfg["conductor"]["provider"] = "openrouter"
    assert needs_openrouter(cfg) is True


def test_load_env_skips_prompt_when_local(mock_config, monkeypatch):
    from sida.runtime import load_env

    cfg = mock_config
    cfg["conductor"]["provider"] = "ollama"
    cfg["worker"]["provider"] = "ollama"
    cfg["state_update"] = {"mode": "off"}
    monkeypatch.setattr(
        "sida.setup_env.ensure_api_key",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not ask for key")),
    )
    monkeypatch.setattr("sida.setup_env.read_api_key_from_env", lambda: "")
    assert load_env(config=cfg) == ""


def test_cloud_runtime_untouched(mock_config):
    mock_config["conductor"]["provider"] = "openrouter"
    rt = resolve_conductor_runtime(mock_config)
    assert rt["provider"] == "openrouter"
    assert rt["num_ctx"] is None
