"""scripts/check_region_packs.py — the one-page check of each 시·도's packs, with 브이월드 stood in for."""

from __future__ import annotations

import json
import sys

from scripts import check_region_packs as crp
from sida.experts.site import landapi, terrain_pack


def pack(folder, name, kind, rows, lon=129.075, lat=35.18):
    conn = terrain_pack.create(folder / f"{name}-{kind}{terrain_pack.SUFFIX}", {"kind": kind, "source_date": "2026-03-01"})
    for i in range(rows):
        ring = [[lon + i * 1e-4, lat], [lon + 1e-4 + i * 1e-4, lat], [lon + i * 1e-4, lat + 1e-4]]
        if kind == "buildings":
            terrain_pack.add_building(conn, ring, {"pnu": "", "use": "", "height": None, "floors": None})
        elif kind == "contours":
            terrain_pack.add_contour(conn, 10.0, ring)
        else:
            terrain_pack.add_area(conn, "road", ring)
    conn.commit()
    conn.close()


def test_one_page_with_counts_cover_and_what_the_sample_address_gives(tmp_path, monkeypatch, capsys):
    pack(tmp_path, "busan", "buildings", 9)
    pack(tmp_path, "busan", "contours", 3)
    pack(tmp_path, "ulsan", "buildings", 2, lon=129.3, lat=35.5)
    pack(tmp_path, "seoul-junggu", "areas", 1, lon=126.98, lat=37.56)
    state = {"regions": {"busan": {"buildings": {"previous": {"buildings": 10}, "refused": []},
                                   "contours": {"previous": {"contours": 3, "spots": 0}}}}}
    (tmp_path / crp.STATE).write_text(json.dumps(state), encoding="utf-8")
    asked = []

    def search(address, size=10, http_get=None):
        asked.append(address)
        if "울산" in address:
            return []
        return [{"pnu": "2647010200100010000", "address": "부산광역시 연제구 연산동 1000", "x": "129.0752", "y": "35.18003"}]

    monkeypatch.setattr(landapi, "search_parcels", search)
    # 부산's packs end 0.05° short of its east side; 울산 is covered (its box is the one pack's own extent)
    monkeypatch.setattr(landapi, "sido_boxes", lambda http_get=None: {
        "26": [129.075, 35.18, 129.126, 35.1801], "31": [129.3, 35.5, 129.3003, 35.5001]})
    monkeypatch.setattr(sys, "argv", ["crp", "--folder", str(tmp_path)])
    assert crp.main() == 0
    page = next((tmp_path / "region-check").iterdir()).read_text(encoding="utf-8")
    assert asked == [crp.SAMPLES["busan"], crp.SAMPLES["ulsan"]]
    assert "| 부산광역시 | 확인 필요 | 확인 필요 | 통과 | — |" in page
    assert "| 울산광역시 | 통과 | 통과 | 확인 필요 | — |" in page
    assert "buildings 9 (지난번 10, -10.0%)" in page and "5% 넘게 줄었어요" in page
    assert "건물: 시·도를 다 덮지 못함 (동쪽" in page
    assert "건물 9동, 등고선 3줄" in page and "미리 푼 지형: 없음" in page
    assert "울산광역시 남구 중앙로 201: 주소를 찾지 못함" in page
    assert "- seoul-junggu-areas.terrain.sqlite" in page  # not a 시·도 pack: listed so it can be tidied
    assert "wrote" in capsys.readouterr().out


def test_without_the_api_only_the_packs_are_checked(tmp_path, monkeypatch):
    pack(tmp_path, "jeju", "buildings", 1, lon=126.5, lat=33.5)
    monkeypatch.setattr(landapi, "search_parcels", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    page = crp.report(tmp_path, ["jeju"], {}, use_api=False)
    assert "| 제주특별자치도 | 통과 | — | — | — |" in page and "--no-api" in page


def test_the_sido_boxes_cover_every_part_of_a_시도_islands_too():
    def http_get(url, params):
        assert params["data"] == "LT_C_ADSIDO_INFO" and params["geometry"] == "true"
        features = [
            {"properties": {"ctprvn_cd": "47"}, "geometry": {"type": "MultiPolygon", "coordinates": [
                [[[128.0, 36.0], [129.5, 36.0], [129.5, 37.0], [128.0, 36.0]]],
                [[[130.8, 37.4], [130.9, 37.4], [130.9, 37.5], [130.8, 37.4]]]]}},  # 울릉도
            {"properties": {"ctprvn_cd": "11"}, "geometry": {"type": "Polygon", "coordinates": [
                [[126.7, 37.4], [127.2, 37.4], [127.2, 37.7], [126.7, 37.4]]]}},
        ]
        return {"response": {"status": "OK", "page": {"total": 1},
                             "result": {"featureCollection": {"features": features}}}}

    assert landapi.sido_boxes(http_get=http_get) == {"47": [128.0, 36.0, 130.9, 37.5], "11": [126.7, 37.4, 127.2, 37.7]}
