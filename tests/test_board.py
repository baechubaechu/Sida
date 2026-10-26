"""board.py — the drawing table: saved papers, and what the Conductor and experts are told."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sida import board, conductor, engine

MASS = {"kind": "mass", "title": "안 A · 판상형", "blocks": [{"u": 0, "v": 0, "w": 36, "d": 24, "floors": 5}]}
SITE = [("site", SimpleNamespace(board_site=lambda path: {"area_m2": 1000.0, "lines": ["대지: 필지 2개"]}))]


def test_a_new_table_holds_only_the_site_and_papers_are_saved_one_by_one(tmp_path):
    assert board.load_board(tmp_path) == {"rev": 0, "papers": [board._site_paper()], "pins": []}
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
