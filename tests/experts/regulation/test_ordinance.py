"""ordinance.py — finding a municipality's 도시·군계획 조례 and quoting its 건폐율 / 용적률 articles.

Recorded law.go.kr responses: searches for 군포시, 서울특별시 and 고성군, and the 군포시 ordinance
(trimmed to the articles about coverage and floor-area ratio).
"""

from __future__ import annotations

from datetime import date

from sida.experts.regulation import lawapi, ordinance
from sida.experts.regulation.lawapi import LawApiError

TODAY = date(2026, 10, 6)


def test_search_and_body_are_parsed(fake_ordinance):
    hits = lawapi.search_ordinances("군포시 도시계획 조례")
    own = next(h for h in hits if h["name"] == "군포시 도시계획 조례")
    assert own == {
        "name": "군포시 도시계획 조례", "org": "경기도 군포시", "kind": "조례",
        "effective": "2025-10-10", "mst": "2077621", "id": "2149243",
    }
    body = lawapi.ordinance_articles("2077621")
    assert (body["name"], body["org"], body["effective"]) == ("군포시 도시계획 조례", "경기도 군포시", "2025-10-10")
    labels = [a["label"] for a in body["articles"]]
    assert "제49조" in labels and "제54조의2" in labels  # 가지번호
    assert all(a["title"] for a in body["articles"])  # chapter headings are not articles
    assert lawapi.search_ordinances("   ") == [] and len(fake_ordinance.calls) == 2


def test_province_names_old_and_new_are_the_same_body():
    assert ordinance.province_key("강원도") == ordinance.province_key("강원특별자치도") == "강원"
    assert ordinance.province_key("전라북도") == ordinance.province_key("전북특별자치도") == "전북"
    assert ordinance.province_key("경상남도") == "경남" != ordinance.province_key("경상북도")
    assert ordinance.same_body("강원특별자치도 고성군", "강원도 고성군")
    assert not ordinance.same_body("경상남도 고성군", "강원도 고성군")
    assert not ordinance.same_body("서울특별시 종로구", "서울특별시")
    assert not ordinance.same_body("", "서울특별시")
    assert ordinance.same_body("(구)광주광역시", "광주광역시")  # merged into 전남광주통합특별시 in 2026
    assert ordinance.same_body("전라남도 여수시", "전남광주통합특별시 여수시")


def test_picks_the_bodys_own_planning_ordinance(fake_ordinance):
    hit = ordinance.find_planning_ordinance("경기도 군포시", today=TODAY)
    assert hit["name"] == "군포시 도시계획 조례"  # not the 노후계획도시 or 특별회계 ordinances

    seoul = ordinance.find_planning_ordinance("서울특별시", today=TODAY)
    assert (seoul["name"], seoul["org"]) == ("서울특별시 도시계획 조례", "서울특별시")  # not a 구's

    south = ordinance.find_planning_ordinance("경상남도 고성군", today=TODAY)
    north = ordinance.find_planning_ordinance("강원도 고성군", today=TODAY)  # 군계획 조례, old 도 name
    assert south["org"] == "경상남도 고성군" and north["org"] == "강원특별자치도 고성군"
    assert south["mst"] != north["mst"]

    assert ordinance.find_planning_ordinance("경기도 없는시", today=TODAY) is None
    assert ordinance.find_planning_ordinance("", today=TODAY) is None


