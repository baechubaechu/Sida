"""Revision bookkeeping is conservative and never becomes model instructions."""

from __future__ import annotations

import pytest

from sida.state_revisions import (
    content_revision,
    module_revisions,
    record_module_revision,
    without_revisions,
)


@pytest.mark.parametrize("data", ["broken", "[]", '{"site_reader": "bad-hash"}'])
def test_invalid_revision_records_are_untrusted(data):
    assert module_revisions(f"# state\n\n<!-- sida-module-revisions: {data} -->\n") == {}


def test_updating_one_revision_preserves_other_accepted_revisions():
    state = record_module_revision("# state\n", "site_reader", "site v1")
    state = record_module_revision(state, "program_analyst", "program v1")
    state = record_module_revision(state, "site_reader", "site v2")
    assert module_revisions(state) == {
        "site_reader": content_revision("site v2"),
        "program_analyst": content_revision("program v1"),
    }
    assert state.count("<!-- sida-module-revisions:") == 1
    assert without_revisions(state) == "# state\n"


def test_revision_records_are_hidden_from_model_context_and_diff(mock_config, agents, project):
    from sida.harness import prepare_conductor_context
    from sida.state_updater import state_diff

    original = project.read_state()
    tracked = record_module_revision(original, "site_reader", "analysis")
    project.state_path.write_text(tracked, encoding="utf-8")
    state, _, _, _ = prepare_conductor_context(
        mock_config, agents, project.modules_dir, [], [], tracked,
        state_path=project.state_path,
    )
    assert "sida-module-revisions" not in state
    assert state_diff(original, tracked) == ""
