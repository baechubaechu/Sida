from __future__ import annotations

import sys
from pathlib import Path

import pytest

import i18n
from console import one_line, open_in_editor, resolve_editor

FAKE_EDITOR = Path(__file__).parent / "_fixtures" / "fake_editor.py"


def test_default_language_is_korean():
    assert i18n.get_language() == "ko"
    assert i18n.t("hub_title") == "프로젝트 허브"


def test_english_switch_and_fallback(monkeypatch):
    i18n.set_language("en")
    assert i18n.t("hub_title") == "Project hub"
    # missing key in en -> key itself
    assert i18n.t("no_such_key") == "no_such_key"
    # missing key in ko falls back to en
    i18n.set_language("ko")
    monkeypatch.setitem(i18n.STRINGS["en"], "only_en", "EN ONLY")
    assert i18n.t("only_en") == "EN ONLY"


def test_every_english_key_has_korean():
    missing = sorted(set(i18n.STRINGS["en"]) - set(i18n.STRINGS["ko"]))
    assert missing == []


def test_format_placeholders_match():
    import re

    for key, en in i18n.STRINGS["en"].items():
        ko = i18n.STRINGS["ko"][key]
        assert set(re.findall(r"{(\w+)}", en)) == set(re.findall(r"{(\w+)}", ko)), key


def test_resolve_editor_precedence(monkeypatch):
    monkeypatch.setenv("EDITOR", "vim -u NONE")
    monkeypatch.setenv("VISUAL", "code --wait")
    monkeypatch.delenv("SIDA_EDITOR", raising=False)
    assert resolve_editor()[0] == "code"
    monkeypatch.setenv("SIDA_EDITOR", "nano")
    assert resolve_editor() == ["nano"]


def test_open_in_editor_detects_change(tmp_path, monkeypatch):
    target = tmp_path / "f.md"
    target.write_text("a", encoding="utf-8")
    argv = [sys.executable, str(FAKE_EDITOR), "b"]
    changed, name = open_in_editor(target, editor=argv)
    assert changed and target.read_text(encoding="utf-8") == "ab"
    changed, _ = open_in_editor(target, editor=[sys.executable, str(FAKE_EDITOR), ""])
    assert not changed


def test_open_in_editor_missing_binary_raises(tmp_path):
    with pytest.raises(RuntimeError):
        open_in_editor(tmp_path / "x.md", editor=["no-such-editor-binary-xyz"])


def test_one_line():
    assert one_line("a\n b   c") == "a b c"
    assert one_line("x" * 100, limit=10).endswith("…")


def test_agent_look_unique_colors():
    from console import AGENT_LOOK, agent_look

    colors = [c for _, c in AGENT_LOOK.values()]
    assert len(colors) == len(set(colors))
    assert agent_look("site_reader") == ("SR", "cyan")
    assert agent_look("design_critic")[0] == "DC"


def test_paint_respects_no_color(monkeypatch):
    from console import paint

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert paint("hi", "cyan", bold=True) == "hi"


def test_paint_force_color(monkeypatch):
    from console import paint

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    out = paint("hi", "cyan")
    assert out.startswith("\033[") and out.endswith("\033[0m") and "hi" in out
