"""The 시·도 of Korea: their codes, a file-safe name for each, and the names people write.

One table for everything that works region by region: the server's monthly 건축물대장 packs
(relay/ledger/ledger_pull.py, one pack per 시·도) and scripts/build_region_packs.py, which tells the
시·도 of a downloaded file from its name or its folder.

A 시·도 can have more than one code: the old one stays in older files and registers after it
changed (강원 42 → 51 in 2023, 전북 45 → 52 in 2024, 광주 29 and 전남 46 → 전남광주통합특별시 12).
The first code is the current one. Standard library only (the server copies this file, relay/README.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    name: str  # file-safe: pack names such as busan-buildings, busan-2026-09.ledger.sqlite.gz
    codes: tuple[str, ...]  # 시·도 codes (the first two digits of a 시군구 code or a PNU), current first
    label: str  # how the screen writes it
    aliases: tuple[str, ...]  # how folders and files are named by people

    @property
    def code(self) -> str:
        return self.codes[0]


REGIONS: tuple[Region, ...] = (
    Region("seoul", ("11",), "서울특별시", ("서울특별시", "서울시", "서울")),
    Region("busan", ("26",), "부산광역시", ("부산광역시", "부산시", "부산")),
    Region("daegu", ("27",), "대구광역시", ("대구광역시", "대구시", "대구")),
    Region("incheon", ("28",), "인천광역시", ("인천광역시", "인천시", "인천")),
    Region("jeonnam-gwangju", ("12", "29", "46"), "전남광주통합특별시",
           ("전남광주통합특별시", "전남광주", "광주광역시", "광주시", "광주", "전라남도", "전남")),
    Region("daejeon", ("30",), "대전광역시", ("대전광역시", "대전시", "대전")),
    Region("ulsan", ("31",), "울산광역시", ("울산광역시", "울산시", "울산")),
    Region("sejong", ("36",), "세종특별자치시", ("세종특별자치시", "세종시", "세종")),
    Region("gyeonggi", ("41",), "경기도", ("경기도", "경기")),
    Region("gangwon", ("51", "42"), "강원특별자치도", ("강원특별자치도", "강원도", "강원")),
    Region("chungbuk", ("43",), "충청북도", ("충청북도", "충북")),
    Region("chungnam", ("44",), "충청남도", ("충청남도", "충남")),
    Region("jeonbuk", ("52", "45"), "전북특별자치도", ("전북특별자치도", "전라북도", "전북")),
    Region("gyeongbuk", ("47",), "경상북도", ("경상북도", "경북")),
    Region("gyeongnam", ("48",), "경상남도", ("경상남도", "경남")),
    Region("jeju", ("50",), "제주특별자치도", ("제주특별자치도", "제주도", "제주")),
)

_BY_CODE = {code: r for r in REGIONS for code in r.codes}
_BY_NAME = {r.name: r for r in REGIONS}
_ALIASES = [(a, r) for r in REGIONS for a in r.aliases]
_CODE = re.compile(r"\d{2}")


def by_code(code: str) -> Region | None:
    """The region of a 시·도 code ("11"), or of a longer code that starts with one (a 시군구 code, a PNU)."""
    return _BY_CODE.get(str(code).strip()[:2])


def by_name(name: str) -> Region | None:
    return _BY_NAME.get(name)


def find(text: str) -> Region | None:
    """The region a folder or file name means: its file-safe name (busan), a Korean name in it
    (부산, 부산광역시, 연속수치지형도_부산), or a 시·도 code as the whole name (26). None when it
    names none, or two (경기도_광주시)."""
    text = text.strip()
    if text.lower() in _BY_NAME:
        return _BY_NAME[text.lower()]
    if _CODE.fullmatch(text):
        return _BY_CODE.get(text)
    named = {region for alias, region in _ALIASES if alias in text}
    return named.pop() if len(named) == 1 else None


def ledger_regions() -> dict[str, tuple[str, ...]]:
    """{name: 시군구 code prefixes} for one 건축물대장 pack per 시·도 (relay/ledger/ledger_pull.py)."""
    return {r.name: r.codes for r in REGIONS}
