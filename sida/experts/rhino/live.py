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

A message to the Conductor that should take the Rhino view along (sida/views.py) asks here
too: want_view queues the command `view` and waits a few seconds for the plugin's picture of
the active viewport (give_view). The picture is handed over once and not kept here.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from sida import views
from sida.experts.rhino import diagrams, snapshot

CONNECTED_FOR = 5.0   # seconds a document stays connected after its plugin last asked
MAX_DOCS = 8          # running Rhino documents remembered (the oldest is forgotten)
MAX_PENDING = 50      # commands waiting for one document
MAX_TEXT = 200
VIEW_WAIT = 8.0       # seconds a message waits for the plugin's picture of the view

# What the panel may ask of the plugin, and the fields each command carries.
COMMANDS: dict[str, tuple[str, ...]] = {
    "pull": (),                                       # the drafting table into the document
    "push": (),                                       # a snapshot with captures to Sida
    "set_project": ("project",),                      # which Sida project the document belongs to
    "set_layer": ("path", "meaning", "floor_height"),  # a layer's meaning and floor height (m, or null)
    "set_autosync": ("on",),                          # push on every save
    "report": (),                                     # say the document again (the panel just opened)
    "draw": ("kinds",),                               # push, then draw these diagrams in the document (diagrams.py)
}
# Sida itself also asks the plugin for `view`: a picture of the active viewport as it is now, for a
# message to the Conductor (want_view). The panel cannot ask for one.
BUSY = ("", "pull", "push", "draw")  # what the plugin may say it is in the middle of

_lock = threading.Lock()
_arrived = threading.Condition(_lock)  # a picture a message waits for has come
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
        "busy": raw.get("busy") if raw.get("busy") in BUSY else "",
        "selected": [],
        "selected_count": 0,
        "snapshot": None,
        "notice": None,
    }
    selected = raw.get("selected")
    if selected is not None:
        if not isinstance(selected, list) or len(selected) > snapshot.MAX_SELECTED:
            raise ValueError(f"selected must be a list of at most {snapshot.MAX_SELECTED} object ids")
        out["selected"] = [_text(item, "selected id", 64) for item in selected]
        count = raw.get("selected_count")
        out["selected_count"] = max(count if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 10**7 else 0,
                                    len(out["selected"]))
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
        entry = _docs[doc] = {"state": None, "rev": 0, "seen": _now(), "pending": [], "path": None, "brief": "",
                              "last_command": int(time.time() * 1000), "wanted": None, "view": None}
    return entry


def report(checked: dict, figures: dict | None, project_known: bool, *, selection: dict | None = None,
           path=None, brief: str = "") -> dict:
    """
    Keep what the plugin reported (clean_report), with the figures Sida computed for it (None
    without a project or a snapshot). `selection` is what is selected in Rhino
    (snapshot.selection); `path` is the project's folder and `brief` what the Conductor is told
    about this document while it is connected (brief_for). The revision goes up only when
    something the panel shows changed. Returns {rev}.
    """
    snap = checked["snapshot"]
    state = {
        "doc": checked["doc"],
        "file": checked["file"],
        "units": checked["units"],
        "project": checked["project"],
        "project_known": project_known,
        "autosync": checked["autosync"],
        "busy": checked["busy"],
        "rhino": snap["rhino"]["version"] if snap else "",
        "layers": _layers(snap) if snap else [],
        "objects": len(snap["objects"]) if snap else 0,
        "figures": figures,
        "selection": {key: selection[key] for key in ("count", "bodies", "floor_area_m2", "footprint_m2")} if selection else None,
    }
    with _lock:
        entry = _entry(checked["doc"])
        entry["seen"] = _now()
        entry["path"] = path
        entry["brief"] = brief
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


def brief_for(path) -> str:
    """
    What the Conductor is told about the Rhino document open on this project right now ("" when
    none is connected): the one whose plugin asked most recently.
    """
    with _lock:
        now = _now()
        live_ones = [e for e in _docs.values() if e.get("path") == path and e.get("brief") and now - e["seen"] <= CONNECTED_FOR]
        return max(live_ones, key=lambda e: e["seen"])["brief"] if live_ones else ""


def want_view(path, wait: float | None = None) -> dict | None:
    """
    A picture of the active viewport of the Rhino open on this project, as it is now: queue the
    command `view` and wait (VIEW_WAIT seconds, or `wait`) for the plugin to send it. Returns
    {"data", "title", "file", "brief"} (the picture, the viewport's name, the document's file
    name, and what the Conductor is told of the document), or None when no Rhino is connected
    on the project or none came in time (the designer is in the middle of a Rhino command).
    """
    with _arrived:
        now = _now()
        live_ones = [e for e in _docs.values() if e.get("path") == path and e["state"] is not None and now - e["seen"] <= CONNECTED_FOR]
        if not live_ones:
            return None
        entry = max(live_ones, key=lambda e: e["seen"])
        if entry["wanted"] is not None or len(entry["pending"]) >= MAX_PENDING:
            return None
        entry["last_command"] += 1
        command = entry["wanted"] = entry["last_command"]
        entry["pending"].append({"type": "view", "id": command})
        _arrived.wait_for(lambda: entry["view"] is not None, VIEW_WAIT if wait is None else wait)
        view, entry["view"], entry["wanted"] = entry["view"], None, None
        entry["pending"] = [c for c in entry["pending"] if c["id"] != command]  # a late one is of no use
        if view is None:
            return None
        return {**view, "file": entry["state"]["file"], "brief": entry["brief"]}


def give_view(doc: str, command: int, data: bytes, title=None) -> dict:
    """
    The plugin's picture for the command `view` (PNG or JPEG). Returns {"taken"}: False when no
    message waits for it any more. Raises ValueError for what is not a picture, or one too large.
    """
    doc = _doc_id(doc)
    title = " ".join(_text(title, "title", 80).split())
    if views.media_type(data) is None:
        raise ValueError(f"the view must be a PNG or JPEG picture of at most {views.MAX_BYTES // (1024 * 1024)} MB")
    with _arrived:
        entry = _docs.get(doc)
        if entry is None or entry["wanted"] != command:
            return {"taken": False}
        entry["view"] = {"data": data, "title": title}
        _arrived.notify_all()
        return {"taken": True}


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
    elif kind == "draw":
        kinds = raw.get("kinds")
        if not isinstance(kinds, list) or not kinds or any(k not in diagrams.KINDS for k in kinds):
            raise ValueError("kinds must be a list of " + ", ".join(diagrams.KINDS))
        command["kinds"] = [k for k in diagrams.KINDS if k in kinds]  # each once, in the order they are laid out
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
