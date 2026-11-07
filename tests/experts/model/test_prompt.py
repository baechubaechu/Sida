"""The site model's facts for the representation planner: Sida's own numbers for each board."""

from __future__ import annotations

from sida.experts import FACTS, ExpertRun
from sida.experts.model import hooks, prompt
from sida.experts.site import context_range, terrain_pack
from tests.experts.site.test_context3d import pack, plan_for_site  # noqa: F401  (pack is a fixture)


def run_for(agent_id: str, project_dir) -> ExpertRun:
    return ExpertRun(config={}, agent={"id": agent_id}, project_dir=project_dir, project_brief="", project_state=None,
                     previous_outputs="", warn=lambda message: None)


def test_the_planner_reads_the_fitted_scale_layers_and_sheets_for_each_board(pack, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(terrain_pack, "TERRAIN_DIR", pack)
    monkeypatch.setattr(prompt, "_site_plan", lambda project_dir: (plan_for_site(), 400.0))
    assert hooks.prompt_blocks(run_for("representation_planner", tmp_path)) == []  # no 3D range saved yet
    context_range.save(tmp_path, "medium", "square")
    (block,) = hooks.prompt_blocks(run_for("representation_planner", tmp_path))
    assert block.slot == FACTS and block.text.startswith(prompt.HEADER)
    assert "- Site: 400 m², 20 × 20 m" in block.text
    assert "- 3D range loaded: medium square, 400 × 400 m" in block.text
    rows = prompt.options(plan_for_site(), {"radius": 200.0, "shape": "square", "orient": "landscape"})
    woodlock = next(r for r in rows if r["board"] == "W600x900" and r["thickness"] == 3)
    assert (woodlock["scale"], woodlock["frame_m"], woodlock["interval_m"]) == (400, [360.0, 240.0], 1.2)
    assert woodlock["layers"] == woodlock["ground_sheets"] and woodlock["layers"] >= 7  # 10–20 m of ground
    line = f"| W600x900 | 우드락 600×900 | {woodlock['orient']} | 3 | 1:400 | 360 × 240 | 1.2 | {woodlock['layers']} |"
    assert line in block.text
    assert len(rows) == 10 and all(r["fits"] for r in rows)  # five boards, 3 and 5 mm
    assert hooks.prompt_blocks(run_for("site_reader", tmp_path)) == []  # the other experts get nothing


def test_without_a_site_the_planner_gets_no_numbers_and_without_ground_it_is_told(tmp_path, monkeypatch):
    context_range.save(tmp_path, "large", "rect")
    assert hooks.prompt_blocks(run_for("representation_planner", tmp_path)) == []  # no site looked up
    monkeypatch.setattr(prompt, "_site_plan", lambda project_dir: (plan_for_site(), None))
    (block,) = hooks.prompt_blocks(run_for("representation_planner", tmp_path))  # conftest's empty TERRAIN_DIR
    assert "no terrain pack covers this site" in block.text and "| W600x900" not in block.text
