"""Shared snapshots of Sida projects (공유) and the comments viewers leave on them.

A designer's app uploads a snapshot of one project (sida/share.py): a zip with `snapshot.json`
(the drafting table as the viewer draws it, the site card) and the photos shrunk for the web.
This server keeps it and gives two links: one to look and comment, one only to look. Whoever has
a link sees the snapshot in a browser (the viewer page, webui/app/share.html); with the comment
link they can leave a comment (a name, the text, and the spot on the model it is about). The
designer's app collects the comments and shows them on the table; the designer answers, marks
them resolved or deletes them from there.

- Uploading and managing need the designer's Sida access key (relay/tokens.py). Looking and
  commenting need only the link.
- What a share keeps: its versions (판), newest last, as unpacked files under
  <root>/files/<share id>/<version>/, and its comments in SQLite (<root>/shares.db). No
  conversation, terrain or contour data is ever in a snapshot (the app does not put it in, and
  only the file names below are taken).
- Limits (Limits, from the environment): the bytes of one share (older versions are dropped to
  make room for a new one), the shares and bytes of one designer, new shares per period and
  uploads per day (counted even after a share is deleted, so deleting does not reset them).
- A share is kept `retention_days` after its last upload, then deleted with its comments.
- Commenters are known only by the name they type. Their addresses are not kept (the minute
  limits live in memory).
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import zipfile
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path

from relay.tokens import korean_now

MB = 1024 * 1024
SNAPSHOT = "snapshot.json"
MAX_SNAPSHOT_BYTES = 4 * MB
MAX_PHOTO_BYTES = 3 * MB
MAX_FILES = 200
# What a snapshot zip may hold, and nothing else.
PHOTO_NAME = re.compile(r"^photos/[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.(?:jpg|png)$")
SHARE_ID = re.compile(r"^sh_[0-9a-f]{12}$")
LINK = re.compile(r"^[A-Za-z0-9_-]{20,40}$")
COMMENT_ID = re.compile(r"^c_[0-9a-f]{12}$")
MAX_TITLE = 120
MAX_BY = 40
MAX_NAME = 40
MAX_TEXT = 1000
MAX_TARGET = 80
MAX_COMMENTS = 500  # per share
MAX_COORD = 100000.0
PNU = re.compile(r"^\d{19}$")
MAX_PARCELS = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS shares (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL,     -- the access key's id
    title         TEXT NOT NULL,
    by_name       TEXT NOT NULL,     -- the designer, as the viewer sees them
    comment_link  TEXT NOT NULL UNIQUE,
    view_link     TEXT NOT NULL UNIQUE,
    comments_open INTEGER NOT NULL DEFAULT 1,
    created       TEXT NOT NULL,
    updated       TEXT NOT NULL,
    expires       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    share_id TEXT NOT NULL,
    number   INTEGER NOT NULL,
    created  TEXT NOT NULL,
    bytes    INTEGER NOT NULL,
    PRIMARY KEY (share_id, number)
);
CREATE TABLE IF NOT EXISTS comments (
    id        TEXT PRIMARY KEY,
    share_id  TEXT NOT NULL,
    version   INTEGER NOT NULL,
    parent    TEXT NOT NULL DEFAULT '',
    author    TEXT NOT NULL,
    by_owner  INTEGER NOT NULL DEFAULT 0,
    body      TEXT NOT NULL,
    target    TEXT NOT NULL DEFAULT '',
    x         REAL,
    y         REAL,
    z         REAL,
    created   TEXT NOT NULL,
    resolved  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS comments_share ON comments (share_id, created);
CREATE TABLE IF NOT EXISTS uploads (
    owner TEXT NOT NULL,
    kind  TEXT NOT NULL,   -- share (a new share) | version (any upload, the first included)
    at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS uploads_owner ON uploads (owner, kind, at);
"""


class ShareError(ValueError):
    """A snapshot or request this server refuses (400)."""


