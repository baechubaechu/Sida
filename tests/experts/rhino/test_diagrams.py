"""Diagrams drawn by rule from a Rhino snapshot: the drawing instructions and their SVG."""

from __future__ import annotations

import types

import pytest

from sida.experts.rhino import diagram_svg, diagrams
from sida.experts.rhino import snapshot as snap


def box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def floors(base, count, storey, area, outline=None):
    return [{"z": base + i * storey, "area": area, **({"outline": outline} if outline else {})} for i in range(count)]


PODIUM, COURT, TOWER = box(-25, -18, 25, 14), box(-8, -6, 8, 4), box(-22, -15, -2, 5)
LOT = [[-32, -24], [33, -26], [36, 18], [-30, 21]]
ZONE = {"zone": "일반상업지역", "bcr_max": 80, "far_min": 200, "far_max": 1300, "ordinance_bcr": 60, "ordinance_far": 800}


def studio(**changes) -> dict:
    """A podium with a courtyard (shops, two storeys), a tower on it (offices, eight storeys from
    +9 m) and a core on a layer without a floor height."""
    raw = {
        "schema": 1, "rhino": {"version": "8.31", "file": "studio.3dm", "units": "m"},
        "layers": [
            {"path": "Shop", "meaning": "commercial", "color": "#000000", "floor_height": 4.5},
            {"path": "Office", "meaning": "office", "color": "#000000", "floor_height": 4.0},
            {"path": "Core", "meaning": "core", "color": "#000000", "floor_height": None},
            {"path": "Around", "meaning": "surroundings", "color": "#000000", "floor_height": None},
        ],
        "objects": [
            {"id": "p", "layer": "Shop", "volume": 12960.0, "height": 9.0, "base": 0.0, "footprint": [PODIUM, COURT],
             "floors": floors(0, 2, 4.5, 1440.0, [PODIUM, COURT])},
            {"id": "t", "layer": "Office", "volume": 13000.0, "height": 32.5, "base": 9.0, "footprint": TOWER,
             "floors": floors(9, 8, 4.0, 400.0, [TOWER])},
            {"id": "c", "layer": "Core", "volume": 1080.0, "height": 45.0, "base": 0.0, "footprint": box(26, -2, 30, 4), "floors": []},
            {"id": "open", "layer": "Shop", "volume": None, "height": 3.0, "base": 0.0, "footprint": None, "floors": []},
            {"id": "n", "layer": "Around", "volume": None, "height": 20.0, "base": 0.0, "footprint": None, "floors": []},
        ],
        "views": [],
    }
    raw.update(changes)
    return snap.clean_snapshot(raw)


def ctx(**changes) -> dict:
    return {"site_area": 3600.0, "lot": [LOT], "limits": [ZONE], "buildings": [], **changes}


def of(drawing: dict, kind: str, **where) -> list[dict]:
    return [i for i in drawing["items"] if i["type"] == kind and all(i.get(k) == v for k, v in where.items())]


def test_every_kind_says_whether_this_snapshot_can_be_drawn_that_way_and_why_not():
    ready = {a["kind"]: a for a in diagrams.available(studio(), ctx())}
    assert list(ready) == ["program", "floors", "stack", "site", "limits"] and all(a["ready"] for a in ready.values())
    assert ready["floors"]["title"] == "층별 분해" and ready["floors"]["view"] == "axo" and ready["site"]["view"] == "flat"

    no_storeys = studio(layers=[{"path": "Shop", "meaning": "commercial", "floor_height": None}],
                        objects=[{"id": "p", "layer": "Shop", "volume": 1.0, "height": 9.0, "base": 0.0, "footprint": PODIUM, "floors": []}])
    state = {a["kind"]: a for a in diagrams.available(no_storeys, ctx())}
    assert state["program"]["ready"] and not state["stack"]["ready"] and "층고" in state["stack"]["reason"]
    with pytest.raises(ValueError, match="층고"):
        diagrams.drawing("floors", no_storeys, ctx())

    empty = studio(objects=[])
    state = {a["kind"]: a for a in diagrams.available(empty, ctx(lot=[]))}
    assert [k for k, a in state.items() if a["ready"]] == ["limits"]  # the limits are said even of nothing
    assert diagrams.available(empty, ctx())[3]["ready"]  # the lot alone is a site plan
    with pytest.raises(ValueError, match="kind must be one of"):
        diagrams.drawing("render", studio(), ctx())


