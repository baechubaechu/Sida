"""The 조경 and 공개 공지 a building asks, read by rule from data/landscape_rules.yaml."""

from sida.experts.landscape import rules

SEOUL = "서울특별시 중구"


def test_seoul_asks_landscape_by_floor_area_with_its_article():
    for gross, ratio in [(5600, 15), (2000, 15), (1999, 10), (1000, 10), (999, 5)]:
        got = rules.requirement("일반상업지역", SEOUL, 1584, gross)["landscape"]
        assert (got["status"], got["ratio"]) == ("read", ratio), gross
    got = rules.requirement("일반상업지역", SEOUL, 1584, 5600)
    assert got["landscape"]["area_m2"] == 237.6 and got["landscape"]["source"] == "서울특별시 건축 조례 제24조"
    assert "원문 대조 전" not in got["landscape"]["detail"]  # compared on 2026-11-20
    # 조경기준: a 상업지역 plants 0.1 trees and 1 shrub per ㎡ of the 조경 asked, half of it planted
    assert (got["planting"]["trees"], got["planting"]["shrubs"], got["planting"]["planted_m2"]) == (24, 238, 118.8)
    assert rules.requirement("제2종일반주거지역", SEOUL, 1584, 5600)["planting"]["trees"] == 48


def test_a_small_site_asks_five_percent_and_one_under_200_none():
    small = rules.requirement("제2종일반주거지역", SEOUL, 250, 3000)["landscape"]
    assert (small["ratio"], small["area_m2"]) == (5, 12.5) and "300㎡ 미만" in small["detail"]
    tiny = rules.requirement("제2종일반주거지역", SEOUL, 180, 3000)["landscape"]
    assert tiny["status"] == "none" and tiny["area_m2"] is None


def test_exempt_zones_unknown_regions_and_an_unknown_floor_area():
    assert rules.requirement("자연녹지지역", SEOUL, 1000, 500)["landscape"]["status"] == "none"
    busan = rules.requirement("일반상업지역", "부산광역시 중구", 1000, 3000)["landscape"]
    assert busan["status"] == "check" and busan["ratio"] is None
    unknown = rules.requirement("일반상업지역", SEOUL, 1000, None)
    assert unknown["landscape"]["status"] == "conditional" and unknown["planting"]["trees"] is None
    assert rules.requirement("일반상업지역", SEOUL, None, 3000)["landscape"]["status"] == "check"


def test_open_space_asks_seoul_ten_percent_for_its_uses_over_5000():
    office = rules.requirement("일반상업지역", SEOUL, 1584, 5600, "office")["open_space"]
    assert (office["status"], office["ratio"], office["area_m2"]) == ("read", 10, 158.4)
    assert (office["least_width_m"], office["least_piece_m2"]) == (9, 90)
    # Seoul adds 의료시설 to the statute's uses; elsewhere only the statute's
    assert rules.requirement("일반상업지역", SEOUL, 1584, 5600, "medical")["open_space"]["status"] == "read"
    assert "medical" not in rules.open_uses("부산광역시 중구") and "medical" in rules.open_uses(SEOUL)
    assert rules.requirement("일반상업지역", SEOUL, 1584, 4999, "office")["open_space"]["status"] == "none"
    assert rules.requirement("제1종전용주거지역", SEOUL, 1584, 9000, "office")["open_space"]["status"] == "none"
    assert rules.requirement("일반상업지역", SEOUL, 1584, 9000, None)["open_space"]["status"] == "conditional"
    assert rules.requirement("일반상업지역", SEOUL, 1584, 9000, "other")["open_space"]["status"] == "none"
    busan = rules.requirement("일반상업지역", "부산광역시 중구", 1584, 9000, "office")["open_space"]
    assert busan["status"] == "check" and "10% 이하" in busan["detail"]


def test_the_card_line_names_the_ratios_by_floor_area():
    line = rules.card_line(["제2종일반주거지역"], SEOUL, 600)
    assert (line["id"], line["status"], line["value"]) == ("landscape", "conditional", "대지면적의 5~15%")
    assert rules.card_line(["제2종일반주거지역"], SEOUL, 250)["value"] == "대지면적의 5%"
    assert rules.card_line(["일반상업지역", "제3종일반주거지역"], SEOUL, 600) is None
    assert [u["key"] for u in rules.uses(SEOUL)][-1] == "other"
