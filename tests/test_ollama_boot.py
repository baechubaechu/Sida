from __future__ import annotations

from sida import ollama_boot as boot
from sida.providers import LLMError


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


# --- GPU advice before download, speed after -------------------------------

GPU_8GB = "NVIDIA GeForce RTX 4060, 8188\n"
GPU_16GB = "NVIDIA GeForce RTX 5070 Ti, 16303\n"
GPU_6GB = "NVIDIA GeForce RTX 2060, 6144\n"


def test_profile_advice_cases():
    from sida.hardware import parse_nvidia_smi

    small, big, tiny = (parse_nvidia_smi(x) for x in (GPU_8GB, GPU_16GB, GPU_6GB))
    assert "local_plus" in boot.profile_advice("local_plus", small)  # too big → names the profile
    assert "'local'" in boot.profile_advice("local_plus", small)  # … and recommends local
    assert "local_plus" in boot.profile_advice("local", big)  # could upgrade
    assert "16GB" in boot.profile_advice("local_plus", big)  # fits
    assert "c → 9" in boot.profile_advice("local", tiny)  # below minimum → cloud
    assert boot.profile_advice("local", None) is None  # nothing detected → say nothing
    assert boot.profile_advice("my_custom_profile", big) is None


def _missing_model_boot(mock_config, monkeypatch, *, profile, gpu_text, answer, warmup=False):
    from sida import hardware

    mock_config["conductor"]["provider"] = "ollama"
    mock_config["conductor"]["local_profile"] = profile
    mock_config["conductor"]["ollama_warmup"] = warmup
    mock_config["conductor"]["ollama_pull_missing"] = "ask"
    monkeypatch.setattr(hardware, "query_nvidia_smi", lambda: gpu_text)
    monkeypatch.setattr(boot, "ollama_reachable", lambda *a, **k: True)
    monkeypatch.setattr(boot, "list_ollama_models", lambda *_: [])
    pulled: list[str] = []
    monkeypatch.setattr(boot, "pull_model", lambda url, model: pulled.append(model))
    monkeypatch.setattr(boot, "warmup_model", lambda *a, **k: None)
    logs: list[str] = []
    seen_before_prompt: list[str] = []

    def prompt(_label):
        seen_before_prompt.extend(logs)
        return answer

    try:
        boot.ensure_ollama_ready(mock_config, prompt_fn=prompt, print_fn=logs.append)
    except LLMError:
        pass
    return logs, seen_before_prompt, pulled


def test_gpu_warning_is_shown_before_the_download_prompt(mock_config, monkeypatch):
    logs, before, pulled = _missing_model_boot(
        mock_config, monkeypatch, profile="local_plus", gpu_text=GPU_8GB, answer="n"
    )
    assert any("[gpu]" in line and "8GB" in line for line in before)
    assert pulled == []  # user could decline after reading the warning


def test_no_gpu_line_when_detection_fails(mock_config, monkeypatch):
    logs, _before, pulled = _missing_model_boot(
        mock_config, monkeypatch, profile="local", gpu_text=None, answer="y"
    )
    assert not any("[gpu]" in line for line in logs)
    assert pulled == ["qwen2.5:7b"]


def test_speed_reported_after_fresh_download_and_slow_warning(mock_config, monkeypatch):
    monkeypatch.setattr(boot, "measure_speed", lambda *a, **k: 4.2)
    logs, _before, pulled = _missing_model_boot(
        mock_config, monkeypatch, profile="local", gpu_text=GPU_8GB, answer="y", warmup=True
    )
    assert pulled == ["qwen2.5:7b"]
    assert any("4" in line and ("tokens/s" in line or "토큰" in line) for line in logs)
    assert any("c → 9" in line for line in logs)  # slow → suggests smaller profile / cloud


def test_speed_not_measured_when_model_already_present(mock_config, monkeypatch):
    mock_config["conductor"]["provider"] = "ollama"
    mock_config["conductor"]["local_profile"] = "local"
    monkeypatch.setattr(boot, "ollama_reachable", lambda *a, **k: True)
    monkeypatch.setattr(boot, "list_ollama_models", lambda *_: ["qwen2.5:7b"])
    monkeypatch.setattr(boot, "warmup_model", lambda *a, **k: None)

    def never(*_a, **_k):
        raise AssertionError("measure_speed must only run after a fresh download")

    monkeypatch.setattr(boot, "measure_speed", never)
    boot.ensure_ollama_ready(mock_config, print_fn=lambda *_: None)


def test_measure_speed_from_ollama_counters(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"eval_count": 60, "eval_duration": 2_000_000_000}

    monkeypatch.setattr(boot.requests, "post", lambda *a, **k: Resp())
    assert boot.measure_speed("http://h", "m", keep_alive="1m", num_ctx=None) == 30.0

    class Bad(Resp):
        def json(self):
            return {"eval_count": 0}

    monkeypatch.setattr(boot.requests, "post", lambda *a, **k: Bad())
    assert boot.measure_speed("http://h", "m", keep_alive="1m", num_ctx=None) is None
