"""board.py — the drawing table: saved papers, and what the Conductor and experts are told."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sida import board, conductor, engine
from sida.errors import SidaError


@pytest.mark.parametrize("damaged", [b'{"papers":[', b'{}', b'\xff'])
def test_edit_refuses_to_replace_an_unreadable_board(tmp_path, damaged):
    path = board.board_path(tmp_path)
    path.write_bytes(damaged)
    with pytest.raises(SidaError):
        board.add_idea(tmp_path, {"text": "new"})
    assert path.read_bytes() == damaged

MASS = {"kind": "mass", "title": "안 A · 판상형", "blocks": [{"u": 0, "v": 0, "w": 36, "d": 24, "floors": 5}]}
SITE = [("site", SimpleNamespace(board_site=lambda path: {"area_m2": 1000.0, "lines": ["대지: 필지 2개"]}))]


def test_a_new_table_holds_only_the_site_and_papers_are_saved_one_by_one(tmp_path):
    assert board.load_board(tmp_path) == {"rev": 0, "papers": [board._site_paper()], "tray": [], "pins": [], "ideas": []}
    assert not board.board_path(tmp_path).exists()  # reading saves nothing

    mass = board.add_paper(tmp_path, {**MASS, "id": "mass-a", "x": 40, "y": 10, "w": 300, "h": 210})
    assert mass["rev"] == 1 and mass["paper"]["floor_height"] == 4.2
    note = board.add_paper(tmp_path, {"kind": "note", "text": "북측 일조 확인", "junk": 1})["paper"]
    assert note["id"].startswith("note-") and "junk" not in note

    moved = board.update_paper(tmp_path, "mass-a", {"x": 60, "kind": "note", "id": "other"})
    assert moved["rev"] == 3 and moved["paper"]["x"] == 60 and moved["paper"]["kind"] == "mass"
    board.update_paper(tmp_path, "site", {"x": 5})
    assert board.delete_paper(tmp_path, note["id"]) == {"rev": 5}
    saved = board.load_board(tmp_path)
    assert [p["id"] for p in saved["papers"]] == ["site", "mass-a"] and saved["papers"][0]["x"] == 5


@pytest.mark.parametrize(
    "data, message",
    [
        ({"kind": "site"}, "kind must be"),
        ({"kind": "expert", "title": "x"}, "kind must be"),
        ({**MASS, "blocks": []}, "1 to 20 blocks"),
        ({**MASS, "blocks": [{"w": 10, "d": 10, "floors": 0}]}, "floors"),
        ({**MASS, "blocks": [{"w": 10, "d": 10, "floors": 2.5}]}, "floors"),
        ({**MASS, "blocks": [{"w": -1, "d": 10, "floors": 2}]}, "greater than 0"),
        ({**MASS, "x": "left"}, "x must be a number"),
        ({"kind": "note", "text": "가" * 4001}, "longer than"),
        ({"kind": "tracing", "strokes": [[[0, 0, 0]]]}, "[x, y]"),
        ({"kind": "note", "id": "../etc"}, "paper id"),
    ],
)
def test_bad_papers_are_refused_and_nothing_is_saved(tmp_path, data, message):
    with pytest.raises(ValueError, match=message):
        board.add_paper(tmp_path, data)
    assert not board.board_path(tmp_path).exists()


def test_the_site_only_moves_and_stays_and_unknown_papers_are_not_found(tmp_path):
    with pytest.raises(ValueError, match="only moves"):
        board.update_paper(tmp_path, "site", {"text": "x"})
    with pytest.raises(ValueError, match="cannot be removed"):
        board.delete_paper(tmp_path, "site")
    with pytest.raises(board.PaperNotFound):
        board.update_paper(tmp_path, "nope", {"x": 1})
    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    with pytest.raises(ValueError, match="already exists"):
        board.add_paper(tmp_path, {**MASS, "id": "mass-a"})


def test_mass_figures_come_from_the_blocks_and_ratios_need_a_known_site_area(tmp_path):
    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    with_area = board.select(tmp_path, ["mass-a"], hooks=SITE)
    text = board.expert_block(with_area)
    assert "36.0 m × 24.0 m × 5 floors" in text
    assert "Building footprint 864.0 m²" in text and "gross floor area 4,320.0 m²" in text
    assert "building coverage 86.4%, FAR 432.0%" in text  # 864 / 1000, 4320 / 1000
    assert "highest 21.0 m" in text

    no_site = board.select(tmp_path, ["mass-a"], hooks=[("site", SimpleNamespace(board_site=lambda p: None))])
    assert "Site area 미확인: coverage and FAR not computed" in board.expert_block(no_site)
    assert "%" not in board.expert_block(no_site)


def test_a_block_keeps_its_turn_from_the_rotate_tool_only_when_turned(tmp_path):
    blocks = [
        {"u": 0, "v": 0, "w": 10, "d": 10, "floors": 2},
        {"u": 20, "v": 0, "w": 10, "d": 10, "floors": 2, "a": 30},
        {"u": 40, "v": 0, "w": 10, "d": 10, "floors": 2, "a": 270},  # read as -90
        {"u": 60, "v": 0, "w": 10, "d": 10, "floors": 2, "a": 360},  # a full turn is no turn
    ]
    saved = board.add_paper(tmp_path, {**MASS, "id": "mass-a", "blocks": blocks})["paper"]["blocks"]
    assert ["a" in b for b in saved] == [False, True, True, False]
    assert saved[1]["a"] == 30 and saved[2]["a"] == -90
    text = board.expert_block(board.select(tmp_path, ["mass-a"], hooks=SITE))
    assert "at u 20.0, v 0.0, turned 30°" in text and "turned -90°" in text
    assert "u 0.0, v 0.0;" in text  # an unturned block says nothing of it
    with pytest.raises(ValueError, match="blocks\\[0\\].a must be"):
        board.add_paper(tmp_path, {**MASS, "id": "mass-b", "blocks": [{"w": 10, "d": 10, "floors": 2, "a": "left"}]})


def test_a_selection_is_checked_and_named(tmp_path):
    assert board.select(tmp_path, []) is None
    with pytest.raises(ValueError, match="unknown paper"):
        board.select(tmp_path, ["gone"])
    with pytest.raises(ValueError, match="at most 8"):
        board.select(tmp_path, [f"p{i}" for i in range(9)])
    board.add_paper(tmp_path, {"kind": "note", "id": "n1", "text": "북측 인접 대지 일조를 꼭 확인할 것 | 동지 기준"})
    selection = board.select(tmp_path, ["n1", "site", "n1"], hooks=SITE)
    assert [p["id"] for p in selection.papers] == ["n1", "site"]
    assert board.paper_name(selection.papers[0]) == "메모: 북측 인접 대지 일조를 꼭 확인할 것…"


def test_the_history_keeps_only_the_paper_names_and_a_screen_gets_them_back(tmp_path):
    board.add_paper(tmp_path, {**MASS, "id": "mass-a", "title": "안 A | 판상형"})
    selection = board.select(tmp_path, ["mass-a", "site"], hooks=SITE)
    stored = board.mark_text("두 안 비교해 줘", selection)
    assert stored == "두 안 비교해 줘\n\n[selected on the table] mass-a = 안 A / 판상형 | site = 대지"
    assert "4,320" not in stored  # the detail is sent for this turn only
    assert board.split_mark(stored) == (
        "두 안 비교해 줘", [{"id": "mass-a", "name": "안 A / 판상형"}, {"id": "site", "name": "대지"}]
    )
    assert board.split_mark("그냥 메시지") == ("그냥 메시지", [])
    assert board.mark_text("x", None) == "x"


@pytest.mark.parametrize(
    "conductor_cfg, mode",
    [
        ({"provider": "chatgpt"}, "full"),
        ({"provider": "openrouter"}, "full"),
        ({"provider": "ollama"}, "names"),
        ({"provider": "ollama", "board_context": "full"}, "full"),
        ({"provider": "chatgpt", "board_context": "names"}, "names"),
        ({"provider": "chatgpt", "board_context": "typo"}, "full"),
    ],
)
def test_how_much_the_conductor_gets_follows_what_it_runs_on(mock_config, conductor_cfg, mode):
    mock_config["conductor"].pop("board_context", None)
    mock_config["conductor"].update(conductor_cfg)
    assert board.context_mode(mock_config) == mode


# --- the engine: what the Conductor and the experts are sent -----------------------


@pytest.fixture
def table(project, monkeypatch):
    """A table with one massing scheme; the site domain reports a known area."""
    monkeypatch.setattr(board, "site_summary", lambda path, hooks=None: SITE[0][1].board_site(path))
    board.add_paper(project.path, {**MASS, "id": "mass-a"})
    board.add_paper(project.path, {"kind": "note", "id": "n1", "text": "북측 일조"})
    return project


def _texts(messages):
    return "\n".join(
        part["text"] if isinstance(part, dict) else str(part)
        for m in messages
        for part in (m["content"] if isinstance(m["content"], list) else [m["content"]])
    )


def test_a_cloud_conductor_gets_the_selected_papers_in_full_but_the_history_only_names(
    make_session, scripted, table, mock_config
):
    mock_config["conductor"]["board_context"] = "full"
    c = scripted(['두 안 모두 상한 안입니다.\n```action\n{"type":"none"}\n```'])
    s = make_session(c_provider=c)
    s.table = board.select(table.path, ["mass-a"])
    engine.converse(s, "안 A 어때?")

    sent = _texts(c.calls[0]["messages"])
    assert "DRAWING TABLE" in sent and "- n1 · note" in sent  # the index, for read_board
    assert "building coverage 86.4%, FAR 432.0%" in sent  # the selected paper in full
    assert s.history[0]["content"] == "안 A 어때?\n\n[selected on the table] mass-a = 안 A · 판상형"
    shown = engine.history_messages(s.history)
    assert shown[0] == {"role": "user", "text": "안 A 어때?", "context": [{"id": "mass-a", "name": "안 A · 판상형"}]}


def test_a_local_conductor_gets_only_the_names_and_the_expert_gets_the_detail(
    make_session, scripted, table, mock_config
):
    mock_config["conductor"]["board_context"] = "names"
    run = '비평가에게 보이겠습니다\n```action\n{"type":"run","agent":"design_critic"}\n```'
    c = scripted([run, '정리했습니다.\n```action\n{"type":"none"}\n```'])
    w = scripted(["## 결과\n- 북측 동이 높음"] * 3)
    s = make_session(c_provider=c, w_provider=w)
    s.table = board.select(table.path, ["mass-a"])
    engine.converse(s, "안 A 비평해 줘")

    for call in c.calls:
        assert "DRAWING TABLE" not in _texts(call["messages"])
        assert "4,320" not in _texts(call["messages"])
    assert "[selected on the table] mass-a = 안 A · 판상형" in _texts(c.calls[0]["messages"])
    expert_prompt = _texts(w.calls[0]["messages"])
    assert "DRAWING TABLE — papers the designer selected" in expert_prompt
    assert "gross floor area 4,320.0 m²" in expert_prompt


def test_without_a_saved_table_nothing_is_added(make_session, scripted, project, mock_config):
    mock_config["conductor"]["board_context"] = "full"
    c = scripted(['안녕하세요\n```action\n{"type":"none"}\n```'])
    s = make_session(c_provider=c)
    engine.converse(s, "안녕")
    assert "DRAWING TABLE" not in _texts(c.calls[0]["messages"])
    assert s.history[0]["content"] == "안녕"


def test_a_cloud_conductor_reads_a_paper_with_the_read_board_tool(make_session, table, mock_config, monkeypatch):
    monkeypatch.setattr(conductor, "_NO_TOOLS", set())
    mock_config["conductor"]["board_context"] = "full"

    class Tools:
        name = "tools"

        def __init__(self):
            self.calls = []
            self.replies = [("", [{"name": "read_board", "arguments": {"paper": "mass-a"}}]), ("안 A는 상한 안입니다.", [])]

        def chat_tools(self, model, messages, tools, temperature, max_tokens, **kw):
            self.calls.append({"messages": messages, "tools": [t["name"] for t in tools]})
            text, calls = self.replies.pop(0)
            return text, calls, {}

    c = Tools()
    s = make_session(c_provider=c)
    s.events = []
    s.emit = lambda kind, data: s.events.append((kind, data))
    turn = engine.converse(s, "안 A 어때?")  # no selection: the Conductor finds it by name
    assert turn.replies == ["안 A는 상한 안입니다."]
    assert "read_board" in c.calls[0]["tools"]
    assert "DRAWING TABLE PAPER mass-a" in _texts(c.calls[1]["messages"])
    assert "FAR 432.0%" in _texts(c.calls[1]["messages"])
    assert ("reading", {"file": "board/mass-a"}) in s.events


def test_a_local_conductor_has_no_read_board_tool(make_session, table, mock_config, monkeypatch):
    monkeypatch.setattr(conductor, "_NO_TOOLS", set())
    mock_config["conductor"]["board_context"] = "names"
    seen = []

    class Tools:
        name = "tools"

        def chat_tools(self, model, messages, tools, temperature, max_tokens, **kw):
            seen.append([t["name"] for t in tools])
            return "네.", [], {}

    engine.converse(make_session(c_provider=Tools()), "안녕")
    assert seen == [["run_expert", "read_expert_output"]]


# --- the AI section -------------------------------------------------------------


def test_the_conductor_proposes_into_the_ai_section_and_never_touches_the_table(tmp_path):
    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    copy = board.propose_paper(tmp_path, {
        "kind": "mass", "based_on": "mass-a", "reason": "북측 일조",
        "blocks": [{"w": 36, "d": 24, "floors": 4.0}],
    })
    assert copy["id"].startswith("ai-mass-") and copy["title"] == "안 A · 판상형 수정안"
    assert copy["origin"] == "conductor" and copy["based_on"] == "mass-a" and copy["blocks"][0]["floors"] == 4
    note = board.propose_paper(tmp_path, {"kind": "note", "text": "하역 동선 확인", "reason": "동선"})

    saved = board.load_board(tmp_path)
    assert [p["id"] for p in saved["papers"]] == ["site", "mass-a"]
    assert saved["papers"][1]["blocks"][0]["floors"] == 5  # the designer's scheme is unchanged
    assert [p["id"] for p in saved["tray"]] == [copy["id"], note["id"]]
    assert "(AI copy of mass-a) — why: 북측 일조" in board.paper_text(copy, None)

    for bad, message in [
        ({"kind": "tracing", "strokes": []}, "kind must be"),
        ({"kind": "mass", "based_on": "gone", "blocks": [{"w": 1, "d": 1, "floors": 1}]}, "unknown paper"),
        ({"kind": "note", "based_on": "mass-a"}, "based_on must be a note"),
        ({"kind": "mass", "blocks": []}, "1 to 20 blocks"),
    ]:
        with pytest.raises(ValueError, match=message):
            board.propose_paper(tmp_path, bad)
    assert len(board.load_board(tmp_path)["tray"]) == 2


def test_the_designer_moves_what_they_like_onto_the_table_and_throws_away_the_rest(tmp_path):
    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    keep = board.propose_paper(tmp_path, {**MASS, "reason": "대안"})
    drop = board.propose_paper(tmp_path, {"kind": "note", "text": "x", "reason": "y"})

    placed = board.place_paper(tmp_path, keep["id"], {"x": 80, "y": -5, "text": "ignored"})
    assert placed["paper"]["x"] == 80 and placed["paper"]["origin"] == "conductor"
    edited = board.update_paper(tmp_path, keep["id"], {"title": "안 C"})["paper"]
    assert edited["title"] == "안 C" and edited["origin"] == "conductor"  # still marked as AI-made
    assert board.discard_paper(tmp_path, drop["id"])["rev"] == placed["rev"] + 2

    saved = board.load_board(tmp_path)
    assert [p["id"] for p in saved["papers"]] == ["site", "mass-a", keep["id"]] and saved["tray"] == []
    with pytest.raises(board.PaperNotFound):
        board.place_paper(tmp_path, "mass-a")  # only papers in the AI section are placed
    with pytest.raises(board.PaperNotFound):
        board.discard_paper(tmp_path, drop["id"])


def test_the_ai_section_keeps_the_newest_papers(tmp_path):
    for i in range(board.MAX_TRAY + 3):
        board.propose_paper(tmp_path, {"kind": "note", "text": str(i), "reason": "r"})
    tray = board.load_board(tmp_path)["tray"]
    assert len(tray) == board.MAX_TRAY and tray[0]["text"] == "3"


def test_an_expert_result_waits_in_the_ai_section_only_for_projects_that_use_the_table(tmp_path):
    agent = {"id": "design_critic", "name": "설계 비평가"}
    assert board.expert_result(tmp_path, agent, "## 결과\n- a", []) is None
    assert not board.board_path(tmp_path).exists()

    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    first = board.expert_result(tmp_path, agent, "## 결과\n\n- 첫 번째", ["mass-a", "gone"])
    assert first["about"] == ["mass-a"] and first["text"] == "## 결과\n- 첫 번째"
    assert board.paper_name(first) == "설계 비평가 결과"
    second = board.expert_result(tmp_path, agent, "## 결과\n- 두 번째", [])
    assert [p["id"] for p in board.load_board(tmp_path)["tray"]] == [second["id"]]  # replaced

    board.place_paper(tmp_path, second["id"])
    with pytest.raises(ValueError, match="only moves"):
        board.update_paper(tmp_path, second["id"], {"text": "고침"})
    third = board.expert_result(tmp_path, agent, "## 결과\n- 세 번째", [])
    saved = board.load_board(tmp_path)
    assert second["id"] in [p["id"] for p in saved["papers"]] and saved["tray"] == [third]


def test_a_folded_paper_stays_folded_until_opened_and_site_papers_may_fold(tmp_path):
    note = board.add_paper(tmp_path, {"kind": "note", "text": "동선"})["paper"]
    assert "folded" not in note
    folded = board.update_paper(tmp_path, note["id"], {"folded": True})["paper"]
    assert folded["folded"] is True and folded["text"] == "동선"
    assert board.load_board(tmp_path)["papers"][-1]["folded"] is True
    opened = board.update_paper(tmp_path, note["id"], {"folded": False})["paper"]
    assert "folded" not in opened
    assert board.update_paper(tmp_path, "site", {"folded": True})["paper"]["folded"] is True
    with pytest.raises(ValueError, match="folded"):
        board.update_paper(tmp_path, note["id"], {"folded": "yes"})


def test_an_expert_result_paper_carries_the_korean_expert_name(tmp_path):
    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    paper = board.expert_result(tmp_path, {"id": "site_reader", "name": "Site Reader"}, "# Site Reader\n## Facts", [])
    assert paper["title"] == "대지 분석가"
    assert board.paper_name(paper) == "대지 분석가 결과"


def test_a_cloud_conductor_puts_a_scheme_in_the_ai_section(make_session, table, mock_config, monkeypatch):
    monkeypatch.setattr(conductor, "_NO_TOOLS", set())
    mock_config["conductor"]["board_context"] = "full"
    scheme = {"kind": "mass", "based_on": "mass-a", "reason": "높이 낮춤", "blocks": [{"w": 36, "d": 24, "floors": 4}]}

    class Tools:
        name = "tools"

        def __init__(self):
            self.calls = []
            self.replies = [
                ("", [{"name": "propose_paper", "arguments": scheme}]),
                ("", [{"name": "propose_paper", "arguments": {"kind": "tracing", "reason": "x"}}]),
                ("4층 수정안을 AI 섹션에 두었습니다.", []),
            ]

        def chat_tools(self, model, messages, tools, temperature, max_tokens, **kw):
            self.calls.append({"messages": messages, "tools": [t["name"] for t in tools]})
            text, calls = self.replies.pop(0)
            return text, calls, {}

    c = Tools()
    s = make_session(c_provider=c)
    s.events = []
    s.emit = lambda kind, data: s.events.append((kind, data))
    s.table = board.select(table.path, ["mass-a"])
    turn = engine.converse(s, "안 A 한 층 낮춰 봐")
    assert turn.replies == ["4층 수정안을 AI 섹션에 두었습니다."]
    assert "propose_paper" in c.calls[0]["tools"]
    added = [d["paper"] for k, d in s.events if k == "tray_added"]
    assert len(added) == 1 and added[0]["based_on"] == "mass-a"
    assert "gross floor area 3,456.0 m²" in _texts(c.calls[1]["messages"])  # the figures, told back
    assert [d["reason"] for k, d in s.events if k == "tray_failed"] == ["kind must be one of mass, note"]
    assert "The paper was refused" in _texts(c.calls[2]["messages"])
    saved = board.load_board(table.path)
    assert saved["papers"][1]["blocks"][0]["floors"] == 5 and len(saved["tray"]) == 1


def test_an_expert_run_lays_its_result_in_the_ai_section(make_session, scripted, table, mock_config):
    mock_config["state_update"]["mode"] = "off"
    w = scripted(["## 결과\n- 북측 동이 높음"] * 2)
    s = make_session(w_provider=w)
    s.events = []
    s.emit = lambda kind, data: s.events.append((kind, data))
    s.table = board.select(table.path, ["mass-a"])
    agent = next(a for a in s.agents if a["id"] == "design_critic")
    engine.run_expert(s, agent)
    paper = next(d["paper"] for k, d in s.events if k == "tray_added")
    assert paper["kind"] == "expert" and paper["agent"] == "design_critic" and paper["about"] == ["mass-a"]
    assert board.load_board(table.path)["tray"] == [paper]


# --- what the screen draws ----------------------------------------------------


def _rect(lon, lat, dlon, dlat):
    return [[lon, lat], [lon + dlon, lat], [lon + dlon, lat + dlat], [lon, lat + dlat], [lon, lat]]


def test_the_site_plan_is_in_metres_around_the_middle_and_blocks_follow_the_largest_parcel():
    big = {"pnu": "1", "address": "가", "area_m2": 900.0,
           "shape": {"type": "Polygon", "coordinates": [_rect(127.0, 37.0, 0.0004, 0.0002)]}}
    small = {"pnu": "2", "address": "나", "area_m2": None,
             "shape": {"type": "MultiPolygon", "coordinates": [[_rect(127.0004, 37.0, 0.0001, 0.0002)]]}}
    plan = board.site_plan([big, small, {"pnu": "3", "shape": None}, {"pnu": "4", "shape": {"type": "Point"}}])

    assert [p["pnu"] for p in plan["parcels"]] == ["1", "2"]  # parcels without a boundary are left out
    ring = plan["parcels"][0]["rings"][0]
    assert len(ring) == 4  # the closing point is dropped
    width = ring[1][0] - ring[0][0]
    assert width == pytest.approx(35.6, abs=0.2)  # 0.0004° of longitude at 37°N
    assert ring[2][1] - ring[1][1] == pytest.approx(22.3, abs=0.2)
    b = plan["bounds"]
    assert (b["min_x"] + b["max_x"]) / 2 == pytest.approx(0, abs=0.01)  # the site's middle is 0, 0
    frame = plan["frame"]
    assert frame["angle"] == pytest.approx(0, abs=1e-3)  # the long side runs east–west
    assert plan["origin"] == {"lon": pytest.approx(127.00025), "lat": pytest.approx(37.0001)}  # where 0, 0 lies
    assert frame["x"] == pytest.approx((ring[0][0] + ring[1][0]) / 2, abs=0.05)
    assert board.site_plan([]) is None and board.site_plan([{"shape": {"type": "Polygon", "coordinates": [[[1, 2]]]}}]) is None


def test_the_frame_angle_stays_within_a_quarter_turn():
    # A parcel whose longest edge runs west → east written backwards still faces east.
    ring = [[127.0004, 37.0002], [127.0, 37.0002], [127.0, 37.0], [127.0004, 37.0]]
    plan = board.site_plan([{"shape": {"type": "Polygon", "coordinates": [ring]}}])
    assert plan["frame"]["angle"] == pytest.approx(0, abs=1e-3)


def test_the_view_adds_the_site_and_each_schemes_figures(tmp_path):
    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    board.propose_paper(tmp_path, {"kind": "mass", "blocks": [{"w": 10, "d": 10, "floors": 2}], "reason": "작게"})
    hooks = [("site", SimpleNamespace(board_site=lambda path: {
        "area_m2": 1000.0, "lines": ["대지: 필지 1개"],
        "parcels": [{"pnu": "1", "shape": {"type": "Polygon", "coordinates": [_rect(127.0, 37.0, 0.0004, 0.0002)]}}],
    }))]
    got = board.view(tmp_path, hooks=hooks)
    assert got["rev"] == 2 and [p["id"] for p in got["papers"]] == ["site", "mass-a"]
    assert got["figures"]["mass-a"]["coverage_pct"] == 86.4
    tray_id = got["tray"][0]["id"]
    assert got["figures"][tray_id]["floor_area_m2"] == 200.0
    assert got["site"]["lines"] == ["대지: 필지 1개"] and len(got["site"]["plan"]["parcels"]) == 1
    assert board.load_board(tmp_path).keys() == {"rev", "papers", "tray", "pins", "ideas"}  # nothing derived is saved

    bare = board.view(tmp_path, hooks=[("site", SimpleNamespace(board_site=lambda path: None))])
    assert bare["site"] is None and bare["figures"]["mass-a"]["coverage_pct"] is None


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def test_a_photo_is_saved_as_a_file_next_to_the_table_and_its_paper_names_it(tmp_path):
    got = board.add_photo(tmp_path, JPEG, {"title": "대지 사진", "x": 30, "y": 5, "w": 300, "h": 200, "junk": 1})
    paper = got["paper"]
    assert got["rev"] == 1 and paper["kind"] == "photo" and paper["id"].startswith("photo-")
    assert paper["file"] == f"{paper['id']}.jpg" and "junk" not in paper and paper["h"] == 200
    path, media = board.photo_file(tmp_path, paper["id"])
    assert path.read_bytes() == JPEG and media == "image/jpeg"
    assert board.paper_name(paper) == "대지 사진"
    assert "image itself is not sent" in board.paper_text(paper, None)

    # It moves, folds and is renamed like other papers; its file never changes.
    moved = board.update_paper(tmp_path, paper["id"], {"x": 50, "title": "북측 전경", "file": "photo-00000000.png"})["paper"]
    assert moved["x"] == 50 and moved["title"] == "북측 전경" and moved["file"] == paper["file"]
    untitled = board.add_photo(tmp_path, PNG)["paper"]
    assert board.paper_name(untitled) == "사진" and untitled["file"].endswith(".png")


@pytest.mark.parametrize(
    "data, message",
    [
        (b"", "empty"),
        (b"%PDF-1.7 not a picture", "PNG, JPEG, GIF or WebP"),
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16, "PNG, JPEG, GIF or WebP"),  # an iPhone HEIC
        (JPEG + b"\x00" * board.MAX_PHOTO_BYTES, "at most 20 MB"),
    ],
)
def test_what_is_not_a_photo_the_browser_can_show_is_refused_and_nothing_is_saved(tmp_path, data, message):
    with pytest.raises(ValueError, match=message):
        board.add_photo(tmp_path, data)
    assert not board.board_path(tmp_path).exists() and not board.photo_dir(tmp_path).exists()


def test_a_photo_is_only_added_by_upload_but_an_undo_can_lay_a_removed_one_back(tmp_path):
    with pytest.raises(ValueError, match="uploading"):
        board.add_paper(tmp_path, {"kind": "photo", "file": "photo-00000000.jpg"})
    paper = board.add_photo(tmp_path, JPEG)["paper"]
    with pytest.raises(ValueError, match="already on the table"):
        board.add_paper(tmp_path, {**paper, "id": "other"})

    board.delete_paper(tmp_path, paper["id"])
    with pytest.raises(board.PaperNotFound):
        board.photo_file(tmp_path, paper["id"])
    assert (board.photo_dir(tmp_path) / paper["file"]).exists()  # kept for an undo
    back = board.add_paper(tmp_path, paper)["paper"]
    assert back == paper and board.photo_file(tmp_path, paper["id"])[0].read_bytes() == JPEG


def test_a_removed_photos_file_is_cleared_a_day_later(tmp_path):
    import os
    import time

    old = board.add_photo(tmp_path, JPEG)["paper"]
    fresh = board.add_photo(tmp_path, PNG)["paper"]
    kept = board.add_photo(tmp_path, PNG)["paper"]
    board.delete_paper(tmp_path, old["id"])
    board.delete_paper(tmp_path, fresh["id"])
    folder = board.photo_dir(tmp_path)
    day_ago = time.time() - board.ORPHAN_SECONDS - 60
    os.utime(folder / old["file"], (day_ago, day_ago))
    os.utime(folder / kept["file"], (day_ago, day_ago))  # still on the table: stays however old

    board.add_photo(tmp_path, PNG)
    assert not (folder / old["file"]).exists()
    assert (folder / fresh["file"]).exists() and (folder / kept["file"]).exists()


def test_a_hand_edited_photo_file_name_cannot_reach_outside_the_photo_folder(tmp_path):
    import json

    paper = board.add_photo(tmp_path, JPEG)["paper"]
    saved = json.loads(board.board_path(tmp_path).read_text(encoding="utf-8"))
    saved["papers"][-1]["file"] = "../board.json"
    board.board_path(tmp_path).write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(board.PaperNotFound):
        board.photo_file(tmp_path, paper["id"])
    with pytest.raises(board.PaperNotFound):
        board.photo_file(tmp_path, "site")


# --- the idea board -------------------------------------------------------------


def test_ideas_are_kept_in_the_designers_order_and_edited_one_by_one(tmp_path):
    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    first = board.add_idea(tmp_path, {"text": "  중정을 중심으로 동을 돌린다  ", "papers": ["mass-a"], "talk": "02"})
    idea = first["idea"]
    assert idea["id"].startswith("idea-") and idea["text"] == "중정을 중심으로 동을 돌린다"
    assert idea["papers"] == ["mass-a"] and idea["talk"] == "02" and idea["off"] is False and idea["created_at"]
    second = board.add_idea(tmp_path, {"text": "북측은 낮게"})["idea"]
    top = board.add_idea(tmp_path, {"text": "길에서 마당이 보이게", "at": 0})["idea"]
    assert [i["id"] for i in board.load_board(tmp_path)["ideas"]] == [top["id"], idea["id"], second["id"]]

    changed = board.update_idea(tmp_path, idea["id"], {"text": "중정 둘", "off": True, "id": "x", "created_at": "y"})
    assert changed["idea"]["id"] == idea["id"] and changed["idea"]["text"] == "중정 둘" and changed["idea"]["off"] is True
    assert changed["idea"]["created_at"] == idea["created_at"]
    ordered = board.order_ideas(tmp_path, [second["id"], idea["id"], top["id"]])
    assert [i["id"] for i in ordered["ideas"]] == [second["id"], idea["id"], top["id"]]
    assert board.delete_idea(tmp_path, top["id"])["rev"] == ordered["rev"] + 1
    assert [i["text"] for i in board.load_board(tmp_path)["ideas"]] == ["북측은 낮게", "중정 둘"]


@pytest.mark.parametrize(
    "data, message",
    [
        ({"text": "  "}, "needs text"),
        ({"text": "가" * 601}, "longer than"),
        ({"text": "x", "papers": ["nope"]}, "unknown paper"),
        ({"text": "x", "papers": "site"}, "list of paper ids"),
        ({"text": "x", "talk": "../01"}, "talk id"),
        ({"text": "x", "off": "yes"}, "true or false"),
        ({"text": "x", "at": "first"}, "whole number"),
    ],
)
def test_bad_ideas_are_refused_and_nothing_is_saved(tmp_path, data, message):
    with pytest.raises(ValueError, match=message):
        board.add_idea(tmp_path, data)
    assert not board.board_path(tmp_path).exists()


def test_reordering_must_name_every_idea_and_unknown_ideas_are_not_found(tmp_path):
    a = board.add_idea(tmp_path, {"text": "a"})["idea"]["id"]
    board.add_idea(tmp_path, {"text": "b"})
    with pytest.raises(ValueError, match="every idea"):
        board.order_ideas(tmp_path, [a])
    with pytest.raises(ValueError, match="every idea"):
        board.order_ideas(tmp_path, [a, a])
    with pytest.raises(board.IdeaNotFound):
        board.update_idea(tmp_path, "idea-nope", {"text": "x"})
    with pytest.raises(board.IdeaNotFound):
        board.delete_idea(tmp_path, "idea-nope")


def test_a_paper_taken_off_the_table_drops_out_of_the_ideas_it_was_linked_to(tmp_path):
    board.add_paper(tmp_path, {"kind": "note", "id": "n1", "text": "북측 일조"})
    idea = board.add_idea(tmp_path, {"text": "북측은 낮게", "papers": ["n1", "site"]})["idea"]
    board.delete_paper(tmp_path, "n1")
    assert board.load_board(tmp_path)["ideas"][0]["papers"] == ["site"]
    assert board.update_idea(tmp_path, idea["id"], {"off": True})["idea"]["papers"] == ["site"]


def test_the_ideas_block_lists_the_ideas_in_play_with_their_links(tmp_path):
    board.add_paper(tmp_path, {**MASS, "id": "mass-a"})
    board.add_idea(tmp_path, {"text": "중정을 중심으로\n동을 돌린다", "papers": ["mass-a"], "talk": "02"})
    aside = board.add_idea(tmp_path, {"text": "옥상 정원"})["idea"]
    board.add_idea(tmp_path, {"text": "북측은 낮게"})
    board.update_idea(tmp_path, aside["id"], {"off": True})
    text = board.ideas_block(board.load_board(tmp_path))
    assert "DESIGNER'S MAIN IDEAS" in text and "never add, rewrite, reorder or drop" in text
    assert '1. 중정을 중심으로\n   동을 돌린다 (linked: mass-a "안 A · 판상형", Conductor talk 02)' in text
    assert "2. 북측은 낮게" in text and "옥상 정원" not in text
    assert "(1 more set aside by the designer for now: do not apply them.)" in text
    board.update_idea(tmp_path, board.load_board(tmp_path)["ideas"][0]["id"], {"off": True})
    board.delete_idea(tmp_path, board.load_board(tmp_path)["ideas"][2]["id"])
    assert board.ideas_block(board.load_board(tmp_path)) == ""  # all set aside: nothing to say
    assert board.ideas_block(None) == ""


@pytest.mark.parametrize("mode", ["full", "names"])
def test_every_conductor_and_every_expert_reads_the_ideas_but_has_no_way_to_change_them(
    make_session, scripted, table, mock_config, mode
):
    mock_config["conductor"]["board_context"] = mode
    board.add_idea(table.path, {"text": "길에서 마당이 보이게"})
    run = '비평가에게 보이겠습니다\n```action\n{"type":"run","agent":"design_critic"}\n```'
    c = scripted([run, '정리했습니다.\n```action\n{"type":"none"}\n```'])
    w = scripted(["## 결과\n- 북측 동이 높음"] * 3)
    s = make_session(c_provider=c, w_provider=w)
    engine.converse(s, "비평해 줘")  # nothing selected on the table
    assert "1. 길에서 마당이 보이게" in _texts(c.calls[0]["messages"])
    assert ("DRAWING TABLE" in _texts(c.calls[0]["messages"])) == (mode == "full")
    assert "1. 길에서 마당이 보이게" in _texts(w.calls[0]["messages"])
    tools = [t["name"] for t in conductor.conductor_tools(s.agents, board=True)]
    assert not any("idea" in name for name in tools)
    assert [i["text"] for i in board.load_board(table.path)["ideas"]] == ["길에서 마당이 보이게"]


def test_the_context_view_shows_the_ideas_the_models_get(tmp_path, mock_config):
    mock_config["conductor"]["board_context"] = "names"
    board.add_idea(tmp_path, {"text": "북측은 낮게"})
    seen = board.context_view(tmp_path, mock_config, [])
    assert "1. 북측은 낮게" in seen["conductor"] and "1. 북측은 낮게" in seen["expert"]
