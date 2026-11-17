"""relay/ledger/ledger_pull.py — the server's monthly 건축물대장 packs, with a fake 건축HUB."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from relay.ledger import ledger_pull

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "ledger" / "mart_djy_03.txt"  # 군포 + 종로


def entry(title: str, task: str, file_id: str) -> str:
    return (f'<li><div class="txt"><p class="tit">{title}</p></div>'
            f'<a href="#" onclick="fnDownloadPop(\'03\',\'{task}\',\'{file_id}\')">전체다운로드</a></li>')


PAGE = "<ul>" + "".join([
    entry("총괄표제부 (2026년 09월)", "0302", "OPN202610201221080001"),
    entry("표제부 (2026년 09월)", "0303", "OPN202610201221084580"),
    entry("표제부 (2026년 08월)", "0303", "OPN202609191100000002"),
]) + "</ul>"


def fake_zip(extra_lines: int = 0):
    def fetch_file(url, dest):
        assert url.endswith("srvrFileNm=OPN202610201221084580")
        text = SAMPLE.read_text(encoding="utf-8")
        seoul = text.splitlines()[1]
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr(ledger_pull.ledger_pack.MEMBER, text + "".join(seoul + "\n" for _ in range(extra_lines)))
        return dest.stat().st_size
    return fetch_file


def test_the_newest_표제부_is_taken_not_총괄표제부():
    assert ledger_pull.newest(PAGE) == ("OPN202610201221084580", "표제부 (2026년 09월)", "2026-09")
    assert ledger_pull.newest(entry("총괄표제부 (2026년 09월)", "0302", "OPN202610201221080001")) is None


def test_a_new_month_makes_the_packs_the_manifest_lists_and_leaves_no_zip(tmp_path):
    out, work = tmp_path / "out", tmp_path / "work"
    out.mkdir()
    (out / "seoul-2026-08.ledger.sqlite.gz").write_bytes(b"last month")
    assert ledger_pull.run(out, work, {"seoul": ("11",)}, page=PAGE, fetch_file=fake_zip(), log=lambda m: None) \
        == "updated 2026-09"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    pack = manifest["packs"][0]
    assert manifest["format"] == 1 and manifest["source_id"] == "OPN202610201221084580"
    assert {k: pack[k] for k in ("name", "month", "prefixes", "rows")} == \
        {"name": "seoul", "month": "2026-09", "prefixes": "11", "rows": 1}  # 군포 left out
    data = (out / pack["file"]).read_bytes()
    assert len(data) == pack["bytes"] and hashlib.sha256(data).hexdigest() == pack["sha256"]
    unpacked = tmp_path / "check.sqlite"
    unpacked.write_bytes(gzip.decompress(data))
    with closing(sqlite3.connect(unpacked)) as conn:
        assert dict(conn.execute("SELECT key, value FROM meta"))["month"] == "2026-09"
    kept = "seoul-2026-09.ledger.sqlite"  # the pack itself, for the relay's lookups; not in the manifest
    assert sorted(p.name for p in out.iterdir()) == sorted(["manifest.json", pack["file"], kept])  # last month's removed
    assert list(work.iterdir()) == []
    # the next night: the same file id, nothing downloaded
    assert ledger_pull.run(out, work, {"seoul": ("11",)}, page=PAGE, fetch_file=None, log=lambda m: None) == "unchanged"
    # without the kept pack (made before packs were kept) the month is made again
    (out / kept).unlink()
    assert ledger_pull.run(out, work, {"seoul": ("11",)}, page=PAGE, fetch_file=fake_zip(),
                           log=lambda m: None) == "updated 2026-09"
    assert (out / kept).is_file()


def test_every_region_comes_from_one_reading_and_an_empty_one_refuses_the_month(tmp_path, monkeypatch):
    out, work = tmp_path / "out", tmp_path / "work"
    reads = []
    real = ledger_pull.ledger_pack.lines
    monkeypatch.setattr(ledger_pull.ledger_pack, "lines", lambda path: reads.append(path) or real(path))
    regions = {"seoul": ("11",), "gyeonggi": ("41",)}
    assert ledger_pull.run(out, work, regions, page=PAGE, fetch_file=fake_zip(), log=lambda m: None) == "updated 2026-09"
    assert len(reads) == 1
    packs = {p["name"]: p for p in json.loads((out / "manifest.json").read_text(encoding="utf-8"))["packs"]}
    assert {n: (p["prefixes"], p["rows"]) for n, p in packs.items()} == {"seoul": ("11", 1), "gyeonggi": ("41", 1)}
    for name in regions:
        with closing(sqlite3.connect(out / f"{name}-2026-09.ledger.sqlite")) as conn:
            assert conn.execute("SELECT count(*) FROM rows").fetchone()[0] == 1
    # a region with no rows at all is a broken file (or a code that changed): nothing is replaced
    before = sorted(p.name for p in out.iterdir())
    with pytest.raises(ledger_pull.PullError, match="busan"):
        ledger_pull.run(out, work, {**regions, "busan": ("26",)}, page=PAGE, fetch_file=fake_zip(), log=lambda m: None)
    assert sorted(p.name for p in out.iterdir()) == before
    assert list(work.iterdir()) == []


def test_without_regions_every_시도_gets_a_pack_with_its_old_codes_too():
    regions = ledger_pull.parse_regions([])
    assert len(regions) == 16 and regions["seoul"] == ("11",) and regions["gangwon"] == ("51", "42")
    assert regions["jeonnam-gwangju"] == ("12", "29", "46")
    codes = [c for prefixes in regions.values() for c in prefixes]
    assert len(codes) == len(set(codes))  # no 시군구 in two packs
    assert ledger_pull.parse_regions(["seoul=11", "metro=11,28"]) == {"seoul": ("11",), "metro": ("11", "28")}


def test_a_pack_much_smaller_than_last_months_is_refused_and_last_month_stays(tmp_path):
    out, work = tmp_path / "out", tmp_path / "work"
    out.mkdir()
    old = {"format": 1, "source_id": "OPN202609191100000002",
           "packs": [{"name": "seoul", "rows": 3, "file": "seoul-2026-08.ledger.sqlite.gz"}]}
    (out / "manifest.json").write_text(json.dumps(old), encoding="utf-8")
    (out / "seoul-2026-08.ledger.sqlite.gz").write_bytes(b"last month")
    with pytest.raises(ledger_pull.PullError):
        ledger_pull.run(out, work, {"seoul": ("11",)}, page=PAGE, fetch_file=fake_zip(), log=lambda m: None)
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == old
    assert sorted(p.name for p in out.iterdir()) == ["manifest.json", "seoul-2026-08.ledger.sqlite.gz"]
    assert list(work.iterdir()) == []
    # with enough rows it goes through
    assert ledger_pull.run(out, work, {"seoul": ("11",)}, page=PAGE, fetch_file=fake_zip(extra_lines=2),
                           log=lambda m: None) == "updated 2026-09"


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, length: int | None):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body) if length is None else length)}


def test_a_download_is_checked_for_size_and_being_a_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_pull, "MIN_ZIP", 10)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("mart_djy_03.txt", "x" * 100)
    good = buffer.getvalue()
    dest = tmp_path / "f.zip"
    assert ledger_pull.download("u", dest, opener=lambda url: FakeResponse(good, None)) == len(good)
    for body, length in ((b"", 0), (good[:-5], len(good)), (b"x" * 50, None)):  # 건축HUB's empty 200, cut short, not a zip
        with pytest.raises(ledger_pull.PullError):
            ledger_pull.download("u", dest, opener=lambda url, b=body, n=length: FakeResponse(b, n))


def test_a_failure_is_one_line_and_exit_1(monkeypatch, tmp_path, capsys):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(ledger_pull, "run", broken)
    monkeypatch.setattr("sys.argv", ["ledger_pull.py", "--out", str(tmp_path / "o"), "--work", str(tmp_path / "w")])
    assert ledger_pull.main() == 1
    assert capsys.readouterr().err.strip() == "failed: disk I/O error"


def test_the_service_lets_sqlite_write_its_temporary_files():
    unit = (Path(ledger_pull.__file__).parent / "ledger-pull.service").read_text(encoding="utf-8")
    lines = [line.strip() for line in unit.splitlines() if not line.startswith("#")]
    assert "PrivateTmp=yes" not in lines  # it would hide the work folder in /var/tmp
    start = next(line for line in lines if line.startswith("ExecStart="))
    assert "--region" not in start  # every 시·도
    work = start.split("--work ")[1].split()[0]
    assert any(line.startswith("Environment=") and f"SQLITE_TMPDIR={work}" in line for line in lines)
    assert any(line.startswith("ReadWritePaths=") and work in line for line in lines)