class LimitReached(Exception):
    """An upload over one of the limits (429); the message says which, for the app to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Limits:
    share_bytes: int = 20 * MB  # one share, all its kept versions
    owner_bytes: int = 100 * MB  # one designer, all their shares
    owner_shares: int = 10  # shares one designer has at a time
    new_shares: int = 10  # new shares per `period_days`
    period_days: int = 14
    uploads_per_day: int = 20  # uploads (new shares and new versions) per 24 hours
    retention_days: int = 30

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Limits:
        env = dict(os.environ if env is None else env)
        values = {}
        for field in fields(cls):
            raw = env.get(f"SIDA_SHARE_{field.name.upper()}", "").strip()  # sizes in MB
            if not raw:
                continue
            number = int(raw) * (MB if field.name.endswith("_bytes") else 1)
            if number < 1:
                raise ValueError(f"SIDA_SHARE_{field.name.upper()} must be at least 1")
            values[field.name] = number
        return cls(**values)

    def public(self) -> dict:
        return {
            "share_mb": self.share_bytes // MB, "owner_mb": self.owner_bytes // MB,
            "owner_shares": self.owner_shares, "new_shares": self.new_shares,
            "period_days": self.period_days, "uploads_per_day": self.uploads_per_day,
            "retention_days": self.retention_days,
        }


@dataclass(frozen=True)
class Share:
    id: str
    owner: str
    title: str
    by_name: str
    comment_link: str
    view_link: str
    comments_open: bool
    created: str
    updated: str
    expires: str


def _clean(text, limit: int, what: str, *, required: bool = True) -> str:
    if not isinstance(text, str):
        raise ShareError(f"{what} must be text")
    text = " ".join(text.split()) if what != "text" else text.strip()
    if required and not text:
        raise ShareError(f"{what} is empty")
    if len(text) > limit:
        raise ShareError(f"{what} is longer than {limit} characters")
    return text


def read_snapshot(data: bytes, max_bytes: int) -> tuple[dict, dict[str, bytes]]:
    """
    The snapshot zip, checked: (snapshot.json read, every file by name). Only snapshot.json
    and photos/<id>.jpg|png are taken, each under its own size, all under `max_bytes`.
    """
    if len(data) > max_bytes:
        raise LimitReached("share_bytes", f"a share may be at most {max_bytes // MB} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise ShareError("not a zip file") from exc
    if len(infos) > MAX_FILES:
        raise ShareError("too many files")
    total = 0
    files: dict[str, bytes] = {}
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        if name != SNAPSHOT and not PHOTO_NAME.match(name):
            raise ShareError(f"unexpected file in the snapshot: {name[:80]}")
        limit = MAX_SNAPSHOT_BYTES if name == SNAPSHOT else MAX_PHOTO_BYTES
        if info.file_size > limit:
            raise ShareError(f"{name} is too large")
        total += info.file_size
        if total > max_bytes:
            raise LimitReached("share_bytes", f"a share may be at most {max_bytes // MB} MB")
        with archive.open(info) as handle:
            body = handle.read(limit + 1)  # the size in the zip may lie
        if len(body) > limit:
            raise ShareError(f"{name} is too large")
        files[name] = body
    if SNAPSHOT not in files:
        raise ShareError("snapshot.json is missing")
    try:
        snapshot = json.loads(files[SNAPSHOT].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ShareError("snapshot.json is not JSON") from exc
    if not isinstance(snapshot, dict):
        raise ShareError("snapshot.json must be an object")
    return snapshot, files


def _number(value, what: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not abs(value) <= MAX_COORD:
        raise ShareError(f"{what} must be a number")
    return float(value)


class ShareStore:
    def __init__(self, root: str | Path, *, limits: Limits | None = None, now=korean_now):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits or Limits()
        self.now = now
        self._db = sqlite3.connect(str(self.root / "shares.db"), check_same_thread=False, isolation_level=None)
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._purged = None

    # -- reading ----------------------------------------------------------

    def _stamp(self, when: datetime | None = None) -> str:
        return (when or self.now()).isoformat(timespec="seconds")

    def _share(self, row) -> Share | None:
        if not row:
            return None
        return Share(row[0], row[1], row[2], row[3], row[4], row[5], bool(row[6]), row[7], row[8], row[9])

    _COLUMNS = "id, owner, title, by_name, comment_link, view_link, comments_open, created, updated, expires"

    def get(self, share_id: str) -> Share | None:
        if not SHARE_ID.match(share_id or ""):
            return None
        self.purge()
        return self._share(self._db.execute(f"SELECT {self._COLUMNS} FROM shares WHERE id = ?", (share_id,)).fetchone())

    def owned(self, share_id: str, owner: str) -> Share | None:
        share = self.get(share_id)
        return share if share and share.owner == owner else None

    def by_link(self, link: str) -> tuple[Share, bool] | None:
        """The share a link opens and whether it is the comment link; None for an unknown link."""
        if not LINK.match(link or ""):
            return None
        self.purge()
        row = self._db.execute(
            f"SELECT {self._COLUMNS} FROM shares WHERE comment_link = ? OR view_link = ?", (link, link)
        ).fetchone()
        share = self._share(row)
        if share is None:
            return None
        return share, secrets.compare_digest(share.comment_link, link)

    def versions(self, share_id: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT number, created, bytes FROM versions WHERE share_id = ? ORDER BY number", (share_id,)
        ).fetchall()
        return [{"number": n, "created": c, "bytes": b} for n, c, b in rows]

    def share_bytes(self, share_id: str) -> int:
        row = self._db.execute("SELECT COALESCE(SUM(bytes), 0) FROM versions WHERE share_id = ?", (share_id,)).fetchone()
        return int(row[0])

    def owner_shares(self, owner: str) -> list[Share]:
        self.purge()
        rows = self._db.execute(f"SELECT {self._COLUMNS} FROM shares WHERE owner = ? ORDER BY created", (owner,)).fetchall()
        return [self._share(r) for r in rows]

    def owner_bytes(self, owner: str) -> int:
        row = self._db.execute(
            "SELECT COALESCE(SUM(v.bytes), 0) FROM versions v JOIN shares s ON s.id = v.share_id WHERE s.owner = ?",
            (owner,),
        ).fetchone()
        return int(row[0])

    def _uploads_since(self, owner: str, kind: str, since: datetime) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) FROM uploads WHERE owner = ? AND kind = ? AND at > ?", (owner, kind, self._stamp(since))
        ).fetchone()
        return int(row[0])

    def usage(self, owner: str) -> dict:
        now = self.now()
        limits = self.limits
        return {
            "shares": len(self.owner_shares(owner)),
            "bytes": self.owner_bytes(owner),
            "new_shares": self._uploads_since(owner, "share", now - timedelta(days=limits.period_days)),
            "uploads_today": self._uploads_since(owner, "version", now - timedelta(days=1)),
            "limits": limits.public(),
        }

    def describe(self, share: Share, *, owner: bool) -> dict:
        """A share as its designer sees it (owner) or as a viewer does (no links, no owner)."""
        versions = self.versions(share.id)
        info = {
            "title": share.title, "by": share.by_name, "comments_open": share.comments_open,
            "updated": share.updated, "expires": share.expires,
            "versions": [{"number": v["number"], "created": v["created"]} for v in versions],
            "latest": versions[-1]["number"] if versions else 0,
        }
        if owner:
            info.update({
                "id": share.id, "comment_link": share.comment_link, "view_link": share.view_link,
                "created": share.created, "bytes": self.share_bytes(share.id),
                "versions": versions,
            })
        return info

    def file(self, share: Share, version: int, name: str) -> Path | None:
        """A file of one kept version, or None."""
        if name != SNAPSHOT and not PHOTO_NAME.match(name):
            return None
        if not any(v["number"] == version for v in self.versions(share.id)):
            return None
        path = self.root / "files" / share.id / str(version) / name
        return path if path.is_file() else None

    def parcel_numbers(self, share: Share) -> list[str]:
        """The PNUs of the site in the newest version (at most MAX_PARCELS)."""
        versions = self.versions(share.id)
        path = self.file(share, versions[-1]["number"], SNAPSHOT) if versions else None
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8")) if path else {}
            parcels = ((snapshot.get("site") or {}).get("plan") or {}).get("parcels") or []
        except (OSError, ValueError, AttributeError):
            return []
        numbers = [str(p.get("pnu", "")) for p in parcels if isinstance(p, dict)]
        return list(dict.fromkeys(n for n in numbers if PNU.match(n)))[:MAX_PARCELS]

    # -- uploading --------------------------------------------------------

    def _check_upload(self, owner: str, *, new_share: bool) -> None:
        limits = self.limits
        now = self.now()
        if self._uploads_since(owner, "version", now - timedelta(days=1)) >= limits.uploads_per_day:
            raise LimitReached("uploads_per_day", f"at most {limits.uploads_per_day} uploads a day")
        if new_share:
            if len(self.owner_shares(owner)) >= limits.owner_shares:
                raise LimitReached("owner_shares", f"at most {limits.owner_shares} shares at a time")
            since = now - timedelta(days=limits.period_days)
            if self._uploads_since(owner, "share", since) >= limits.new_shares:
                raise LimitReached(
                    "new_shares", f"at most {limits.new_shares} new shares in {limits.period_days} days"
                )

    def _meta(self, snapshot: dict) -> tuple[str, str]:
        title = _clean(snapshot.get("title", ""), MAX_TITLE, "title")
        by_name = _clean(snapshot.get("by", "") or "", MAX_BY, "by", required=False)
        return title, by_name

    def _write_version(self, share_id: str, number: int, files: dict[str, bytes]) -> int:
        folder = self.root / "files" / share_id / str(number)
        if folder.exists():
            shutil.rmtree(folder)
        for name, body in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return sum(len(b) for b in files.values())

    def _make_room(self, share_id: str, owner: str, incoming: int) -> None:
        """Drop the oldest versions of this share until the new one fits its limits."""
        limits = self.limits
        if incoming > limits.share_bytes:
            raise LimitReached("share_bytes", f"a share may be at most {limits.share_bytes // MB} MB")
        others = self.owner_bytes(owner) - self.share_bytes(share_id)
        if others + incoming > limits.owner_bytes:
            raise LimitReached("owner_bytes", f"at most {limits.owner_bytes // MB} MB of shares in all")
        for version in self.versions(share_id):
            if self.share_bytes(share_id) + incoming <= limits.share_bytes and \
                    others + self.share_bytes(share_id) + incoming <= limits.owner_bytes:
                break
            self._drop_version(share_id, version["number"])

    def _drop_version(self, share_id: str, number: int) -> None:
        self._db.execute("DELETE FROM versions WHERE share_id = ? AND number = ?", (share_id, number))
        shutil.rmtree(self.root / "files" / share_id / str(number), ignore_errors=True)

    def create(self, owner: str, data: bytes) -> Share:
        """A new share from a snapshot zip, as its first version."""
        with self._lock:
            self.purge()
            self._check_upload(owner, new_share=True)
            snapshot, files = read_snapshot(data, self.limits.share_bytes)
            title, by_name = self._meta(snapshot)
            size = sum(len(b) for b in files.values())
            if self.owner_bytes(owner) + size > self.limits.owner_bytes:
                raise LimitReached("owner_bytes", f"at most {self.limits.owner_bytes // MB} MB of shares in all")
            share_id = "sh_" + secrets.token_hex(6)
            now = self.now()
            stamp = self._stamp(now)
            expires = self._stamp(now + timedelta(days=self.limits.retention_days))
            self._db.execute(
                f"INSERT INTO shares ({self._COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (share_id, owner, title, by_name, secrets.token_urlsafe(18), secrets.token_urlsafe(18),
                 stamp, stamp, expires),
            )
            size = self._write_version(share_id, 1, files)
            self._db.execute("INSERT INTO versions VALUES (?, 1, ?, ?)", (share_id, stamp, size))
            self._db.executemany("INSERT INTO uploads VALUES (?, ?, ?)",
                                 [(owner, "share", stamp), (owner, "version", stamp)])
            return self.get(share_id)

    def add_version(self, share: Share, data: bytes) -> int:
        """A new version of a share (the same links show it); its number."""
        with self._lock:
            self._check_upload(share.owner, new_share=False)
            snapshot, files = read_snapshot(data, self.limits.share_bytes)
            title, by_name = self._meta(snapshot)
            self._make_room(share.id, share.owner, sum(len(b) for b in files.values()))
            row = self._db.execute("SELECT COALESCE(MAX(number), 0) FROM versions WHERE share_id = ?", (share.id,)).fetchone()
            last = self._db.execute(
                "SELECT COALESCE(MAX(version), 0) FROM comments WHERE share_id = ?", (share.id,)
            ).fetchone()
            number = max(int(row[0]), int(last[0])) + 1  # never reuse a number a comment names
            now = self.now()
            stamp = self._stamp(now)
            size = self._write_version(share.id, number, files)
            self._db.execute("INSERT INTO versions VALUES (?, ?, ?, ?)", (share.id, number, stamp, size))
            self._db.execute(
                "UPDATE shares SET title = ?, by_name = ?, updated = ?, expires = ? WHERE id = ?",
                (title, by_name, stamp, self._stamp(now + timedelta(days=self.limits.retention_days)), share.id),
            )
            self._db.execute("INSERT INTO uploads VALUES (?, 'version', ?)", (share.owner, stamp))
            return number

    def change(self, share: Share, *, comments_open: bool | None = None, new_links: bool = False) -> Share:
        with self._lock:
            if comments_open is not None:
                self._db.execute("UPDATE shares SET comments_open = ? WHERE id = ?", (int(comments_open), share.id))
            if new_links:
                self._db.execute(
                    "UPDATE shares SET comment_link = ?, view_link = ? WHERE id = ?",
                    (secrets.token_urlsafe(18), secrets.token_urlsafe(18), share.id),
                )
            return self.get(share.id)

    def delete(self, share_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM comments WHERE share_id = ?", (share_id,))
            self._db.execute("DELETE FROM versions WHERE share_id = ?", (share_id,))
            self._db.execute("DELETE FROM shares WHERE id = ?", (share_id,))
            shutil.rmtree(self.root / "files" / share_id, ignore_errors=True)

    def purge(self) -> None:
        """Delete the shares past their keeping time (at most once an hour)."""
        now = self.now()
        if self._purged and now - self._purged < timedelta(hours=1):
            return
        with self._lock:
            self._purged = now
            rows = self._db.execute("SELECT id FROM shares WHERE expires <= ?", (self._stamp(now),)).fetchall()
            for (share_id,) in rows:
                self.delete(share_id)
            old = self._stamp(now - timedelta(days=max(self.limits.period_days, 2)))
            self._db.execute("DELETE FROM uploads WHERE at <= ?", (old,))

    # -- comments ---------------------------------------------------------

    def comments(self, share_id: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, version, parent, author, by_owner, body, target, x, y, z, created, resolved"
            " FROM comments WHERE share_id = ? ORDER BY rowid", (share_id,)
        ).fetchall()
        out = []
        for cid, version, parent, author, by_owner, body, target, x, y, z, created, resolved in rows:
            at = None if x is None else {"x": x, "y": y, "z": z or 0.0}
            out.append({
                "id": cid, "version": version, "parent": parent, "author": author, "by_owner": bool(by_owner),
                "text": body, "target": target, "at": at, "created": created, "resolved": bool(resolved),
            })
        return out

    def _comment(self, share_id: str, comment_id: str) -> tuple | None:
        if not COMMENT_ID.match(comment_id or ""):
            return None
        return self._db.execute(
            "SELECT id, parent FROM comments WHERE share_id = ? AND id = ?", (share_id, comment_id)
        ).fetchone()

    def add_comment(self, share: Share, data: dict, *, by_owner: bool = False) -> dict:
        """
        A viewer's comment {name, text, version, target, at {x, y, z}} or a reply {name, text,
        parent}; the designer's own replies (by_owner) take the share's name.
        """
        if not isinstance(data, dict):
            raise ShareError("a comment must be an object")
        with self._lock:
            count = self._db.execute("SELECT COUNT(*) FROM comments WHERE share_id = ?", (share.id,)).fetchone()[0]
            if count >= MAX_COMMENTS:
                raise LimitReached("comments", f"at most {MAX_COMMENTS} comments on one share")
            text = _clean(data.get("text", ""), MAX_TEXT, "text")
            if by_owner:
                author = share.by_name or "설계자"
            else:
                author = _clean(data.get("name", ""), MAX_NAME, "name")
            parent = data.get("parent") or ""
            versions = [v["number"] for v in self.versions(share.id)]
            x = y = z = None
            target = ""
            if parent:
                found = self._comment(share.id, parent) if isinstance(parent, str) else None
                if found is None:
                    raise ShareError("no such comment to reply to")
                if found[1]:  # a reply to a reply goes under the first comment
                    parent = found[1]
                version = self._db.execute("SELECT version FROM comments WHERE id = ?", (parent,)).fetchone()[0]
            else:
                version = data.get("version", versions[-1] if versions else 0)
                if isinstance(version, bool) or not isinstance(version, int) or version not in versions:
                    raise ShareError("no such version")
                target = _clean(data.get("target", "") or "", MAX_TARGET, "target", required=False)
                at = data.get("at")
                if at is not None:
                    if not isinstance(at, dict):
                        raise ShareError("at must be {x, y, z}")
                    x, y = _number(at.get("x"), "x"), _number(at.get("y"), "y")
                    z = _number(at.get("z", 0.0), "z")
                    if x is None or y is None:
                        raise ShareError("at must have x and y")
            comment_id = "c_" + secrets.token_hex(6)
            self._db.execute(
                "INSERT INTO comments (id, share_id, version, parent, author, by_owner, body, target, x, y, z, created)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (comment_id, share.id, version, parent, author, int(by_owner), text, target, x, y, z, self._stamp()),
            )
            return next(c for c in self.comments(share.id) if c["id"] == comment_id)

    def resolve(self, share: Share, comment_id: str, resolved: bool) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE comments SET resolved = ? WHERE share_id = ? AND id = ?", (int(resolved), share.id, comment_id)
            )
        return cur.rowcount == 1

    def delete_comment(self, share: Share, comment_id: str) -> bool:
        """Delete a comment and, for a first comment, its replies."""
        with self._lock:
            cur = self._db.execute("DELETE FROM comments WHERE share_id = ? AND id = ?", (share.id, comment_id))
            if cur.rowcount:
                self._db.execute("DELETE FROM comments WHERE share_id = ? AND parent = ?", (share.id, comment_id))
        return cur.rowcount == 1