def test_the_program_masses_are_the_counted_floors_in_their_own_shapes_and_meanings_colours():
    drawing = diagrams.drawing("program", studio(), ctx())
    assert drawing["kind"] == "program" and drawing["view"] == "axo"
    shops = of(drawing, "slab", tag="commercial")
    assert [(s["z"], s["height"]) for s in shops] == [(0.0, 4.5), (4.5, 4.5)]
    assert shops[0]["rings"] == [PODIUM, COURT] and shops[0]["color"] == snap.MEANINGS["commercial"]["color"]  # the courtyard stays open
    offices = of(drawing, "slab", tag="office")
    assert len(offices) == 8 and offices[0]["z"] == 9.0
    assert offices[-1]["height"] == 4.5  # the top storey takes what is left up to the roof (a parapet), no extra floor
    core = of(drawing, "slab", tag="core")
    assert [(s["z"], s["height"]) for s in core] == [(0.0, 45.0)]  # no floor height: one mass, and said
    assert any("한 덩어리" in note for note in drawing["notes"]) and any("잴 수 없는 개체 1개" in note for note in drawing["notes"])
    lot = of(drawing, "line", bold=True)[0]
    assert lot["closed"] and lot["points"][0] == [-32, -24, 0.0]
    legend = [t["text"] for t in of(drawing, "text", role="legend")]
    assert legend[0] == "상업 2,880.0㎡ · 47%" and legend[1] == "업무 3,200.0㎡ · 53%"
    assert of(drawing, "text", role="legend")[0]["swatch"] == snap.MEANINGS["commercial"]["color"]
    assert [t["text"] for t in of(drawing, "text", role="title")] == ["프로그램 매스"]
    caption = [t["text"] for t in of(drawing, "text", role="caption")]
    assert caption[-1] == "건폐율 42.3% · 용적률 168.9%"  # the figures' own lines, nothing recomputed here
    assert drawing["bounds"][2] == 0.0 and drawing["bounds"][5] == 45.0


def test_a_body_without_a_base_stands_on_its_lowest_floor_and_one_without_either_is_left_out():
    old = studio(objects=[
        {"id": "a", "layer": "Shop", "volume": 1.0, "height": 9.0, "footprint": PODIUM, "floors": floors(2.0, 2, 4.5, 1600.0)},
        {"id": "b", "layer": "Shop", "volume": 1.0, "height": 9.0, "footprint": PODIUM, "floors": []},
    ])
    drawn, left = diagrams.bodies(old)
    assert left == 1 and [(b["base"], b["top"]) for b in drawn] == [(2.0, 11.0)]
    assert [level["rings"] for level in drawn[0]["levels"]] == [[PODIUM], [PODIUM]]  # no outline of its own: the footprint


def test_the_floor_plates_are_pulled_apart_and_each_level_says_its_height_and_area():
    drawing = diagrams.drawing("floors", studio(), ctx())
    plates = of(drawing, "slab")
    assert len(plates) == 10 and not of(drawing, "slab", tag="core")  # the core has no floors
    assert any("층이 없어 빠졌습니다" in note for note in drawing["notes"])
    assert [p["z"] for p in of(drawing, "slab", tag="commercial")] == [0.0, 4.5 * diagrams.EXPLODE]
    assert of(drawing, "slab", tag="office")[0]["z"] == pytest.approx(9.0 * diagrams.EXPLODE)
    assert all(p["height"] < 1.0 for p in plates)  # thin plates, not storeys
    labels = [t for t in of(drawing, "text", role="") if t["upright"]]
    assert [t["text"] for t in labels][:3] == ["+0.0m  1,440.0㎡", "+4.5m  1,440.0㎡", "+9.0m  400.0㎡"]
    assert [t["at"][2] for t in labels] == [pytest.approx(level * diagrams.EXPLODE) for level in (0, 4.5, 9, 13, 17, 21, 25, 29, 33, 37)]
    assert len({(t["at"][0], t["at"][1]) for t in labels}) == 1  # far enough apart: one column
    assert [t["text"] for t in of(drawing, "text", role="legend")] == ["상업 2,880.0㎡ · 47%", "업무 3,200.0㎡ · 53%"]  # only what is drawn


