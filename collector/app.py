"""Sida usage-record collector: one write-only endpoint in front of Postgres, on the team VPS.

Sida apps on designers' machines POST batches of records here (sida/telemetry.py). The app
carries no secret (anyone can read its code), so this endpoint only takes records in: no
route reads them back, shapes and sizes are strict, and each installation and each sending
address has an hourly limit. Sending addresses are used for that limit only, never stored.

Run: uvicorn collector.app:from_env --factory (see collector/README.md).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_BODY = 512 * 1024  # bytes per request
MAX_EVENTS = 100  # records per request (the app sends 100 at most)
MAX_DATA = 8 * 1024  # bytes of one record's data
WINDOW = 3600.0  # seconds the limits below count over
INSTALL_LIMIT = 2000  # records per installation per hour
ADDRESS_LIMIT = 5000  # records per sending address per hour (an office shares one)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          text PRIMARY KEY,
    install_id  text NOT NULL,
    app_version text NOT NULL,
    os          text NOT NULL,
    kind        text NOT NULL,
    at          timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    data        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS events_kind_at ON events (kind, at);
CREATE INDEX IF NOT EXISTS events_install ON events (install_id);
"""


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    kind: str = Field(pattern=r"^[a-z_]{1,40}$")
    at: datetime
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def small(cls, value: dict) -> dict:
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_DATA:
            raise ValueError(f"data is larger than {MAX_DATA} bytes")
        return value

    @field_validator("at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    install_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    app_version: str = Field(min_length=1, max_length=40)
    os: str = Field(default="", max_length=40)
    events: list[Event] = Field(min_length=1, max_length=MAX_EVENTS)


class Store(Protocol):
    def add(self, batch: Batch) -> int:
        """Save the batch's records; one already saved (same id, a resend) is skipped."""


class RateLimit:
    """At most `limit` records per key within the last `window` seconds."""

    def __init__(self, limit: int, window: float = WINDOW, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def take(self, key: str, n: int) -> bool:
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0][0] <= now - self.window:
                self._counts[key] -= hits.popleft()[1]
            if self._counts[key] + n > self.limit:
                return False
            hits.append((now, n))
            self._counts[key] += n
            return True


def create_app(store: Store, *, clock: Callable[[], float] = time.monotonic) -> FastAPI:
    app = FastAPI(title="Sida collector", docs_url=None, redoc_url=None, openapi_url=None)
    per_install = RateLimit(INSTALL_LIMIT, clock=clock)
    per_address = RateLimit(ADDRESS_LIMIT, clock=clock)

    @app.get("/api/v1/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/v1/events", status_code=202)
    async def events(request: Request) -> dict:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY:
            raise HTTPException(status_code=413, detail="request too large")
        body = await request.body()
        if len(body) > MAX_BODY:
            raise HTTPException(status_code=413, detail="request too large")
        try:
            batch = Batch.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="invalid batch") from exc
        # Behind Caddy the sender is the first X-Forwarded-For address.
        forwarded = request.headers.get("x-forwarded-for", "")
        address = forwarded.split(",")[0].strip() or (request.client.host if request.client else "")
        n = len(batch.events)
        if not per_address.take(address, n) or not per_install.take(batch.install_id, n):
            raise HTTPException(status_code=429, detail="too many records")
        return {"accepted": n, "stored": store.add(batch)}

    return app


class PostgresStore:
    """Records in one `events` table; `data` is JSONB so each kind keeps its own fields."""

    def __init__(self, dsn: str):
        import psycopg

        self.dsn = dsn
        with psycopg.connect(dsn) as conn:
            conn.execute(SCHEMA)

    def add(self, batch: Batch) -> int:
        import psycopg
        from psycopg.types.json import Jsonb

        rows = [
            (e.id, batch.install_id, batch.app_version, batch.os, e.kind, e.at, Jsonb(e.data))
            for e in batch.events
        ]
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            stored = 0
            for row in rows:
                cur.execute(
                    "INSERT INTO events (id, install_id, app_version, os, kind, at, data)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                    row,
                )
                stored += cur.rowcount
        return stored


def dsn_from_env(env: dict[str, str] | None = None) -> str:
    """Postgres address from SIDA_DB_* variables; the password is read from its secret file."""
    env = dict(os.environ if env is None else env)
    with open(env.get("SIDA_DB_PASSWORD_FILE", "/run/secrets/db_password"), encoding="utf-8") as f:
        password = f.read().strip()
    user = env.get("SIDA_DB_USER", "sida")
    host = env.get("SIDA_DB_HOST", "db")
    name = env.get("SIDA_DB_NAME", "sida")
    return f"postgresql://{quote(user)}:{quote(password, safe='')}@{host}:5432/{quote(name)}"


def from_env() -> FastAPI:
    return create_app(PostgresStore(dsn_from_env()))
