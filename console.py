#!/usr/bin/env python3
"""Small console helpers: prompts, external editor, stdio encoding."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def configure_stdio() -> None:
    """Force UTF-8 on stdout/stderr (Windows consoles default to cp949 etc.)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def prompt_line(label: str) -> str | None:
    """Return stripped input, or None if cancelled (Ctrl+C / EOF)."""
    try:
        return input(label).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def one_line(text: str, limit: int = 70) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def resolve_editor() -> list[str] | None:
    """
    Editor command as argv, from (in order): SIDA_EDITOR, VISUAL, EDITOR,
    then a platform default (notepad on Windows; nano/vim/vi elsewhere).
    """
    for var in ("SIDA_EDITOR", "VISUAL", "EDITOR"):
        value = os.environ.get(var, "").strip()
        if value:
            if os.name == "nt":
                # Non-POSIX split keeps quotes on tokens; drop them so paths with spaces work.
                return [tok.strip('"') for tok in shlex.split(value, posix=False)]
            return shlex.split(value)
    if os.name == "nt":
        return ["notepad"]
    for candidate in ("nano", "vim", "vi"):
        if shutil.which(candidate):
            return [candidate]
    return None


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def open_in_editor(path: Path, *, editor: list[str] | None = None) -> tuple[bool, str]:
    """
    Open `path` in an external editor and block until it closes.
    Returns (changed, editor_name). Raises RuntimeError when no editor can run.
    """
    argv = editor or resolve_editor()
    if not argv:
        raise RuntimeError("no editor found")
    before = _digest(path)
    try:
        subprocess.call([*argv, str(path)])
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(str(exc)) from exc
    return _digest(path) != before, argv[0]
