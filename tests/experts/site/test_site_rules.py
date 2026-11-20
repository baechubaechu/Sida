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


def test_the_card_for_mugyo_45_says_what_applies_in_six_lines():
    lines = site_rules.card(facts(districts=MUGYO))
    assert [(x["id"], x["status"], x["value"]) for x in lines] == [
        ("far", "read", "600%"),
        ("bcr", "read", "60%"),
        ("height", "conditional", "대공방어협조구역(위탁고도:77-257m)"),
        ("sunlight", "none", "해당 없음"),
        ("landscape", "conditional", "대지면적의 5~15%"),
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
    assert lines["sunlight"]["source"] == "건축법 제61조제1항" and "17미터 이하인 부분: 인접 대지경계선으로부터 5미터" in lines["sunlight"]["quote"]
    assert "height" not in lines and "plan" not in lines


def test_the_sunlight_line_says_when_its_statute_text_is_not_yet_compared(monkeypatch):
    f = facts("제2종일반주거지역", ordinance=False)
    rules = site_rules.load_rules()
    assert rules["north_sunlight"]["verified"] and "원문 대조 전" not in site_rules.sunlight_line(f)["detail"]
    assert site_rules.sunlight_line(f)["quote"].startswith("전용주거지역과 일반주거지역 안에서 건축하는 건축물은")
    pending = {**rules, "north_sunlight": {**rules["north_sunlight"], "verified": None}}
    monkeypatch.setattr(site_rules, "load_rules", lambda: pending)
    assert site_rules.sunlight_line(f)["detail"].endswith("(조문 원문 대조 전)")


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


def test_the_height_line_links_to_the_parcels_land_use_page():
    f = facts(districts=MUGYO)
    f["parcels"] = [{"pnu": "1114010100100450000", "address": "서울특별시 중구 무교동 45"}]
    height = {x["id"]: x for x in site_rules.card(f)}["height"]
    assert height["links"] == [{"label": "토지이음 토지이용계획(이 필지)",
                                "url": "https://www.eum.go.kr/web/ar/lu/luLandDet.jsp?pnu=1114010100100450000&mode=search&isNoScr=script&selGbn=umd"}]


def test_the_landscape_line_gives_the_seoul_ratios_by_floor_area_with_their_article():
    green = {x["id"]: x for x in site_rules.card(facts())}["landscape"]
    assert green["tiers"] == [[2000, 15], [1000, 10], [0, 5]] and green["min_site_m2"] == 200
    assert green["detail"] == "연면적 2,000㎡ 이상 15% · 1,000㎡ 이상 10% · 그 밖 5%"
    assert green["source"] == "서울특별시 건축 조례 제24조" and "대지면적의 15퍼센트 이상" in green["quote"]
    small = {x["id"]: x for x in site_rules.card(facts(area=150))}["landscape"]
    assert (small["status"], small["value"]) == ("none", "해당 없음") and "200㎡ 미만" in small["detail"]
    green_zone = {x["id"]: x for x in site_rules.card(facts("자연녹지지역"))}["landscape"]
    assert green_zone["status"] == "none" and green_zone["source"] == "건축법 시행령 제27조제1항"
