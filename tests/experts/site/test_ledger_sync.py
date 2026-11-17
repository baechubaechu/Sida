"""ledger_sync — this PC takes a newer month's 건축물대장 pack from the Sida relay."""

from __future__ import annotations

import gzip
import hashlib
import json

import pytest

from sida import relay
from sida.experts.site import ledger_pack, ledger_sync
from tests.experts.site.test_ledger_pack import bulk_zip

BASE = "https://relay.test"


def made_pack(tmp_path, month: str) -> tuple[bytes, int]:
    """(gzip of a real pack of the sample's Seoul line for `month`, its rows)."""
    path = tmp_path / f"made-{month}{ledger_pack.SUFFIX}"
    rows = ledger_pack.build(bulk_zip(tmp_path), path, ("11",), month=month, log=lambda _m: None)
    return gzip.compress(path.read_bytes()), rows


class Answer:
    def __init__(self, body: bytes):
        self.body = body

    def json(self):
        return json.loads(self.body)

    def iter_content(self, size):
        for k in range(0, len(self.body), 7):
            yield self.body[k:k + 7]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A relay with an access key, serving what `files` holds; `asked` lists the URLs asked."""
    monkeypatch.setenv(relay.ENV_NAME, BASE)
    monkeypatch.setenv(relay.TOKEN_ENV, "sida_test_key_123")
    files, asked = {}, []

    def http_get(url, stream=False):
        asked.append(url)
        assert relay.headers(url) == {"Authorization": "Bearer sida_test_key_123"}
        name = url.rsplit("/", 1)[1]
        if name not in files:
            raise ledger_sync.LedgerSyncError("network", "HTTP 404")
        return Answer(files[name])

    monkeypatch.setattr(ledger_sync, "_http_get", http_get)
    return files, asked


def publish(files, data: bytes, rows: int, month: str, sha: str | None = None):
    file = f"seoul-{month}.ledger.sqlite.gz"
    files[file] = data
    files["manifest.json"] = json.dumps({"format": 1, "packs": [{
        "name": "seoul", "month": month, "prefixes": "11", "rows": rows, "file": file, "bytes": len(data),
        "sha256": sha or hashlib.sha256(data).hexdigest()}]}).encode()


def test_a_newer_month_is_downloaded_checked_and_put_in_place(tmp_path, server):
    files, asked = server
    folder = tmp_path / "context_data"
    publish(files, *made_pack(tmp_path, "2026-09"), "2026-09")
    out = ledger_sync.update(folder, now=lambda: 1000.0)
    assert [p["month"] for p in out["packs"]] == ["2026-09"] and out["updated"] == ["seoul 2026-09"] and not out["error"]
    assert ledger_pack.lookup(["1111011900101060000"], folder)[1]["month"] == "2026-09"
    assert sorted(p.name for p in folder.iterdir()) == ["ledger_sync.json", "seoul.ledger.sqlite"]
    asked.clear()
    assert ledger_sync.update(folder)["updated"] == []  # the same month: only the manifest is asked
    assert asked == [BASE + ledger_sync.MANIFEST]


def test_a_broken_download_leaves_the_old_pack(tmp_path, server):
    files, _ = server
    folder = tmp_path / "context_data"
    publish(files, *made_pack(tmp_path, "2026-08"), "2026-08")
    ledger_sync.update(folder)
    data, rows = made_pack(tmp_path, "2026-09")
    publish(files, data, rows, "2026-09", sha="0" * 64)
    with pytest.raises(ledger_sync.LedgerSyncError) as err:
        ledger_sync.update(folder)
    assert err.value.kind == "bad_file"
    assert ledger_sync.status(folder)["error"] == "bad_file"
    assert [p["month"] for p in ledger_sync.local_packs(folder)] == ["2026-08"]
    assert sorted(p.name for p in folder.iterdir()) == ["ledger_sync.json", "seoul.ledger.sqlite"]  # no leftovers
    publish(files, data, rows + 1, "2026-09")  # the pack inside says otherwise than the manifest
    with pytest.raises(ledger_sync.LedgerSyncError):
        ledger_sync.update(folder)


@pytest.mark.parametrize("manifest", [{"format": 2, "packs": []}, {"format": 1, "packs": [{"name": "../x"}]}],
                         ids=["format", "name"])
def test_a_manifest_that_is_not_as_expected_is_refused(manifest):
    with pytest.raises(ledger_sync.LedgerSyncError):
        ledger_sync.entries(manifest)


def test_without_an_access_key_nothing_is_asked(tmp_path):
    folder = tmp_path / "context_data"
    assert ledger_sync.check_soon(folder) is False
    with pytest.raises(ledger_sync.LedgerSyncError) as err:
        ledger_sync.update(folder)
    assert err.value.kind == "no_relay" and ledger_sync.status(folder)["relay"] is False


def test_the_check_runs_at_most_once_a_day_in_the_background(tmp_path, server, monkeypatch):
    files, _ = server
    folder = tmp_path / "context_data"
    publish(files, *made_pack(tmp_path, "2026-08"), "2026-08")
    ledger_sync.update(folder, now=lambda: 0.0)
    files.clear()
    started = []
    monkeypatch.setattr(ledger_sync.threading, "Thread",
                        lambda target, **kw: type("T", (), {"start": lambda self: started.append(target)})())
    assert ledger_sync.check_soon(folder, now=lambda: 2 * ledger_sync.CHECK_EVERY)
    started.pop()()  # run it here; nothing published → a network error, kept
    assert ledger_sync.status(folder)["error"] == "network" and not ledger_sync.status(folder)["running"]
    assert not ledger_sync.check_soon(folder, now=lambda: 3 * ledger_sync.CHECK_EVERY - 1)
    assert ledger_sync.check_soon(folder, now=lambda: 3 * ledger_sync.CHECK_EVERY - 1, force=True)
    started.pop()()
    assert ledger_sync.check_soon(folder, now=lambda: 4 * ledger_sync.CHECK_EVERY)
    started.pop()()


def test_the_daily_check_only_keeps_packs_this_pc_has_current(tmp_path, server, monkeypatch):
    files, _ = server
    folder = tmp_path / "context_data"
    publish(files, *made_pack(tmp_path, "2026-09"), "2026-09")
    started = []
    monkeypatch.setattr(ledger_sync.threading, "Thread",
                        lambda target, **kw: type("T", (), {"start": lambda self: started.append(target)})())
    assert not ledger_sync.check_soon(folder, now=lambda: 0.0)  # no pack here: nothing downloaded
    assert ledger_sync.update(folder, new=False)["updated"] == []
    assert ledger_sync.check_soon(folder, now=lambda: 0.0, force=True)  # the designer asked
    started.pop()()
    assert [p["month"] for p in ledger_sync.local_packs(folder)] == ["2026-09"]
