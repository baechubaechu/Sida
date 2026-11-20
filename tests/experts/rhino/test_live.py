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
    drawn = live.ask({"doc": "4242-1", "type": "draw", "kinds": ["site", "program", "site"]})["id"]
    assert live.pending("4242-1", after=drawn - 1)["commands"] == [{"type": "draw", "kinds": ["program", "site"], "id": drawn}]
    # 자동 조경 in the curve picked: the style, and whether to shuffle (anything but true is no)
    laid = live.ask({"doc": "4242-1", "type": "landscape", "style": "natural", "shuffle": "yes"})["id"]
    assert live.pending("4242-1", after=laid - 1)["commands"] == [{"type": "landscape", "style": "natural", "shuffle": False, "id": laid}]


def test_the_plugin_says_what_it_is_in_the_middle_of_so_the_panel_can_wait_for_it():
    live.report(live.clean_report(said()), None, True)
    assert live.current()["state"]["busy"] == ""
    assert live.report(live.clean_report(said(busy="pull")), None, True) == {"rev": 2}  # a long first pull: the panel shows it
    assert live.current()["state"]["busy"] == "pull"
    live.report(live.clean_report(said(busy="landscape")), None, True)
    assert live.current()["state"]["busy"] == "landscape"
    assert live.clean_report(said(busy="reticulating"))["busy"] == ""  # only what the panel has words for


@pytest.mark.parametrize("command, reason", [
    ({"type": "pull"}, "doc is needed"),
    ({"doc": "4242-1", "type": "explode"}, "type must be one of"),
    ({"doc": "4242-1", "type": "set_layer", "meaning": "housing"}, "path is needed"),
    ({"doc": "4242-1", "type": "set_layer", "path": "A", "meaning": "garage"}, "meaning must be one of"),
    ({"doc": "4242-1", "type": "set_layer", "path": "A", "meaning": "", "floor_height": 0}, "floor_height must be"),
    ({"doc": "4242-1", "type": "set_layer", "path": "A", "meaning": "", "floor_height": True}, "floor_height must be"),
    ({"doc": "4242-1", "type": "draw"}, "kinds must be a list of"),
    ({"doc": "4242-1", "type": "draw", "kinds": ["program", "render"]}, "kinds must be a list of"),
    ({"doc": "4242-1", "type": "landscape", "style": "baroque"}, "style must be one of"),
], ids=["no-doc", "type", "no-path", "meaning", "height-zero", "height-bool", "no-kinds", "kind", "landscape-style"])
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


def test_the_selection_in_rhino_reaches_the_panel_and_the_conductor_only_while_rhino_is_connected(fresh, tmp_path):
    from sida.experts.rhino import snapshot

    checked = live.clean_report(said(selected=["a1", "c1", "nothing-measured"], selected_count=7))
    assert checked["selected"] == ["a1", "c1", "nothing-measured"] and checked["selected_count"] == 7
    assert live.clean_report(said())["selected"] == [] and live.clean_report(said(selected=["a1"], selected_count="x"))["selected_count"] == 1
    with pytest.raises(ValueError, match="selected"):
        live.clean_report(said(selected="a1"))
    with pytest.raises(ValueError, match="selected"):
        live.clean_report(said(selected=["x"] * (snapshot.MAX_SELECTED + 1)))

    picked = snapshot.selection(checked["snapshot"], checked["selected"], checked["selected_count"])
    here, there = tmp_path / "here", tmp_path / "there"
    live.report(checked, {"floor_area_m2": 900.0}, True, selection=picked, path=here, brief="RHINO NOW")
    state = live.current("4242-1")["state"]
    assert state["selection"] == {key: picked[key] for key in ("count", "bodies", "floor_area_m2", "footprint_m2")}
    assert "lines" not in state["selection"]  # the panel shows the count; the lines are for the Conductor
    assert live.brief_for(here) == "RHINO NOW" and live.brief_for(there) == ""

    # a second Rhino on the same project, reporting later, is the one the Conductor hears about
    fresh["t"] += 1
    live.report(live.clean_report(said(doc="4242-2")), {"floor_area_m2": 900.0}, True, path=here, brief="THE OTHER RHINO")
    assert live.brief_for(here) == "THE OTHER RHINO"
    assert live.current("4242-2")["state"]["selection"] is None

    fresh["t"] += live.CONNECTED_FOR + 1  # both stopped asking: the Conductor is told nothing stale
    assert live.brief_for(here) == ""
    live.pending("4242-1")
    assert live.brief_for(here) == "RHINO NOW"


