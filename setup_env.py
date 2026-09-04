#!/usr/bin/env python3
"""Interactive first-time setup: language, then verified OpenRouter API key.

Run: python setup_env.py [--force] [--language]
(Named setup_env.py so it is never mistaken for a packaging setup.py.)
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from i18n import (
    DEFAULT_LANGUAGE,
    get_language,
    has_language,
    set_language,
    t,
)

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"


def _configure_stdio() -> None:
    from console import configure_stdio

    configure_stdio()


def _mask_key(key: str) -> str:
    key = key.strip()
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]}"


def _ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default_yes
    return answer in {"y", "yes", "ㅇ", "네", "예"}


def read_api_key_from_env() -> str:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True)
    return os.getenv("OPENROUTER_API_KEY", "").strip()


def write_api_key(api_key: str) -> None:
    api_key = api_key.strip()
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    elif ENV_EXAMPLE.exists():
        lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()

    key_line = f"OPENROUTER_API_KEY={api_key}"
    found = False
    new_lines: list[str] = []
    for line in lines:
        if re.match(r"^\s*OPENROUTER_API_KEY\s*=", line):
            new_lines.append(key_line)
            found = True
        else:
            new_lines.append(line)
    if not found:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(key_line)

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ["OPENROUTER_API_KEY"] = api_key


def verify_api_key(api_key: str) -> tuple[bool, str]:
    """Check key against OpenRouter. Returns (ok, detail)."""
    try:
        response = requests.get(
            OPENROUTER_KEY_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, "authorized"
    if response.status_code in {401, 403}:
        return False, f"unauthorized ({response.status_code})"
    return False, f"HTTP {response.status_code}: {response.text[:200]}"


def prompt_language(*, force: bool = False) -> str:
    """
    First setup screen is bilingual; Korean is the default.
    After choice, UI follows saved language. Commands stay English.
    """
    if has_language() and not force:
        return get_language()

    print()
    print("=" * 40)
    print(f"  {t('lang_title')}")
    print("=" * 40)
    print()
    print(t("lang_prompt"))
    try:
        choice = input(t("lang_input")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        choice = ""

    lang = DEFAULT_LANGUAGE
    if choice in {"2", "en", "english", "영어"}:
        lang = "en"
    elif choice in {"1", "ko", "korean", "한국어", "ㅎ", ""}:
        lang = "ko"

    set_language(lang)
    print()
    if lang == "ko":
        print(t("lang_saved_ko"))
    else:
        print(t("lang_saved"))
    return lang


def print_api_guide(*, existing: str = "") -> None:
    print()
    print("=" * 40)
    print(f"  {t('api_title')}")
    print("=" * 40)
    print()
    print(t("api_intro"))
    if existing:
        print()
        print(t("api_current_overwrite", masked=_mask_key(existing)))


def prompt_for_api_key() -> str | None:
    print()
    try:
        raw = getpass.getpass(t("api_paste")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if not raw:
        return None

    raw = raw.strip().strip('"').strip("'")
    if len(raw) < 20:
        print(t("api_too_short"))
        return None
    return raw


def setup_api_key(*, force: bool = False) -> str | None:
    """Prompt, verify, save. Retry loop on failure."""
    existing = read_api_key_from_env()
    if existing and not force:
        print(t("api_exists", masked=_mask_key(existing)))
        print(t("api_reconfigure"))
        return existing

    while True:
        print_api_guide(existing=existing if force else "")
        key = prompt_for_api_key()
        if not key:
            print(t("api_cancelled"))
            return None

        print()
        print(t("api_verifying"))
        ok, detail = verify_api_key(key)
        if ok:
            write_api_key(key)
            print()
            print(t("api_ok"))
            print(t("api_ok_detail", path=str(ENV_PATH), masked=_mask_key(key)))
            return key

        print()
        print(t("api_fail"))
        print(t("api_fail_detail", reason=detail))
        if not _ask_yes_no(t("api_retry"), default_yes=True):
            print(t("api_cancelled"))
            return None


def run_setup(*, force: bool = False, force_language: bool = False) -> str | None:
    """Full setup: language (once) → verified API key."""
    _configure_stdio()
    prompt_language(force=force_language)
    print()
    return setup_api_key(force=force or not read_api_key_from_env())


def ensure_api_key(*, interactive: bool = True) -> str:
    _configure_stdio()
    if not has_language() and interactive:
        prompt_language(force=False)
        print()

    key = read_api_key_from_env()
    if key:
        # Light check only when forcing re-setup; existing keys are trusted for speed.
        return key

    if not interactive:
        raise SystemExit(f"Error: {t('api_required')}")

    print(t("api_missing"))
    key = setup_api_key(force=True)
    if not key:
        raise SystemExit(t("api_required"))
    return key


def main() -> None:
    _configure_stdio()
    force = "--force" in sys.argv or "-f" in sys.argv
    force_lang = "--language" in sys.argv or "--lang" in sys.argv
    result = run_setup(
        force=force or not read_api_key_from_env(),
        force_language=force_lang or not has_language(),
    )
    raise SystemExit(0 if result else 1)


if __name__ == "__main__":
    main()
