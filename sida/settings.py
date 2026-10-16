"""This machine's settings for the web settings screen.

Reads the effective settings (config.yaml overlaid with config.local.yaml) and writes
changes to config.local.yaml only; config.yaml holds team defaults and is never written
here. API keys go to .env. Key values are never returned, only whether each is set and
its last four characters.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from sida import hardware, runtime, setup_env
from sida.config import ROOT, local_config_path
from sida.experts.regulation.rag import key_missing, rag_settings

ENV_PATH = ROOT / ".env"
MODES = ("cloud", "local")
MODE_PROVIDER = {"cloud": "openrouter", "local": "ollama"}
WEB_PROVIDERS = ("openrouter", "ollama")
STATE_MODES = ("ask", "auto", "off")
LOCAL_CONFIG_HEADER = (
    "# This machine only — not committed. Values here override config.yaml.\n"
    "# Change them from the settings screen or edit this file directly.\n"
)

# Keys the settings screen can set: id → .env name. `secret: False` values are shown in full.
KEYS: dict[str, dict[str, Any]] = {
    "openrouter": {"env": "OPENROUTER_API_KEY", "secret": True},
    "openai": {"env": "OPENAI_API_KEY", "secret": True},
    "vworld": {"env": "VWORLD_API_KEY", "secret": True},
    "vworld_domain": {"env": "VWORLD_DOMAIN", "secret": False},
    "data_go_kr": {"env": "DATA_GO_KR_API_KEY", "secret": True},
    "law": {"env": "LAW_OPEN_API_OC", "secret": True},
}


# ---------------------------------------------------------------------------
# config.local.yaml
# ---------------------------------------------------------------------------


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if re.search(r"[:#\[\]{}&*!|>'\"%@`]", text) or text != text.strip():
        return repr(text)
    return text


def set_section_key(text: str, section: str, key: str, value: Any) -> str:
    """
    Replace `key:` under a top-level `section:` block. Preserves trailing comments
    on the same line when present. Inserts the key if missing inside the section.
    """
    raw = _yaml_scalar(value)
    lines = text.splitlines(keepends=True)
    section_re = re.compile(rf"^{re.escape(section)}:\s*(?:#.*)?$")
    key_re = re.compile(rf"^([ \t]*){re.escape(key)}\s*:(.*)$")
    top_re = re.compile(r"^[A-Za-z_][\w-]*\s*:")

    start = None
    for i, line in enumerate(lines):
        if section_re.match(line.rstrip("\n\r")):
            start = i
            break
    if start is None:
        sep = "" if text.endswith("\n") or not text else "\n"
        return f"{text}{sep}\n{section}:\n  {key}: {raw}\n"

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if top_re.match(lines[j]) and not lines[j].startswith((" ", "\t")):
            end = j
            break

    indent = "  "
    for j in range(start + 1, end):
        m = key_re.match(lines[j].rstrip("\n\r"))
        if not m:
            continue
        indent = m.group(1) or "  "
        rest = m.group(2)
        comment = ""
        if " #" in rest:
            comment = " #" + rest.split(" #", 1)[1].rstrip()
        nl = "\n" if lines[j].endswith("\n") else ""
        lines[j] = f"{indent}{key}: {raw}{comment}{nl}"
        return "".join(lines)

    lines.insert(start + 1, f"{indent}{key}: {raw}\n")
    return "".join(lines)


def save_config_patches(patches: list[tuple[str, str, Any]], *, path: Path | None = None) -> Path:
    """Apply (section, key, value) patches to config.local.yaml (created if missing)."""
    path = path or local_config_path()
    text = path.read_text(encoding="utf-8") if path.exists() else LOCAL_CONFIG_HEADER
    for section, key, value in patches:
        text = set_section_key(text, section, key, value)
    path.write_text(text, encoding="utf-8")
    return path


def run_mode_patches(mode: str, profile: str | None = None) -> list[tuple[str, str, Any]]:
    """Config patches for a run mode: cloud = OpenRouter, local = Ollama (both roles)."""
    provider = MODE_PROVIDER[mode]
    patches: list[tuple[str, str, Any]] = [
        ("conductor", "provider", provider),
        ("worker", "provider", provider),
    ]
    if mode == "local" and profile:
        patches.append(("conductor", "local_profile", profile))
    return patches


def current_run_mode(config: dict) -> str:
    """cloud | local | custom (roles differ, or mock)."""
    c = runtime.resolve_conductor_runtime(config)["provider"]
    w = runtime.resolve_worker_runtime(config)["provider"]
    if c == w == "openrouter":
        return "cloud"
    if c in {"ollama", "local"} and w in {"ollama", "local"}:
        return "local"
    return "custom"


# ---------------------------------------------------------------------------
# .env keys
# ---------------------------------------------------------------------------


def _env_values() -> dict[str, str]:
    """.env values with this process's environment on top (what the running server uses)."""
    values = {k: str(v or "") for k, v in dotenv_values(ENV_PATH).items()} if ENV_PATH.exists() else {}
    for spec in KEYS.values():
        if os.environ.get(spec["env"]):
            values[spec["env"]] = os.environ[spec["env"]]
    return values


def _hint(value: str) -> str:
    return f"…{value[-4:]}" if len(value) > 8 else ""


