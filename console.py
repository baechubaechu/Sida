#!/usr/bin/env python3
"""Small console helpers: prompts, external editor, stdio encoding, busy spinner."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# ANSI / xterm-256 friendly names. Values are SGR params after ESC[.
_FG = {
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "bright_red": "91",
    "bright_green": "92",
    "bright_yellow": "93",
    "bright_blue": "94",
    "bright_magenta": "95",
    "bright_cyan": "96",
    "bright_white": "97",
}

# Stable per-expert look: short tag + color (phase-ish but unique).
AGENT_LOOK: dict[str, tuple[str, str]] = {
    "site_reader": ("SR", "cyan"),
    "program_analyst": ("PA", "blue"),
    "regulation_checker": ("RC", "yellow"),
    "precedent_scout": ("PS", "magenta"),
    "concept_framer": ("CF", "bright_magenta"),
    "constraint_mapper": ("CM", "bright_yellow"),
    "synthesizer": ("SY", "bright_white"),
    "spatial_reviewer": ("SP", "green"),
    "systems_advisor": ("SA", "bright_green"),
    "design_critic": ("DC", "bright_red"),
    "representation_planner": ("RP", "bright_cyan"),
    "presentation_editor": ("PE", "bright_blue"),
}

ROLE_COLOR = {
    "conductor": "bright_white",
    "action_recovery": "dim",
    "state_update": "dim",
    "rag": "yellow",
    "law_search": "yellow",
    "modeling": "bright_cyan",
    "worker": "cyan",
}

_vt_enabled = False


def configure_stdio() -> None:
    """Force UTF-8 on stdout/stderr (Windows consoles default to cp949 etc.)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    _ensure_windows_vt()


def _ensure_windows_vt() -> None:
    """Enable ANSI escape processing on Windows consoles (once)."""
    global _vt_enabled
    if _vt_enabled or os.name != "nt":
        _vt_enabled = True
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL
        _vt_enabled = True
    except Exception:
        _vt_enabled = True  # don't retry forever


def color_enabled(stream=None) -> bool:
    """True when ANSI colors should be emitted (TTY, no NO_COLOR)."""
    if os.environ.get("NO_COLOR", "").strip():
        return False
    if os.environ.get("FORCE_COLOR", "").strip():
        return True
    out = stream or sys.stdout
    if not getattr(out, "isatty", lambda: False)():
        return False
    _ensure_windows_vt()
    return True


def paint(text: str, color: str | None = None, *, bold: bool = False, stream=None) -> str:
    """Wrap text in ANSI color when the stream supports it; else return plain."""
    if not color and not bold:
        return text
    if not color_enabled(stream):
        return text
    parts: list[str] = []
    if bold:
        parts.append("1")
    if color:
        code = _FG.get(color)
        if code:
            parts.append(code)
    if not parts:
        return text
    return f"\033[{';'.join(parts)}m{text}\033[0m"


def agent_look(agent_id: str | None) -> tuple[str, str]:
    """Return (tag, color_name) for an expert id."""
    aid = str(agent_id or "").strip()
    if aid in AGENT_LOOK:
        return AGENT_LOOK[aid]
    tag = (aid[:2] or "??").upper()
    # Stable fallback from id hash into the bright palette.
    palette = (
        "cyan",
        "blue",
        "yellow",
        "magenta",
        "green",
        "bright_cyan",
        "bright_blue",
        "bright_yellow",
        "bright_magenta",
        "bright_green",
    )
    return tag, palette[sum(ord(c) for c in aid) % len(palette)]


def agent_color(agent_id: str | None) -> str:
    return agent_look(agent_id)[1]


def agent_badge(agent: dict | str, *, stream=None) -> str:
    """Colored `[TAG] Name` for module banners."""
    if isinstance(agent, dict):
        aid = str(agent.get("id") or "")
        name = str(agent.get("name") or aid)
    else:
        aid = str(agent)
        name = aid
    tag, color = agent_look(aid)
    return paint(f"[{tag}] {name}", color, bold=True, stream=stream)


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


@contextmanager
def busy_line(message: str, *, stream=None, color: str | None = None) -> Iterator[None]:
    """
    Show a spinner on stderr while the body runs (LLM / network waits).
    No-op when stderr is not a TTY (pytest, pipes).
    """
    out = stream or sys.stderr
    if not getattr(out, "isatty", lambda: False)():
        yield
        return

    stop = threading.Event()
    frames = "|/-\\"
    use_color = color_enabled(out)

    def spin() -> None:
        i = 0
        while not stop.is_set():
            frame = frames[i % len(frames)]
            body = paint(f"{frame} {message}", color, stream=out) if use_color and color else f"{frame} {message}"
            try:
                out.write(f"\r{body}\033[K" if use_color else f"\r{body}")
                out.flush()
            except Exception:
                break
            i += 1
            stop.wait(0.12)
        try:
            if use_color:
                out.write("\r\033[K")
            else:
                out.write("\r" + " " * (len(message) + 4) + "\r")
            out.flush()
        except Exception:
            pass

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)


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