def test_lookup_quotes_the_two_base_articles(fake_ordinance):
    result = ordinance.lookup("경기도 군포시", today=TODAY)
    assert result["error"] is None
    assert (result["name"], result["effective"], result["mst"]) == ("군포시 도시계획 조례", "2025-10-10", "2077621")
    bcr, far = result["articles"]
    assert (bcr["kind"], bcr["label"], bcr["title"]) == ("bcr", "제49조", "용도지역안에서의 건폐율")
    assert (far["kind"], far["label"]) == ("far", "제53조")
    assert "12. 일반공업지역 : 100분의 70 이하" in bcr["text"]  # as written, not converted
    assert "12. 일반공업지역 : 100분의 350 이하" in far["text"]
    assert "\n②" in far["text"]  # paragraphs on their own lines
    related = {r["label"]: r["title"] for r in result["related"]}
    assert related["제52조"] == "건폐율의 완화" and "제54조의2" in related
    assert "제49조" not in related
    groups = {r["label"]: r["group"] for r in result["related"]}
    assert groups["제34조"] == "site"  # 자연ㆍ특화경관지구안에서의 건폐율
    assert groups["제50조"] == "site"  # 그 밖의 용도지구ㆍ구역 등의 건폐율
    assert groups["제52조"] == "design" and groups["제55조"] == "design"  # 완화
    assert groups["제51조"] == "admin"  # 건폐율의 강화
    assert all(r["text"] for r in result["related"])  # every related article keeps its text


def test_lookup_reports_failures_instead_of_raising(fake_ordinance):
    assert ordinance.lookup("경기도 없는시", today=TODAY)["error"] == "not_found"

    fake_ordinance.overrides["search"] = LawApiError("network", "ConnectTimeout")
    failed = ordinance.lookup("경기도 군포시", today=TODAY)
    assert failed["error"] == "network" and failed["articles"] == [] and failed["name"] == ""

    del fake_ordinance.overrides["search"]
    fake_ordinance.overrides["body"] = LawApiError("network", "ReadTimeout")
    failed = ordinance.lookup("경기도 군포시", today=TODAY)
    assert failed["error"] == "network" and failed["name"] == "군포시 도시계획 조례"  # found, not read

    fake_ordinance.overrides["body"] = '{"LawService": {"자치법규기본정보": {}, "조문": {"조": []}}}'
    assert ordinance.lookup("경기도 군포시", today=TODAY)["error"] == "no_articles"


def test_non_json_reply_is_retried_once_then_reported(fake_ordinance):
    good = (lawapi.ROOT / "tests/fixtures/lawapi/ordin_search_gunpo.json").read_text(encoding="utf-8")
    fake_ordinance.overrides["search"] = ["<html>잠시 후 다시</html>", good]
    assert ordinance.lookup("경기도 군포시", today=TODAY)["error"] is None

    fake_ordinance.overrides["search"] = ["<html>오류</html>"]
    assert ordinance.lookup("경기도 군포시", today=TODAY)["error"] == "bad_response"

    not_applied = (lawapi.ROOT / "tests/fixtures/lawapi/not_applied.html").read_text(encoding="utf-8")
    fake_ordinance.overrides["search"] = [not_applied]
    assert ordinance.lookup("경기도 군포시", today=TODAY)["error"] == "denied"


def test_pick_articles_leaves_relaxations_and_combined_titles_out():
    def article(label, title, text="본문"):
        return {"label": label, "title": title, "text": text}

    base, related = ordinance.pick_articles(
        [
            article("제1조", "목적"),
            article("제19조", "지구단위계획구역안에서의 건폐율 등의 완화적용"),
            article("제51조", "용도지역 안에서의 건폐율 <개정 2014.5.30>"),
            article("제52조", "용도지역ㆍ지구안에서의 건폐율의 완화"),
            article("제56조", "용도지역 안에서의 용적률", text=""),  # deleted article
            article("제57조", "용도지역안에서의 용적률"),
        ]
    )
    assert [(a["kind"], a["label"], a["title"]) for a in base] == [
        ("bcr", "제51조", "용도지역 안에서의 건폐율"),
        ("far", "제57조", "용도지역안에서의 용적률"),
    ]
    assert [r["label"] for r in related] == ["제19조", "제52조", "제56조"]
    assert ordinance.pick_articles([article("제1조", "목적")]) == ([], [])

    # a district's article that sets a ratio only in its text (서울: "자연경관지구 안에서의 건축제한")
    _, seoul = ordinance.pick_articles(
        [
            article("제34조", "자연경관지구 안에서의 건축제한", "① 건폐율은 30퍼센트 이하로 한다."),
            article("제39조", "보호지구 안에서의 건축제한", "① 다음 건축물을 건축할 수 없다."),
            article("제20조", "지구단위계획의 수립기준 등", "건폐율 완화 기준을 포함한다."),
        ]
    )
    assert [(r["label"], r["group"]) for r in seoul] == [("제34조", "site")]


