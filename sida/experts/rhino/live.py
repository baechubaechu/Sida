"""Rhino as it is right now: what the plugin says about the open document, and what the panel asks of it.

The panel in Rhino is a Sida page (webui/app/rhino.html) in a web view; it talks to Sida only,
never to Rhino. Sida is the hub in between:

    plugin  --report-->  Sida  <--read--  panel page       (the document, its layers, the figures)
    plugin  <--pending-- Sida  <--ask---  panel page       (pull, push, a layer's meaning, ...)

The plugin reports the document whenever it changes (the snapshot without views and meshes, so
Sida can compute the figures while the designer models) and asks every half second for what
the panel wants done. Nothing here is saved: it is the state of a running Rhino, kept in
memory, and gone when Sida stops (the plugin sees `known: false` and reports again). A
document is "connected" while its plugin keeps asking.

Both sides ask by short polling, not by a held request: a held request would keep the server
from stopping when the designer closes Sida.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from sida.experts.rhino import snapshot

CONNECTED_FOR = 5.0   # seconds a document stays connected after its plugin last asked
MAX_DOCS = 8          # running Rhino documents remembered (the oldest is forgotten)
MAX_PENDING = 50      # commands waiting for one document
MAX_TEXT = 200

# What the panel may ask of the plugin, and the fields each command carries.
COMMANDS: dict[str, tuple[str, ...]] = {
    "pull": (),                                       # the drafting table into the document
    "push": (),                                       # a snapshot with captures to Sida
    "set_project": ("project",),                      # which Sida project the document belongs to
    "set_layer": ("path", "meaning", "floor_height"),  # a layer's meaning and floor height (m, or null)
    "set_autosync": ("on",),                          # push on every save
    "report": (),                                     # say the document again (the panel just opened)
}

_lock = threading.Lock()
_docs: dict[str, dict] = {}
_now = time.monotonic  # a test steps time by replacing this


def reset() -> None:
    """Forget every document (tests)."""
    with _lock:
        _docs.clear()


def _text(value, what: str, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{what} must be text of at most {limit} characters")
    return value.strip()


def _doc_id(value) -> str:
    doc = _text(value, "doc", 64)
    if not doc:
        raise ValueError("doc is needed (the plugin's id for the open document)")
    return doc


def clean_report(raw) -> dict:
    """What the plugin said about its document, checked. Raises ValueError with a plain reason."""
    if not isinstance(raw, dict):
        raise ValueError("the report must be a JSON object")
    out = {
        "doc": _doc_id(raw.get("doc")),
        "file": _text(raw.get("file"), "file"),
        "units": _text(raw.get("units"), "units", 20),
        "project": _text(raw.get("project"), "project"),
        "autosync": raw.get("autosync") is True,
        "snapshot": None,
        "notice": None,
    }
    if raw.get("snapshot") is not None:
        out["snapshot"] = snapshot.clean_snapshot(raw["snapshot"])
    notice = raw.get("notice")
    if isinstance(notice, dict) and notice.get("text"):
        out["notice"] = {"text": _text(notice.get("text"), "notice.text", 600), "ok": notice.get("ok") is not False}
    return out


def _layers(snap: dict) -> list[dict]:
    """The layers with how many bodies each holds, so the panel can show which still need a meaning."""
    counts: dict[str, int] = {}
    for item in snap["objects"]:
        counts[item["layer"]] = counts.get(item["layer"], 0) + 1
    return [{**layer, "objects": counts.get(layer["path"], 0)} for layer in snap["layers"]]


def _entry(doc: str) -> dict:
    """The remembered document (made when new; the least recently seen is forgotten over MAX_DOCS)."""
    entry = _docs.get(doc)
    if entry is None:
        while len(_docs) >= MAX_DOCS:
            del _docs[min(_docs, key=lambda key: _docs[key]["seen"])]
        # Command ids go on from the clock, so a plugin that outlived a restart of Sida (and
        # still says "done up to 7") does not have its next commands taken for old ones.
        entry = _docs[doc] = {"state": None, "rev": 0, "seen": _now(), "pending": [], "last_command": int(time.time() * 1000)}
    return entry


def report(checked: dict, figures: dict | None, project_known: bool) -> dict:
    """
    Keep what the plugin reported (clean_report), with the figures Sida computed for it (None
    without a project or a snapshot). The revision goes up only when something the panel
    shows changed. Returns {rev}.
    """
    snap = checked["snapshot"]
    state = {
        "doc": checked["doc"],
        "file": checked["file"],
        "units": checked["units"],
        "project": checked["project"],
        "project_known": project_known,
        "autosync": checked["autosync"],
        "rhino": snap["rhino"]["version"] if snap else "",
        "layers": _layers(snap) if snap else [],
        "objects": len(snap["objects"]) if snap else 0,
        "figures": figures,
    }
    with _lock:
        entry = _entry(checked["doc"])
        entry["seen"] = _now()
        before = entry["state"]
        notice = before.get("notice") if before else None
        if checked["notice"]:
            notice = {**checked["notice"], "at": datetime.now().isoformat(timespec="seconds"), "n": (notice or {}).get("n", 0) + 1}
        state["notice"] = notice
        if state != before:
            entry["state"] = state
            entry["rev"] += 1
        return {"rev": entry["rev"]}


def current(doc: str | None = None) -> dict:
    """
    What the panel shows: {connected, rev, state}. With no doc named it is the document whose
    plugin asked most recently (a browser tab beside Rhino). `state` is None when no Rhino has
    reported; `connected` is False once the plugin has stopped asking.
    """
    with _lock:
        if doc is None:
            doc = max(_docs, key=lambda key: _docs[key]["seen"], default=None)
        entry = _docs.get(doc) if doc else None
        if entry is None or entry["state"] is None:
            return {"connected": False, "rev": 0, "state": None}
        return {"connected": _now() - entry["seen"] <= CONNECTED_FOR, "rev": entry["rev"], "state": entry["state"]}


def ask(raw) -> dict:
    """Queue a command from the panel for a document's plugin. Raises ValueError. Returns {id}."""
    if not isinstance(raw, dict):
        raise ValueError("the command must be a JSON object")
    doc = _doc_id(raw.get("doc"))
    kind = raw.get("type")
    if kind not in COMMANDS:
        raise ValueError("type must be one of " + ", ".join(COMMANDS))
    command: dict = {"type": kind}
    if kind == "set_project":
        command["project"] = _text(raw.get("project"), "project")
    elif kind == "set_layer":
        command["path"] = _text(raw.get("path"), "path", 400)
        if not command["path"]:
            raise ValueError("path is needed (the layer's full path)")
        meaning = _text(raw.get("meaning"), "meaning", 40)
        if meaning and meaning not in snapshot.MEANINGS:
            raise ValueError("meaning must be one of " + ", ".join(snapshot.MEANINGS) + " or empty")
        command["meaning"] = meaning
        height = raw.get("floor_height")
        if height is not None:
            if isinstance(height, bool) or not isinstance(height, (int, float)) or not 0 < height <= 100:
                raise ValueError("floor_height must be a number of metres above 0, or null")
            height = round(float(height), 3)
        command["floor_height"] = height
    elif kind == "set_autosync":
        command["on"] = raw.get("on") is True
    with _lock:
        entry = _docs.get(doc)
        if entry is None:
            raise ValueError("no Rhino document with that id is connected")
        if len(entry["pending"]) >= MAX_PENDING:
            raise ValueError("too many commands are waiting for Rhino")
        entry["last_command"] += 1
        command["id"] = entry["last_command"]
        entry["pending"].append(command)
        return {"id": command["id"]}


def pending(doc: str, after: int = 0) -> dict:
    """
    What the plugin should do next: {known, commands}. Asking is also the plugin's heartbeat.
    Commands up to `after` are done and dropped; `known` is False when Sida has no report for
    this document (Sida restarted), so the plugin reports it again.
    """
    doc = _doc_id(doc)
    with _lock:
        entry = _entry(doc)
        entry["seen"] = _now()
        entry["pending"] = [c for c in entry["pending"] if c["id"] > after]
        return {"known": entry["state"] is not None, "commands": list(entry["pending"])}
