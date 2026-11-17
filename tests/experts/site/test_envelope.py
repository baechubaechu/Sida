"""envelope.py — the 법규 볼륨 of a site (정북 일조 by the 건축 조례, 건폐율·용적률) and the two
reference schemes in it. Lots and neighbours are drawn here in the table's metres; the API's
lookups (연속지적, 토지이용계획, 건축 조례) are faked."""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import Polygon

from sida.experts.regulation import ordinance
from sida.experts.site import envelope, landapi, site_facts

SEOUL = {"steps": [[1.5, 10.0], [5.0, 17.0]], "half_above": 17.0}
TURN = 15  # degrees: the lot's long side from east


def rect(cx, cy, w, d, deg=TURN):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [[cx + u * c - v * s, cy + u * s + v * c] for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]


def north_of(distance, w, d):
    """A rectangle `distance` m up the lot's short axis (its north side), as wide as `w`."""
    a = math.radians(TURN)
    return rect(-distance * math.sin(a), distance * math.cos(a), w, d)


LOT = rect(0, 0, 28, 18)  # 504 ㎡
PLAN = {"parcels": [{"pnu": "1", "rings": [LOT]}], "frame": {"x": 0.0, "y": 0.0, "angle": math.radians(TURN)},
        "bounds": {"min_x": -16, "min_y": -13, "max_x": 16, "max_y": 13}, "origin": {"lon": 127.0, "lat": 37.5}}


def facts(zone="제2종일반주거지역", area=504.0, building=None):
    limits = site_facts.load_limits()["zones"][zone]
    out = {"summary": {"zoning": [{"zone": zone, "pnus": ["1"], "area_m2": area, **limits}], "districts": [],
                       "total_area_m2": area, "area_complete": True, "municipality": "서울특별시 중구",
                       "parcel_count": 1},
           "parcels": [{"pnu": "1"}]}
    if building is not None:
        out["building_ordinance"] = building
    return out


def seoul_building():
    return {"municipality": "서울특별시 중구", "name": "서울특별시 건축 조례", "label": "제35조", "mst": "2171799",
            "text": "제35조 ① … 높이 10미터 이하인 부분 … ② 다른 항", "rule": SEOUL, "error": None}


def run(neighbours, zone_of=lambda pnu: "제2종일반주거지역", **kw):
    f = facts(building=seoul_building(), **kw)
    return envelope.compute(PLAN, f, envelope.sunlight_rule(f), neighbours, zone_of, floor_height=3.0)


def lot_poly():
    return Polygon(LOT)


def block_ring(b):
    a = math.radians(TURN)
    pts = [(b["u"] + du, b["v"] + dv) for du, dv in ((-b["w"] / 2, -b["d"] / 2), (b["w"] / 2, -b["d"] / 2), (b["w"] / 2, b["d"] / 2), (-b["w"] / 2, b["d"] / 2))]
    return Polygon([(u * math.cos(a) - v * math.sin(a), u * math.sin(a) + v * math.cos(a)) for u, v in pts])


def test_the_height_a_part_may_reach_by_its_distance_from_the_line():
    h = lambda d: envelope.allowed_height(d, SEOUL["steps"], SEOUL["half_above"])  # noqa: E731
    assert [h(d) for d in (1.0, 1.5, 4.9, 5.0, 8.5, 10.0)] == [0.0, 10.0, 10.0, 17.0, 17.0, 20.0]
    statute = lambda d: envelope.allowed_height(d, [[1.5, 10]], 10)  # noqa: E731
    assert [statute(d) for d in (1.0, 3.0, 7.0)] == [0.0, 10.0, 14.0]


def test_the_rule_is_the_ordinances_when_read_and_the_statutes_least_otherwise():
    read = envelope.sunlight_rule(facts(building=seoul_building()))
    assert (read["applies"], read["status"], read["steps"], read["half_above"]) == (True, "read", SEOUL["steps"], 17.0)
    assert read["source"] == "서울특별시 건축 조례 제35조" and "② 다른 항" not in read["quote"]
    fallback = envelope.sunlight_rule(facts(building={"municipality": "서울특별시 중구", "error": "no_article"}))
    # the law's own distances (건축법 제61조①, 2026-11-12): 1.5 m up to 10 m, 5 m up to 17 m, then half
    assert (fallback["status"], fallback["steps"], fallback["half_above"]) == ("check", [[1.5, 10], [5, 17]], 17.0)
    assert "정북 일조 조문이 없음" in fallback["detail"] and "17m 이하 5m" in fallback["detail"]
    assert fallback["source"] == "건축법 제61조제1항" and "17미터 이하인 부분" in fallback["quote"]
    commercial = envelope.sunlight_rule(facts("일반상업지역"))
    assert (commercial["applies"], commercial["status"]) == (False, "none")
    two = facts()
    two["summary"]["zoning"].append({**two["summary"]["zoning"][0], "zone": "일반상업지역"})
    assert envelope.sunlight_rule(two)["applies"] is None


