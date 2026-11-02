import json

import pytest

from sida import talks
from sida.project import MAIN_TALK


def test_first_talk_is_the_project_history(project):
    assert talks.talk_ids(project.path) == [MAIN_TALK]
    project.save_history([{"role": "user", "content": "대지부터"}, {"role": "assistant", "content": "네"}])
    assert talks.talk_summaries(project.path)[0]["title"] == "대지부터"


def test_new_talks_are_numbered_and_stored_apart(project):
    assert talks.new_talk(project.path) == "02"
    assert talks.new_talk(project.path) == "03"
    assert talks.talk_ids(project.path) == ["01", "02", "03"]
    assert json.loads((project.path / "talks" / "03.json").read_text(encoding="utf-8")) == []

    project.talk = "02"
    project.save_history([{"role": "user", "content": "  긴  질문입니다 " * 10}])
    assert project.load_history() and (project.path / "talks" / "02.json").exists()
    project.talk = MAIN_TALK
    assert project.load_history() == []
    title = talks.talk_summaries(project.path)[1]["title"]
    assert title.startswith("긴 질문입니다 긴") and len(title) == talks.TITLE_CHARS


@pytest.mark.parametrize("talk_id", ["02", "1", "abc", "../01", ""])
def test_require_talk_refuses_unknown_ids(project, talk_id):
    with pytest.raises(LookupError):
        talks.require_talk(project.path, talk_id)


def test_delete_talk_preserves_other_data_and_does_not_reuse_ids(project):
    talks.new_talk(project.path)
    path = project.path / "talks" / "02.json"
    path.write_text('[{"role":"user","content":"지울 대화"}]', encoding="utf-8")
    brief = project.brief_path.read_bytes()
    talks.delete_talk(project.path, "02")
    assert not path.exists()
    assert json.loads((project.path / "talks" / ".deleted" / "02.json").read_text(encoding="utf-8")) == []
    assert talks.talk_ids(project.path) == ["01"]
    assert project.brief_path.read_bytes() == brief
    assert talks.new_talk(project.path) == "03"
    with pytest.raises(LookupError):
        talks.delete_talk(project.path, "02")


def test_first_talk_can_be_deleted_without_reappearing(project):
    project.save_history([{"role": "user", "content": "첫 대화"}])
    talks.delete_talk(project.path, "01")
    assert not project.history_path.exists()
    assert talks.talk_ids(project.path) == []
    assert talks.talk_summaries(project.path) == []
    with pytest.raises(LookupError):
        talks.require_talk(project.path, "01")
    assert talks.new_talk(project.path) == "02"


def test_delete_failure_leaves_the_conversation_visible(project, monkeypatch):
    from pathlib import Path

    from sida.errors import SidaError

    project.save_history([{"role": "user", "content": "남겨야 하는 대화"}])
    unlink = Path.unlink

    def locked(path, **kwargs):
        if path == project.history_path:
            raise PermissionError("locked")
        return unlink(path, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(SidaError):
        talks.delete_talk(project.path, "01")
    assert talks.talk_ids(project.path) == ["01"]
    assert project.load_history()[0]["content"] == "남겨야 하는 대화"