# --- reading the figure for a zone (fixed rules, text taken from real ordinances) ----

IND = {"bcr_max": 70, "far_min": 150, "far_max": 350}
RES2 = {"bcr_max": 60, "far_min": 100, "far_max": 250}
COM = {"bcr_max": 90, "far_min": 200, "far_max": 1500}


def test_items_are_split_by_counting_even_when_glued_to_a_figure():
    text = (
        "① 영 제84조제1항에 따라 건폐율은 다음 각 호의 비율 이하로 한다.<개정 2016.8.10.>"
        "1. 제1종전용주거지역：100분의 402. 제2종전용주거지역：100분의 40"  # "402." is 40 then item 2
        "3. 준주거지역 : 60퍼센트 이하. 다만, 해제지역은 따로 정한다.<개정, 2020. 12. 18.>"
        "4. 유통상업지역 : 100분의 6010. 이건 10호가 아님"
        "\n② 제1항에도 불구하고 1. 시장은 65퍼센트 이하로 한다."
    )
    items = ordinance.list_items(ordinance._TAG.sub("", text))
    assert [i.split("：")[0].split(" :")[0] for i in items] == [
        "제1종전용주거지역", "제2종전용주거지역", "준주거지역", "유통상업지역",
    ]
    assert items[3].startswith("유통상업지역") and "②" not in items[3]  # stops at the next 항
    assert ordinance.zone_figure(text, "제1종전용주거지역")["value"] == 40
    assert ordinance.zone_figure(text, "제2종전용주거지역")["value"] == 40


def test_each_way_of_writing_a_percentage():
    def read(line, zone="일반공업지역"):
        return ordinance.zone_figure(f"① 다음 각 호와 같다.1. {line}2. 그밖의지역 : 10퍼센트", zone)

    assert read("일반공업지역 : 100분의 70 이하")["value"] == 70
    assert read("일반공업지역: 70퍼센트")["value"] == 70
    assert read("일반공업지역 : 70% 이하")["value"] == 70
    assert read("일 반 공 업 지 역 : 350퍼센트 이하")["value"] == 350  # "농 림 지 역" style spacing
    assert read("중심상업지역 : 1천300퍼센트 이하", "중심상업지역")["value"] == 1300
    assert read("중심상업지역 : 1,500퍼센트", "중심상업지역")["value"] == 1500
    assert read("중심상업지역 : 100분의 1,000 이하", "중심상업지역")["value"] == 1000
    assert read("일반공업지역안의 산업단지 : 80퍼센트") is None  # a longer name is another item
    assert read("준공업지역 : 70퍼센트") is None  # zone not listed


def test_provisos_are_flagged_and_unclear_items_give_no_figure():
    def read(line):
        return ordinance.zone_figure(f"다음 각 호와 같다.1. {line}", "제2종일반주거지역")

    plain = read("제2종일반주거지역 : 220퍼센트 이하(단, 대지면적 1천제곱미터 초과 시 200퍼센트 이하)")
    assert (plain["value"], plain["conditional"]) == (220, True)
    assert "200퍼센트 이하)" in plain["quote"]  # the proviso stays in the quote
    proviso = read("제2종일반주거지역 : 100분의 230 이하. 다만, 주택재건축사업은 100분의 250 이하")
    assert (proviso["value"], proviso["conditional"]) == (230, True)
    assert read("제2종일반주거지역: 250퍼센트")["conditional"] is False

    sub_items = read("제2종일반주거지역: 250퍼센트 이하가. 아파트 230퍼센트 이하나. 그 밖의 건축물 250퍼센트 이하")
    assert sub_items["value"] is None and sub_items["conditional"] is True and sub_items["quote"]
    two = read("제2종일반주거지역 : 동지역 250퍼센트, 읍면지역 200퍼센트")
    assert two["value"] is None
    assert read("제2종일반주거지역 : 별표 3과 같다")["value"] is None


