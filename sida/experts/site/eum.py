"""Links to 토지이음 (eum.go.kr) pages a designer opens to read what the app cannot.

A 고도지구's height is in its notice, not in the government's data (height_districts.py). Where the
app has no table for that notice, the card points to two public 토지이음 pages instead
(2026-11-17 지훈: 표가 없는 지역은 고시 번호와 찾는 링크로 안내):

- the parcel's 토지이용계획 열람: its 지역·지구 list names the 고도지구 with its height
  ("고도지구(28m이하)", 우이동 100-1);
- the 고시정보 list for the notice number VWorld gives a piece, narrowed to titles with "고도"
  ("2024-317" finds 서울특별시 고시 제2024-317호 only). An old or unnumbered notice ("0000") may
  not be listed, so no search is offered for 0000.

Both opened and checked in a browser on 2026-11-18. The pages are only linked, never read.
"""

from __future__ import annotations

from urllib.parse import quote

LAND_USE_PAGE = "https://www.eum.go.kr/web/ar/lu/luLandDet.jsp?pnu={pnu}&mode=search&isNoScr=script&selGbn=umd"
NOTICE_SEARCH = "https://www.eum.go.kr/web/gs/gv/gvGosiList.jsp?gosino={number}&zonenm={word}&pageNo=1"
NOTICE_WORD = quote("고도".encode("cp949"))  # the site reads its query in cp949


def land_use_page(pnu: str) -> dict | None:
    """{"label", "url"} of the parcel's 토지이용계획 열람, or None for a PNU that is not 19 digits."""
    pnu = str(pnu or "")
    if len(pnu) != 19 or not pnu.isdigit():
        return None
    return {"label": "토지이음 토지이용계획(이 필지)", "url": LAND_USE_PAGE.format(pnu=pnu)}


def notice_search(number: str) -> dict | None:
    """{"label", "url"} of the 고시정보 search for a VWorld notice number ("2023-1986", "2024-0317"),
    or None for an unnumbered one ("0000-0000")."""
    year, _sep, serial = str(number or "").partition("-")
    if not (len(year) == 4 and year.isdigit() and serial.isdigit()) or int(year) == 0 or int(serial) == 0:
        return None
    short = f"{int(year)}-{int(serial)}"
    return {"label": f"토지이음 고시 검색({short})", "url": NOTICE_SEARCH.format(number=short, word=NOTICE_WORD)}


def height_links(pnus: list[str], notices: list[str]) -> list[dict]:
    """The links for a 고도지구 whose height the app does not know: the first parcel's 토지이용계획
    and a search per numbered notice."""
    out = [link for link in [land_use_page(pnus[0]) if pnus else None] if link]
    out += [link for link in (notice_search(n) for n in notices) if link]
    return out
