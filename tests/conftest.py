"""Shared fixtures: isolated settings, isolated projects dir, mock providers."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import harness  # noqa: E402
import i18n  # noqa: E402
import project as prj  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Never touch ~/Sida/settings.json during tests. Default language: ko."""
    settings_dir = tmp_path / "settings"
    monkeypatch.setattr(i18n, "SETTINGS_DIR", settings_dir)
    monkeypatch.setattr(i18n, "SETTINGS_PATH", settings_dir / "settings.json")
    monkeypatch.setattr(i18n, "_OLD_SETTINGS_PATH", settings_dir / "old.json")
    yield


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Real config.yaml with providers switched to mock and projects_dir in tmp."""
    cfg = copy.deepcopy(harness.load_config(ROOT / "config.yaml"))
    cfg["projects_dir"] = str(tmp_path / "projects")
    cfg["conductor"]["provider"] = "mock"
    cfg["worker"]["provider"] = "mock"
    monkeypatch.setattr(harness, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(prj, "load_config", lambda *a, **k: cfg)
    return cfg


@pytest.fixture
def agents(mock_config):
    return mock_config["agents"]


@pytest.fixture
def project(mock_config):
    return prj.create_project_from_brief(ROOT / "input" / "geumjeong_station_brief.md", config=mock_config)


@pytest.fixture
def conductor_prompt():
    return (ROOT / "agents" / "00_conductor.md").read_text(encoding="utf-8")


class ScriptedProvider:
    """Returns queued replies in order; records calls."""

    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, model, messages, temperature, max_tokens, **kw):
        self.calls.append({"model": model, "messages": messages, "kw": kw})
        if not self.replies:
            raise harness.LLMError("script exhausted")
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {"prompt_tokens": 10, "completion_tokens": 5}


@pytest.fixture
def scripted():
    return ScriptedProvider


@pytest.fixture
def make_session(mock_config, agents, project, conductor_prompt):
    """Build a Session with mock/scripted providers, no network."""
    from session import Session, load_existing_outputs

    def _make(c_provider=None, w_provider=None, history=None):
        return Session(
            api_key="",
            config=mock_config,
            agents=agents,
            conductor_prompt=conductor_prompt,
            project=project,
            project_brief=project.read_brief(),
            previous_blocks=load_existing_outputs(agents, project.modules_dir),
            history=list(history or []),
            c_provider=c_provider or harness.MockProvider(),
            w_provider=w_provider or harness.MockProvider(),
            created=True,
        )

    return _make
