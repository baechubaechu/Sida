#!/usr/bin/env python3
"""Start Ollama and warm the Conductor model when the app opens a local session.

Does nothing unless conductor.provider is ollama/local. Never fails the app for a
missing model download — pull is optional (ask/auto/off).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

from harness import DEFAULT_OLLAMA_URL, LLMError, resolve_conductor_runtime


def ollama_boot_settings(config: dict) -> dict:
    c = config.get("conductor") or {}
    pull = str(c.get("ollama_pull_missing", "ask")).lower()
    if pull not in {"ask", "auto", "off"}:
        pull = "ask"
    return {
        "autostart": bool(c.get("ollama_autostart", True)),
        "pull_missing": pull,
        "warmup": bool(c.get("ollama_warmup", True)),
        "keep_alive": str(c.get("ollama_keep_alive", "30m")),
        "wait_seconds": float(c.get("ollama_wait_seconds", 45)),
    }


def _base_url(runtime: dict) -> str:
    url = (runtime.get("base_url") or DEFAULT_OLLAMA_URL).rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    return url


def ollama_reachable(base_url: str, *, timeout: float = 1.5) -> bool:
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def list_ollama_models(base_url: str) -> list[str]:
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=5)
        r.raise_for_status()
        models = r.json().get("models") or []
    except (requests.RequestException, ValueError, TypeError):
        return []
    names: list[str] = []
    for m in models:
        if isinstance(m, dict) and m.get("name"):
            names.append(str(m["name"]))
    return names


def model_is_present(names: list[str], wanted: str) -> bool:
    """Match `qwen3.5:9b` against tags like `qwen3.5:9b` or `qwen3.5:9b-q4_K_M`."""
    w = wanted.strip().lower()
    if not w:
        return False
    for name in names:
        n = name.lower()
        if n == w or n.startswith(w + "-") or n.startswith(w + "@"):
            return True
    return False


def _find_ollama_bin() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(local) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
        ]
        for path in candidates:
            if path.is_file():
                return str(path)
    return None


def try_start_ollama() -> str | None:
    """
    Launch the Ollama server in the background. Returns a short status note,
    or None if no binary was found.
    """
    binary = _find_ollama_bin()
    if not binary:
        return None
    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        # Prefer the installed app (registers the tray service) when present.
        app = Path(binary).with_name("ollama app.exe")
        if app.is_file():
            try:
                subprocess.Popen(
                    [str(app)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation,
                    close_fds=True,
                )
                return f"started {app.name}"
            except OSError:
                pass
    try:
        kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = creation
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([binary, "serve"], **kwargs)
        return f"started `{binary} serve`"
    except OSError:
        return None


def wait_until_reachable(base_url: str, *, seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if ollama_reachable(base_url):
            return True
        time.sleep(0.5)
    return ollama_reachable(base_url)


def pull_model(base_url: str, model: str) -> None:
    """Stream a pull; raises LLMError on failure. Blocks until done."""
    try:
        with requests.post(
            f"{base_url}/api/pull",
            json={"name": model, "stream": False},
            timeout=3600,
        ) as response:
            if response.status_code != 200:
                raise LLMError(
                    f"ollama pull failed ({response.status_code}): {response.text[:300]}"
                )
            # Non-stream response is a final status object; check for error field.
            try:
                data = response.json()
            except ValueError:
                data = {}
            if isinstance(data, dict) and data.get("error"):
                raise LLMError(f"ollama pull failed: {data['error']}")
    except requests.RequestException as exc:
        raise LLMError(f"ollama pull failed: {exc}") from exc


def warmup_model(base_url: str, model: str, *, keep_alive: str, num_ctx: int | None) -> None:
    """Load weights into VRAM with a 1-token generate; keep_alive holds them."""
    options: dict[str, Any] = {"num_predict": 1}
    if num_ctx:
        options["num_ctx"] = int(num_ctx)
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "keep_alive": keep_alive,
        "options": options,
    }
    try:
        r = requests.post(f"{base_url}/api/chat", json=body, timeout=300)
    except requests.RequestException as exc:
        raise LLMError(f"Ollama warmup failed: {exc}") from exc
    if r.status_code == 404:
        raise LLMError(f"Ollama model '{model}' not found. Run: ollama pull {model}")
    if r.status_code != 200:
        raise LLMError(f"Ollama warmup failed ({r.status_code}): {r.text[:300]}")


def ensure_ollama_ready(
    config: dict,
    *,
    prompt_fn=None,
    print_fn=print,
) -> None:
    """
    If Conductor uses Ollama: start server if needed, ensure model exists, warm it.
    Raises LLMError when the server cannot be reached after autostart attempts.
    """
    from i18n import t

    runtime = resolve_conductor_runtime(config)
    if runtime["provider"] not in {"ollama", "local"}:
        return

    settings = ollama_boot_settings(config)
    base = _base_url(runtime)
    model = str(runtime["model"])
    prompt_fn = prompt_fn or (lambda label: input(label))

    if not ollama_reachable(base):
        if not settings["autostart"]:
            raise LLMError(
                t("ollama_not_running", url=base)
            )
        print_fn(t("ollama_starting"))
        note = try_start_ollama()
        if note is None:
            raise LLMError(t("ollama_not_installed"))
        if not wait_until_reachable(base, seconds=settings["wait_seconds"]):
            raise LLMError(t("ollama_start_timeout", url=base))
        print_fn(t("ollama_started"))

    names = list_ollama_models(base)
    if not model_is_present(names, model):
        mode = settings["pull_missing"]
        if mode == "off":
            raise LLMError(t("ollama_model_missing", model=model))
        do_pull = mode == "auto"
        if mode == "ask":
            print_fn(t("ollama_model_missing_ask", model=model))
            try:
                answer = (prompt_fn(t("ollama_pull_prompt", model=model)) or "").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print_fn()
                answer = "n"
            do_pull = answer in {"", "y", "yes", "ㅇ"}
        if not do_pull:
            raise LLMError(t("ollama_model_missing", model=model))
        print_fn(t("ollama_pulling", model=model))
        pull_model(base, model)
        print_fn(t("ollama_pulled", model=model))

    if settings["warmup"]:
        print_fn(t("ollama_warming", model=model))
        warmup_model(
            base,
            model,
            keep_alive=settings["keep_alive"],
            num_ctx=runtime.get("num_ctx"),
        )
        print_fn(t("ollama_warm", model=model))
