"""Publish complete UTF-8 files without truncating the previous version.

The temporary file is flushed to disk and closed before replacing the destination
(including on Windows). This protects each file separately; it is not a transaction
across files or a lock against concurrent editors. Append-only transcripts and files
edited by an external editor use their own write paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from sida.errors import SidaError


def atomic_write_text(path: Path, text: str) -> None:
    """Save text with LF newlines, preserving the existing file if saving fails."""
    path = Path(path)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except (OSError, UnicodeError) as exc:
        raise SidaError(f"Could not save {path}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Do not hide the original failure if cleanup is also refused.
