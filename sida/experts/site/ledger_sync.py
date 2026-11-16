"""Keep this PC's 건축물대장 packs (ledger_pack.py) current from the Sida relay.

The Korean server makes the packs each month from 건축HUB's bulk 표제부 file
(relay/ledger/ledger_pull.py) and lists them in /relay/ledger/manifest.json:
{"format": 1, "packs": [{"name", "month", "prefixes", "rows", "file", "bytes", "sha256"}]}, each
file a gzip of the pack. This PC takes a pack whose month is newer than the one it has under the
same name (~/Sida/context_data/<name>.ledger.sqlite): it downloads the gzip next to it, checks
size and SHA-256, unpacks it, checks the pack's own month and rows, then puts it in place. The
surroundings read the newest pack from the next build on (ledger_pack.lookup).

Asking needs a Sida access key (sida/relay.py), as the relay's other paths do. The app asks at
most once a day, in the background, when a site's surroundings are built (check_soon), and when
the designer asks (POST /api/site/ledger/update). What happened last is kept in
<folder>/ledger_sync.json.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

import requests

from sida import relay
from sida.experts.site import ledger_pack, terrain_pack

ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT / ".env"
MANIFEST = "/relay/ledger/manifest.json"
FORMAT = 1
CHECK_EVERY = 24 * 3600.0  # s between automatic checks
STATE = "ledger_sync.json"
TIMEOUT = 60
CHUNK = 1 << 20
MAX_BYTES = 2_000_000_000  # a gzip bigger than this is not a pack

_NAME = re.compile(r"^[a-z0-9_-]{1,40}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_FILE = re.compile(r"^[a-z0-9_-]{1,40}-\d{4}-\d{2}\.ledger\.sqlite\.gz$")
_SHA = re.compile(r"^[0-9a-f]{64}$")

_lock = threading.Lock()
_running = threading.Event()


class LedgerSyncError(Exception):
    """kind: no_relay (no access key), refused (the relay refused the key), network, bad_manifest, bad_file, disk."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind, detail)
        self.kind = kind
        self.detail = detail


def _load_env() -> None:
    if ENV_PATH.exists():
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH, override=False)


