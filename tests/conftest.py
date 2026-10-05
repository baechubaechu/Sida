"""Shared fixtures: isolated settings, isolated projects dir, mock providers."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sida import conductor_context, hardware, i18n, providers, runtime  # noqa: E402
from sida import config as sida_config  # noqa: E402
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
def fake_ordinance(monkeypatch):
    """Serve recorded law.go.kr ordinance responses (군포시, 서울특별시, 고성군); records calls."""
    calls: list[dict] = []
    overrides: dict[str, object] = {}
    searches = {"군포시": "gunpo", "서울특별시": "seoul", "고성군": "goseong"}

    previous = lawapi._http_get  # another fixture's fake, or the network block

    def http_get(url, params):
        if params.get("target") != "ordin":
            return previous(url, params)
        calls.append(dict(params))
        op = "body" if "MST" in params else "search"
        if op in overrides:
            value = overrides[op]
            if isinstance(value, list):  # a queue of replies, one per call
                value = value.pop(0) if len(value) > 1 else value[0]
            if isinstance(value, Exception):
                raise value
            return value
        if op == "body":
            return (LAW_FIXTURES / f"ordin_body_gunpo_{params['MST']}.json").read_text(encoding="utf-8")
        name = searches.get(params["query"].split()[0])
        if name is None:
            return '{"OrdinSearch": {"totalCnt": "0", "resultCode": "00"}}'
        return (LAW_FIXTURES / f"ordin_search_{name}.json").read_text(encoding="utf-8")

    monkeypatch.setattr(lawapi, "_http_get", http_get)
    http_get.calls = calls
    http_get.overrides = overrides
    return http_get


@pytest.fixture
def fake_vworld(monkeypatch, fake_ordinance):
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
    monkeypatch.setattr(sida_config, "LOCAL_CONFIG_PATH", tmp_path / "config.local.yaml")
    # Guard: if this ever stops redirecting, tests would write this machine's real settings.
    assert sida_config.local_config_path() != ROOT / "config.local.yaml"
    # No real land-API calls or keys: tests pass fixtures through landapi._http_get.
    monkeypatch.setattr(landapi, "ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("VWORLD_API_KEY", "test-key")
    monkeypatch.setenv("VWORLD_DOMAIN", "http://localhost:8765")
    monkeypatch.setattr(landapi, "_http_get", _no_network)
    monkeypatch.setattr(lawapi, "ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("LAW_OPEN_API_OC", "test-oc")
    monkeypatch.setattr(lawapi, "_http_get", _no_network)
    monkeypatch.setattr(lawapi, "_http_get_bytes", lambda url: _no_network(url, {}))
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
    cfg = copy.deepcopy(sida_config.load_config(ROOT / "config.yaml"))
    cfg["projects_dir"] = str(tmp_path / "projects")
    cfg["conductor"]["provider"] = "mock"
    cfg["worker"]["provider"] = "mock"
    # every module that calls load_config by its own name gets the mock config
    for module in (sida_config, runtime, prj):
        monkeypatch.setattr(module, "load_config", lambda *a, **k: cfg)
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
    return conductor_context.render_conductor_prompt(template, mock_config)


class ScriptedProvider:
    """Returns queued replies in order; records calls."""

    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, model, messages, temperature, max_tokens, **kw):
        self.calls.append({"model": model, "messages": messages, "kw": kw})
        if not self.replies:
            raise providers.LLMError("script exhausted")
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
            c_provider=c_provider or providers.MockProvider(),
            w_provider=w_provider or providers.MockProvider(),
            created=True,
        )

    return _make
