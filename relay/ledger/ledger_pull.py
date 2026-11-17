#!/usr/bin/env python3
"""
Make the month's 건축물대장 packs on the Korean server, for the Sida apps to download through the
relay (GET /relay/ledger/..., sida/experts/site/ledger_sync.py on the PC side).

Runs daily from ledger-pull.timer (systemd) as the `ledger` account; it does work only when 건축HUB
has a new month:

1. Read 건축HUB's bulk data list (원하는대로 건축데이터 → 대용량 데이터 제공, 건축물대장) and take
   the newest 표제부 (task code 0303; 0302 is 총괄표제부). Its file id changes every month, so the
   list is read each time. No sign-in, cookie or CSRF token is needed (checked 2026-11-16).
2. Stop when the manifest already has that file id.
3. Download the zip (~650MB, no resume: the server ignores Range) and check it: the declared
   size, all of it arrived, a zip. 건축HUB answers an unknown id with 200 and nothing.
4. Make every region's pack in one reading of the zip (sida.experts.site.ledger_pack; one per
   시·도 by default, sida.experts.site.regions), and refuse the month when a pack has no rows or
   fewer than 95% of last month's (a broken file, not a month of demolition).
5. Gzip each pack next to the manifest for the apps to download, and keep the pack itself there
   too (<name>-<month>.ledger.sqlite, not in the manifest) for the relay to look parcels up in.
   Then write the manifest (atomically) and remove the files of other months. The zip and the
   work files are removed whatever happened.

    python3 ledger_pull.py --out /opt/sida-kr/data/ledger --work /opt/sida-kr/data/ledger-work
    python3 ledger_pull.py --out … --work … --region seoul=11 --region gyeonggi=41   # only these

The ledger_pack module is taken from the repository when run there, else from src/ next to this
file (a copy made at install, relay/README.md).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))  # the installed copy; in the repository sida is found anyway
sys.path.insert(1, str(HERE.parents[1]))

from sida.experts.site import ledger_pack  # noqa: E402
from sida.experts.site.regions import ledger_regions  # noqa: E402

HUB = "https://www.hub.go.kr"
LIST_URL = HUB + "/portal/opn/lps/idx-lgcpt-pvsn-srvc-list.do?opnLgcptTaskSeCd=03&pageCountPerPage=10&pageIndex=1"
DOWNLOAD_URL = HUB + "/cmm/fms/fileOpnDown.do?srvrFileNm={id}"
TASK = "0303"  # 표제부 (0302 is 총괄표제부)
MANIFEST = "manifest.json"
FORMAT = 1
MIN_SHARE = 0.95  # of last month's rows
MIN_ZIP = 100_000_000  # the national 표제부 is ~650MB; anything far smaller is not it
TIMEOUT = 120
CHUNK = 1 << 20
AGENT = "Mozilla/5.0 (compatible; Sida ledger update; monthly)"

_BUTTON = re.compile(r"fnDownloadPop\(\s*'03'\s*,\s*'(\d{4})'\s*,\s*'(OPN\d{10,30})'\s*\)")
_TITLE = re.compile(r'<p class="tit">\s*([^<]*?)\s*</p>')


class PullError(Exception):
    pass


def newest(page: str) -> tuple[str, str, str] | None:
    """(file id, title, month 'YYYY-MM') of the newest 표제부 on the list page, or None."""
    titles = [(m.start(), html.unescape(m.group(1))) for m in _TITLE.finditer(page)]
    found = []
    for m in _BUTTON.finditer(page):
        if m.group(1) != TASK:
            continue
        title = next((t for at, t in reversed(titles) if at < m.start()), "")
        month = ledger_pack.month_of(title)
        if month and "표제부" in title and "총괄" not in title:
            found.append((month, m.group(2), title))
    if not found:
        return None
    month, file_id, title = max(found)
    return file_id, title, month


def _open(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=TIMEOUT)


def fetch_text(url: str) -> str:
    with _open(url) as response:
        return response.read().decode("utf-8", errors="replace")


def download(url: str, dest: Path, *, opener=_open) -> int:
    """The file at `url` into `dest`, checked: declared size, all of it, a zip. Returns its bytes."""
    with opener(url) as response, open(dest, "wb") as out:
        declared = int(response.headers.get("Content-Length") or 0)
        if declared < MIN_ZIP:
            raise PullError(f"declared size {declared}")
        got = 0
        while chunk := response.read(CHUNK):
            got += len(chunk)
            out.write(chunk)
    if got != declared:
        raise PullError(f"got {got} of {declared} bytes")
    if not zipfile.is_zipfile(dest):
        raise PullError("not a zip")
    return got


def read_manifest(out: Path) -> dict:
    try:
        manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
        return manifest if isinstance(manifest, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, text: str) -> None:
    part = path.with_name(path.name + ".part")
    part.write_text(text, encoding="utf-8")
    os.chmod(part, 0o644)
    os.replace(part, path)


def _gzip(src: Path, dest: Path) -> tuple[int, str]:
    part = dest.with_name(dest.name + ".part")
    with open(src, "rb") as raw, gzip.open(part, "wb", compresslevel=6) as packed:
        shutil.copyfileobj(raw, packed, CHUNK)
    digest = hashlib.sha256()
    with open(part, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    os.chmod(part, 0o644)
    os.replace(part, dest)
    return dest.stat().st_size, digest.hexdigest()


def run(out: Path, work: Path, regions: dict[str, tuple[str, ...]], *, page: str | None = None,
        fetch=fetch_text, fetch_file=download, log=print) -> str:
    """Make the packs when 건축HUB has a new 표제부. Returns 'unchanged' or 'updated <month>'."""
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    found = newest(page if page is not None else fetch(LIST_URL))
    if found is None:
        raise PullError("no 표제부 on 건축HUB's list (the page changed?)")
    file_id, title, month = found
    old = read_manifest(out)
    listed = {p.get("name") for p in old.get("packs", []) if isinstance(p, dict)}
    kept = all((out / f"{name}-{month}{ledger_pack.SUFFIX}").is_file() for name in regions)
    if old.get("source_id") == file_id and listed == set(regions) and kept:
        log(f"unchanged: {title} ({file_id})")
        return "unchanged"
    before = {p.get("name"): int(p.get("rows", 0)) for p in old.get("packs", []) if isinstance(p, dict)}
    source = work / f"{file_id}.zip"
    made = {name: work / f"{name}{ledger_pack.SUFFIX}" for name in regions}
    try:
        log(f"downloading {title} ({file_id})")
        size = fetch_file(DOWNLOAD_URL.format(id=file_id), source)
        rows = ledger_pack.build_many(source, {made[name]: prefixes for name, prefixes in regions.items()},
                                      month=month, log=log)
        for name in regions:
            got = rows[made[name]]
            if got <= 0 or got < MIN_SHARE * before.get(name, 0):
                raise PullError(f"{name}: {got} rows, last month {before.get(name, 0)}")
        packs = []
        for name, prefixes in regions.items():
            file = f"{name}-{month}{ledger_pack.SUFFIX}.gz"
            gz_bytes, sha = _gzip(made[name], out / file)
            packs.append({"name": name, "month": month, "prefixes": ",".join(prefixes), "rows": rows[made[name]],
                          "file": file, "bytes": gz_bytes, "sha256": sha})
            log(f"{name}: {rows[made[name]]} rows, {gz_bytes} bytes")
        for name in regions:  # the packs themselves, for the relay's lookups (same disk: a rename)
            shutil.move(made[name], out / f"{name}-{month}{ledger_pack.SUFFIX}")
            os.chmod(out / f"{name}-{month}{ledger_pack.SUFFIX}", 0o644)
        manifest = {"format": FORMAT, "source": "국토교통부 건축물대장 표제부 (건축HUB 대용량 데이터 제공)",
                    "source_title": title, "source_id": file_id, "source_bytes": size,
                    "made_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "packs": packs}
        _write_atomic(out / MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
        keep = {MANIFEST} | {p["file"] for p in packs} | {f"{name}-{month}{ledger_pack.SUFFIX}" for name in regions}
        for path in out.iterdir():
            if path.is_file() and path.name not in keep:
                path.unlink()
        return f"updated {month}"
    finally:
        for path in (source, *made.values()):
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".part").unlink(missing_ok=True)


def parse_regions(items: list[str]) -> dict[str, tuple[str, ...]]:
    """--region values (name=시군구 prefixes) as {name: prefixes}; every 시·도 when none are given."""
    if not items:
        return ledger_regions()
    out = {}
    for item in items:
        name, _, prefixes = item.partition("=")
        out[name.strip()] = tuple(p.strip() for p in prefixes.split(",") if p.strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="what the relay serves (manifest + packs)")
    ap.add_argument("--work", type=Path, required=True, help="room for the zip (~650MB) and the packs")
    ap.add_argument("--region", action="append", default=[],
                    help="name=시군구 prefixes, e.g. seoul=11 (repeat; default: one pack per 시·도)")
    args = ap.parse_args()
    try:
        print(run(args.out, args.work, parse_regions(args.region), log=lambda m: print(m, flush=True)), flush=True)
    except (PullError, OSError, zipfile.BadZipFile, sqlite3.Error) as exc:
        print(f"failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
