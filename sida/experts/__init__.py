"""Code that belongs to one expert domain. One folder per domain; the shared core is `sida/`.

A domain plugs into the core through an optional `hooks.py` in its folder, so the core never
imports a domain by name and adding a domain touches no shared file. `hooks.py` may define:

  prompt_blocks(run: ExpertRun) -> list[PromptBlock]
      Text to add to an expert's prompt (site facts, retrieved statutes, ...). Called for
      every expert run; return [] for experts the domain has nothing for. Report problems
      with `run.warn(message)` and carry on — a hook must not stop the expert run.
  COMMANDS: dict[str, handler]
      Slash commands for the terminal session, e.g. {"/site": cmd_site}. A handler takes
      (session, argument string) and returns "continue", "close" or "quit".

Folders are discovered automatically and called in alphabetical order.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType

FACTS = "facts"  # right after the brief; always sent whole
KNOWLEDGE = "knowledge"  # after the expert outputs; trimmed to fit a local model's context
SLOTS = (FACTS, KNOWLEDGE)


@dataclass(frozen=True)
class ExpertRun:
    """What a hook may read about the expert run it contributes to."""

    config: dict
    agent: dict
    project_dir: Path
    project_brief: str
    project_state: str | None
    previous_outputs: str
    warn: Callable[[str], None]


@dataclass(frozen=True)
class PromptBlock:
    text: str
    slot: str = FACTS


@lru_cache(maxsize=1)
def domain_hooks() -> tuple[tuple[str, ModuleType], ...]:
    """(domain, hooks module) for every `sida/experts/<domain>/hooks.py`, alphabetically."""
    found = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if not info.ispkg:
            continue
        name = f"{__name__}.{info.name}.hooks"
        try:
            found.append((info.name, importlib.import_module(name)))
        except ModuleNotFoundError as exc:
            if exc.name != name:  # the domain has hooks, and they are broken: say so
                raise
    return tuple(found)


def collect_prompt_blocks(run: ExpertRun, hooks=None) -> dict[str, str]:
    """Ask every domain for prompt text; returns the joined text per slot ("" when none)."""
    from sida.i18n import t

    parts: dict[str, list[str]] = {slot: [] for slot in SLOTS}
    for domain, module in domain_hooks() if hooks is None else hooks:
        provide = getattr(module, "prompt_blocks", None)
        if provide is None:
            continue
        try:
            blocks = [b for b in provide(run) if b.text and b.text.strip()]
            unknown = [b.slot for b in blocks if b.slot not in SLOTS]
            if unknown:
                raise ValueError(f"unknown prompt slot {unknown[0]!r}")
        except Exception as exc:  # a domain's context must never block the expert run
            run.warn(t("expert_hook_failed", domain=domain, reason=str(exc) or type(exc).__name__))
            continue
        for block in blocks:
            parts[block.slot].append(block.text.strip())
    return {slot: "\n\n".join(texts) for slot, texts in parts.items()}


def expert_commands(hooks=None) -> dict[str, Callable]:
    """Slash commands contributed by the domains. The first domain to claim a name keeps it."""
    commands: dict[str, Callable] = {}
    for _domain, module in domain_hooks() if hooks is None else hooks:
        for name, handler in (getattr(module, "COMMANDS", None) or {}).items():
            commands.setdefault(name.lower(), handler)
    return commands
