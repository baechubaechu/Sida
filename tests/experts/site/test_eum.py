"""eum.py — the 토지이음 pages a card links to for a 고도지구 the app has no height table for."""

from __future__ import annotations

from sida.experts.site import eum


def test_the_parcels_land_use_page_and_the_notice_search_are_linked():
    page = eum.land_use_page("1130510400101000001")  # 우이동 100-1: its page names "고도지구(28m이하)"
    assert page == {"label": "토지이음 토지이용계획(이 필지)",
                    "url": "https://www.eum.go.kr/web/ar/lu/luLandDet.jsp?pnu=1130510400101000001&mode=search&isNoScr=script&selGbn=umd"}
    assert eum.land_use_page("123") is None and eum.land_use_page("") is None
    search = eum.notice_search("2024-0317")  # leading zeros dropped: the site finds "2024-317"
    assert search["label"] == "토지이음 고시 검색(2024-317)"
    assert search["url"] == "https://www.eum.go.kr/web/gs/gv/gvGosiList.jsp?gosino=2024-317&zonenm=%B0%ED%B5%B5&pageNo=1"
    assert eum.notice_search("0000-0000") is None and eum.notice_search("x") is None
    links = eum.height_links(["1130510400101000001"], ["0000-0000", "2023-1986"])
    assert [link["label"] for link in links] == ["토지이음 토지이용계획(이 필지)", "토지이음 고시 검색(2023-1986)"]
    assert eum.height_links([], []) == []