def test_a_road_to_the_north_is_crossed_and_raises_the_envelope():
    by_a_lot = run([{"pnu": "2", "mark": "대", "rings": [north_of(18, 40, 18)]}])
    by_a_road = run([{"pnu": "3", "mark": "도", "rings": [north_of(12, 60, 6)]}])
    assert by_a_road["max_height_m"] > by_a_lot["max_height_m"]
    assert by_a_road["neighbours"]["crossed"] == ["도로"]
    north = {x["id"]: x for x in by_a_road["lines"]}["north"]
    assert north["status"] == "read" and "도로 건너편" in north["detail"]
    # The lot's north edge: nothing may stand within 1.5 m of the line, so the grid's top rows near it hold 0.
    grid = np.array([[np.nan if v is None else v for v in row] for row in by_a_lot["grid"]["h"]], dtype=float)
    assert np.nanmin(grid) == 0.0
    # Levels shrink as they rise.
    areas = [sum(Polygon(r).area for r in level["rings"]) for level in by_a_lot["levels"]]
    assert areas == sorted(areas, reverse=True) and areas[0] <= lot_poly().area + 1


def test_land_to_the_north_that_is_not_residential_lifts_the_limit_there():
    out = run([{"pnu": "2", "mark": "대", "rings": [north_of(18, 40, 18)]}], zone_of=lambda pnu: "일반상업지역")
    assert out["max_height_m"] is None  # no 정북 limit left anywhere
    assert "제86조②1" in {x["id"]: x for x in out["lines"]}["north"]["detail"]
    unknown = run([{"pnu": "2", "mark": "대", "rings": [north_of(18, 40, 18)]}], zone_of=lambda pnu: None)
    assert {x["id"]: x for x in unknown["lines"]}["north"]["status"] == "check"
    assert unknown["max_height_m"] is not None  # applied when the zone is not known


def test_schemes_hold_to_the_ratios_the_lot_and_the_envelope():
    out = run([{"pnu": "2", "mark": "대", "rings": [north_of(18, 40, 18)]}])
    assert [s["name"] for s in out["schemes"]] == ["넓게 낮게", "남쪽 탑형"]
    grid = out["grid"]
    h = np.array([[np.nan if v is None else (np.inf if v == -1 else v) for v in row] for row in grid["h"]], dtype=float)
    for s in out["schemes"]:
        assert s["footprint_m2"] <= 504 * out["bcr"] / 100 + 1e-6
        assert s["floor_area_m2"] <= 504 * out["far"] / 100 + 1e-6
        assert s["floor_area_m2"] >= 504 * out["far"] / 100 * 0.85  # the ratio is mostly used
        for b in s["blocks"]:
            assert lot_poly().buffer(0.01).contains(block_ring(b))
            # every grid cell whose middle is under the block lets it stand that tall
            i0 = math.ceil((b["u"] - b["w"] / 2 - grid["u0"]) / grid["step"] - 0.5 + 1e-6)
            i1 = math.floor((b["u"] + b["w"] / 2 - grid["u0"]) / grid["step"] - 0.5 - 1e-6)
            j0 = math.ceil((b["v"] - b["d"] / 2 - grid["v0"]) / grid["step"] - 0.5 + 1e-6)
            j1 = math.floor((b["v"] + b["d"] / 2 - grid["v0"]) / grid["step"] - 0.5 - 1e-6)
            under = h[j0:j1 + 1, i0:i1 + 1]
            assert np.nanmin(under) >= b["floors"] * 3.0 - 1e-6
    tower = out["schemes"][1]
    assert tower["height_m"] > out["schemes"][0]["height_m"]


def test_a_commercial_site_has_no_sunlight_limit_and_says_its_top_is_open():
    f = facts("일반상업지역")
    out = envelope.compute(PLAN, f, envelope.sunlight_rule(f), [], lambda pnu: None, floor_height=4.2)
    lines = {x["id"]: x for x in out["lines"]}
    assert lines["sunlight"]["status"] == "none" and lines["height"]["status"] == "check"
    assert out["levels"] == [] and out["grid"] is None and out["max_height_m"] is None
    for s in out["schemes"]:
        assert s["floor_area_m2"] <= 504 * out["far"] / 100 + 1e-6
    assert lines["open_space"]["status"] == "check"


