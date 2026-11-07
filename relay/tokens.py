"""Access keys (sida_…) for the relay, one per person, kept as hashes in SQLite.

A key is shown once, when it is made (relay/admin.py); the database keeps only its SHA-256.
Each key has a name (who it is for), a daily call limit, and may expire or be revoked.
Usage is counted per key, per Korean day and per service, with how many calls failed:
no addresses, parcel numbers or queries are kept.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))  # no daylight saving in Korea
PREFIX = "sida_"
DEFAULT_DAILY_LIMIT = 3000

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id          TEXT PRIMARY KEY,
    hash        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    daily_limit INTEGER NOT NULL,
    created     TEXT NOT NULL,
    expires     TEXT,
    revoked     TEXT,
    last_used   TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    token_id TEXT NOT NULL,
    day      TEXT NOT NULL,
    service  TEXT NOT NULL,
    calls    INTEGER NOT NULL DEFAULT 0,
    failed   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (token_id, day, service)
);
"""


def korean_now() -> datetime:
    return datetime.now(KST)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Token:
    id: str
    name: str
    daily_limit: int
    created: str
    expires: str | None
    revoked: str | None
    last_used: str | None

    def usable(self, today: date) -> bool:
        return not self.revoked and (not self.expires or today.isoformat() <= self.expires)


class TokenStore:
    def __init__(self, path: str | Path, *, now=korean_now):
        self.now = now
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # -- keys -------------------------------------------------------------

    def issue(self, name: str, *, daily_limit: int = DEFAULT_DAILY_LIMIT, days: int | None = None) -> tuple[str, Token]:
        """A new key for `name`: (the key itself, shown only now; its record)."""
        name = " ".join((name or "").split())
        if not name or len(name) > 80:
            raise ValueError("name must be 1-80 characters")
        if daily_limit < 1:
            raise ValueError("daily_limit must be at least 1")
        token = PREFIX + secrets.token_urlsafe(24)
        token_id = secrets.token_hex(4)
        now = self.now()
        expires = (now.date() + timedelta(days=days)).isoformat() if days else None
        with self._lock:
            self._db.execute(
                "INSERT INTO tokens (id, hash, name, daily_limit, created, expires) VALUES (?, ?, ?, ?, ?, ?)",
                (token_id, _hash(token), name, daily_limit, now.isoformat(timespec="seconds"), expires),
            )
        return token, self.get(token_id)

    def get(self, token_id: str) -> Token | None:
        row = self._db.execute(
            "SELECT id, name, daily_limit, created, expires, revoked, last_used FROM tokens WHERE id = ?",
            (token_id,),
        ).fetchone()
        return Token(*row) if row else None

    def find(self, token: str) -> Token | None:
        """The record of a key as the app sends it; None for an unknown key."""
        if not token.startswith(PREFIX) or len(token) > 100:
            return None
        row = self._db.execute("SELECT id FROM tokens WHERE hash = ?", (_hash(token),)).fetchone()
        return self.get(row[0]) if row else None

    def all(self) -> list[Token]:
        rows = self._db.execute("SELECT id FROM tokens ORDER BY created").fetchall()
        return [self.get(r[0]) for r in rows]

    def revoke(self, token_id: str) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE tokens SET revoked = ? WHERE id = ? AND revoked IS NULL",
                (self.now().isoformat(timespec="seconds"), token_id),
            )
        return cur.rowcount == 1

    def set_limit(self, token_id: str, daily_limit: int) -> bool:
        if daily_limit < 1:
            raise ValueError("daily_limit must be at least 1")
        with self._lock:
            cur = self._db.execute("UPDATE tokens SET daily_limit = ? WHERE id = ?", (daily_limit, token_id))
        return cur.rowcount == 1

    # -- usage ------------------------------------------------------------

    def calls_today(self, token_id: str) -> int:
        day = self.now().date().isoformat()
        row = self._db.execute(
            "SELECT COALESCE(SUM(calls), 0) FROM usage WHERE token_id = ? AND day = ?", (token_id, day)
        ).fetchone()
        return int(row[0])

    def take(self, token: Token) -> bool:
        """Count one call for today if the key is under its daily limit."""
        with self._lock:
            if self.calls_today(token.id) >= token.daily_limit:
                return False
            now = self.now()
            self._db.execute("UPDATE tokens SET last_used = ? WHERE id = ?",
                             (now.isoformat(timespec="seconds"), token.id))
            return True

    def record(self, token_id: str, service: str, ok: bool) -> None:
        day = self.now().date().isoformat()
        with self._lock:
            self._db.execute(
                "INSERT INTO usage (token_id, day, service, calls, failed) VALUES (?, ?, ?, 1, ?)"
                " ON CONFLICT (token_id, day, service) DO UPDATE SET calls = calls + 1, failed = failed + excluded.failed",
                (token_id, day, service, 0 if ok else 1),
            )

    def usage(self, days: int = 7) -> list[tuple[str, str, str, int, int]]:
        """(day, key name, service, calls, failed) for the last `days` days, newest first."""
        since = (self.now().date() - timedelta(days=days - 1)).isoformat()
        return self._db.execute(
            "SELECT u.day, t.name, u.service, u.calls, u.failed FROM usage u JOIN tokens t ON t.id = u.token_id"
            " WHERE u.day >= ? ORDER BY u.day DESC, t.name, u.service",
            (since,),
        ).fetchall()
