from __future__ import annotations

import i18n
from hub_about import format_about_text, worker_label


def test_format_about_lists_workers(mock_config):
    i18n.set_language("ko")
    text = format_about_text(mock_config)
    assert "[SR]" in text
    assert "[RC]" in text
    assert "사이트" in text or "지리" in text


def test_worker_label_follows_language(agents):
    i18n.set_language("ko")
    name, desc = worker_label(agents[0])  # site_reader
    assert "사이트" in name or "리더" in name
    assert "지리" in desc or "공간" in desc
    i18n.set_language("en")
    name_en, desc_en = worker_label(agents[0])
    assert "Site" in name_en
    assert "Geographic" in desc_en or "spatial" in desc_en.lower()


def test_hub_about_returns_to_menu(mock_config, monkeypatch):
    import hub

    called = {"n": 0}

    def fake_about(cfg):
        called["n"] += 1

    monkeypatch.setattr(hub, "load_config", lambda *a, **k: mock_config)
    monkeypatch.setattr(hub, "show_hub_about", fake_about)
    it = iter(["h", "q"])
    monkeypatch.setattr("builtins.input", lambda *_: next(it))
    assert hub.project_hub() is None
    assert called["n"] == 1