# --- the active view as a picture, for a message to the Conductor ---

PNG = b"\x89PNG\r\n\x1a\n" + b"view"


def plugin(doc: str, *, answer=PNG, title="Perspective"):
    """A plugin beside Sida: asks what to do until it is told `view`, then sends its picture."""
    import threading
    import time

    seen: list[dict] = []

    def work():
        for _ in range(400):
            commands = live.pending(doc)["commands"]
            if commands:
                seen.extend(commands)
                seen.append(live.give_view(doc, commands[0]["id"], answer, title))
                return
            time.sleep(0.005)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread, seen


def test_a_message_gets_the_view_of_the_rhino_open_on_its_project(tmp_path):
    here, there = tmp_path / "here", tmp_path / "there"
    assert live.want_view(here, wait=0) is None  # no Rhino at all
    live.report(live.clean_report(said()), {"floor_area_m2": 900.0}, True, path=here, brief="RHINO NOW")
    assert live.want_view(there, wait=0) is None and live.pending("4242-1")["commands"] == []  # another project's Rhino is not asked

    thread, seen = plugin("4242-1")
    got = live.want_view(here, wait=5)
    thread.join(5)
    assert got == {"data": PNG, "title": "Perspective", "file": "studio.3dm", "brief": "RHINO NOW"}
    assert seen[0]["type"] == "view" and seen[1] == {"taken": True}
    assert live.pending("4242-1")["commands"] == []  # done with: the plugin is not asked again

    # the picture is handed over once: a second one for the same command, or one nobody asked for, is not kept
    assert live.give_view("4242-1", seen[0]["id"], PNG) == {"taken": False}
    assert live.give_view("nobody", 1, PNG) == {"taken": False}
    with pytest.raises(ValueError, match="type must be one of"):
        live.ask({"doc": "4242-1", "type": "view"})  # the panel cannot ask for one


def test_no_view_comes_when_rhino_is_busy_or_gone_and_what_is_not_a_picture_is_refused(fresh, tmp_path):
    live.report(live.clean_report(said()), {"floor_area_m2": 900.0}, True, path=tmp_path, brief="RHINO NOW")
    assert live.want_view(tmp_path, wait=0.01) is None  # the plugin did not answer in time
    assert live.pending("4242-1")["commands"] == []  # and is not left with a command that is of no use now

    with pytest.raises(ValueError, match="PNG or JPEG"):
        live.give_view("4242-1", 1, b"<html>")
    with pytest.raises(ValueError, match="title"):
        live.give_view("4242-1", 1, PNG, "x" * 81)
    with pytest.raises(ValueError, match="doc"):
        live.give_view("", 1, PNG)

    fresh["t"] += live.CONNECTED_FOR + 1  # Rhino stopped asking
    assert live.want_view(tmp_path, wait=0) is None


def test_the_rhino_domain_gives_the_view_to_the_conductor_with_what_the_document_said(tmp_path):
    from sida import views
    from sida.experts.rhino import hooks

    assert hooks.conductor_views(tmp_path) == []  # no Rhino: nothing, and no waiting
    live.report(live.clean_report(said()), {"floor_area_m2": 900.0}, True, path=tmp_path.resolve(), brief="## Rhino right now\nFAR 210%")
    thread, _seen = plugin("4242-1")
    asked = views.ask(tmp_path, [("rhino", hooks)])
    thread.join(5)
    assert asked == [{
        "data": PNG, "media_type": "image/png",
        "about": 'the Rhino viewport "Perspective" of the document studio.3dm as the designer sees it now (a screen capture, not to scale).',
        "facts": "## Rhino right now\nFAR 210%",
    }]
