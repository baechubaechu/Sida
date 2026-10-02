"""Shared fixtures: isolated settings, isolated projects dir, mock providers."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sida import hardware, harness, i18n  # noqa: E402
from sida import project as prj  # noqa: E402
from sida.experts.regulation import lawapi  # noqa: E402
from sida.experts.site import landapi  # noqa: E402

REAL_HTTP_GET = landapi._http_get  # the autouse fixture below replaces it for every test
REAL_LAW_HTTP_GET = lawapi._http_get
LAW_FIXTURES = ROOT / "tests" / "fixtures" / "lawapi"


def _no_network(url, params):
    raise AssertionError(f"unexpected network call in a test: {url}")


LAND_FIXTURES = ROOT / "tests" / "fixtures" / "landapi"


def land_fixture(name: str):
    import json

    return json.loads((LAND_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fake_vworld(monkeypatch):
    """Serve recorded VWorld responses (금정동 689) instead of the network; records calls."""
    calls: list[tuple[str, dict]] = []
    overrides: dict[str, object] = {}

    def http_get(url, params):
        calls.append((url, dict(params)))
        op = url.rsplit("/", 1)[-1]
        if op in overrides:
            value = overrides[op]
            if isinstance(value, Exception):
                raise value
            return value
        if op == "search":
            return land_fixture("search_geumjeong_689.json")
        path = LAND_FIXTURES / f"{op}_{params['pnu']}.json"
        if path.exists():
            return land_fixture(path.name)
        return land_fixture("getLandUseAttr_unknown_pnu.json")

    monkeypatch.setattr(landapi, "_http_get", http_get)
    http_get.calls = calls
    http_get.overrides = overrides
    return http_get


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Never touch ~/Sida/settings.json or config.local.yaml during tests. Default language: ko."""
    monkeypatch.setattr(harness, "LOCAL_CONFIG_PATH", tmp_path / "config.local.yaml")
    # No real land-API calls or keys: tests pass fixtures through landapi._http_get.
    monkeypatch.setattr(landapi, "ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("VWORLD_API_KEY", "test-key")
    monkeypatch.setenv("VWORLD_DOMAIN", "http://localhost:8765")
    monkeypatch.setattr(landapi, "_http_get", _no_network)
    monkeypatch.setattr(lawapi, "ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("LAW_OPEN_API_OC", "test-oc")
    monkeypatch.setattr(lawapi, "_http_get", _no_network)
    lawapi.clear_cache()
    # No real nvidia-smi calls: tests that need a GPU patch query_nvidia_smi themselves.
    monkeypatch.setattr(hardware, "query_nvidia_smi", lambda: None)
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
def conductor_prompt(mock_config):
    template = (ROOT / "agents" / "00_conductor.md").read_text(encoding="utf-8")
    return harness.render_conductor_prompt(template, mock_config)


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
    from sida.session import Session, load_existing_outputs

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
