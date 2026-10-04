"""UI-independent document editing preserves backups and detects stale edits."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("kind", ["brief", "state"])
def test_edit_document_backups_and_preserves_custom_markdown(project, kind):
    from sida.project_documents import read_document, save_document

    original = read_document(project, kind)
    changed = original.content + "\n## 사용자 작성 항목\n- 직접 작성한 내용\n"
    saved = save_document(project, kind, changed, expected_revision=original.revision)
    assert "## 사용자 작성 항목" in saved.content
    assert saved.revision != original.revision
    backup = project.path / ("brief.prev.md" if kind == "brief" else "project_state.prev.md")
    assert backup.read_text(encoding="utf-8") == original.content


@pytest.mark.parametrize("kind", ["brief", "state"])
def test_stale_document_edit_cannot_overwrite_newer_content(project, kind):
    from sida.project_documents import DocumentConflict, read_document, save_document

    original = read_document(project, kind)
    latest = save_document(project, kind, "newer content", expected_revision=original.revision)
    backup = project.path / ("brief.prev.md" if kind == "brief" else "project_state.prev.md")
    before_backup = backup.read_bytes()
    with pytest.raises(DocumentConflict):
        save_document(project, kind, "stale content", expected_revision=original.revision)
    assert read_document(project, kind) == latest
    assert backup.read_bytes() == before_backup


def test_editable_documents_reject_arbitrary_paths(project):
    from sida.project_documents import read_document, save_document

    with pytest.raises(ValueError):
        read_document(project, "../session.json")
    with pytest.raises(ValueError):
        save_document(project, "history", "x", expected_revision="x")


def test_no_change_does_not_replace_backup(project):
    from sida.project_documents import read_document, save_document

    original = read_document(project, "brief")
    backup = project.path / "brief.prev.md"
    assert save_document(
        project, "brief", original.content, expected_revision=original.revision
    ) == original
    assert not backup.exists()


def test_state_editor_preserves_internal_revisions_without_exposing_them(project):
    from sida.project_documents import read_document, save_document
    from sida.state_revisions import module_revisions, record_module_revision

    state = record_module_revision(project.read_state(), "site_reader", "accepted analysis")
    project.state_path.write_text(state, encoding="utf-8")
    document = read_document(project, "state")
    assert "sida-module-revisions" not in document.content
    save_document(
        project, "state", document.content + "\n## 추가 항목\n- 검토\n",
        expected_revision=document.revision,
    )
    assert module_revisions(project.read_state()) == module_revisions(state)
