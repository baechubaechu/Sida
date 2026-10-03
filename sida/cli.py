"""Translate application errors to terminal output only at CLI entry points."""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from sida.errors import SidaError

P = ParamSpec("P")
T = TypeVar("T")


def cli_entrypoint(main: Callable[P, T]) -> Callable[P, T]:
    @wraps(main)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return main(*args, **kwargs)
        except SidaError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            raise SystemExit(exc.code) from None

    return wrapped
