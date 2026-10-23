from __future__ import annotations

from sida import i18n


def test_default_language_is_korean():
    assert i18n.get_language() == "ko"
    assert i18n.t("worker_name_site_reader") == "대지 분석가"


def test_english_switch_and_fallback(monkeypatch):
    i18n.set_language("en")
    assert i18n.t("worker_name_site_reader") == "Site Reader"
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


def test_agent_look_unique_colors():
    from sida.console import AGENT_LOOK, agent_look

    colors = [c for _, c in AGENT_LOOK.values()]
    assert len(colors) == len(set(colors))
    assert agent_look("site_reader") == ("SR", "cyan")
    assert agent_look("design_critic")[0] == "DC"


def test_paint_respects_no_color(monkeypatch):
    from sida.console import paint

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert paint("hi", "cyan", bold=True) == "hi"


def test_paint_force_color(monkeypatch):
    from sida.console import paint

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    out = paint("hi", "cyan")
    assert out.startswith("\033[") and out.endswith("\033[0m") and "hi" in out


def test_agent_name_is_korean_on_screen_and_english_in_config():
    agent = {"id": "site_reader", "name": "Site Reader"}
    assert i18n.agent_name(agent) == "대지 분석가"
    i18n.set_language("en")
    assert i18n.agent_name(agent) == "Site Reader"
    i18n.set_language("ko")
    # unknown ids fall back to the config name, then the id
    assert i18n.agent_name({"id": "new_expert", "name": "New Expert"}) == "New Expert"
    assert i18n.agent_name({"id": "new_expert"}) == "new_expert"
