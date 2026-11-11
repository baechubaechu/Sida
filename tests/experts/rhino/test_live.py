"""live.py — the running Rhino between the plugin (reports, asks what to do) and the panel page."""

from __future__ import annotations

import json

import pytest

from sida.experts.rhino import live
from tests.conftest import ROOT

FIXTURE = ROOT / "tests" / "fixtures" / "rhino" / "snapshot_studio.json"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    live.reset()
    clock = {"t": 100.0}
    monkeypatch.setattr(live, "_now", lambda: clock["t"])
    yield clock
    live.reset()


def said(**change) -> dict:
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snap["views"] = []
    return {"doc": "4242-1", "file": "studio.3dm", "units": "mm", "project": "무교동", "autosync": False, "snapshot": snap, **change}


def test_nothing_is_connected_until_a_plugin_reports_and_then_the_panel_reads_it(fresh):
    assert live.current() == {"connected": False, "rev": 0, "state": None}
    assert live.pending("4242-1") == {"known": False, "commands": []}  # the plugin asked first: Sida wants a report
    assert live.current()["state"] is None

    assert live.report(live.clean_report(said()), {"floor_area_m2": 900.0}, True) == {"rev": 1}
    got = live.current("4242-1")
    assert got["connected"] is True and got["rev"] == 1
    state = got["state"]
    assert (state["file"], state["units"], state["project"], state["project_known"], state["objects"]) == ("studio.3dm", "mm", "무교동", True, 5)
    assert state["figures"] == {"floor_area_m2": 900.0} and state["rhino"] == "8.12" and state["notice"] is None
    assert [(x["path"], x["meaning"], x["objects"]) for x in state["layers"]] == [
        ("Program::Housing", "housing", 2), ("Program::Shop", "commercial", 1), ("Context::Buildings", "surroundings", 1), ("Sketch", "", 1),
    ]
    assert "footprint" not in json.dumps(state) and "floors" not in json.dumps(state)  # the geometry itself is not kept
    assert live.current() == got  # no doc named: the one whose plugin asked last

    assert live.report(live.clean_report(said()), {"floor_area_m2": 900.0}, True) == {"rev": 1}  # nothing changed
    assert live.report(live.clean_report(said(autosync=True)), {"floor_area_m2": 900.0}, True) == {"rev": 2}

    fresh["t"] += live.CONNECTED_FOR + 1  # the plugin stopped asking (Rhino closed)
    assert live.current("4242-1")["connected"] is False and live.current("4242-1")["state"]["autosync"] is True
    live.pending("4242-1")
    assert live.current("4242-1")["connected"] is True


def test_what_the_panel_asks_waits_for_the_plugin_until_it_says_it_is_done():
    with pytest.raises(ValueError, match="no Rhino document"):
        live.ask({"doc": "4242-1", "type": "pull"})
    live.report(live.clean_report(said()), None, True)
    first = live.ask({"doc": "4242-1", "type": "set_layer", "path": "Sketch", "meaning": "office", "floor_height": 3.6})["id"]
    second = live.ask({"doc": "4242-1", "type": "push", "extra": "ignored"})["id"]
    assert second == first + 1
    waiting = live.pending("4242-1")
    assert waiting["known"] is True and waiting["commands"] == [
        {"type": "set_layer", "path": "Sketch", "meaning": "office", "floor_height": 3.6, "id": first},
        {"type": "push", "id": second},
    ]
    assert live.pending("4242-1", after=first)["commands"] == [{"type": "push", "id": second}]  # the first is done
    assert live.pending("4242-1", after=second)["commands"] == []
    assert live.ask({"doc": "4242-1", "type": "set_autosync", "on": True})["id"] == second + 1
    assert live.ask({"doc": "4242-1", "type": "set_project", "project": " 무교동 "})["id"] == second + 2
    assert [c.get("project", c.get("on")) for c in live.pending("4242-1", after=second)["commands"]] == [True, "무교동"]


@pytest.mark.parametrize("command, reason", [
    ({"type": "pull"}, "doc is needed"),
    ({"doc": "4242-1", "type": "explode"}, "type must be one of"),
    ({"doc": "4242-1", "type": "set_layer", "meaning": "housing"}, "path is needed"),
    ({"doc": "4242-1", "type": "set_layer", "path": "A", "meaning": "garage"}, "meaning must be one of"),
    ({"doc": "4242-1", "type": "set_layer", "path": "A", "meaning": "", "floor_height": 0}, "floor_height must be"),
    ({"doc": "4242-1", "type": "set_layer", "path": "A", "meaning": "", "floor_height": True}, "floor_height must be"),
], ids=["no-doc", "type", "no-path", "meaning", "height-zero", "height-bool"])
def test_a_command_the_plugin_could_not_do_is_refused_with_a_plain_reason(command, reason):
    live.report(live.clean_report(said()), None, True)
    with pytest.raises(ValueError, match=reason):
        live.ask(command)


def test_a_notice_from_the_plugin_is_shown_once_more_each_time_and_a_bad_report_is_refused():
    live.report(live.clean_report(said(notice={"text": "보냈습니다 (스냅샷 1)", "ok": True})), None, True)
    one = live.current()["state"]["notice"]
    assert (one["text"], one["ok"], one["n"]) == ("보냈습니다 (스냅샷 1)", True, 1) and one["at"]
    live.report(live.clean_report(said()), None, True)  # a plain report keeps the last notice
    assert live.current()["state"]["notice"]["n"] == 1
    assert live.report(live.clean_report(said(notice={"text": "보냈습니다 (스냅샷 1)", "ok": False})), None, True) == {"rev": 2}
    assert (live.current()["state"]["notice"]["n"], live.current()["state"]["notice"]["ok"]) == (2, False)

    with pytest.raises(ValueError, match="doc is needed"):
        live.clean_report(said(doc=""))
    with pytest.raises(ValueError, match="schema must be 1"):
        live.clean_report(said(snapshot={"schema": 9}))
    no_document = live.clean_report({"doc": "9-1", "project": "", "snapshot": None})
    assert live.report(no_document, None, False) == {"rev": 1}
    assert live.current("9-1")["state"]["layers"] == [] and live.current("9-1")["state"]["project_known"] is False


def test_only_a_few_documents_are_remembered_and_the_longest_silent_one_goes(fresh):
    for i in range(live.MAX_DOCS + 1):
        fresh["t"] += 1
        live.report(live.clean_report(said(doc=f"p-{i}")), None, True)
    assert live.current("p-0")["state"] is None and live.current("p-1")["state"] is not None
    assert live.current()["state"]["doc"] == f"p-{live.MAX_DOCS}"
