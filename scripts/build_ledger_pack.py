#!/usr/bin/env python3
"""
Make a 건축물대장 pack (sida/experts/site/ledger_pack.py) from the 건축HUB monthly bulk file
"국토교통부_건축물대장_표제부 (YYYY년 MM월).zip" (원하는대로 건축데이터 → 대용량 데이터 제공 →
표제부 → 전체다운로드; no sign-in). The zip is read as it is; only the regions asked for are kept.

    python scripts/build_ledger_pack.py --zip "~/Sida/context_data/ledger/국토교통부_건축물대장_표제부+(2026년+09월).zip" --name seoul --sigungu 11

The pack goes to ~/Sida/context_data/<name>.ledger.sqlite (outside the repository). With a new
month's file, run it again: the pack is replaced.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sida.experts.site import ledger_pack, terrain_pack  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--zip", type=Path, required=True, help="the bulk 표제부 zip (or mart_djy_03.txt)")
    ap.add_argument("--name", required=True, help="pack name, e.g. seoul")
    ap.add_argument("--sigungu", default="11", help="시군구 code prefixes to keep, comma separated (11: Seoul)")
    ap.add_argument("--month", default="", help="the file's month as YYYY-MM (default: from the file name)")
    ap.add_argument("--folder", type=Path, default=terrain_pack.TERRAIN_DIR)
    args = ap.parse_args()
    source = args.zip.expanduser()
    prefixes = tuple(p.strip() for p in args.sigungu.split(",") if p.strip())
    started = time.perf_counter()
    kept = ledger_pack.build(source, args.folder / f"{args.name}{ledger_pack.SUFFIX}", prefixes, month=args.month,
                             log=lambda m: print(m, flush=True))
    print(f"{kept} rows, {time.perf_counter() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
