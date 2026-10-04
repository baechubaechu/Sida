"""Remember exactly which expert output versions are represented in project state.

Revisions live in one reserved Markdown comment in project_state.md, so accepting
state and its revision record is a single atomic file save. No timestamps or network.
"""

from __future__ import annotations

import hashlib
import json
import re

_REVISIONS = re.compile(r"^<!-- sida-module-revisions: (.*?) -->\s*$", re.MULTILINE)
_HASH = re.compile(r"[0-9a-f]{64}")


def content_revision(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def module_revisions(state: str) -> dict[str, str]:
    match = _REVISIONS.search(state)
    if match is None:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: value for key, value in data.items()
        if isinstance(key, str) and isinstance(value, str) and _HASH.fullmatch(value)
    }


def without_revisions(state: str) -> str:
    """Hide internal bookkeeping from model prompts and human-readable diffs."""
    return _REVISIONS.sub("", state).rstrip() + "\n"


def record_module_revision(state: str, module_id: str, output: str) -> str:
    revisions = module_revisions(state)
    revisions[module_id] = content_revision(output)
    record = json.dumps(revisions, ensure_ascii=False, sort_keys=True)
    return without_revisions(state).rstrip() + f"\n\n<!-- sida-module-revisions: {record} -->\n"


def preserve_revisions(edited: str, previous: str) -> str:
    """Keep trusted bookkeeping while accepting designer-authored Markdown."""
    body = without_revisions(edited)
    revisions = module_revisions(previous)
    if not revisions:
        return body
    record = json.dumps(revisions, ensure_ascii=False, sort_keys=True)
    return body.rstrip() + f"\n\n<!-- sida-module-revisions: {record} -->\n"
