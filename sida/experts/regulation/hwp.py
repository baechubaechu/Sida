#!/usr/bin/env python3
"""Plain text out of an HWP 5 file (the format law.go.kr serves ordinance annexes in).

Only what is needed to read an annex: the paragraphs in document order, table cells
included (each cell is its own paragraph). No layout, no styles.
"""

from __future__ import annotations

import io
import struct
import zlib

import olefile

_PARA_TEXT = 67  # HWPTAG_PARA_TEXT
# Control codes that are a single character; every other code below 32 is a control that
# occupies 8 characters (the code, 6 of payload, the code again).
_CHAR_CONTROLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


class HwpError(ValueError):
    """The bytes are not an HWP 5 document this reader understands."""


def _paragraph(raw: bytes) -> str:
    units = struct.unpack(f"<{len(raw) // 2}H", raw[: len(raw) // 2 * 2])
    out: list[str] = []
    i = 0
    while i < len(units):
        code = units[i]
        if code >= 32:
            out.append(chr(code))
            i += 1
        elif code in _CHAR_CONTROLS:
            out.append(" ")
            i += 1
        else:
            i += 8
    return " ".join("".join(out).split())


def paragraphs(data: bytes) -> list[str]:
    """Non-empty paragraphs of an HWP 5 file, in order. Raises HwpError."""
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
        header = ole.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File"):
            raise HwpError("not an HWP document")
        compressed = bool(header[36] & 1)
        sections = sorted(
            (entry for entry in ole.listdir() if entry[0] == "BodyText"),
            key=lambda entry: int(entry[-1].replace("Section", "") or 0),
        )
        out: list[str] = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            pos = 0
            while pos + 4 <= len(raw):
                head = struct.unpack_from("<I", raw, pos)[0]
                tag, size = head & 0x3FF, head >> 20
                pos += 4
                if size == 0xFFF:
                    size = struct.unpack_from("<I", raw, pos)[0]
                    pos += 4
                if tag == _PARA_TEXT:
                    text = _paragraph(raw[pos : pos + size])
                    if text:
                        out.append(text)
                pos += size
        return out
    except HwpError:
        raise
    except Exception as exc:  # olefile / zlib / struct: a damaged or different file
        raise HwpError(f"{type(exc).__name__}: {exc}") from exc
