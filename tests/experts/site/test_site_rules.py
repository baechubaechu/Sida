"""The site card's "이 대지에 걸리는 것" lines (site_rules) and the ordinance proviso they apply."""

from sida.experts.site import site_facts, site_rules

FAR_QUOTE = "일반상업지역: 800퍼센트(단, 서울도심: 600퍼센트)"


def facts(zone="일반상업지역", districts=(), far=None, bcr=None, area=3622.9, ordinance=True):
    limits = site_facts.load_limits()["zones"][zone]
    values = {zone: {
        "bcr": bcr if bcr is not None else {"value": 60, "quote": f"{zone}: 60퍼센트", "conditional": False, "label": "제44조"},
        "far": far if far is not None else {"value": 800, "quote": FAR_QUOTE, "conditional": True, "label": "제48조"},
    }}
    return {
        "summary": {
            "zoning": [{"zone": zone, "pnus": ["1"], "area_m2": area, **limits}],
            "districts": [{"name": n, "relation": r} for n, r in districts],
            "total_area_m2": area, "area_complete": True, "parcel_count": 1, "municipality": "서울특별시",
        },
        "ordinance": {"articles": [{"label": "제48조", "kind": "far"}], "values": values} if ordinance else {"error": "not_found"},
    }


MUGYO = [("서울도심", "포함"), ("정비구역", "포함"), ("대공방어협조구역(위탁고도:77-257m)", "포함"), ("중점경관관리구역", "포함")]


def test_a_proviso_naming_the_sites_district_gives_the_figure_that_holds():
    f = facts(districts=MUGYO)
    figure = site_facts.site_figure(f, "일반상업지역", "far")
    assert figure["applied"] == {"value": 600, "where": "서울도심", "base": 800}
    limit = site_facts.limits(f)[0]
    assert (limit["ordinance_far"], limit["ordinance_far_where"]) == (600, "서울도심")
    assert (limit["ordinance_bcr"], limit["ordinance_bcr_where"]) == (60, "")
    text = "\n".join(site_facts._ordinance_value_lines(f))
    assert "용적률 600% 이하 — 대지가 서울도심 안이라 단서의 수치를 적용(기본 800%)" in text


def test_a_proviso_is_not_applied_outside_its_district_or_to_a_condition():
    assert "applied" not in site_facts.site_figure(facts(), "일반상업지역", "far")
    assert "applied" not in site_facts.site_figure(facts(districts=[("서울도심", "접함")]), "일반상업지역", "far")
    size = {"value": 220, "quote": "제2종일반주거지역 : 220퍼센트 이하(단, 대지면적 1천제곱미터 초과 시 200퍼센트 이하)",
            "conditional": True, "label": "제55조"}
    f = facts("제2종일반주거지역", districts=MUGYO, far=size)  # a condition names no 지구·구역
    assert "applied" not in site_facts.site_figure(f, "제2종일반주거지역", "far")
    assert site_facts.limits(f)[0]["ordinance_far"] == 220


def test_two_provisos_for_the_site_or_one_out_of_range_give_no_figure():
    two = {"value": 1000, "conditional": True, "label": "제48조",
           "quote": "중심상업지역 : 1천퍼센트 이하(단, 서울도심 : 800퍼센트 이하, 역사문화미관지구 : 600퍼센트)"}
    f = facts("중심상업지역", districts=[("서울도심", "포함"), ("역사문화미관지구", "포함")], far=two)
    assert site_facts.site_figure(f, "중심상업지역", "far")["applied"] == {"value": None, "where": "서울도심, 역사문화미관지구", "base": 1000}
    assert site_facts.limits(f)[0]["ordinance_far"] is None
    wild = {"value": 800, "conditional": True, "label": "제48조", "quote": "일반상업지역: 800퍼센트(단, 서울도심: 6000퍼센트)"}
    assert site_facts.limits(facts(districts=MUGYO, far=wild))[0]["ordinance_far"] is None


def test_the_card_for_mugyo_45_says_what_applies_in_five_lines():
    lines = site_rules.card(facts(districts=MUGYO))
    assert [(x["id"], x["status"], x["value"]) for x in lines] == [
        ("far", "read", "600%"),
        ("bcr", "read", "60%"),
        ("height", "conditional", "대공방어협조구역(위탁고도:77-257m)"),
        ("sunlight", "none", "해당 없음"),
        ("plan", "check", "정비구역, 중점경관관리구역"),
    ]
    far = lines[0]
    assert far["detail"].startswith("연면적 최대 21,737㎡. 일반상업지역 기본 800%, 대지가 서울도심 안이라 단서의 600%")
    assert (far["quote"], far["source"]) == (FAR_QUOTE, "제48조")
    assert lines[1]["detail"] == "건축면적 최대 2,174㎡"


def test_the_card_on_a_residential_site_without_an_ordinance():
    f = facts("제2종일반주거지역", ordinance=False)
    lines = {x["id"]: x for x in site_rules.card(f)}
    assert (lines["far"]["status"], lines["far"]["value"]) == ("check", "법정 상한 250%")
    assert "도시·군계획 조례를 찾지 못함" in lines["far"]["detail"]
    assert (lines["sunlight"]["status"], lines["sunlight"]["value"]) == ("read", "적용")
    sun = lines["sunlight"]
    assert sun["source"] == "건축법 제61조제1항" and "17미터" in sun["quote"]  # 2026-11-12 개정
    assert "10m 넘고 17m 이하 부분은 5m 이상" in sun["detail"] and "원문 대조 전" not in sun["detail"]
    assert "height" not in lines and "plan" not in lines


def test_the_card_with_an_unread_or_unconditioned_figure():
    unread = {"value": None, "quote": "일반상업지역: 가. 800퍼센트 나. 600퍼센트", "conditional": True, "label": "제48조"}
    far = {x["id"]: x for x in site_rules.card(facts(far=unread))}["far"]
    assert (far["status"], far["value"]) == ("check", "미확인") and far["quote"]
    kept = {x["id"]: x for x in site_rules.card(facts())}["far"]  # 서울도심 is not among the site's districts
    assert (kept["status"], kept["value"]) == ("conditional", "800%") and "단서·예외" in kept["detail"]


def test_several_zones_make_one_line_and_no_site_makes_none():
    f = facts()
    f["summary"]["zoning"].append({**f["summary"]["zoning"][0], "zone": "제3종일반주거지역"})
    lines = site_rules.card(f)
    assert lines[0]["id"] == "zones" and lines[0]["value"] == "일반상업지역, 제3종일반주거지역"
    assert {x["id"]: x for x in lines}["sunlight"]["value"] == "적용"
    assert site_rules.card(None) == []