def test_values_outside_the_statutory_range_are_not_reported(fake_ordinance):
    articles = ordinance.lookup("경기도 군포시", today=TODAY)["articles"]
    values = ordinance.zone_values(articles, "일반공업지역", IND)
    assert (values["bcr"]["value"], values["bcr"]["label"]) == (70, "제49조")
    assert (values["far"]["value"], values["far"]["label"]) == (350, "제53조")
    res = ordinance.zone_values(articles, "제2종일반주거지역", RES2)
    assert res["bcr"]["value"] == 60 and (res["far"]["value"], res["far"]["conditional"]) == (230, True)

    # the same text read against a narrower range: a misreading must not pass as a fact
    narrow = ordinance.zone_values(articles, "일반공업지역", {"bcr_max": 60, "far_min": 150, "far_max": 300})
    assert narrow["bcr"]["value"] is None and narrow["bcr"]["out_of_range"] and narrow["bcr"]["quote"]
    assert narrow["far"]["value"] is None and narrow["far"]["out_of_range"]
    assert ordinance.zone_values(articles, "계획관리지역", COM) == {"bcr": None, "far": None}  # 군포 has none


def test_combined_or_annex_articles_are_quoted_without_a_figure():
    def article(label, title, text):
        return {"label": label, "title": title, "text": text}

    base, _ = ordinance.pick_articles(
        [article("제46조", "용도지역 안에서의 건폐율‧용적률", "건폐율 및 용적률은 별표 24에 따른다.")]
    )
    assert [a["kind"] for a in base] == ["both"]
    assert ordinance.zone_values(base, "일반상업지역", COM) == {"bcr": None, "far": None}

    yeosu, _ = ordinance.pick_articles([article("제33조", "용도구역·지역·지구안에서의 건폐율", "1. 준주거지역 : 60퍼센트")])
    assert [a["kind"] for a in yeosu] == ["bcr"]


# --- "별표 N과 같다": the annex file (HWP) is read the same way ----------------------

FIXTURES = lawapi.ROOT / "tests" / "fixtures" / "lawapi"
ANNEX_URL = "http://www.law.go.kr/flDownload.do?gubun=ELIS&flSeq=1&flNm=x"


def _annex(label, name):
    return {"label": label, "title": f"[{label}] 표", "url": f"{ANNEX_URL}&f={name}", "format": "hwp"}