def test_levels_close_together_get_their_labels_side_by_side_not_on_each_other():
    close = studio(objects=[
        {"id": "t", "layer": "Office", "volume": 1.0, "height": 8.0, "base": 0.0, "footprint": TOWER, "floors": floors(0, 2, 4.0, 400.0)},
        {"id": "s", "layer": "Shop", "volume": 1.0, "height": 9.0, "base": 0.2, "footprint": box(0, 0, 10, 10), "floors": floors(0.2, 2, 4.5, 100.0)},
    ])
    labels = [t for t in of(diagrams.drawing("floors", close, ctx()), "text", role="") if t["upright"]]
    assert [t["text"].split()[0] for t in labels] == ["+0.0m", "+0.2m", "+4.0m", "+4.7m"]
    first, second = labels[0]["at"], labels[1]["at"]
    assert second[0] > first[0] and second[1] < first[1]  # a step to the south-east: straight to the right in the picture
    assert labels[2]["at"][:2] == first[:2] and labels[3]["at"][:2] == second[:2]


def test_the_stack_is_a_bar_per_level_as_long_as_its_area_coloured_by_meaning():
    both = studio(objects=[
        {"id": "p", "layer": "Shop", "volume": 1.0, "height": 4.5, "base": 0.0, "footprint": PODIUM, "floors": floors(0, 1, 4.5, 1000.0)},
        {"id": "t", "layer": "Office", "volume": 1.0, "height": 8.0, "base": 0.0, "footprint": TOWER, "floors": floors(0, 2, 4.0, 250.0)},
    ])
    drawing = diagrams.drawing("stack", both, ctx())
    bars = [f for f in of(drawing, "fill") if not f["role"]]
    widths = [(f["color"], round(f["rings"][0][1][0] - f["rings"][0][0][0], 2), f["rings"][0][0][1]) for f in bars]
    shop, office = snap.MEANINGS["commercial"]["color"], snap.MEANINGS["office"]["color"]
    assert widths == [(shop, 32.0, 0.0), (office, 8.0, 0.0), (office, 8.0, 3.0)]  # the widest level (1,250㎡) runs 40 m
    assert bars[1]["rings"][0][0][0] == 32.0  # the office part goes on after the shops
    words = [t["text"] for t in of(drawing, "text", role="")]
    assert words == ["+0.0m", "1,250.0㎡", "+4.0m", "250.0㎡"]
    assert [t["text"] for t in of(drawing, "text", role="caption")] == ["연면적 1,500.0㎡"]
    assert drawing["view"] == "flat"


def test_the_site_plan_has_the_lot_the_footprints_and_only_the_buildings_near_to_scale():
    around = [{"outline": box(45, -30, 67, -12), "base": 0, "height": 12, "estimate": False},
              {"outline": box(46, 0, 66, 25), "base": 0, "height": 30, "estimate": True},
              {"outline": box(300, 300, 320, 320), "base": 0, "height": 9, "estimate": False}]
    drawing = diagrams.drawing("site", studio(), ctx(buildings=around))
    soft = of(drawing, "fill", color=diagrams.SOFT)
    assert [f["rings"][0][0] for f in soft] == [[45, -30], [46, 0]] and [f["light"] for f in soft] == [False, True]  # the far one is out
    own = of(drawing, "fill", color=diagrams.INK)
    assert [f["rings"] for f in own] == [[PODIUM, COURT], [TOWER], [box(26, -2, 30, 4)]]
    lot = of(drawing, "line", bold=True, dashed=True)
    assert len(lot) == 1 and lot[0]["closed"] and lot[0]["points"][2] == [36, 18, 0.0]
    words = [t["text"] for t in of(drawing, "text")]
    assert "N" in words and "50m" in words  # 148 m across: the first of 1-2-5 steps not under a sixth of it
    assert [t["text"] for t in of(drawing, "text", role="caption")] == ["대지면적 3,600.0㎡", "건축면적 1,524.0㎡"]  # the tower over the courtyard counts once
    assert drawing["bounds"][0] <= -32 - diagrams.SITE_REACH + 0.001 and not drawing["notes"][1:]

    bare = diagrams.drawing("site", studio(), ctx(lot=[], site_area=None))
    assert any("대지 경계가 없습니다" in n for n in bare["notes"]) and any("주변은 비어" in n for n in bare["notes"])
    assert [t["text"] for t in of(bare, "text", role="caption")][0] == "대지면적 미확인"


