"""Shared fixtures: isolated settings, isolated projects dir, mock providers."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sida import conductor_context, hardware, i18n, providers, runtime, settings  # noqa: E402
from sida import config as sida_config  # noqa: E402
from sida import project as prj  # noqa: E402
from sida.experts.regulation import lawapi  # noqa: E402
from sida.experts.site import datago, landapi  # noqa: E402

REAL_HTTP_GET = landapi._http_get  # the autouse fixture below replaces it for every test
REAL_LAW_HTTP_GET = lawapi._http_get
LAW_FIXTURES = ROOT / "tests" / "fixtures" / "lawapi"
DATAGO_FIXTURES = ROOT / "tests" / "fixtures" / "datago"


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
def fake_datago(monkeypatch):
    """
    Serve recorded data.go.kr replies (금정동 689-14/15, 토지이음 for 일반공업지역 UQA320 and
    과밀억제권역 UBA100) as (status, raw bytes); records calls. `overrides[op]` replaces one
    operation's reply: (status, bytes), a fixture file name, or an exception.
    """
    calls: list[tuple[str, dict]] = []
    overrides: dict[str, object] = {}
    uses = {"단독주택": "house", "공장": "factory", "근린생활시설": "neighborhood", "업무시설": "office"}

    def read(name: str) -> tuple[int, bytes]:
        status = 403 if "badkey" in name else 200
        return status, (DATAGO_FIXTURES / name).read_bytes()

    def http_get(url, params):
        calls.append((url, dict(params)))
        op = url.rsplit("/", 1)[-1]
        if op in overrides:
            value = overrides[op]
            if isinstance(value, Exception):
                raise value
            return read(value) if isinstance(value, str) else value
        if op == "DTsearchLunCd":
            name = uses.get(params["landUseNm"])
            return read(f"lun_{name}.xml") if name else (200, EMPTY_EUM)
        if op == "DTarLandUseInfo":
            codes = params["ucodeList"].split(",")
            name = uses.get(params["landUseNm"])
            if "UQA320" not in codes or name not in {"house", "factory"}:
                return 200, EMPTY_EUM
            multi = "_multi" if "UBA100" in codes and name == "factory" else ""
            return read(f"arlanduse_{name}{multi}.xml")
        if op == "DTluLawInfo":
            codes = params["ucodeList"].split(",")
            if "UQA320" not in codes:
                return 200, EMPTY_EUM
            return read("lulaw_multi.xml" if "UBA100" in codes else "lulaw_UQA320.xml")
        if op == "getBrTitleInfo":
            lot = f"{int(params['bun'])}_{int(params['ji'])}"
            path = DATAGO_FIXTURES / f"brtitle_{lot}.json"
            return read(path.name if path.exists() else "brtitle_none.json")
        raise AssertionError(f"unexpected data.go.kr call: {url}")

    monkeypatch.setattr(datago, "_http_get", http_get)
    http_get.calls = calls
    http_get.overrides = overrides
    return http_get


EMPTY_EUM = (
    "<response><header><resultCode>0</resultCode><resultMsg>OK</resultMsg></header>"
    "<body><items></items><totalCount>0</totalCount></body></response>"
).encode("cp949")


@pytest.fixture
def fake_vworld(monkeypatch, fake_ordinance, fake_datago):
    """Serve recorded VWorld responses (금정동 689, address lists) instead of the network; records calls."""
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
        if op == "data":  # the data API: address lists, lot numbers and shapes, by layer and filter
            value = str(params.get("attrFilter") or "").rsplit(":", 1)[-1]
            geom = str(params.get("geomFilter") or "")
            if not value and geom.startswith("POINT("):  # a map click
                value = "at_" + "_".join(geom[6:-1].split())
            suffix = "_geom" if params.get("geometry") == "true" else ""
            path = LAND_FIXTURES / f"data_{params['data']}{'_' + value if value else ''}{suffix}.json"
            return land_fixture(path.name if path.exists() else "data_not_found.json")
        if op == "search":
            if "공단로" in params["query"]:  # a road-name address: no lot-number match, one road match
                road = params.get("category") == "road"
                return land_fixture("search_road_gongdan.json" if road else "search_not_found.json")
            if params.get("category") == "road":
                return land_fixture("search_not_found.json")
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
    landapi.clear_cache()
    monkeypatch.setattr(lawapi, "ENV_PATH", tmp_path / "no.env")
    monkeypatch.setenv("LAW_OPEN_API_OC", "test-oc")
    monkeypatch.setattr(lawapi, "_http_get", _no_network)
    monkeypatch.setattr(lawapi, "_http_get_bytes", lambda url: _no_network(url, {}))
    monkeypatch.setattr(datago, "ENV_PATH", tmp_path / "no.env")
    monkeypatch.setattr(settings, "ENV_PATH", tmp_path / "settings.env")  # the settings screen writes keys here
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "test-key")
    monkeypatch.setattr(datago, "_http_get", _no_network)
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
    from sida.engine import Session, load_existing_outputs

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