def _serve_files(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        return (FIXTURES / url.rsplit("f=", 1)[-1]).read_bytes()

    monkeypatch.setattr(lawapi, "_http_get_bytes", get)
    return calls


def test_hwp_paragraphs_come_out_clean():
    from sida.experts.regulation import hwp

    lines = hwp.paragraphs((FIXTURES / "annex_changwon_bcr.hwp").read_bytes())
    assert lines[0].startswith("【별표 27】")  # no control-character debris in front
    assert "4. 제2종 일반주거지역 : 60퍼센트" in lines
    table = hwp.paragraphs((FIXTURES / "annex_ulsan_table.hwp").read_bytes())
    assert "건폐율(%)" in table and "용적률(%)" in table and "제1종 전용주거지역" in table
    for junk in (b"", b"<html>not a file</html>", b"\xd0\xcf\x11\xe0" + b"\x00" * 600):
        try:
            hwp.paragraphs(junk)
        except hwp.HwpError:
            continue
        raise AssertionError("expected HwpError")


def test_article_pointing_at_an_annex_list_is_read_from_the_file(monkeypatch):
    calls = _serve_files(monkeypatch)
    article = {"kind": "bcr", "label": "제58조", "title": "용도지역에서의 건폐율",
               "text": "제58조(용도지역에서의 건폐율) 영 제84조제1항에 따라 건폐율은 별표 27과 같다."}
    followed = ordinance.follow_annex(article, [_annex("별표 27", "annex_changwon_bcr.hwp")])
    assert followed["annex"]["label"] == "별표 27" and len(calls) == 1
    assert calls[0].startswith("https://www.law.go.kr/flDownload.do?")  # always law.go.kr, https

    values = ordinance.zone_values([followed], "제2종일반주거지역", RES2)
    assert values["bcr"]["value"] == 60 and values["bcr"]["label"] == "제58조 별표 27"
    com = ordinance.zone_values([followed], "일반상업지역", {"bcr_max": 80, "far_min": 200, "far_max": 1300})
    assert (com["bcr"]["value"], com["bcr"]["conditional"]) == (80, True)  # "다만, 창원신도시구역은 60퍼센트"
    assert values["far"] is None

    listed = {**article, "text": "① 다음 각 호와 같다.1. 준주거지역 : 60퍼센트 (별표 3 참조)"}
    assert "annex" not in ordinance.follow_annex(listed, [_annex("별표 3", "annex_changwon_bcr.hwp")])
    assert len(calls) == 1  # an article that lists zones itself is not sent to the annex


def test_combined_annex_table_gives_both_ratios(monkeypatch):
    _serve_files(monkeypatch)
    article = {"kind": "both", "label": "제46조", "title": "용도지역 안에서의 건폐율‧용적률",
               "text": "건폐율 및 용적률은 별표 24에 따른다."}
    followed = ordinance.follow_annex(article, [_annex("별표 24", "annex_ulsan_table.hwp")])
    values = ordinance.zone_values([followed], "일반상업지역", {"bcr_max": 80, "far_min": 200, "far_max": 1300})
    assert (values["bcr"]["value"], values["far"]["value"]) == (70, 1200)
    assert values["far"]["quote"] == "일반상업지역 | 70 | 1,200 (표의 열: 건폐율, 용적률)"
    assert ordinance.zone_values([followed], "없는지역", RES2) == {"bcr": None, "far": None}
    assert ordinance.table_figures(["용도", "건폐율(%)", "제2종일반주거지역", "별도"], "제2종일반주거지역") == {}


def test_annex_that_cannot_be_read_is_reported_not_guessed(monkeypatch):
    article = {"kind": "far", "label": "제60조", "title": "용도지역에서의 용적률", "text": "용적률은 별표 28과 같다."}

    assert ordinance.follow_annex(article, [])["annex"] == {"label": "별표 28", "error": "not_listed"}

    def down(url):
        raise LawApiError("network", "ReadTimeout")

    monkeypatch.setattr(lawapi, "_http_get_bytes", down)
    failed = ordinance.follow_annex(article, [_annex("별표 28", "x.hwp")])
    assert failed["annex"]["error"] == "network"

    monkeypatch.setattr(lawapi, "_http_get_bytes", lambda url: b"%PDF-1.7 not hwp")
    assert ordinance.follow_annex(article, [_annex("별표 28", "x.hwp")])["annex"]["error"] == "unreadable"
    pdf = {**_annex("별표 28", "x.pdf"), "format": "pdf"}
    assert ordinance.follow_annex(article, [pdf])["annex"]["error"] == "unreadable"
    assert ordinance.zone_values([failed], "준공업지역", IND) == {"bcr": None, "far": None}

    elsewhere = {**_annex("별표 28", "x.hwp"), "url": "http://example.com/flDownload.do?x=1"}
    assert ordinance.follow_annex(article, [elsewhere])["annex"]["error"] == "bad_response"  # not fetched


def test_ordinance_body_lists_its_annexes(fake_ordinance):
    fake_ordinance.overrides["body"] = (
        '{"LawService": {"자치법규기본정보": {"자치법규명": "가시 도시계획 조례"}, "조문": {"조": []}, '
        '"별표": {"별표단위": [{"별표제목": "[별표 27] 건폐율", "별표번호": "0027", "별표가지번호": "00", '
        '"별표첨부파일구분": "hwp", "별표첨부파일명": "http://www.law.go.kr/flDownload.do?flSeq=1"}, '
        '{"별표제목": "[별표 3의2] 표", "별표번호": "0003", "별표가지번호": "02", "별표첨부파일구분": "pdf", '
        '"별표첨부파일명": ""}]}}}'
    )
    annexes = lawapi.ordinance_articles("1")["annexes"]
    assert [(a["label"], a["format"]) for a in annexes] == [("별표 27", "hwp"), ("별표 3의2", "pdf")]
    assert annexes[0]["url"].endswith("flSeq=1")


def test_related_articles_fall_into_three_groups_by_title():
    site = ["경관지구안에서의 건폐율", "방화지구 안에서의 건폐율의 완화", "그 밖의 용도지구ㆍ구역 등의 용적률",
            "도시지역 내 지구단위계획구역에서의 건폐율 등의 완화적용", "성장관리계획구역에서의 건폐율 완화",
            "경제자유구역안에서의 용적률 등", "그 밖의 건폐율", "기타 용도지구·구역 등의 용적률"]
    design = ["건폐율의 완화", "공원 등에 인접한 대지에 대한 용적률의 완화", "장수명 주택의 용적률 완화",
              "공지의 설치·조성후 제공할 경우의 용적률 완화", "「농지법」에 따라 허용되는 건축물의 건폐율 완화",
              "생산녹지지역 등에서 기존 공장의 건폐율"]
    admin = ["건폐율의 강화", "용적률의 강화", "용도지역 안에서의 건폐율 강화"]
    assert {ordinance.classify(t) for t in site} == {"site"}
    assert {ordinance.classify(t) for t in design} == {"design"}
    assert {ordinance.classify(t) for t in admin} == {"admin"}


def test_readable_puts_each_paragraph_and_item_on_its_own_line():
    glued = ("제49조(용도지역안에서의 건폐율)① 다음 각 호와 같다.1. 제1종 전용주거지역 : 100분의 40"
             "2. 제2종 전용주거지역 : 100분의 50② 제1항에도 불구하고 시장은 65퍼센트 이하로 한다.")
    assert ordinance.readable(glued).split("\n") == [
        "제49조(용도지역안에서의 건폐율)",
        "① 다음 각 호와 같다.",
        "  1. 제1종 전용주거지역 : 100분의 40",
        "  2. 제2종 전용주거지역 : 100분의 50",
        "② 제1항에도 불구하고 시장은 65퍼센트 이하로 한다.",
    ]
    plain = "제51조(건폐율의 강화) 40퍼센트까지 낮출 수 있다."
    assert ordinance.readable(plain) == plain and ordinance.readable("") == ""


def test_excerpt_keeps_the_sites_zone_lines_and_everything_that_is_not_a_zone_line():
    zones = ["제1종전용주거지역", "제2종일반주거지역", "준주거지역", "일반공업지역"]
    text = ("제49조(건폐율)① 다음 각 호와 같다.1. 제1종 전용주거지역 : 100분의 402. 제2종 일반주거지역 : 100분의 60"
            "3. 준주거지역 : 100분의 604. 일 반 공 업 지 역 : 100분의 70② 다음 각 호의 경우는 완화한다."
            "1. 정비사업2. 시장정비사업")
    out = ordinance.excerpt_for_zones(text, ["제2종일반주거지역", "일반공업지역"], zones)
    assert out.split("\n") == [
        "제49조(건폐율)",
        "① 다음 각 호와 같다.",
        "  2. 제2종 일반주거지역 : 100분의 60",
        "  4. 일 반 공 업 지 역 : 100분의 70",
        "② 다음 각 호의 경우는 완화한다.",
        "  1. 정비사업",
        "  2. 시장정비사업",
        "  (다른 용도지역의 호 2개 생략)",
    ]
    assert "생략" not in ordinance.excerpt_for_zones(text, zones, zones)
    assert ordinance.ratio_paragraphs("제1조(목적) 건폐율을 정한다.") == "제1조(목적) 건폐율을 정한다."
    assert "생략" not in ordinance.ratio_paragraphs("제2조(완화)① 건폐율 완화② 용적률 완화")


# --- decimal figures: never read as a wrong whole number ------------------------------


def test_decimal_percentages_give_no_figure_instead_of_a_wrong_one():
    def read(line):
        return ordinance.zone_figure(
            f"① 다음 각 호와 같다.1. {line}2. 준주거지역 : 60퍼센트", "제2종일반주거지역"
        )

    for line in (
        "제2종일반주거지역 : 62.5퍼센트 이하",  # was read as 5
        "제2종일반주거지역 : 62.5% 이하",  # was read as 5
        "제2종일반주거지역 : 100분의 62.5 이하",  # was read as 62
        "제2종일반주거지역 : 1,250.5퍼센트",  # was read as 5
    ):
        figure = read(line)
        assert figure["value"] is None, line
        assert figure["quote"] == line  # the line itself is still shown

    # a decimal that is a whole number is that number
    assert read("제2종일반주거지역 : 60.0퍼센트 이하")["value"] == 60
    assert read("제2종일반주거지역 : 100분의 60.00 이하")["value"] == 60
    # the next item is still found right after a decimal figure
    after = ordinance.zone_figure("① 같다.1. 제2종일반주거지역 : 62.5퍼센트2. 준주거지역 : 60퍼센트", "준주거지역")
    assert after["value"] == 60
    glued = ordinance.zone_figure("① 같다.1. 제2종일반주거지역 : 100분의 62.52. 준주거지역 : 100분의 60", "제2종일반주거지역")
    assert glued["value"] is None and glued["quote"] == "제2종일반주거지역 : 100분의 62.5"

    # the range check alone would not have caught 5%: it is a valid 건폐율
    article = {"kind": "bcr", "label": "제1조", "text": "① 같다.1. 제2종일반주거지역 : 62.5퍼센트 이하"}
    assert ordinance.zone_values([article], "제2종일반주거지역", RES2)["bcr"]["value"] is None


def test_decimal_cells_in_an_annex_table_give_no_figure_for_that_cell():
    lines = ["용도", "건폐율(%)", "용적률(%)", "제2종일반주거지역", "62.5", "250", "준주거지역", "60.0", "400"]
    found = ordinance.table_figures(lines, "제2종일반주거지역")
    assert found["bcr"]["value"] is None and found["far"]["value"] == 250
    assert found["bcr"]["quote"].startswith("제2종일반주거지역 | 62.5 | 250")
    whole = ordinance.table_figures(lines, "준주거지역")
    assert (whole["bcr"]["value"], whole["far"]["value"]) == (60, 400)


def test_a_date_left_in_the_line_is_not_a_decimal_figure():
    # 경상남도 고성군: "…20퍼센트 이하[제목 개정 2013.01.01. 조 2095]" must still read as 20
    line = "① 같다.1. 자연환경보전지역 : 20퍼센트 이하[제목 개정 2013.01.01. 조 2095]"
    figure = ordinance.zone_figure(line, "자연환경보전지역")
    assert figure["value"] == 20 and figure["quote"] == "자연환경보전지역 : 20퍼센트 이하"
    dated = ordinance.zone_figure("① 같다.1. 준주거지역 : 60퍼센트 이하 2013.01.01. 시행", "준주거지역")
    assert dated["value"] == 60
