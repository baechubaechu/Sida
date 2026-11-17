"""views.py — pictures the designer shows the Conductor with a message: asked of the domains, kept
in the project, named in the stored message, and the newest given back for the talk's later messages."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sida import views

PNG = b"\x89PNG\r\n\x1a\n" + b"picture"
JPEG = b"\xff\xd8\xff" + b"picture"


def hooks(*gives):
    return [(f"d{i}", SimpleNamespace(conductor_views=give)) for i, give in enumerate(gives)]


def test_a_picture_is_what_its_bytes_say_and_no_larger_than_may_be_sent(monkeypatch):
    assert views.media_type(PNG) == "image/png" and views.media_type(JPEG) == "image/jpeg"
    assert views.media_type(b"GIF89a") is None and views.media_type(b"") is None and views.media_type("text") is None
    monkeypatch.setattr(views, "MAX_BYTES", 10)
    assert views.media_type(PNG) is None


def test_asking_takes_only_pictures_and_a_domain_that_fails_stops_nothing(tmp_path):
    def broken(_path):
        raise RuntimeError("no Rhino")

    asked = views.ask(tmp_path, hooks(
        broken,
        lambda _p: [{"data": PNG, "media_type": "text/html", "about": "the  Rhino\nview", "facts": " FAR 210% "},
                    {"data": b"<html>", "about": "not a picture"}, "nonsense"],
        lambda _p: None,
        lambda _p: [{"data": JPEG}, {"data": PNG, "about": "a third"}],
    ) + [("plain", SimpleNamespace())])
    assert asked == [{"data": PNG, "media_type": "image/png", "about": "the Rhino view", "facts": "FAR 210%"},
                     {"data": JPEG, "media_type": "image/jpeg", "about": "", "facts": ""}]  # at most MAX_VIEWS


def test_kept_pictures_are_named_in_the_message_and_the_newest_come_back(tmp_path):
    first = views.keep(tmp_path, [{"data": PNG, "media_type": "image/png", "about": "plan", "facts": "FAR 210%"}])
    second = views.keep(tmp_path, [{"data": JPEG, "media_type": "image/jpeg", "about": "perspective", "facts": ""},
                                   {"data": PNG, "media_type": "image/png", "about": "plan again", "facts": ""}])
    files = [v["file"] for v in second]
    assert files[0].endswith("-0.jpg") and files[1].endswith("-1.png") and first[0]["file"] not in files
    assert views.path_of(tmp_path, first[0]["file"]).read_bytes() == PNG
    kept = views.record(tmp_path, first[0]["file"])
    assert kept == {"file": first[0]["file"], "about": "plan", "facts": "FAR 210%", "at": kept["at"]} and kept["at"]

    asked = views.mark("이 매스 어때?\n\n[selected on the table] n1 = 메모", files)
    assert views.split(asked) == ("이 매스 어때?\n\n[selected on the table] n1 = 메모", files)
    assert views.mark("그냥 질문", []) == "그냥 질문" and views.split("그냥 질문") == ("그냥 질문", [])
    # a line the designer typed that only looks like the mark stays in the message
    typed = "보여 줘\n\n[pictures shown] ../../secret.png"
    assert views.split(typed) == (typed, [])

    history = [
        {"role": "user", "content": views.mark("처음", [first[0]["file"]])},
        {"role": "assistant", "content": "답"},
        {"role": "user", "content": asked},
        {"role": "assistant", "content": "답"},
        {"role": "user", "content": "그림 없는 다음 질문"},
    ]
    latest = views.latest(tmp_path, history)
    assert [(v["file"], v["media_type"], v["about"], v["data"]) for v in latest] == [
        (files[0], "image/jpeg", "perspective", JPEG), (files[1], "image/png", "plan again", PNG)]
    assert views.files_in(history) == [first[0]["file"], *files]
    assert views.latest(tmp_path, history[-1:]) == []


def test_a_picture_that_is_gone_is_not_sent_and_names_outside_the_folder_are_refused(tmp_path):
    file = views.keep(tmp_path, [{"data": PNG, "media_type": "image/png", "about": "plan", "facts": ""}])[0]["file"]
    history = [{"role": "user", "content": views.mark("질문", [file])}]
    views.forget(tmp_path, [file, "../../board.json"])
    assert views.latest(tmp_path, history) == [] and list((tmp_path / views.DIR).iterdir()) == []
    assert views.record(tmp_path, file) == {"file": file, "about": "", "facts": "", "at": ""}
    (tmp_path / "board.json").write_text("{}", encoding="utf-8")
    for name in ("../board.json", "board.json", file, "20261117-101502-000000-0.gif"):
        with pytest.raises(LookupError):
            views.path_of(tmp_path, name)


def test_the_record_beside_a_picture_is_plain_json(tmp_path):
    file = views.keep(tmp_path, [{"data": PNG, "media_type": "image/png", "about": "plan", "facts": "연면적 1,200㎡"}])[0]["file"]
    data = json.loads((tmp_path / views.DIR / file).with_suffix(".json").read_text(encoding="utf-8"))
    assert data["about"] == "plan" and data["facts"] == "연면적 1,200㎡"