def test_a_ratio_is_drawn_against_the_ordinance_then_the_legal_ceiling_and_only_in_one_zone():
    assert diagrams.gauge(42.4, [ZONE], "ordinance_bcr", "bcr_max") == {"value": 42.4, "limit": 60, "source": "조례"}
    legal_only = {**ZONE, "ordinance_far": None}
    assert diagrams.gauge(900.0, [legal_only], "ordinance_far", "far_max") == {"value": 900.0, "limit": 1300, "source": "법정 상한"}
    assert diagrams.gauge(42.4, [ZONE, ZONE], "ordinance_bcr", "bcr_max")["limit"] is None  # no weighted limit is made up
    assert diagrams.gauge(None, [], "ordinance_bcr", "bcr_max") == {"value": None, "limit": None, "source": ""}
    assert diagrams.limit_lines([ZONE, {"zone": "자연녹지지역"}]) == [
        "일반상업지역: 법정 건폐율 80% 이하, 용적률 1300% 이하 (조례 건폐율 60%, 용적률 800%)", "자연녹지지역: 법정 미확인"]


def test_the_limits_drawing_marks_the_limit_fills_to_the_ratio_and_shows_what_is_over():
    drawing = diagrams.drawing("limits", studio(), ctx(site_area=1905.0))  # coverage 80.0%: over the ordinance's 60
    words = [t["text"] for t in of(drawing, "text", role="")]
    assert words[0] == "건폐율 80.0%" and "조례 60% 초과" in words and "조례 800%" in words
    mark = 40.0 / diagrams.GAUGE_RUN
    over = of(drawing, "fill", color=diagrams.OVER)
    assert len(over) == 1 and over[0]["rings"][0][0][0] == mark
    assert over[0]["rings"][0][1][0] == 40.0  # 80 against 60 is past the track's end (125% of the limit): the bar stops there
    within = of(drawing, "fill", color=diagrams.PLAIN)
    assert within[0]["rings"][0][1][0] == mark and within[1]["rings"][0][1][0] == pytest.approx(mark * 319.2 / 800, abs=0.01)
    assert len(of(drawing, "line", bold=True)) == 2  # a mark at each limit
    caption = [t["text"] for t in of(drawing, "text", role="caption")]
    assert caption[0] == "대지면적 1,905.0㎡" and caption[-1].startswith("일반상업지역: 법정 건폐율 80% 이하")

    unknown = diagrams.drawing("limits", studio(), ctx(site_area=None, limits=[]))
    assert [t["text"] for t in of(unknown, "text", role="")] == ["건폐율 미확인", "용적률 미확인"]
    assert not [f for f in of(unknown, "fill") if not f["role"]] and "한도가 없습니다" in unknown["notes"][0]
    two = diagrams.drawing("limits", studio(), ctx(limits=[ZONE, {**ZONE, "zone": "제3종일반주거지역"}]))
    assert not [f for f in of(two, "fill") if not f["role"]] and "여러 개" in two["notes"][0]
    assert len([t for t in of(two, "text", role="caption") if "지역:" in t["text"]]) == 2


def test_the_context_comes_from_the_project_and_leaves_out_the_building_now_on_the_site(tmp_path):
    parcel = {"pnu": "1", "address": "a", "area_m2": 100.0,
              "shape": {"type": "Polygon", "coordinates": [[[126.9, 37.5], [126.9002, 37.5], [126.9002, 37.5002], [126.9, 37.5002], [126.9, 37.5]]]}}
    site = types.SimpleNamespace(
        board_site=lambda path: {"area_m2": 100.0, "lines": [], "parcels": [parcel]},
        board_surroundings=lambda path: {"ground": None, "buildings": [{"outline": box(0, 0, 5, 5), "on_site": True},
                                                                        {"outline": box(30, 0, 40, 9), "on_site": False}]})
    got = diagrams.context(tmp_path, hooks=[("site", site)])
    assert got["site_area"] == 100.0 and len(got["lot"]) == 1 and len(got["lot"][0]) >= 4
    assert max(abs(p[0]) for p in got["lot"][0]) < 12  # metres around the site's middle, the snapshot's frame
    assert [b["outline"] for b in got["buildings"]] == [box(30, 0, 40, 9)] and got["limits"] == []

    quick = diagrams.context(tmp_path, hooks=[("site", site)], around=False)  # the list of kinds does not wait for the surroundings
    assert quick["buildings"] == [] and len(quick["lot"]) == 1

    def broken(path):
        raise RuntimeError("no map files")

    without = diagrams.context(tmp_path, hooks=[("site", types.SimpleNamespace(board_surroundings=broken))])
    assert without == {"site_area": None, "lot": [], "limits": [], "buildings": []}  # a diagram is still drawn


