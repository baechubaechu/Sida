from __future__ import annotations

import ollama_boot as boot
from harness import LLMError


def test_model_is_present_matches_variants():
    names = ["qwen3.5:9b", "qwen2.5:7b-instruct-q4_K_M"]
    assert boot.model_is_present(names, "qwen3.5:9b")
    assert boot.model_is_present(names, "qwen2.5:7b")
    assert not boot.model_is_present(names, "gemma3:12b")
    assert not boot.model_is_present([], "qwen3.5:9b")


def test_boot_skipped_for_openrouter(mock_config):
    mock_config["conductor"]["provider"] = "openrouter"
    boot.ensure_ollama_ready(mock_config, print_fn=lambda *_: None)


def test_boot_autostart_then_warmup(mock_config, monkeypatch):
    mock_config["conductor"]["provider"] = "ollama"
    mock_config["conductor"]["local_profile"] = "local_plus"
    mock_config["conductor"]["ollama_pull_missing"] = "off"
    mock_config["conductor"]["ollama_warmup"] = True

    calls = {"reach": 0, "start": 0, "warm": 0}

    def reach(_url, *, timeout=1.5):
        calls["reach"] += 1
        return calls["reach"] >= 2  # first miss, then up after start

    monkeypatch.setattr(boot, "ollama_reachable", reach)
    monkeypatch.setattr(boot, "try_start_ollama", lambda: calls.__setitem__("start", 1) or "started")
    monkeypatch.setattr(boot, "wait_until_reachable", lambda *a, **k: True)
    monkeypatch.setattr(boot, "list_ollama_models", lambda *_: ["qwen3.5:9b"])
    monkeypatch.setattr(
        boot,
        "warmup_model",
        lambda *a, **k: calls.__setitem__("warm", 1),
    )
    logs: list[str] = []
    boot.ensure_ollama_ready(mock_config, print_fn=logs.append)
    assert calls["start"] == 1 and calls["warm"] == 1
    assert any("starting" in x.lower() or "시작" in x for x in logs)


def test_boot_asks_before_pull(mock_config, monkeypatch):
    mock_config["conductor"]["provider"] = "ollama"
    mock_config["conductor"]["local_profile"] = "local_plus"
    mock_config["conductor"]["ollama_warmup"] = False
    mock_config["conductor"]["ollama_pull_missing"] = "ask"

    monkeypatch.setattr(boot, "ollama_reachable", lambda *a, **k: True)
    monkeypatch.setattr(boot, "list_ollama_models", lambda *_: [])
    pulled: list[str] = []
    monkeypatch.setattr(boot, "pull_model", lambda url, model: pulled.append(model))

    boot.ensure_ollama_ready(
        mock_config,
        prompt_fn=lambda *_: "y",
        print_fn=lambda *_: None,
    )
    assert pulled == ["qwen3.5:9b"]


def test_boot_declined_pull_raises(mock_config, monkeypatch):
    mock_config["conductor"]["provider"] = "ollama"
    mock_config["conductor"]["local_profile"] = "local"
    mock_config["conductor"]["ollama_warmup"] = False
    monkeypatch.setattr(boot, "ollama_reachable", lambda *a, **k: True)
    monkeypatch.setattr(boot, "list_ollama_models", lambda *_: [])
    try:
        boot.ensure_ollama_ready(
            mock_config, prompt_fn=lambda *_: "n", print_fn=lambda *_: None
        )
        raise AssertionError("expected LLMError")
    except LLMError as exc:
        assert "qwen2.5:7b" in str(exc)


def test_boot_not_installed(mock_config, monkeypatch):
    mock_config["conductor"]["provider"] = "ollama"
    monkeypatch.setattr(boot, "ollama_reachable", lambda *a, **k: False)
    monkeypatch.setattr(boot, "try_start_ollama", lambda: None)
    try:
        boot.ensure_ollama_ready(mock_config, print_fn=lambda *_: None)
        raise AssertionError("expected LLMError")
    except LLMError as exc:
        assert "ollama.com" in str(exc).lower() or "Ollama" in str(exc)