def key_status(key_id: str, values: dict[str, str] | None = None) -> dict:
    spec = KEYS[key_id]
    value = (values if values is not None else _env_values()).get(spec["env"], "").strip()
    status: dict[str, Any] = {"env": spec["env"], "set": bool(value)}
    if spec["secret"]:
        status["hint"] = _hint(value)
    else:
        status["value"] = value
    return status


def write_env_value(name: str, value: str, *, path: Path | None = None) -> None:
    """Set NAME=value in .env (created if missing), keeping every other line as it is."""
    path = path or ENV_PATH
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    line = f"{name}={value}"
    pattern = re.compile(rf"^\s*#?\s*{re.escape(name)}\s*=")
    for i, old in enumerate(lines):
        if pattern.match(old):
            lines[i] = line
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _verify(key_id: str, value: str) -> tuple[bool, str] | None:
    """Check a model key against its service before saving; None for keys with no check."""
    if key_id == "openrouter":
        return setup_env.verify_api_key(value)
    if key_id == "openai":
        return setup_env.verify_openai_api_key(value)
    return None


def set_key(key_id: str, value: str) -> dict:
    """
    Save one key to .env and to this process, so the running server uses it at once.
    OpenRouter and OpenAI keys are checked first and not saved when the service rejects
    them (ValueError). Government keys are saved as given.
    """
    if key_id not in KEYS:
        raise LookupError(key_id)
    value = (value or "").strip().strip('"').strip("'")
    if not value or any(c in value for c in "\r\n"):
        raise ValueError("value must be one non-empty line")
    check = _verify(key_id, value)
    if check is not None and not check[0]:
        raise ValueError(f"{key_id} key rejected: {check[1]}")
    env = KEYS[key_id]["env"]
    write_env_value(env, value)
    os.environ[env] = value
    return {"key": key_id, **key_status(key_id), "verified": check is not None}


# ---------------------------------------------------------------------------
# Read and change
# ---------------------------------------------------------------------------


def settings_view(config: dict) -> dict:
    """Everything the settings screen shows: current values, choices, GPU and key status."""
    conductor = runtime.resolve_conductor_runtime(config)
    worker = runtime.resolve_worker_runtime(config)
    rag = rag_settings(config)
    gpu = hardware.detect_gpu()
    values = _env_values()
    profiles = [str(p) for p in (config.get("local_profiles") or {})]
    return {
        "first_run": not local_config_path().exists(),
        "mode": current_run_mode(config),
        "local_profile": str((config.get("conductor") or {}).get("local_profile") or "local"),
        "conductor": {"provider": conductor["provider"], "model": conductor["model"]},
        "worker": {"provider": worker["provider"], "model": worker["model"]},
        "rag_enabled": bool(rag["enabled"]),
        "state_update": str((config.get("state_update") or {}).get("mode") or "ask"),
        "gpu": (
            {
                "name": gpu["name"],
                "vram_gb": hardware.vram_gb(gpu),
                "recommended_profile": hardware.recommend_profile(gpu["vram_mb"]),
            }
            if gpu
            else None
        ),
        "keys": {key_id: key_status(key_id, values) for key_id in KEYS},
        "warnings": {
            "openrouter_key_missing": runtime.needs_openrouter(config)
            and not values.get("OPENROUTER_API_KEY", "").strip(),
            "rag_key_missing": key_missing(rag),
        },
        "options": {
            "modes": list(MODES),
            "providers": list(WEB_PROVIDERS),
            "local_profiles": profiles,
            "state_update": list(STATE_MODES),
        },
    }


def _choice(field: str, value: Any, options: tuple[str, ...] | list[str]) -> str:
    if value not in options:
        raise ValueError(f"{field} must be one of: {', '.join(options)}")
    return str(value)


def settings_patches(config: dict, changes: dict) -> list[tuple[str, str, Any]]:
    """
    config.local.yaml patches for the fields given; absent (None) fields stay as they are.
    `mode` sets both roles; `conductor_provider` / `worker_provider` set one role and
    apply after `mode`. Raises ValueError on a value outside the choices.
    """
    profiles = [str(p) for p in (config.get("local_profiles") or {})]
    patches: list[tuple[str, str, Any]] = []
    profile = changes.get("local_profile")
    if profile is not None:
        profile = _choice("local_profile", profile, profiles)
    if changes.get("mode") is not None:
        patches += run_mode_patches(_choice("mode", changes["mode"], MODES))
    if profile is not None:
        patches.append(("conductor", "local_profile", profile))
    for role in ("conductor", "worker"):
        value = changes.get(f"{role}_provider")
        if value is not None:
            patches.append((role, "provider", _choice(f"{role}_provider", value, WEB_PROVIDERS)))
    if changes.get("rag_enabled") is not None:
        if not isinstance(changes["rag_enabled"], bool):
            raise ValueError("rag_enabled must be true or false")
        patches.append(("rag", "enabled", changes["rag_enabled"]))
    if changes.get("state_update") is not None:
        patches.append(("state_update", "mode", _choice("state_update", changes["state_update"], STATE_MODES)))
    return patches


def update_settings(config: dict, changes: dict) -> None:
    """Write the given changes to config.local.yaml (validated first; nothing written on error)."""
    # Written even with no changes: the file existing is what marks setup as done (first_run).
    save_config_patches(settings_patches(config, changes))