def test_the_axonometric_picture_paints_what_is_below_or_behind_first():
    def solid(z, top, depth):
        return {"z": z, "top": top, "depth": depth, "faces": []}

    podium, tower, front, back = solid(0, 9, -2), solid(9, 40, -20), solid(9, 12, -30), solid(9, 12, 50)
    order = diagram_svg._far_first([front, tower, back, podium])
    assert order[0] is podium  # wholly below the rest: it cannot hide them
    assert order.index(back) < order.index(tower) < order.index(front)  # side by side: the far one first
    ring = [solid(0, 5, 3), solid(4, 9, 2), solid(8, 13, 1), solid(12, 17, 0)]
    assert len(diagram_svg._far_first(ring)) == 4
    many = [solid(i, i + 1, 0) for i in range(401)]
    assert diagram_svg._far_first(list(reversed(many)))[0] is many[0]


def test_the_svg_follows_the_drawing_and_writes_nothing_of_its_own():
    made = diagram_svg.to_svg(diagrams.drawing("program", studio(), ctx())).decode("utf-8")
    assert made.startswith("<svg ") and 'data-kind="program"' in made and made.rstrip().endswith("</svg>")
    # 11 solids (2 + 8 + 1): each a lid and its walls towards the south-west (2 of a box, 2 more inside the courtyard)
    assert made.count('data-type="face"') == 2 * (3 + 2) + 8 * 3 + 3
    assert made.count('data-type="swatch"') == 3 and "상업 2,880.0㎡ · 47%" in made and "프로그램 매스" in made
    assert made.count("프로그램 매스") == 1  # the title is set once, on the page, not also on the ground
    assert snap.MEANINGS["office"]["color"] in made and 'data-type="line"' in made

    flat = diagram_svg.to_svg(diagrams.drawing("site", studio(file="a<b>&.3dm"), ctx())).decode("utf-8")
    assert 'data-kind="site"' in flat and flat.count('data-type="fill"') == 3 and "대지 배치도" in flat and ">N<" in flat
    assert 'stroke-dasharray' in flat and 'fill-rule="evenodd"' in flat
    weird = {"kind": "x", "title": "t", "view": "flat", "bounds": [0, 0, 0, 1, 1, 0],
             "items": [{"type": "text", "at": [0, 0, 0], "text": "a<b>&c", "size": 1, "anchor": "start", "upright": False, "role": "", "swatch": None}]}
    assert "a&lt;b&gt;&amp;c" in diagram_svg.to_svg(weird).decode("utf-8")


def test_a_floor_may_carry_its_own_outline_and_a_malformed_one_is_refused():
    kept = studio()["objects"][0]["floors"][0]
    assert kept["outline"] == [PODIUM, COURT]
    with pytest.raises(ValueError, match=r"floors\[0\]\.outline"):
        studio(objects=[{"id": "p", "layer": "Shop", "height": 9.0, "base": 0.0, "footprint": PODIUM,
                         "floors": [{"z": 0, "area": 1.0, "outline": [[0, 0], [1, 1]]}]}])


def test_a_page_can_be_set_without_the_drawings_words_which_are_then_given_apart():
    for kind in ("program", "stack"):  # one seen from the south-west, one flat
        drawing = diagrams.drawing(kind, studio(), ctx())
        whole, alone = diagram_svg.layout(drawing), diagram_svg.layout(drawing, words=False)
        said = diagram_svg.words(drawing)
        assert said["legend"][0] == (snap.MEANINGS["commercial"]["color"], of(drawing, "text", role="legend")[0]["text"])
        assert said["caption"] == [item["text"] for item in of(drawing, "text", role="caption")] and said["caption"]
        texts = {shape["text"] for shape in alone["shapes"] if shape["type"] == "text"}
        assert drawing["title"] not in texts and not texts & {text for _color, text in said["legend"]} and not texts & set(said["caption"])
        assert [s for s in alone["shapes"] if s["tag"] == "face"] or kind == "stack"
        assert len(alone["shapes"]) < len(whole["shapes"]) and not any(s["tag"] == "swatch" for s in alone["shapes"])
    assert diagram_svg.to_svg(drawing) == diagram_svg.to_svg(diagrams.drawing("stack", studio(), ctx()))  # the file keeps its words

