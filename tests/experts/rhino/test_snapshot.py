"""snapshot.py — the designer's Rhino model as the plugin sends it, checked, kept and measured."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sida import board
from sida.experts import FACTS, ExpertRun
from sida.experts.rhino import hooks, snapshot
from tests.conftest import ROOT

FIXTURE = ROOT / "tests" / "fixtures" / "rhino" / "snapshot_studio.json"
PNG = snapshot.PNG + b"\x00" * 16


def studio() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def views() -> dict[str, bytes]:
    return {"plan.png": PNG, "axo.png": PNG}


def test_a_snapshot_is_checked_and_only_what_sida_reads_is_kept():
    clean = snapshot.clean_snapshot(studio())
    assert clean["schema"] == 1 and clean["rhino"] == {"version": "8.12", "file": "studio.3dm", "units": "m"}
    assert clean["origin"] == {"lon": 126.978, "lat": 37.568, "matches_project": True}
    assert [x["meaning"] for x in clean["layers"]] == ["housing", "commercial", "surroundings", ""]
    assert clean["layers"][0]["floor_height"] == 3.0 and clean["layers"][2]["floor_height"] is None
    a1 = clean["objects"][0]
    assert a1["sida_id"] == "mass-a:0" and a1["mesh"]["f"][0] == [0, 1, 2, 3] and len(a1["floors"]) == 4
    assert clean["objects"][2]["volume"] is None and clean["objects"][4]["footprint"] is None
    assert clean["views"] == [{"kind": "plan", "file": "plan.png"}, {"kind": "axo", "file": "axo.png"}]


@pytest.mark.parametrize("change, reason", [
    (lambda s: s.update(schema=2), "schema must be 1"),
    (lambda s: s["rhino"].update(units="mm"), "units must be m"),
    (lambda s: s["objects"][0].update(volume=float("nan")), "volume must be a number"),
    (lambda s: s["objects"][0].update(footprint=[[0, 0], [1, 1]]), "at least 3 points"),
    (lambda s: s["objects"][1].update(id="a1"), "own id"),
    (lambda s: s["views"][0].update(file="../x.png"), "unique name like plan.png"),
    (lambda s: s["views"][0].update(kind="top"), "kind must be one of"),
    (lambda s: s["layers"][0].update(color="red"), "#rrggbb"),
], ids=["schema", "units", "nan", "outline", "dup-id", "view-file", "view-kind", "color"])
def test_what_is_malformed_is_refused_with_a_plain_reason(change, reason):
    raw = studio()
    change(raw)
    with pytest.raises(ValueError, match=reason):
        snapshot.clean_snapshot(raw)


def test_an_unknown_meaning_is_no_meaning_and_an_oversize_mesh_is_dropped_not_refused():
    raw = studio()
    raw["layers"][0]["meaning"] = "garage"
    raw["objects"][0]["mesh"] = {"v": [[0, 0, 0]] * (snapshot.MAX_MESH_VERTICES + 1), "f": [[0, 0, 0]]}
    raw["objects"][1]["mesh"] = {"v": [[0, 0, 0], [1, 0, 0]], "f": [[0, 1, 5]]}  # a face past the vertices
    clean = snapshot.clean_snapshot(raw)
    assert clean["layers"][0]["meaning"] == ""
    assert "mesh" not in clean["objects"][0] and clean["objects"][0]["mesh_dropped"] is True
    assert clean["objects"][1]["mesh_dropped"] is True


def test_figures_count_built_meanings_only_merge_overlapping_footprints_and_never_estimate():
    clean = snapshot.clean_snapshot(studio())
    fig = snapshot.figures(clean, 1000.0)
    # housing: 동 A (4 floors of 180) + the open one (no floors, no volume); shop: one floor of 180
    assert fig["floor_area_m2"] == 900.0
    assert fig["footprint_m2"] == 320.0  # 동 A and the shop overlap by 10 × 9 m: 270, plus the open one's 50
    assert fig["coverage_pct"] == 32.0 and fig["far_pct"] == 90.0 and fig["site_area_m2"] == 1000.0
    assert fig["volume_m3"] is None and fig["unmeasured"] == ["c1"]  # one open object: no total volume
    assert fig["height_m"] == 12.0 and fig["objects"] == 3 and fig["unassigned"] == 1  # the sketch layer
    assert [(p["meaning"], p["word"], p["floor_area_m2"], p["footprint_m2"], p["objects"]) for p in fig["by_meaning"]] == [
        ("housing", "주거", 720.0, 230.0, 2), ("commercial", "상업", 180.0, 180.0, 1),
    ]
    none = snapshot.figures(clean, None)
    assert none["coverage_pct"] is None and none["far_pct"] is None
    lines = snapshot.figure_lines(none)
    assert lines[0] == "연면적 900.0㎡ (주거 720.0, 상업 180.0)"
    assert lines[2] == "건폐율 미확인 · 용적률 미확인 (대지 면적 미확인)"
    assert "잴 수 없는 개체 1개 (닫히지 않은 도형)" in lines and "의미 없는 레이어의 개체 1개 (수치에서 제외)" in lines


def test_a_snapshot_without_built_objects_has_no_volume_and_no_areas():
    raw = studio()
    raw["objects"] = [raw["objects"][3]]  # only the surroundings
    fig = snapshot.figures(snapshot.clean_snapshot(raw), 500.0)
    assert fig["floor_area_m2"] == 0.0 and fig["footprint_m2"] == 0.0 and fig["volume_m3"] is None
    assert fig["by_meaning"] == [] and fig["coverage_pct"] == 0.0


def test_snapshots_are_kept_under_the_project_with_their_views_newest_first(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="plan.png was not sent"):
        snapshot.save_snapshot(tmp_path, studio(), {"axo.png": PNG})
    with pytest.raises(ValueError, match="must be a PNG"):
        snapshot.save_snapshot(tmp_path, studio(), {"plan.png": b"GIF89a", "axo.png": PNG})

    first = snapshot.save_snapshot(tmp_path, studio(), views())
    assert snapshot.SNAPSHOT_ID.fullmatch(first["id"]) and first["taken_at"]
    assert (tmp_path / "rhino" / "snapshots" / first["id"] / "views" / "plan.png").read_bytes() == PNG
    assert snapshot.load_snapshot(tmp_path, first["id"]) == first
    assert snapshot.view_file(tmp_path, first["id"], "axo.png").name == "axo.png"
    with pytest.raises(snapshot.SnapshotNotFound):
        snapshot.view_file(tmp_path, first["id"], "persp.png")
    with pytest.raises(snapshot.SnapshotNotFound):
        snapshot.load_snapshot(tmp_path, "../../etc")

    monkeypatch.setattr(snapshot, "MAX_SNAPSHOTS", 2)
    later = [snapshot.save_snapshot(tmp_path, studio(), views()) for _ in range(2)]
    listed = snapshot.list_snapshots(tmp_path)
    assert [s["id"] for s in listed] == sorted((s["id"] for s in later), reverse=True)  # the first was pruned
    assert listed[0]["file"] == "studio.3dm" and listed[0]["objects"] == 5 and listed[0]["layers"][0]["meaning"] == "housing"
    assert snapshot.latest_snapshot(tmp_path)["id"] == listed[0]["id"]
    snapshot.delete_snapshot(tmp_path, listed[0]["id"])
    assert [s["id"] for s in snapshot.list_snapshots(tmp_path)] == [listed[1]["id"]]
    assert snapshot.latest_snapshot(Path(tmp_path / "nowhere")) is None


def test_the_experts_get_the_newest_snapshots_figures_and_meanings_never_the_geometry(tmp_path, monkeypatch):
    run = ExpertRun(config={}, agent={"id": "program_analyst"}, project_dir=tmp_path, project_brief="", project_state=None,
                    previous_outputs="", warn=lambda m: None)
    assert hooks.prompt_blocks(run) == []
    snapshot.save_snapshot(tmp_path, studio(), views())
    monkeypatch.setattr(board, "site_summary", lambda path, hooks=None: {"area_m2": 1000.0})
    (block,) = hooks.prompt_blocks(run)
    assert block.slot == FACTS and block.text.startswith(snapshot.HEADER)
    assert "from studio.3dm (5 objects)" in block.text
    assert "- 건폐율 32.0% · 용적률 90.0%" in block.text
    assert "Program::Housing = 주거; Program::Shop = 상업; Context::Buildings = 주변 건물" in block.text
    assert "footprint" not in block.text.lower().replace("건축면적", "") and "[[" not in block.text


def test_the_limits_come_from_the_site_facts_as_they_stand(tmp_path, monkeypatch):
    from sida.experts.site import site_facts

    assert snapshot.limits(tmp_path) == []
    facts = {"summary": {"zoning": [{"zone": "제2종일반주거지역", "bcr_max": 60, "far_min": 100, "far_max": 250}]},
             "ordinance": {"values": {"제2종일반주거지역": {"bcr": {"value": 60}, "far": None}}}}
    monkeypatch.setattr(site_facts, "load_facts", lambda path: copy.deepcopy(facts))
    assert snapshot.limits(tmp_path) == [{
        "zone": "제2종일반주거지역", "bcr_max": 60, "far_min": 100, "far_max": 250, "ordinance_bcr": 60, "ordinance_far": None,
    }]
