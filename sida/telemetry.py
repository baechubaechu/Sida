"""Usage records for the Sida team's collection server. Off unless this machine turns it on.

Sida runs on each designer's own computer, so nothing reaches the team unless the app sends
it. When `telemetry.enabled` is on (settings screen → config.local.yaml), short records are
appended to a queue file in ~/Sida/telemetry/ and sent in batches over HTTPS; a failed send
keeps them for the next try and never affects the app.

What a record may hold (see docs/telemetry.md):
  usage     which expert or job ran, how long it took, whether it failed (an error kind,
            never the error text), the model names, the Sida version and OS
  feedback  a designer's rating of an expert's result, and the comment they typed for it
  failure   which government or statute lookup failed and why (a fixed kind); the address
            or question that failed only when `telemetry.share_failure_inputs` is also on
Briefs, generated documents and project names are never recorded.
"""

from __future__ import annotations

import json
import platform
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from sida import config as sida_config

TELEMETRY_DIR = Path.home() / "Sida" / "telemetry"
DEFAULT_ENDPOINT = "https://sida-data.duckdns.org/api/v1/events"
BATCH_SIZE = 100  # events per request; the server refuses larger batches
MAX_QUEUED = 5000  # oldest records are dropped beyond this, so an offline machine stays small
FLUSH_SECONDS = 300
MAX_COMMENT = 1000
MAX_INPUT = 200
RATINGS = ("up", "down")
STATE_RESULTS = {
    "state_proposed": "proposed",
    "state_applied": "applied",
    "state_unchanged": "unchanged",
    "state_failed": "failed",
}
# Error text can carry keys, addresses or prompt fragments, so only a kind is sent.
_ERROR_KINDS = (
    ("timeout", ("timed out", "timeout")),
    ("rate_limit", ("429", "rate limit", "too many requests")),
    ("auth", ("401", "403", "unauthorized", "forbidden", "api key", "invalid key")),
    ("network", ("connection", "network", "name resolution", "unreachable")),
    ("empty_reply", ("empty",)),
    ("server", ("500", "502", "503", "504", "server error")),
)

_lock = threading.Lock()


def telemetry_settings(config: dict) -> dict:
    raw = config.get("telemetry") or {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "share_failure_inputs": bool(raw.get("share_failure_inputs", False)),
        "endpoint": str(raw.get("endpoint") or DEFAULT_ENDPOINT),
    }


def error_kind(reason: Any) -> str | None:
    """A fixed word for what went wrong ("" or None in → None out); never the message itself."""
    if not reason:
        return None
    text = str(reason).lower()
    for kind, needles in _ERROR_KINDS:
        if any(n in text for n in needles):
            return kind
    return "other"


# ---------------------------------------------------------------------------
# Queue on this machine
# ---------------------------------------------------------------------------


def _queue_path() -> Path:
    return TELEMETRY_DIR / "queue.jsonl"


def install_id() -> str:
    """A random id for this installation, made on first use. It says nothing about the person."""
    path = TELEMETRY_DIR / "install_id"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) == 32:
            return value
    except OSError:
        pass
    value = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    return value


def app_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("sida")
    except PackageNotFoundError:
        return "dev"


