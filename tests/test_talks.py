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
