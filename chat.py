#!/usr/bin/env python3
"""Sida CLI entry point — first-run setup, project hub, Conductor sessions.

Module layout:
  chat.py       entry point (this file)
  hub.py        project picker
  session.py    one Conductor session: state, turns, actions, loop
  commands.py   slash commands inside a session
  conductor.py  Conductor message assembly + one LLM call
  briefs.py     brief.md authoring (guided fields / external editor)
  console.py    prompts, editor launch, UTF-8 stdio
  harness.py    providers (OpenRouter / Ollama / mock), workers, context budget
  project.py    project folder I/O
  i18n.py       UI strings (Korean default, English fallback)
  setup_env.py  language + API key setup
"""

from __future__ import annotations

import sys
from pathlib import Path

from console import configure_stdio
from harness import fail
from hub import project_hub
from i18n import has_language, t
from project import list_projects, projects_dir
from session import run_session


def ensure_app_setup() -> None:
    """Language + API key only. No project creation here."""
    from setup_env import ensure_api_key, prompt_language, read_api_key_from_env

    configure_stdio()
    if not has_language():
        prompt_language(force=False)
        print()

    print("=" * 40)
    print(f"  {t('welcome_title')}")
    print("=" * 40)
    print(t("welcome_body"))
    print()

    had_key = bool(read_api_key_from_env())
    if not had_key:
        print(t("api_missing"))
        print()
    ensure_api_key(interactive=True)
    if not had_key:
        print()


def print_usage() -> None:
    print("Usage:")
    print("  python chat.py")
    print("  python chat.py sample_brief")
    print("  python chat.py input/project_brief.md")
    print("  python chat.py --name my_project input/brief.md")
    print("  python chat.py --list")
    print("  python setup_env.py")


def main() -> None:
    args = sys.argv[1:]

    if args and args[0] in {"-h", "--help"}:
        print_usage()
        raise SystemExit(0)

    if args and args[0] == "--list":
        ensure_app_setup()
        root = projects_dir()
        projects = list_projects()
        print(t("sess_projects_root", path=root))
        if not projects:
            print(t("hub_empty"))
            return
        print(t("hub_projects_list"))
        for path in projects:
            print(f"  {path}")
        return

    ensure_app_setup()

    initial: Path | None = None
    project_name = None
    if args:
        if args[0] == "--name":
            if len(args) < 3:
                fail("Usage: python chat.py --name my_project input/brief.md")
            project_name = args[1]
            initial = Path(args[2])
        else:
            initial = Path(args[0])

    while True:
        created: bool | None = None
        if initial is not None:
            target, name = initial, project_name
            initial, project_name = None, None
        else:
            choice = project_hub()
            name = None
            if choice is None:
                print(t("hub_goodbye"))
                break
            target, created = choice

        outcome = run_session(target, project_name=name, created=created)
        if outcome == "quit":
            break
        print(t("hub_closed"))


if __name__ == "__main__":
    main()
