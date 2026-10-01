"""Hub settings: YAML section patch + summary."""

from __future__ import annotations

from hub_settings import (
    save_config_patches,
    set_section_key,
    settings_one_liner,
    settings_summary,
)

SAMPLE = """\
provider: openrouter

conductor:
  # comment
  provider: openrouter
  local_profile: local          # 8GB
  model: anthropic/claude-haiku-4.5

worker:
  provider: openrouter
  model: openai/gpt-4o-mini

rag:
  enabled: false
  provider: http

state_update:
  mode: ask
  provider: worker
"""


def test_set_section_key_preserves_comment():
    out = set_section_key(SAMPLE, "conductor", "provider", "ollama")
    assert "  provider: ollama" in out
    assert "# comment" in out
    assert "local_profile: local          # 8GB" in out
    out2 = set_section_key(out, "conductor", "local_profile", "local_plus")
    assert "local_profile: local_plus # 8GB" in out2 or "local_profile: local_plus" in out2


def test_set_section_key_bool_and_insert(tmp_path):
    text = "rag:\n  provider: http\n"
    out = set_section_key(text, "rag", "enabled", True)
    assert "enabled: true" in out
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE, encoding="utf-8")
    save_config_patches(
        [
            ("conductor", "provider", "ollama"),
            ("worker", "provider", "ollama"),
            ("rag", "enabled", True),
            ("state_update", "mode", "off"),
        ],
        path=path,
    )
    saved = path.read_text(encoding="utf-8")
    assert "provider: ollama" in saved
    assert "enabled: true" in saved
    assert "mode: off" in saved


def test_summary_one_liner(mock_config):
    mock_config["conductor"]["provider"] = "ollama"
    mock_config["worker"]["provider"] = "ollama"
    mock_config["rag"] = {"enabled": True, "provider": "http"}
    one = settings_one_liner(mock_config)
    assert "ollama" in one and "rag:on" in one
    block = settings_summary(mock_config)
    assert "Conductor" in block or "conductor" in block.lower() or "ollama" in block


# --- config.local.yaml -------------------------------------------------------


def _answers(monkeypatch, *replies):
    queue = list(replies)

    def fake_input(_label=""):
        if not queue:
            raise AssertionError("unexpected prompt")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr("builtins.input", fake_input)


def _base(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


def test_save_config_patches_defaults_to_local_file_not_config_yaml():
    import harness
    from tests.conftest import ROOT

    tracked = (ROOT / "config.yaml").read_text(encoding="utf-8")
    written = save_config_patches([("rag", "enabled", True)])
    assert written == harness.LOCAL_CONFIG_PATH
    assert "enabled: true" in written.read_text(encoding="utf-8")
    assert (ROOT / "config.yaml").read_text(encoding="utf-8") == tracked
    cfg = harness.load_config()
    assert cfg["rag"]["enabled"] is True and cfg["rag"]["provider"] == "http"


def test_first_run_enter_picks_cloud_and_leaves_base_untouched(tmp_path, monkeypatch):
    import harness
    from hub_settings import choose_run_mode, current_run_mode

    base = _base(tmp_path)
    _answers(monkeypatch, "")
    assert choose_run_mode(config_path=base, first_run=True) == "cloud"
    assert base.read_text(encoding="utf-8") == SAMPLE
    assert (tmp_path / "config.local.yaml").exists()
    assert current_run_mode(harness.load_config(base)) == "cloud"


def test_run_mode_local_sets_both_roles_and_profile(tmp_path, monkeypatch):
    import harness
    from hub_settings import choose_run_mode, current_run_mode

    base = _base(tmp_path)
    base.write_text(
        SAMPLE + "\nlocal_profiles:\n  local:\n    model: a\n  local_plus:\n    model: b\n",
        encoding="utf-8",
    )
    _answers(monkeypatch, "2", "2")  # local, then profile local_plus
    assert choose_run_mode(config_path=base) == "local"
    cfg = harness.load_config(base)
    assert cfg["conductor"]["provider"] == "ollama"
    assert cfg["worker"]["provider"] == "ollama"
    assert cfg["conductor"]["local_profile"] == "local_plus"
    assert current_run_mode(cfg) == "local"

    _answers(monkeypatch, "1")  # switch back later
    assert choose_run_mode(config_path=base) == "cloud"
    assert current_run_mode(harness.load_config(base)) == "cloud"


def test_run_mode_cancel_writes_nothing(tmp_path, monkeypatch):
    from hub_settings import choose_run_mode

    base = _base(tmp_path)
    _answers(monkeypatch, KeyboardInterrupt())
    assert choose_run_mode(config_path=base, first_run=True) is None
    _answers(monkeypatch, "")  # Enter outside first run = cancel
    assert choose_run_mode(config_path=base) is None
    assert not (tmp_path / "config.local.yaml").exists()


def test_ensure_run_mode_asks_only_when_local_file_missing(tmp_path, monkeypatch):
    from hub_settings import ensure_run_mode

    base = _base(tmp_path)
    _answers(monkeypatch, "1")
    ensure_run_mode(config_path=base)
    assert (tmp_path / "config.local.yaml").exists()
    _answers(monkeypatch)  # any further prompt fails the test
    ensure_run_mode(config_path=base)


def test_settings_menu_writes_local_file_only(tmp_path, monkeypatch):
    import harness
    from hub_settings import hub_settings_menu

    base = _base(tmp_path)
    _answers(monkeypatch, "4", "y", "0")  # toggle RAG on, back
    cfg = hub_settings_menu(config_path=base)
    assert cfg["rag"]["enabled"] is True
    assert base.read_text(encoding="utf-8") == SAMPLE
    assert harness.load_config(base)["rag"]["enabled"] is True


def test_run_mode_preselects_profile_the_gpu_can_run(tmp_path, monkeypatch, capsys):
    import hardware
    import harness
    from hub_settings import choose_run_mode

    base = _base(tmp_path)
    base.write_text(
        SAMPLE + "\nlocal_profiles:\n  local:\n    model: a\n  local_plus:\n    model: b\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(hardware, "query_nvidia_smi", lambda: "RTX 5070 Ti, 16303\n")
    _answers(monkeypatch, "2", "")  # local, then Enter on the profile list = keep recommendation
    assert choose_run_mode(config_path=base) == "local"
    assert "RTX 5070 Ti" in capsys.readouterr().out
    # SAMPLE says local, but a 16GB card gets local_plus pre-selected.
    assert harness.load_config(base)["conductor"]["local_profile"] == "local_plus"


def test_run_mode_recommends_cloud_for_small_gpu(tmp_path, monkeypatch, capsys):
    import hardware
    from hub_settings import choose_run_mode

    monkeypatch.setattr(hardware, "query_nvidia_smi", lambda: "GTX 1650, 4096\n")
    _answers(monkeypatch, "")
    assert choose_run_mode(config_path=_base(tmp_path), first_run=True) == "cloud"
    out = capsys.readouterr().out
    assert "GTX 1650" in out and ("클라우드를 추천" in out or "cloud is recommended" in out)


def test_one_liner_flags_rag_on_without_url(mock_config, monkeypatch):
    monkeypatch.delenv("SIDA_RAG_URL", raising=False)
    mock_config["rag"] = {"enabled": True, "provider": "http"}
    assert "rag:on(no url)" in settings_one_liner(mock_config)
    monkeypatch.setenv("SIDA_RAG_URL", "https://vps.example")
    assert "rag:on(no url)" not in settings_one_liner(mock_config)
    mock_config["rag"] = {"enabled": False, "provider": "http"}
    assert "rag:off" in settings_one_liner(mock_config)
