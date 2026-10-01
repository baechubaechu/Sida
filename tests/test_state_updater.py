from __future__ import annotations

from harness import LLMError, MockProvider
from project import module_status_rows
from state_updater import (
    StatePatch,
    apply_patch,
    build_state_update_messages,
    parse_state_patch,
    propose_state_patch,
    replace_section_bullets,
    state_diff,
    state_update_settings,
    update_meta_line,
    update_module_row,
)
from tests.conftest import ROOT

TEMPLATE = (ROOT / "templates" / "project_state.md").read_text(encoding="utf-8").replace(
    "{{MODULE_ROWS}}",
    module_status_rows([{"id": "site_reader"}, {"id": "constraint_mapper"}, {"id": "design_critic"}]),
)


def test_settings_defaults_and_validation(mock_config):
    s = state_update_settings(mock_config)
    assert s["mode"] == "ask" and s["provider"] == "worker"
    mock_config["state_update"] = {"mode": "bogus", "provider": "nope"}
    s = state_update_settings(mock_config)
    assert s["mode"] == "ask" and s["provider"] == "worker"


def test_parse_patch_tolerant():
    raw = 'Sure!\n```json\n{"module_status":{"status":"DONE","key_takeaway":"  two   spaces "},' \
          '"meta":{"phase":"concept","active_focus":"x"},' \
          '"sections":{"open_questions":["- a","a","b"],"Module Status":["ignored"],"Nope":["z"]}}\n```'
    p = parse_state_patch(raw, "site_reader")
    assert p.status == "done" and p.key_takeaway == "two spaces"
    assert p.meta == {"phase": "concept", "active_focus": "x"}
    assert p.sections == {"Open Questions": ["a", "b"]}  # dedup, canonical heading, unknown dropped


def test_parse_patch_garbage_gives_status_only():
    p = parse_state_patch("not json", "x")
    assert p.status == "done" and p.is_empty()
    p = parse_state_patch("[1,2]", "x")
    assert p.is_empty()
    p = parse_state_patch('{"module_status":{"status":"weird"}}', "x")
    assert p.status == "done"


def test_caps_enforced():
    p = parse_state_patch('{"sections":{"Next Focus":["1","2","3","4","5"]}}', "x")
    assert p.sections["Next Focus"] == ["1", "2", "3"]


def test_replace_section_bullets_keeps_comment():
    new = replace_section_bullets(TEMPLATE, "Open Questions", ["q1 — why — blocks"])
    assert (
        "## Open Questions\n\n<!-- Each line: question — why it matters — what it blocks -->\n\n"
        "- q1 — why — blocks\n\n## Tensions"
    ) in new
    # idempotent: same bullets again -> identical text (no blank-line drift)
    assert replace_section_bullets(new, "Open Questions", ["q1 — why — blocks"]) == new
    # neighbouring sections untouched
    assert "## Tensions\n\n<!-- A vs B" in new
    # empty list -> placeholder dash
    assert "\n-\n" in replace_section_bullets(TEMPLATE, "Tensions", [])


def test_update_module_row_and_meta():
    new = update_module_row(TEMPLATE, "site_reader", "done", "takeaway | with pipe")
    assert "| site_reader | done | takeaway / with pipe |" in new
    assert "| constraint_mapper | pending | |" in new
    new = update_module_row(new, "new_agent", "done", "x")
    assert "| new_agent | done | x |" in new
    new = update_meta_line(new, "Last updated", "2026-09-04")
    assert "- **Last updated**: 2026-09-04" in new
    assert update_meta_line(new, "Nonexistent", "v") == new


def test_apply_patch_full():
    patch = StatePatch(
        module_id="site_reader",
        status="done",
        key_takeaway="복잡한 레벨 차",
        meta={"phase": "site_reading"},
        sections={"Recent Notes": ["[2026-09-04] site_reader 완료"], "Missing Information": ["지형 측량"]},
    )
    out = apply_patch(TEMPLATE, patch, today="2026-09-04")
    assert "| site_reader | done | 복잡한 레벨 차 |" in out
    assert "- **Phase**: site_reading" in out
    assert "- **Last updated**: 2026-09-04" in out
    assert "- [2026-09-04] site_reader 완료" in out
    assert "- 지형 측량" in out
    assert "## Core Problem" in out and "## Next Focus" in out
    diff = state_diff(TEMPLATE, out)
    assert "+| site_reader | done" in diff


def test_build_messages_truncates_and_labels():
    msgs = build_state_update_messages("STATE", "site_reader", "Site Reader", "x" * 20000, lang="ko")
    assert msgs[0]["role"] == "system" and "Korean" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "MODULE ID: site_reader" in user and "[... truncated ...]" in user


def test_propose_with_mock(mock_config, agents, project):
    (project.modules_dir / "11_site_reader.md").write_text("# out\n\n## Site Conditions\n- a", encoding="utf-8")
    patch, proposed = propose_state_patch(mock_config, "", project, agents[0], w_provider=MockProvider(), lang="ko")
    assert patch.status == "done" and patch.key_takeaway == "(mock) takeaway"
    assert "| site_reader | done | (mock) takeaway |" in proposed
    assert "(mock) site_reader completed" in proposed
    # state file itself untouched until write_state
    assert "(mock)" not in project.read_state()


def test_propose_requires_module_output(mock_config, agents, project):
    import pytest

    with pytest.raises(LLMError):
        propose_state_patch(mock_config, "", project, agents[0], w_provider=MockProvider())


def test_propose_uses_conductor_provider_when_configured(mock_config, agents, project, scripted):
    mock_config["state_update"] = {"provider": "conductor"}
    (project.modules_dir / "11_site_reader.md").write_text("x", encoding="utf-8")
    c = scripted(['{"module_status":{"status":"done","key_takeaway":"via conductor"}}'])
    w = scripted([])
    patch, _ = propose_state_patch(mock_config, "", project, agents[0], c_provider=c, w_provider=w)
    assert patch.key_takeaway == "via conductor"
    assert len(c.calls) == 1 and c.calls[0]["kw"].get("json_mode") is True and w.calls == []
