"""Failed saves must leave the previous complete file available."""

from __future__ import annotations

import os
from functools import partial
from pathlib import Path

import pytest

from sida import errors, providers, worker
from sida.state_updater import write_state


@pytest.mark.parametrize("operation", ["history", "session", "brief", "state", "module"])
def test_failed_project_save_preserves_previous_file(
    operation, project, mock_config, agents, monkeypatch
):
    if operation == "history":
        project.save_history([{"role": "user", "content": "원래 대화"}])
        target = project.history_path
        save = partial(project.save_history, [{"role": "user", "content": "새 대화"}])
    elif operation == "session":
        target = project.session_path
        save = partial(project.save_session, history_messages=99)
    elif operation == "brief":
        target = project.brief_path
        save = partial(project.update_brief_sections, {"Core Problem": "새 문제"})
    elif operation == "state":
        target = project.state_path
        save = partial(write_state, project, "# 새 상태\n")
    else:
        target = project.modules_dir / agents[0]["output"]
        target.write_text("# 이전 분석\n", encoding="utf-8")
        save = partial(
            worker.run_worker_agent,
            "", mock_config, agents[0], project.read_brief(), [], project.modules_dir,
            provider=providers.MockProvider(), notify=lambda _: None,
        )
    before = target.read_bytes()
    replace = os.replace

    def reject_target(source, destination):
        if Path(destination) == target:
            raise PermissionError("simulated locked destination")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", reject_target)
    with pytest.raises(errors.SidaError, match="simulated locked destination"):
        save()
    assert target.read_bytes() == before
    assert not list(target.parent.glob(".*.tmp"))


@pytest.mark.parametrize("operation", ["brief", "state", "module"])
def test_backup_failure_prevents_overwrite(operation, project, mock_config, agents, monkeypatch):
    if operation == "brief":
        target = project.brief_path
        save = partial(project.update_brief_sections, {"Core Problem": "changed"})
    elif operation == "state":
        target = project.state_path
        save = partial(write_state, project, "changed")
    else:
        target = project.modules_dir / agents[0]["output"]
        target.write_text("previous output", encoding="utf-8")
        save = partial(
            worker.run_worker_agent,
            "", mock_config, agents[0], project.read_brief(), [], project.modules_dir,
            provider=providers.MockProvider(), notify=lambda _: None,
        )
    before = target.read_bytes()
    replace = os.replace

    def reject_backup(source, destination):
        if Path(destination) != target:
            raise OSError("backup disk failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", reject_backup)
    with pytest.raises(errors.SidaError, match="backup disk failure"):
        save()
    assert target.read_bytes() == before
    assert not list(project.path.rglob(".*.tmp"))


@pytest.mark.parametrize("failure", ["flush", "replace"])
@pytest.mark.parametrize("existing", [False, True])
def test_atomic_write_failure_never_exposes_partial_content(tmp_path, monkeypatch, failure, existing):
    from sida.storage import atomic_write_text

    target = tmp_path / "history.json"
    if existing:
        target.write_bytes(b"old content")

    def broken(*_args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "fsync" if failure == "flush" else "replace", broken)
    with pytest.raises(errors.SidaError, match="simulated disk failure"):
        atomic_write_text(target, "새 내용\n" * 1000)
    if existing:
        assert target.read_bytes() == b"old content"
    else:
        assert not target.exists()
    assert list(tmp_path.iterdir()) == ([target] if existing else [])


def test_atomic_write_publishes_complete_utf8_file(tmp_path, monkeypatch):
    from sida.storage import atomic_write_text

    target = tmp_path / "brief.md"
    target.write_bytes(b"old")
    replace = os.replace
    seen = []

    def check_replace(source, destination):
        source = Path(source)
        assert source.parent == target.parent
        assert target.read_bytes() == b"old"
        assert source.read_bytes() == "새 브리프\n둘째 줄\n".encode()
        seen.append(destination)
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", check_replace)
    atomic_write_text(target, "새 브리프\n둘째 줄\n")
    assert seen == [target]
    assert target.read_bytes() == "새 브리프\n둘째 줄\n".encode()
    assert list(tmp_path.iterdir()) == [target]
