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
