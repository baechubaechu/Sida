"""landscape.py — the 자동 조경 of a project: what the designer picked, the three plans on the site with
its mass scheme, the road edges asked once, and what the export and the Conductor are given."""

from __future__ import annotations

import json
import math

import pytest

from sida import board
from sida.experts.landscape import export, hooks, landscape
from sida.experts.site import envelope, landapi, site_facts

LON, LAT = 126.98, 37.57
W, D = 36.0, 44.0  # the lot, m


def lot_shape():
    k = math.pi / 180
    dx = W / 2 / (6371008.8 * k * math.cos(LAT * k))
    dy = D / 2 / (6371008.8 * k)
    ring = [[LON - dx, LAT - dy], [LON + dx, LAT - dy], [LON + dx, LAT + dy], [LON - dx, LAT + dy], [LON - dx, LAT - dy]]
    return {"type": "Polygon", "coordinates": [ring]}


def save_site(path, zone="일반상업지역"):
    limits = site_facts.load_limits()["zones"][zone]
    facts = {"summary": {"zoning": [{"zone": zone, "pnus": ["1"], "area_m2": W * D, **limits}], "districts": [],
                         "total_area_m2": W * D, "area_complete": True, "municipality": "서울특별시 중구", "parcel_count": 1},
             "parcels": [{"pnu": "1", "shape": lot_shape()}]}
    site_facts.save_facts(path, facts)


ASKED: list = []  # the 연속지적 lookups made (neighbours faked)


@pytest.fixture
def site(tmp_path, monkeypatch):
    save_site(tmp_path)
    ASKED.clear()
    asked = ASKED

    def neighbours(plan, own, http_get=None):  # no map here: the roads fall back to the longest edge
        asked.append(own)
        raise landapi.LandApiError("network", "offline")

    monkeypatch.setattr(envelope, "neighbours", neighbours)
    return tmp_path


def add_mass(path, floors=10):
    return board.add_paper(path, {"kind": "mass", "title": "안 A", "blocks": [{"u": 0, "v": 0, "w": 24, "d": 20, "floors": floors}]})["paper"]


def test_the_settings_are_checked_and_kept(tmp_path):
    assert landscape.load_settings(tmp_path) == landscape._defaults()
    kept = landscape.save_settings(tmp_path, {"style": "plaza", "seed": 42, "use": "office", "region": [[0, 0], [10, 0], [10, 10]],
                                              "placed": True})
    assert (kept["style"], kept["seed"], kept["use"], kept["placed"]) == ("plaza", 42, "office", True)
    assert landscape.load_settings(tmp_path)["region"] == [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]
    for bad in ({"style": "baroque"}, {"seed": 0}, {"seed": True}, {"use": "castle"}, {"region": [[0, 0], [1, 1]]},
                {"region": [[0, 0], [0.1, 0], [0, 0.1]]}, {"placed": "yes"}, {"mass": ""}):
        with pytest.raises(ValueError, match=next(iter(bad))):
            landscape.save_settings(tmp_path, bad)
    assert landscape.save_settings(tmp_path, {"region": None, "use": None})["region"] is None
    (tmp_path / landscape.SETTINGS_FILE).write_text("{not json", encoding="utf-8")
    assert landscape.load_settings(tmp_path) == landscape._defaults()


def test_the_plans_need_a_site_and_its_boundary(tmp_path):
    with pytest.raises(LookupError, match="no_site"):
        landscape.plans(tmp_path)
    save_site(tmp_path)
    facts = site_facts.load_facts(tmp_path)
    facts["parcels"][0]["shape"] = None
    site_facts.save_facts(tmp_path, facts)
    with pytest.raises(LookupError, match="no_plan"):
        landscape.plans(tmp_path)