def _read_lines() -> list[str]:
    try:
        return [ln for ln in _queue_path().read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return []


def _write_lines(lines: list[str]) -> None:
    path = _queue_path()
    if not lines:
        path.unlink(missing_ok=True)
        return
    path.write_text("".join(f"{ln}\n" for ln in lines), encoding="utf-8")


def queued() -> list[dict]:
    """The records waiting to be sent, oldest first."""
    with _lock:
        lines = _read_lines()
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _append(event: dict) -> None:
    with _lock:
        path = _queue_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        lines = _read_lines()
        if len(lines) > MAX_QUEUED:
            _write_lines(lines[-MAX_QUEUED:])


def clear_queue() -> None:
    """Drop every unsent record (used when this machine turns sending off)."""
    with _lock:
        _write_lines([])


def forget_inputs() -> None:
    """Remove failed addresses/questions from unsent records (sharing inputs turned off)."""
    with _lock:
        kept = []
        for line in _read_lines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            (event.get("data") or {}).pop("inputs", None)
            kept.append(json.dumps(event, ensure_ascii=False))
        _write_lines(kept)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def _config(config: dict | None) -> dict:
    return config if config is not None else sida_config.load_config()


def record(kind: str, data: dict, *, config: dict | None = None) -> bool:
    """Queue one record when sending is on. Never raises: a record must not break the app."""
    try:
        if not telemetry_settings(_config(config))["enabled"]:
            return False
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _append({"id": uuid.uuid4().hex, "kind": kind, "at": at, "data": data})
        return True
    except Exception:
        return False


def record_failure(
    stage: str, error: str, *, inputs: tuple | list = (), config: dict | None = None
) -> bool:
    """A lookup that failed; what was looked up is added only when sharing inputs is on."""
    try:
        cfg = _config(config)
        data: dict[str, Any] = {"stage": stage, "error": error}
        if telemetry_settings(cfg)["share_failure_inputs"] and inputs:
            data["inputs"] = [str(value)[:MAX_INPUT] for value in list(inputs)[:5]]
        return record("failure", data, config=cfg)
    except Exception:
        return False


def record_feedback(config: dict, agent_id: str, rating: str, comment: str = "") -> bool:
    """A designer's rating of one expert's result. ValueError on a bad rating or long comment."""
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of: {', '.join(RATINGS)}")
    comment = (comment or "").strip()
    if len(comment) > MAX_COMMENT:
        raise ValueError(f"comment is longer than {MAX_COMMENT} characters")
    data = {"agent": agent_id, "rating": rating}
    if comment:
        data["comment"] = comment
    return record("feedback", data, config=config)


class JobObserver:
    """One conversation job's engine events → usage records: ids, timings and outcomes, no text."""

    def __init__(
        self,
        config: dict,
        job: str,
        agent: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self.job = job
        self.agent = agent
        self.clock = clock
        self.started = clock()
        self.enabled = telemetry_settings(config)["enabled"]
        self._expert_started: dict[str | None, float] = {}

    def _seconds(self, start: float | None) -> float | None:
        return None if start is None else round(self.clock() - start, 1)

    def event(self, kind: str, data: dict) -> None:
        if not self.enabled:
            return
        try:
            agent = data.get("agent")
            agent_id = agent.get("id") if isinstance(agent, dict) else None
            if kind == "module_started":
                self._expert_started[agent_id] = self.clock()
            elif kind in {"module_saved", "module_failed"}:
                run = {
                    "agent": agent_id,
                    "ok": kind == "module_saved",
                    "seconds": self._seconds(self._expert_started.pop(agent_id, None)),
                }
                if kind == "module_failed":
                    run["error"] = error_kind(data.get("reason"))
                record("expert_run", run, config=self.config)
            elif kind == "conductor_error":
                record("conductor_error", {"error": error_kind(data.get("reason"))}, config=self.config)
            elif kind in STATE_RESULTS:
                record("state_update", {"agent": agent_id, "result": STATE_RESULTS[kind]}, config=self.config)
            elif kind == "unknown_agent":
                record("unknown_agent", {"agent": str(data.get("agent") or "")[:60]}, config=self.config)
        except Exception:
            pass

    def finished(self, error: str | None) -> None:
        if not self.enabled:
            return
        try:
            from sida import runtime

            conductor = runtime.resolve_conductor_runtime(self.config)
            worker = runtime.resolve_worker_runtime(self.config)
            record(
                "job",
                {
                    "job": self.job,
                    "agent": self.agent,
                    "ok": error is None,
                    "seconds": self._seconds(self.started),
                    "error": error_kind(error),
                    "conductor": f"{conductor['provider']}:{conductor['model']}",
                    "worker": f"{worker['provider']}:{worker['model']}",
                },
                config=self.config,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def _http_post(url: str, payload: dict) -> int:
    return requests.post(url, json=payload, timeout=15).status_code


def flush(config: dict | None = None) -> int:
    """
    Send queued records in batches; returns how many the server took. Stops at the first
    network error or server trouble (kept for the next try). A batch the server rejects as
    malformed (400/413/422) is dropped, or it would block every later record.
    """
    sent = 0
    try:
        settings = telemetry_settings(_config(config))
        if not settings["enabled"]:
            return 0
        while True:
            with _lock:
                batch = _read_lines()[:BATCH_SIZE]
            if not batch:
                break
            events = []
            for line in batch:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
            payload = {
                "install_id": install_id(),
                "app_version": app_version(),
                "os": platform.system(),
                "events": events,
            }
            status = _http_post(settings["endpoint"], payload) if events else 200
            accepted = 200 <= status < 300
            if not accepted and status not in {400, 413, 422}:
                break
            with _lock:
                # New records are only appended at the end, so the batch is still the head.
                _write_lines(_read_lines()[len(batch):])
            if accepted:
                sent += len(events)
    except Exception:
        pass
    return sent


def start_flusher(interval: float = FLUSH_SECONDS) -> None:
    """Send queued records now and every `interval` seconds, on a background thread."""

    def loop() -> None:
        while True:
            flush()
            time.sleep(interval)

    threading.Thread(target=loop, name="sida-telemetry", daemon=True).start()