def _http_get(url: str, *, stream: bool = False) -> requests.Response:
    """The relay's answer (status checked). Errors never carry the URL."""
    try:
        response = requests.get(url, timeout=TIMEOUT, stream=stream, headers=relay.headers(url))
    except requests.RequestException as exc:
        raise LedgerSyncError("network", type(exc).__name__) from None
    if response.status_code in (401, 403):
        raise LedgerSyncError("refused", f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise LedgerSyncError("network", f"HTTP {response.status_code}")
    return response


def entries(manifest: object) -> list[dict]:
    """The manifest's packs, each checked; LedgerSyncError('bad_manifest') when anything is off."""
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or not isinstance(manifest.get("packs"), list):
        raise LedgerSyncError("bad_manifest", "format")
    out = []
    for e in manifest["packs"]:
        ok = (isinstance(e, dict) and isinstance(e.get("name"), str) and _NAME.match(e["name"])
              and isinstance(e.get("month"), str) and _MONTH.match(e["month"])
              and isinstance(e.get("file"), str) and _FILE.match(e["file"])
              and isinstance(e.get("sha256"), str) and _SHA.match(e["sha256"])
              and isinstance(e.get("bytes"), int) and 0 < e["bytes"] <= MAX_BYTES
              and isinstance(e.get("rows"), int) and e["rows"] > 0)
        if not ok:
            raise LedgerSyncError("bad_manifest", "pack")
        out.append({k: e[k] for k in ("name", "month", "file", "sha256", "bytes", "rows")}
                   | {"prefixes": str(e.get("prefixes", ""))})
    return out


def local_packs(folder: Path) -> list[dict]:
    """The packs in the folder: name, month, rows, prefixes."""
    out = []
    for path in sorted(folder.glob(f"*{ledger_pack.SUFFIX}")) if folder.is_dir() else []:
        meta = ledger_pack.info(path)
        out.append({"name": path.name[: -len(ledger_pack.SUFFIX)], "month": meta.get("month", ""),
                    "rows": int(meta.get("rows", 0) or 0), "prefixes": meta.get("prefixes", "")})
    return out


def _fetch(base: str, entry: dict, folder: Path) -> None:
    """Download, check and put one pack in place. The old pack stays when anything fails."""
    target = folder / f"{entry['name']}{ledger_pack.SUFFIX}"
    packed = target.with_name(target.name + ".gz.part")
    part = target.with_name(target.name + ".part")
    try:
        digest, size = hashlib.sha256(), 0
        with _http_get(f"{base}/relay/ledger/{entry['file']}", stream=True) as response, open(packed, "wb") as out:
            for chunk in response.iter_content(CHUNK):
                size += len(chunk)
                if size > entry["bytes"]:
                    raise LedgerSyncError("bad_file", "size")
                digest.update(chunk)
                out.write(chunk)
        if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
            raise LedgerSyncError("bad_file", "size" if size != entry["bytes"] else "sha256")
        try:
            with gzip.open(packed, "rb") as src, open(part, "wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
        except (OSError, EOFError) as exc:
            raise LedgerSyncError("bad_file", "gzip") from exc
        meta = ledger_pack.info(part)
        if meta.get("month") != entry["month"] or str(meta.get("rows")) != str(entry["rows"]):
            raise LedgerSyncError("bad_file", "contents")
        os.replace(part, target)
    finally:
        for leftover in (packed, part):
            leftover.unlink(missing_ok=True)


def _read_state(folder: Path) -> dict:
    try:
        state = json.loads((folder / STATE).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(folder: Path, state: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / STATE).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def update(folder: Path | None = None, *, now=time.time) -> dict:
    """
    Ask the relay for its packs and take each one newer than this PC's. Returns status(). Raises
    LedgerSyncError; what happened is kept for status() either way.
    """
    folder = terrain_pack.TERRAIN_DIR if folder is None else folder
    with _lock:
        state = {"checked_at": now(), "updated": [], "error": ""}
        try:
            _load_env()
            base = relay.base_url()
            if not base:
                raise LedgerSyncError("no_relay")
            try:
                manifest = _http_get(base + MANIFEST).json()
            except ValueError:
                raise LedgerSyncError("bad_manifest", "json") from None
            have = {p["name"]: p["month"] for p in local_packs(folder)}
            for entry in entries(manifest):
                if entry["month"] > have.get(entry["name"], ""):
                    folder.mkdir(parents=True, exist_ok=True)
                    _fetch(base, entry, folder)
                    state["updated"].append(f"{entry['name']} {entry['month']}")
        except LedgerSyncError as exc:
            state["error"] = exc.kind
            raise
        except OSError as exc:  # the folder: full, read-only, or the pack held open by a reader (Windows)
            state["error"] = "disk"
            raise LedgerSyncError("disk", type(exc).__name__) from None
        finally:
            _write_state(folder, state)
    return status(folder)


def status(folder: Path | None = None) -> dict:
    """This PC's packs and the last check: {packs, checked_at, updated, error, running, relay}."""
    folder = terrain_pack.TERRAIN_DIR if folder is None else folder
    state = _read_state(folder)
    _load_env()
    return {"packs": local_packs(folder), "checked_at": state.get("checked_at"), "updated": state.get("updated", []),
            "error": state.get("error", ""), "running": _running.is_set(), "relay": bool(relay.base_url())}


def due(folder: Path, now: float) -> bool:
    checked = _read_state(folder).get("checked_at")
    return not isinstance(checked, (int, float)) or now - checked >= CHECK_EVERY


def check_soon(folder: Path | None = None, *, force: bool = False, now=time.time) -> bool:
    """
    Start update() on a background thread when a day has passed since the last check (or `force`)
    and none is running. True when one was started. Never raises: a failed check waits a day.
    """
    folder = terrain_pack.TERRAIN_DIR if folder is None else folder
    _load_env()
    if not relay.base_url() or _running.is_set() or not (force or due(folder, now())):
        return False
    _running.set()

    def work() -> None:
        try:
            update(folder, now=now)
        except Exception:  # kept in the state file; the surroundings carry on with what they have
            pass
        finally:
            _running.clear()

    threading.Thread(target=work, name="sida-ledger-sync", daemon=True).start()
    return True
