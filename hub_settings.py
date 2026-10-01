#!/usr/bin/env python3
"""Hub settings menu — writes this machine's config.local.yaml.

config.yaml holds team defaults and is never written here; choices land in the
git-ignored config.local.yaml, which load_config overlays on top.

Supports run mode (cloud / local), Conductor/Worker provider, local GPU profile,
RAG on/off, state_update mode, API keys, and UI language.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from console import prompt_line
from hardware import detect_gpu, recommend_profile, vram_gb
from harness import (
    CONFIG_PATH,
    load_config,
    local_config_path,
    needs_openrouter,
    resolve_conductor_runtime,
    resolve_worker_runtime,
)
from i18n import get_language, t

PROVIDERS = ("ollama", "openrouter", "mock")
PROFILES = ("local", "local_plus")
STATE_MODES = ("ask", "auto", "off")
MODE_PROVIDER = {"cloud": "openrouter", "local": "ollama"}
LOCAL_CONFIG_HEADER = (
    "# This machine only — not committed. Values here override config.yaml.\n"
    "# Change them from the hub (c = settings) or edit this file directly.\n"
)


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
    c = resolve_conductor_runtime(config)["provider"]
    w = resolve_worker_runtime(config)["provider"]
    if c == w == "openrouter":
        return "cloud"
    if c in {"ollama", "local"} and w in {"ollama", "local"}:
        return "local"
    return "custom"


def choose_run_mode(*, config_path: Path | None = None, first_run: bool = False) -> str | None:
    """
    Ask cloud vs local and save it to config.local.yaml.
    Enter picks cloud on first run. Returns the mode, or None if cancelled.
    """
    base = config_path or CONFIG_PATH
    print()
    print("=" * 40)
    print(f"  {t('mode_title')}")
    print("=" * 40)
    print(t("mode_intro"))
    gpu = detect_gpu()
    rec = recommend_profile(gpu["vram_mb"]) if gpu else None
    if gpu:
        key = "mode_detected_local" if rec else "mode_detected_cloud"
        print(t(key, name=gpu["name"], gb=vram_gb(gpu), rec=rec or ""))
    print()
    raw = prompt_line(t("mode_prompt_first") if first_run else t("mode_prompt"))
    if raw is None:
        return None
    raw = raw.strip().lower()
    if raw in {"1", "cloud", "c", "클라우드"} or (first_run and raw == ""):
        mode = "cloud"
    elif raw in {"2", "local", "l", "로컬"}:
        mode = "local"
    else:
        if raw:
            print(t("hub_invalid"))
        return None

    profile = None
    if mode == "local":
        # Pre-select what the detected GPU can run; otherwise keep the configured profile.
        cur = rec or str(
            (load_config(base).get("conductor") or {}).get("local_profile") or "local"
        )
        profile = _pick(t("set_pick_profile"), PROFILES, cur) or cur
    save_config_patches(run_mode_patches(mode, profile), path=local_config_path(base))
    print(t("mode_saved", mode=t(f"mode_name_{mode}")))
    if first_run:
        print(t("mode_change_later"))
    return mode


def ensure_run_mode(*, config_path: Path | None = None) -> None:
    """First launch on this machine (no config.local.yaml yet): ask cloud vs local."""
    if local_config_path(config_path or CONFIG_PATH).exists():
        return
    choose_run_mode(config_path=config_path, first_run=True)


def settings_summary(config: dict) -> str:
    c = resolve_conductor_runtime(config)
    w = resolve_worker_runtime(config)
    rag = config.get("rag") or {}
    su = config.get("state_update") or {}
    lang = get_language()
    or_needed = needs_openrouter(config)
    lines = [
        t("set_line_mode", mode=t(f"mode_name_{current_run_mode(config)}")),
        t(
            "set_line_conductor",
            provider=c["provider"],
            profile=c.get("local_profile") or "-",
            model=c["model"],
        ),
        t("set_line_worker", provider=w["provider"], model=w["model"]),
        t(
            "set_line_rag",
            enabled=("on" if rag.get("enabled") else "off"),
            provider=str(rag.get("provider") or "-"),
        ),
        t(
            "set_line_state",
            mode=str(su.get("mode") or "ask"),
            provider=str(su.get("provider") or "worker"),
        ),
        t("set_line_lang", lang=lang),
        t("set_line_openrouter", status=t("set_or_needed") if or_needed else t("set_or_skip")),
    ]
    return "\n".join(lines)


def settings_one_liner(config: dict) -> str:
    c = resolve_conductor_runtime(config)
    w = resolve_worker_runtime(config)
    rag_on = "rag:on" if (config.get("rag") or {}).get("enabled") else "rag:off"
    return f"C:{c['provider']}/{c['model']}  W:{w['provider']}/{w['model']}  {rag_on}"


def _pick(label: str, options: tuple[str, ...], current: str) -> str | None:
    print(label)
    for i, opt in enumerate(options, start=1):
        mark = " *" if opt == current else ""
        print(f"  {i}) {opt}{mark}")
    print(f"  0) {t('set_cancel')}")
    raw = prompt_line(t("set_prompt"))
    if raw is None or raw.strip() in {"", "0", "b", "back", "q"}:
        return None
    raw = raw.strip().lower()
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(options):
            return options[idx - 1]
        print(t("hub_invalid"))
        return None
    if raw in options:
        return raw
    print(t("hub_invalid"))
    return None


def _toggle_bool(current: bool) -> bool | None:
    nxt = not current
    print(t("set_toggle", cur=("on" if current else "off"), nxt=("on" if nxt else "off")))
    ans = prompt_line(t("set_confirm"))
    if ans is None:
        return None
    a = ans.strip().lower()
    if a in {"", "y", "yes", "ㅇ", "네"}:
        return nxt
    return None


def hub_settings_menu(*, config_path: Path | None = None) -> dict:
    """
    Interactive settings loop. Writes config.local.yaml / language / API key as chosen.
    Returns the reloaded config dict.
    """
    base = config_path or CONFIG_PATH
    path = local_config_path(base)
    while True:
        config = load_config(base)
        print()
        print("=" * 40)
        print(f"  {t('set_title')}")
        print("=" * 40)
        print(settings_summary(config))
        print(t("set_line_file", path=str(path)))
        print()
        print(t("set_menu"))
        print()
        choice = prompt_line(t("set_prompt"))
        if choice is None or choice.strip().lower() in {"", "0", "b", "back", "q"}:
            return load_config(base)
        choice = choice.strip().lower()

        c_rt = resolve_conductor_runtime(config)
        w_rt = resolve_worker_runtime(config)
        rag = dict(config.get("rag") or {})
        su = dict(config.get("state_update") or {})

        if choice in {"1", "c", "conductor"}:
            picked = _pick(t("set_pick_conductor"), PROVIDERS, c_rt["provider"])
            if picked:
                save_config_patches([("conductor", "provider", picked)], path=path)
                print(t("set_saved", what=f"conductor.provider={picked}"))
            continue

        if choice in {"2", "w", "worker"}:
            picked = _pick(t("set_pick_worker"), PROVIDERS, w_rt["provider"])
            if picked:
                save_config_patches([("worker", "provider", picked)], path=path)
                print(t("set_saved", what=f"worker.provider={picked}"))
            continue

        if choice in {"3", "p", "profile"}:
            cur = str((config.get("conductor") or {}).get("local_profile") or "local")
            picked = _pick(t("set_pick_profile"), PROFILES, cur)
            if picked:
                save_config_patches([("conductor", "local_profile", picked)], path=path)
                print(t("set_saved", what=f"conductor.local_profile={picked}"))
            continue

        if choice in {"4", "r", "rag"}:
            cur = bool(rag.get("enabled", False))
            nxt = _toggle_bool(cur)
            if nxt is not None:
                save_config_patches([("rag", "enabled", nxt)], path=path)
                print(t("set_saved", what=f"rag.enabled={nxt}"))
            continue

        if choice in {"5", "s", "state"}:
            cur = str(su.get("mode") or "ask")
            picked = _pick(t("set_pick_state"), STATE_MODES, cur)
            if picked:
                save_config_patches([("state_update", "mode", picked)], path=path)
                print(t("set_saved", what=f"state_update.mode={picked}"))
            continue

        if choice in {"6", "k", "key", "api"}:
            from setup_env import setup_api_key

            setup_api_key(force=True)
            continue

        if choice in {"7", "openai", "oai"}:
            from setup_env import setup_openai_api_key

            setup_openai_api_key(force=True)
            continue

        if choice in {"8", "l", "lang", "language"}:
            from setup_env import prompt_language

            prompt_language(force=True)
            continue

        if choice in {"9", "m", "mode"}:
            choose_run_mode(config_path=base)
            continue

        print(t("hub_invalid"))
