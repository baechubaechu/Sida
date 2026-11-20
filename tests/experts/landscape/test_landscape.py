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


def studio_snapshot():
    from sida.config import ROOT
    from sida.experts.rhino import snapshot as snap

    raw = json.loads((ROOT / "tests" / "fixtures" / "rhino" / "snapshot_studio.json").read_text(encoding="utf-8"))
    return snap.clean_snapshot({**raw, "views": []})  # as a saved snapshot holds it


def test_a_rhino_snapshots_buildings_and_region_give_one_plan_to_draw_in_place(site):
    from shapely.geometry import Point

    from sida.experts.landscape import drawing

    shot = studio_snapshot()
    built = landscape.rhino_buildings(shot)
    # the housing and shop bodies (the surroundings and the sketch are not buildings), up to their tops
    assert [(round(b.area), h) for b, h in built] == [(180, 12.0), (180, 4.0), (50, 6.0)]
    landscape.save_settings(site, {"style": "natural", "seed": 3})
    made = landscape.rhino_plan(site, shot, region=[[-18, -22], [18, -22], [18, 0], [-18, 0]])
    plan = made["plan"]
    assert plan["style"] == "natural" and made["gross_m2"] == 900.0  # the table's style; the snapshot's floor area
    assert all(t["y"] <= 0.01 for t in plan["trees"]) and plan["trees"]
    assert not any(b.buffer(2.4).contains(Point(t["x"], t["y"])) for b, _ in built for t in plan["trees"])
    assert {c["id"] for c in plan["checks"]} >= {"landscape", "trees"}
    assert landscape.rhino_plan(site, shot, style="plaza", seed=9)["plan"]["style"] == "plaza"
    for bad, word in (({"style": "baroque"}, "style"), ({"seed": 0}, "seed"), ({"region": [[0, 0], [1, 0]]}, "region"),
                      ({"region": [[100, 100], [120, 100], [120, 120]]}, "region")):
        with pytest.raises(ValueError, match=word):
            landscape.rhino_plan(site, shot, **bad)
    assert landscape.load_settings(site)["style"] == "natural"  # nothing kept from Rhino

    drawn = drawing.drawing(plan)
    assert (drawn["kind"], drawn["layer"], drawn["in_place"], drawn["title"]) == ("landscape", "Sida 조경", True, "자동 조경 · 자연형 · 산책")
    trees = [i for i in drawn["items"] if i["type"] == "tree"]
    assert len(trees) == len(plan["trees"]) and {i["layer"] for i in trees} == {"교목"}
    fills = {i["layer"] for i in drawn["items"] if i["type"] == "fill"}
    assert {"잔디·초화", "관목 띠"} <= fills
    assert drawn["bounds"][5] == 6.5 and drawn["notes"][0].startswith(("맞음 조경면적", "모자람 조경면적"))


def test_the_rhino_panels_styles_are_the_generators():
    from sida.experts.landscape import generator
    from sida.experts.rhino import live

    assert live.LANDSCAPE_STYLES == tuple(generator.STYLES)


def test_the_knobs_are_kept_and_turn_all_three_plans(site):
    add_mass(site)
    with pytest.raises(ValueError, match="plaza"):
        landscape.save_settings(site, {"tune": {"plaza": "huge"}})
    kept = landscape.save_settings(site, {"tune": {"plaza": "wide", "hedge": 0}})
    assert kept["tune"] == {"plaza": "wide", "trees": "law", "path": None, "hedge": 0.0}
    got = landscape.plans(site)
    assert got["settings"]["tune"] == kept["tune"] and got["proposals"] == []
    assert all(p["tune"] == kept["tune"] and p["areas"]["hedge"] == 0 for p in got["plans"])
    landscape.save_settings(site, {"placed": True})
    landscape.plans(site)
    assert "formal with 광장 넓게, 관목 띠 없음" in hooks.conductor_site(site)
    assert landscape.save_settings(site, {"tune": None})["tune"] == landscape._defaults()["tune"]  # back to the style's own
    data = json.loads((site / landscape.SETTINGS_FILE).read_text(encoding="utf-8"))
    data["tune"] = {"plaza": "nope"}
    (site / landscape.SETTINGS_FILE).write_text(json.dumps(data), encoding="utf-8")
    assert landscape.load_settings(site)["tune"] == landscape._defaults()["tune"]  # a bad file falls back


def test_the_conductors_proposals_are_laid_out_by_rule_and_kept_beside_the_three(site):
    add_mass(site)
    landscape.plans(site)  # the road edges are asked once (the proposals use only the kept ones)
    asked = len(ASKED)
    made = landscape.propose(site, {"style": "formal", "plaza": "wide", "trees": "most", "reason": "광장 넓게, 나무 더"})
    assert len(ASKED) == asked  # no map is asked: the kept road edges only
    p = made["proposal"]
    assert (p["id"], p["title"], p["style"], p["by"]) == ("p1", "정형 · 광장 넓게 · 나무 50% 더", "formal", "conductor")
    assert made["placed"] is None and "No landscape plan is placed" in made["text"]
    assert made["text"].startswith('Landscape proposal p1 "정형 · 광장 넓게 · 나무 50% 더" (formal, 광장 넓게, 나무 50% 더)')
    assert f"{made['plan']['trees_in_lot']}" in made["text"] and "meets" in made["text"]
    got = landscape.plans(site)
    assert [k["id"] for k in got["proposals"]] == ["p1"]
    shown = got["proposals"][0]["plan"]
    formal = next(x for x in got["plans"] if x["style"] == "formal")
    assert shown["plaza_m2"] > formal["plaza_m2"] and shown["trees_in_lot"] > formal["trees_in_lot"]
    assert shown["trees"] == made["plan"]["trees"]  # the same layout as told to the Conductor
    # with a plan placed, its figures come back to compare
    landscape.save_settings(site, {"placed": True, "style": "natural"})
    made = landscape.propose(site, {"style": "plaza", "hedge": 0, "title": "도로 쪽 광장", "reason": "x"})
    assert made["proposal"]["title"] == "도로 쪽 광장" and made["placed"]["style"] == "natural"
    assert "The plan now on the table (자연형)" in made["text"]
    for raw, word in (({"style": "baroque"}, "style"), ({"style": "formal", "trees": "lots"}, "trees"),
                      ({"style": "formal", "path": 9}, "path")):
        with pytest.raises(ValueError, match=word):
            landscape.propose(site, raw)
    for _ in range(3):
        landscape.propose(site, {"style": "natural", "reason": "x"})
    ids = [k["id"] for k in landscape.load_settings(site)["proposals"]]
    assert len(ids) == landscape.MAX_PROPOSALS and "p1" not in ids  # the oldest go
    assert landscape.drop_proposal(site, ids[0]) and not landscape.drop_proposal(site, ids[0])
    assert [k["id"] for k in landscape.plans(site)["proposals"]] == ids[1:]
    assert all("plan" not in k for k in landscape.load_settings(site)["proposals"])  # only the knobs are kept


def test_a_proposal_needs_a_site(tmp_path):
    with pytest.raises(LookupError):
        landscape.propose(tmp_path, {"style": "formal", "reason": "x"})
    assert hooks.conductor_tools(tmp_path) == []