def test_three_plans_around_the_mass_checked_against_the_rules(site):
    paper = add_mass(site)
    landscape.save_settings(site, {"use": "office"})
    got = landscape.plans(site)
    assert got["mass"] == paper["id"] and got["gross_m2"] == 4800.0 and got["site_area_m2"] == W * D
    assert [p["style"] for p in got["plans"]] == ["formal", "natural", "plaza"]
    # 서울 일반상업지역, 연면적 4,800㎡: 조경 15% of 1,584㎡; 공개 공지 asks 5,000㎡ of 업무시설, so none
    assert got["requirement"]["landscape"]["area_m2"] == 237.6 and got["requirement"]["open_space"]["status"] == "none"
    for plan in got["plans"]:
        checks = {c["id"]: c for c in plan["checks"]}
        assert checks["landscape"]["ok"] is (plan["planting_m2"] >= 237.6) and checks["landscape"]["source"] == "서울특별시 건축 조례 제24조"
        assert checks["trees"]["need"] == "24주 이상" and "open_space" not in checks
    assert got["roads_note"].startswith("도로 위치를 지적도에서 받지 못해")
    # one floor more makes it 5,280㎡: the 공개 공지 is asked and checked
    board.update_paper(site, paper["id"], {"blocks": [{"u": 0, "v": 0, "w": 24, "d": 20, "floors": 11}]})
    got = landscape.plans(site)
    assert got["requirement"]["open_space"]["area_m2"] == 158.4
    assert all({c["id"] for c in p["checks"]} >= {"open_space"} for p in got["plans"])
    # a drawn region is laid out alone, the buildings left out of it
    landscape.save_settings(site, {"region": [[-30, 12], [30, 12], [30, 40], [-30, 40]]})  # past the lot: kept to it
    got = landscape.plans(site)
    ys = [y for r in got["region"] for _x, y in r["outer"]]
    xs = [x for r in got["region"] for x, _y in r["outer"]]
    assert got["region_drawn"] and min(ys) >= 11.99 and max(ys) <= D / 2 + 0.1 and max(abs(x) for x in xs) <= W / 2 + 0.1
    landscape.save_settings(site, {"region": [[-5, -5], [5, -5], [5, 5], [-5, 5]]})  # inside the building: nothing left
    with pytest.raises(ValueError, match="region"):
        landscape.plans(site)


def test_the_road_edges_are_asked_once_and_kept(site, monkeypatch):
    landscape.plans(site)
    landscape.plans(site)
    assert len(ASKED) == 2  # a failure is not kept: asked again next time
    monkeypatch.setattr(envelope, "neighbours", lambda plan, own, http_get=None: ASKED.append(own) or [])
    landscape.plans(site)
    landscape.plans(site)
    assert len(ASKED) == 3
    kept = json.loads((site / landscape.SETTINGS_FILE).read_text(encoding="utf-8"))["roads"]
    assert kept["key"] == "1" and kept["lines"] == []


def test_the_placed_plan_reaches_the_export_and_the_conductor(site):
    add_mass(site)
    assert hooks.board_export_layers(site) == [] and hooks.conductor_site(site) == ""
    landscape.plans(site)
    assert hooks.conductor_site(site) == ""  # looked at, not placed
    landscape.save_settings(site, {"placed": True, "style": "natural"})
    shown = landscape.plans(site)
    asked = len(ASKED)
    layers = hooks.board_export_layers(site)
    assert len(ASKED) == asked  # the export asks no map
    names = [x["name"] for x in layers]
    assert "조경 - 교목" in names and "조경 - 잔디" in names and all(x["parent"] == "조경" for x in layers)
    natural = next(p for p in shown["plans"] if p["style"] == "natural")
    trees = next(x for x in layers if x["name"] == "조경 - 교목")["curves"]
    assert len(trees) == len(natural["trees"]) and all(c["closed"] and len(c["points"]) == export.CIRCLE for c in trees)
    line = hooks.conductor_site(site)
    assert line.startswith("Landscape plan on the drafting table (natural") and "(asks 24)" in line
    landscape.save_settings(site, {"placed": False})
    assert hooks.board_export_layers(site) == [] and hooks.conductor_site(site) == ""
