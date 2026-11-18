#!/usr/bin/env python3
"""
Check the map packs of each 시·도 after they are made, and write what was found on one page:

    python scripts/check_region_packs.py                       # every 시·도 with a pack
    python scripts/check_region_packs.py --region busan --sample "busan=부산광역시 연제구 중앙대로 1001"
    python scripts/check_region_packs.py --no-api              # without asking 브이월드

For each 시·도 (packs named <region>-buildings / -contours / -areas, sida/experts/site/regions.py):
  1. 묶음: how much each pack holds against the pack it replaced (scripts/build_region_packs.py keeps
     both in region_packs.json), and any new pack that was refused for holding far less.
  2. 범위: whether what the packs hold reaches every side of the 시·도 (its boundary box from
     브이월드 LT_C_ADSIDO_INFO; only the box is kept).
  3. 견본 주소: the 시·도청 (or --sample) found with 브이월드 address search, and what the packs give
     within 150 m of it: buildings, contours, ground areas, the ground heights made ahead, the
     건축물대장 pack. A wrong projection or a pack of the wrong place shows here as nothing found.
  4. 지형 칸: how many of the box's tiles <region>.ground.sqlite has solved.

The page goes to <folder>/region-check/check-<YYYYMMDD-HHMM>.md (and its path is printed). 브이월드
is asked as the app asks it (sida/experts/site/landapi.py: this PC's key, else the Sida relay).
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sida.console import configure_stdio  # noqa: E402
from sida.experts.site import (  # noqa: E402
    ground_tiles,
    landapi,
    ledger_pack,
    regions,
    terrain_pack,
)

KINDS = {"buildings": "건물", "contours": "등고선·표고점", "areas": "도로·인도·물"}
BOX_TABLES = {"buildings": ("buildings_box",), "contours": ("contours_box", "spots_box"),
              "areas": ("areas_box", "map_buildings_box")}
COUNTED = {"buildings": ("buildings",), "contours": ("contours", "spots"), "areas": ("areas", "map_buildings")}
MIN_SHARE = 0.95
SLACK = 0.01  # degrees (about 1 km) a pack may fall short of the 시·도 box before it counts as not covering
NEAR = 150.0  # m around the sample address
STATE = "region_packs.json"
# 시·도청 addresses, as samples: well known and inside each 시·도's busiest area.
SAMPLES = {
    "seoul": "서울특별시 중구 세종대로 110",
    "busan": "부산광역시 연제구 중앙대로 1001",
    "daegu": "대구광역시 중구 공평로 88",
    "incheon": "인천광역시 남동구 정각로 29",
    "jeonnam-gwangju": "광주광역시 서구 내방로 111",
    "daejeon": "대전광역시 서구 둔산로 100",
    "ulsan": "울산광역시 남구 중앙로 201",
    "sejong": "세종특별자치시 한누리대로 2130",
    "gyeonggi": "경기도 수원시 영통구 도청로 30",
    "gangwon": "강원특별자치도 춘천시 중앙로 1",
    "chungbuk": "충청북도 청주시 상당구 상당로 82",
    "chungnam": "충청남도 홍성군 홍북읍 충남대로 21",
    "jeonbuk": "전북특별자치도 전주시 완산구 효자로 225",
    "gyeongbuk": "경상북도 안동시 풍천면 도청대로 455",
    "gyeongnam": "경상남도 창원시 의창구 중앙대로 300",
    "jeju": "제주특별자치도 제주시 문연로 6",
}
OK, WARN, NONE = "통과", "확인 필요", "—"


def pack_path(folder: Path, name: str, kind: str) -> Path:
    return folder / f"{name}-{kind}{terrain_pack.SUFFIX}"


def extent(path: Path, kind: str) -> list[float] | None:
    """west, south, east, north of what a pack holds of a kind (from its R*Tree boxes)."""
    boxes = []
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        for table in BOX_TABLES[kind]:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
                row = conn.execute(f"SELECT min(west), min(south), max(east), max(north) FROM {table}").fetchone()  # noqa: S608
                if row and row[0] is not None:
                    boxes.append(row)
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def counts(path: Path, kind: str) -> dict[str, int]:
    out = {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        for table in COUNTED[kind]:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
                out[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
    return out


def short_of(have: list[float], want: list[float]) -> list[str]:
    """The sides of `want` that `have` falls short of by more than SLACK, with how far (km)."""
    lat = (want[1] + want[3]) / 2
    km_lon, km_lat = 111.32 * math.cos(math.radians(lat)), 110.57
    sides = [("서", want[0] - have[0], km_lon), ("남", want[1] - have[1], km_lat),
             ("동", have[2] - want[2], km_lon), ("북", have[3] - want[3], km_lat)]
    return [f"{name}쪽 {-gap * scale:.1f} km" for name, gap, scale in sides if gap < -SLACK]


def check_packs(folder: Path, name: str, state: dict) -> tuple[str, list[str], list[float] | None]:
    """(verdict, lines, the extent of all the region's packs)."""
    lines, verdict, boxes = [], NONE, []
    recorded = (state.get("regions") or {}).get(name) or {}
    for kind, label in KINDS.items():
        path = pack_path(folder, name, kind)
        if not path.exists():
            lines.append(f"- {label}: 묶음 없음")
            continue
        verdict = OK if verdict == NONE else verdict
        meta = terrain_pack.info(path)
        now = counts(path, kind)
        record = recorded.get(kind) or {}
        before = record.get("previous") or {}
        change = ", ".join(f"{t} {n:,}" + (f" (지난번 {before[t]:,}, {100 * (n - before[t]) / before[t]:+.1f}%)"
                                            if before.get(t) else "") for t, n in now.items())
        lines.append(f"- {label}: {path.name}, 기준일 {meta.get('source_date') or '미확인'}, {change}")
        if any(before.get(t) and n < MIN_SHARE * before[t] for t, n in now.items()):
            verdict = WARN
            lines.append("  - 지난번보다 5% 넘게 줄었어요. 받은 파일이 잘렸는지 확인해 주세요.")
        if record.get("refused"):
            verdict = WARN
            lines.append(f"  - 새로 만든 묶음이 지난번보다 크게 적어서({', '.join(record['refused'])}) 바꾸지 않았어요. "
                         "받은 파일을 확인하고, 맞으면 --accept-drop으로 다시 돌려 주세요.")
        if (box := extent(path, kind)) is not None:
            boxes.append(box)
    whole = None
    if boxes:
        whole = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    return verdict, lines, whole


def check_cover(region: regions.Region, folder: Path, sido: dict | None) -> tuple[str, list[str]]:
    if sido is None:
        return NONE, ["- 시·도 경계를 받지 못해 확인 못함"]
    want = None
    for code in region.codes:
        if code in sido:
            b = sido[code]
            want = b if want is None else [min(want[0], b[0]), min(want[1], b[1]), max(want[2], b[2]), max(want[3], b[3])]
    if want is None:
        return NONE, [f"- 브이월드 시·도 목록에 {region.label}({', '.join(region.codes)})가 없어 확인 못함"]
    lines, verdict = [f"- 시·도 경계 상자 {', '.join(f'{v:.4f}' for v in want)}"], OK
    for kind, label in KINDS.items():
        path = pack_path(folder, region.name, kind)
        if not path.exists() or (have := extent(path, kind)) is None:
            continue
        short = short_of(have, want)
        if short:
            verdict = WARN
            lines.append(f"- {label}: 시·도를 다 덮지 못함 ({', '.join(short)} 모자람)")
        else:
            lines.append(f"- {label}: 시·도를 덮음")
    return verdict, lines


def near_box(lon: float, lat: float, metres: float) -> tuple[float, float, float, float]:
    dlat = metres / 111_320.0
    dlon = metres / (111_320.0 * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def check_sample(region: regions.Region, folder: Path, address: str, use_api: bool) -> tuple[str, list[str]]:
    if not use_api:
        return NONE, [f"- {address}: 브이월드를 묻지 않아 확인 못함 (--no-api)"]
    try:
        hits = landapi.search_parcels(address, size=1)
    except Exception as exc:  # noqa: BLE001 — any failure of the search is reported, not raised
        return NONE, [f"- {address}: 주소 검색 실패 ({getattr(exc, 'kind', '') or type(exc).__name__})"]
    if not hits:
        return WARN, [f"- {address}: 주소를 찾지 못함 (--sample로 다른 주소를 주세요)"]
    hit = hits[0]
    try:
        lon, lat = float(hit["x"]), float(hit["y"])
    except (KeyError, ValueError):
        return WARN, [f"- {address}: 검색 결과에 좌표가 없음"]
    found = terrain_pack.query(*near_box(lon, lat, NEAR), folder=folder)
    areas: dict[str, int] = {}
    for a in found["areas"]:
        areas[a["kind"]] = areas.get(a["kind"], 0) + 1
    lines = [f"- {address} → {hit.get('address') or ''} ({lon:.5f}, {lat:.5f}), 둘레 {NEAR:.0f} m 안:",
             f"  - 건물 {len(found['buildings'])}동, 등고선 {len(found['contours'])}줄, 표고점 {len(found['spots'])}점, "
             f"도로 면 {areas.get('road', 0)}, 인도 면 {areas.get('sidewalk', 0)}, 물 면 {areas.get('water', 0)}"]
    verdict = OK
    if not found["buildings"] or not (found["contours"] or found["spots"]):
        verdict = WARN
        lines.append("  - 건물이나 지형이 하나도 나오지 않아요. 이 시·도 묶음이 없거나, 좌표계가 어긋났을 수 있어요.")
    try:
        heights = ground_tiles.heights([lon], [lat], folder)
    except sqlite3.Error:
        heights = None
    lines.append("  - 미리 푼 지형: " + (f"있음 (해발 {heights[0]:.1f} m)" if heights is not None
                                     else "없음 (대지마다 직접 풂)"))
    pnu = str(hit.get("pnu") or "")
    if pnu:
        rows, used = ledger_pack.lookup([pnu], folder)
        lines.append("  - 건축물대장 묶음: " + (f"{used.get('month')} 묶음에 있음 ({len(rows.get(pnu, []))}동)"
                                         if pnu in rows else "이 PC 묶음에 없음 (API로 물음)"))
    return verdict, lines


def check_ground(name: str, folder: Path, box: list[float] | None) -> tuple[str, list[str]]:
    path = folder / f"{name}{ground_tiles.SUFFIX}"
    if not path.exists():
        return NONE, ["- 미리 푼 지형 파일 없음"]
    meta = ground_tiles.info(path)
    try:
        box = [float(v) for v in meta.get("box", "").split(",")] if meta.get("box") else box
    except ValueError:
        pass
    done = ground_tiles.done(path)
    total = len(ground_tiles.tiles_in_box(*box)) if box else 0
    others = set()
    for other in ground_tiles.files(folder):
        if other != path:
            others |= ground_tiles.done(other)
    covered = len({t for t in ground_tiles.tiles_in_box(*box) if t in done or t in others}) if box else len(done)
    current = ground_tiles.current(path, folder)
    verdict = OK if current and covered >= total else WARN
    lines = [f"- {path.name}: 칸 {len(done):,}개 (상자 안 {total:,}칸 중 다른 파일 것까지 {covered:,}칸)"]
    if not current:
        lines.append("  - 묶음이 바뀌어서 일부 칸을 다시 풀어야 해요: build_ground_tiles.py를 다시 돌려 주세요.")
    elif covered < total:
        lines.append("  - 아직 다 풀지 못했어요: 같은 명령으로 이어서 합니다.")
    return verdict, lines


def report(folder: Path, names: list[str], samples: dict[str, str], use_api: bool) -> str:
    try:
        state = json.loads((folder / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    sido = None
    if use_api:
        try:
            sido = landapi.sido_boxes()
        except Exception:  # noqa: BLE001 — reported as not checked
            sido = None
    rows, sections = [], []
    for name in names:
        region = regions.by_name(name)
        packs_v, packs_l, whole = check_packs(folder, name, state)
        cover_v, cover_l = check_cover(region, folder, sido)
        sample_v, sample_l = check_sample(region, folder, samples.get(name, SAMPLES.get(name, "")), use_api)
        ground_v, ground_l = check_ground(name, folder, whole)
        rows.append(f"| {region.label} | {packs_v} | {cover_v} | {sample_v} | {ground_v} |")
        sections += [f"## {region.label} ({name})", "", "**묶음**", *packs_l, "", "**범위**", *cover_l, "",
                     "**견본 주소**", *sample_l, "", "**미리 푼 지형**", *ground_l, ""]
    known = {pack_path(folder, n, k).name for n in (r.name for r in regions.REGIONS) for k in KINDS}
    other = [p.name for p in terrain_pack.packs(folder) if p.name not in known]
    page = [f"# 지도 묶음 점검 ({time.strftime('%Y-%m-%d %H:%M')})", "",
            f"폴더: `{folder}`", "",
            "| 시·도 | 묶음 | 범위 | 견본 주소 | 미리 푼 지형 |", "|---|---|---|---|---|", *rows, "",
            f"\"{WARN}\"인 칸만 아래에서 보면 돼요. \"{NONE}\"는 확인할 것이 없거나 확인하지 못한 칸이에요.", "",
            *sections]
    if other:
        page += ["## 시·도 이름이 아닌 묶음", "", "주변 3D는 이 묶음들도 함께 읽어요. 같은 곳을 시·도 묶음이 덮으면 지워도 돼요.", "",
                 *[f"- {n}" for n in other], ""]
    return "\n".join(page)


def main() -> int:
    configure_stdio()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("--folder", type=Path, default=terrain_pack.TERRAIN_DIR)
    ap.add_argument("--region", default="", help="only these 시·도, comma separated (default: every one with a pack)")
    ap.add_argument("--sample", action="append", default=[], help="region=address to look around (repeat)")
    ap.add_argument("--no-api", action="store_true", help="do not ask 브이월드 (no 범위 and 견본 주소)")
    args = ap.parse_args()
    folder = args.folder.expanduser().resolve()
    if args.region:
        names = []
        for item in args.region.split(","):
            region = regions.by_name(item.strip().lower()) or regions.find(item.strip())
            if region is None:
                ap.error(f"not a 시·도: {item}")
            names.append(region.name)
    else:
        names = [r.name for r in regions.REGIONS if any(pack_path(folder, r.name, k).exists() for k in KINDS)]
    if not names:
        print(f"no 시·도 packs in {folder}")
        return 1
    samples = {}
    for item in args.sample:
        key, _, address = item.partition("=")
        region = regions.by_name(key.strip().lower()) or regions.find(key.strip())
        if region is None or not address.strip():
            ap.error(f"--sample needs region=address: {item}")
        samples[region.name] = address.strip()
    page = report(folder, names, samples, not args.no_api)
    out = folder / "region-check" / f"check-{time.strftime('%Y%m%d-%H%M')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(page)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