def test_no_schemes_without_the_sites_area_and_no_envelope_for_several_zones():
    f = facts(building=seoul_building())
    f["summary"]["area_complete"] = False
    out = envelope.compute(PLAN, f, envelope.sunlight_rule(f), [], lambda pnu: None, floor_height=3.0)
    assert out["schemes"] == [] and out["levels"]
    two = facts()
    two["summary"]["zoning"].append({**two["summary"]["zoning"][0], "zone": "일반상업지역"})
    out = envelope.compute(PLAN, two, envelope.sunlight_rule(two), [], lambda pnu: None, floor_height=3.0)
    assert out["available"] is False and out["schemes"] == [] and out["lines"][0]["value"] == "계산 안 함"


def test_neighbours_come_from_the_cadastral_map_in_the_tables_metres(monkeypatch):
    asked = {}

    def features(layer, west, south, east, north, http_get=None):
        asked.update(layer=layer, box=(west, south, east, north))
        return [
            {"properties": {"pnu": "1", "jibun": "1 대"}, "shape": {"type": "Polygon", "coordinates": [[[127, 37.5], [127.0001, 37.5], [127.0001, 37.5001]]]}},
            {"properties": {"pnu": "2", "jibun": "12-3 도"}, "shape": {"type": "Polygon", "coordinates": [[[127, 37.5001], [127.0001, 37.5001], [127.0001, 37.5002]]]}},
        ]

    monkeypatch.setattr(landapi, "features_in_box", features)
    found = envelope.neighbours(PLAN, {"1"})
    assert asked["layer"] == "LP_PA_CBND_BUBUN" and asked["box"][0] < 127 < asked["box"][2]
    assert [(n["pnu"], n["mark"]) for n in found] == [("2", "도")]  # the lot's own parcel is left out
    x, y = found[0]["rings"][0][0]
    assert abs(x) < 1e-6 and 11.0 < y < 11.2  # 0.0001° of latitude is about 11.1 m north
    assert [envelope.mark_of(j) for j in ("689-14 장", "12 도", "산 1 임", "1-2", "")] == ["장", "도", "임", "", ""]


def test_envelope_for_looks_the_building_ordinance_up_once_and_keeps_it(tmp_path, monkeypatch):
    shape = {"type": "Polygon", "coordinates": [[[126.9780, 37.5660], [126.9783, 37.5660], [126.9783, 37.5662], [126.9780, 37.5662], [126.9780, 37.5660]]]}
    f = facts()
    f["parcels"] = [{"pnu": "1", "address": "서울특별시 중구 가동 1", "characteristics": {"area_m2": 504.0}, "shape": shape}]
    site_facts.save_facts(tmp_path, f)
    calls = []
    monkeypatch.setattr(ordinance, "sunlight_lookup", lambda m, http_get=None: calls.append(m) or seoul_building())
    monkeypatch.setattr(landapi, "features_in_box", lambda *a, **k: [])
    out = envelope.envelope_for(tmp_path)
    again = envelope.envelope_for(tmp_path, floor_height=2.8)
    assert calls == ["서울특별시 중구"]  # kept in the site facts after the first time
    assert site_facts.load_facts(tmp_path)["building_ordinance"]["rule"] == SEOUL
    assert out["floor_height"] == 3.0 and again["floor_height"] == 2.8
    assert {x["id"]: x for x in out["lines"]}["sunlight"]["status"] == "read"

    def offline(*a, **k):
        raise landapi.LandApiError("network", "down")

    monkeypatch.setattr(landapi, "features_in_box", offline)
    lines = {x["id"]: x for x in envelope.envelope_for(tmp_path)["lines"]}
    assert lines["north"]["status"] == "check" and "연속지적을 받지 못해" in lines["north"]["detail"]


def test_a_failed_ordinance_lookup_is_tried_again_and_no_site_is_an_error(tmp_path, monkeypatch):
    with pytest.raises(LookupError, match="no_site"):
        envelope.envelope_for(tmp_path)
    shape = {"type": "Polygon", "coordinates": [[[126.9780, 37.5660], [126.9783, 37.5660], [126.9783, 37.5662], [126.9780, 37.5660]]]}
    f = facts()
    f["parcels"] = [{"pnu": "1", "address": "", "characteristics": {"area_m2": 504.0}, "shape": shape}]
    site_facts.save_facts(tmp_path, f)
    calls = []
    monkeypatch.setattr(ordinance, "sunlight_lookup",
                        lambda m, http_get=None: calls.append(m) or {"municipality": m, "error": "network", "rule": None})
    monkeypatch.setattr(landapi, "features_in_box", lambda *a, **k: [])
    out = envelope.envelope_for(tmp_path)
    envelope.envelope_for(tmp_path)
    assert len(calls) == 2 and "building_ordinance" not in site_facts.load_facts(tmp_path)
    assert {x["id"]: x for x in out["lines"]}["sunlight"]["status"] == "check"


def test_an_ordinance_read_as_asking_less_than_the_law_is_not_used():
    law = {"steps": [[1.5, 10], [5, 17]], "half_above": 17}
    assert envelope.within_law(SEOUL, law)
    assert envelope.within_law({"steps": [[2, 10], [6, 17]], "half_above": 17}, law)  # stricter: fine
    assert envelope.within_law({"steps": [[1.5, 10]], "half_above": 10}, law)  # the 시행령's old two steps ask more
    assert not envelope.within_law({"steps": [[1.5, 12]], "half_above": 12}, law)  # 12 m at 1.5 m
    assert not envelope.within_law({"steps": [[1.0, 10], [5, 17]], "half_above": 17}, law)
    loose = {**seoul_building(), "rule": {"steps": [[1.5, 12.0]], "half_above": 12.0}}
    rule = envelope.sunlight_rule(facts(building=loose))
    assert (rule["status"], rule["steps"]) == ("check", law["steps"])
    assert "법(제61조①)의 범위보다 짧게" in rule["detail"]


def test_a_height_entered_for_a_height_district_cuts_the_envelope_and_its_schemes():
    nb = [{"pnu": "2", "mark": "대", "rings": [north_of(18, 40, 18)]}]
    f = facts(building=seoul_building())
    f["summary"]["districts"] = [{"name": "최고고도지구", "relation": "포함"}]
    free = envelope.compute(PLAN, f, envelope.sunlight_rule(f), nb, lambda pnu: "제2종일반주거지역", floor_height=3.0)
    lines = {x["id"]: x for x in free["lines"]}
    assert free["height_districts"] == ["최고고도지구"] and free["height_limit_m"] is None
    assert (lines["height"]["status"], lines["height"]["value"]) == ("check", "입력 필요")
    cut = envelope.compute(PLAN, f, envelope.sunlight_rule(f), nb, lambda pnu: "제2종일반주거지역", floor_height=3.0, height_cap=12)
    lines = {x["id"]: x for x in cut["lines"]}
    assert (lines["height"]["status"], lines["height"]["value"], lines["height"]["source"]) == ("read", "12m", "사용자 입력")
    assert cut["max_height_m"] == 12 and cut["levels"][-1]["z"] <= 12
    assert all(s["height_m"] <= 12 for s in cut["schemes"])
    # a commercial site has no 정북 limit, but the entered height still gives it a top
    c = facts("일반상업지역")
    top = envelope.compute(PLAN, c, envelope.sunlight_rule(c), [], lambda pnu: None, floor_height=4.0, height_cap=30)
    assert top["max_height_m"] == 30 and len(top["levels"]) == 7 and top["grid"]["h"][9][14] == 30
    assert all(s["height_m"] <= 30 for s in top["schemes"])


def test_the_entered_height_is_kept_per_project_and_checked(tmp_path):
    none = {"height_limit_m": None, "use": None, "use_area_m2": None}
    assert envelope.load_settings(tmp_path) == none
    assert envelope.save_settings(tmp_path, {"height_limit_m": 45.567}) == {**none, "height_limit_m": 45.57}
    assert envelope.load_settings(tmp_path)["height_limit_m"] == 45.57
    with pytest.raises(ValueError, match="height_limit_m"):
        envelope.save_settings(tmp_path, {"height_limit_m": 0})
    assert envelope.save_settings(tmp_path, {}) == {**none, "height_limit_m": 45.57}  # nothing asked, nothing changed
    assert envelope.save_settings(tmp_path, {"height_limit_m": None}) == none
    # the use and its floor area (대지 안의 공지, 채광)
    assert envelope.save_settings(tmp_path, {"use": "apartment", "use_area_m2": 1200}) == {**none, "use": "apartment", "use_area_m2": 1200.0}
    with pytest.raises(ValueError, match="use"):
        envelope.save_settings(tmp_path, {"use": "castle"})
    with pytest.raises(ValueError, match="use_area_m2"):
        envelope.save_settings(tmp_path, {"use_area_m2": -5})
    assert envelope.save_settings(tmp_path, {"use": None})["use"] is None
    (tmp_path / envelope.SETTINGS_FILE).write_text("{oops", encoding="utf-8")
    assert envelope.load_settings(tmp_path) == none
    (tmp_path / envelope.SETTINGS_FILE).write_text('{"use": "castle", "use_area_m2": true}', encoding="utf-8")
    assert envelope.load_settings(tmp_path) == none
