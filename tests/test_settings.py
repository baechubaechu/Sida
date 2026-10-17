"""settings.py / settings_api.py — the web settings screen's JSON API."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from sida import config as sida_config
from sida import hardware, settings, webapp

ROOT = sida_config.ROOT


@pytest.fixture
def client():
    # Real config.yaml; config.local.yaml and .env point at tmp (conftest isolated_settings).
    return TestClient(webapp.create_app(allowed_hosts={"testserver"}))


@pytest.fixture
def env_keys(monkeypatch):
    """Start every key empty; monkeypatch puts the real environment back after the test."""
    for spec in settings.KEYS.values():
        monkeypatch.setenv(spec["env"], "")


def test_tests_never_touch_this_machines_files():
    assert settings.ENV_PATH != ROOT / ".env"
    assert sida_config.local_config_path() != ROOT / "config.local.yaml"


def test_first_run_shows_team_defaults(client, env_keys):
    body = client.get("/api/settings").json()
    assert body["first_run"] is True
    assert body["mode"] == "cloud"
    assert body["conductor"]["provider"] == body["worker"]["provider"] == "openrouter"
    assert body["options"]["modes"] == ["cloud", "local"]
    assert body["options"]["local_profiles"] == ["local", "local_plus"]
    assert body["options"]["state_update"] == ["ask", "auto", "off"]
    assert body["keys"]["openrouter"] == {"env": "OPENROUTER_API_KEY", "set": False, "hint": ""}
    assert body["warnings"]["openrouter_key_missing"] is True
    assert body["gpu"] is None


def test_put_local_mode_writes_only_config_local(client):
    team = (ROOT / "config.yaml").read_bytes()
    r = client.put("/api/settings", json={"mode": "local", "local_profile": "local_plus"})
    assert r.status_code == 200
    body = r.json()
    assert body["first_run"] is False
    assert body["mode"] == "local" and body["local_profile"] == "local_plus"
    assert body["conductor"]["model"] == "qwen3.5:9b"  # the profile's model
    text = sida_config.local_config_path().read_text(encoding="utf-8")
    assert "provider: ollama" in text and "local_profile: local_plus" in text
    assert (ROOT / "config.yaml").read_bytes() == team


def test_put_changes_only_the_fields_given(client):
    client.put("/api/settings", json={"mode": "local"})
    body = client.put("/api/settings", json={"worker_provider": "openrouter", "rag_enabled": True}).json()
    assert body["mode"] == "custom"
    assert body["conductor"]["provider"] == "ollama" and body["worker"]["provider"] == "openrouter"
    assert body["rag_enabled"] is True
    assert body["state_update"] == "ask"
    body = client.put("/api/settings", json={"state_update": "auto"}).json()
    assert body["state_update"] == "auto" and body["rag_enabled"] is True


def test_put_empty_body_finishes_first_run(client):
    assert client.put("/api/settings", json={}).json()["first_run"] is False
    assert sida_config.local_config_path().exists()


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "hybrid"},
        {"local_profile": "huge"},
        {"conductor_provider": "mock"},
        {"state_update": "sometimes"},
    ],
)
def test_put_rejects_a_bad_value_and_writes_nothing(client, change):
    r = client.put("/api/settings", json={"mode": "local", **change})
    assert r.status_code == 400
    assert not sida_config.local_config_path().exists()


def test_put_rejects_unknown_fields(client):
    assert client.put("/api/settings", json={"language": "en"}).status_code == 422


def test_gpu_and_recommended_profile(client, monkeypatch):
    monkeypatch.setattr(hardware, "query_nvidia_smi", lambda: "RTX 5070 Ti, 16303\n")
    gpu = client.get("/api/settings").json()["gpu"]
    assert gpu["name"] == "RTX 5070 Ti" and gpu["recommended_profile"] == "local_plus"


def test_put_key_saves_to_env_and_never_returns_it(client, env_keys):
    r = client.put("/api/settings/keys/vworld", json={"value": "  ABCD-1234-EFGH-5678 \n"})
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "key": "vworld",
        "env": "VWORLD_API_KEY",
        "set": True,
        "hint": "…5678",
        "verified": False,
    }
    assert "ABCD-1234-EFGH-5678" not in client.get("/api/settings").text
    assert "VWORLD_API_KEY=ABCD-1234-EFGH-5678" in settings.ENV_PATH.read_text(encoding="utf-8")
    assert os.environ["VWORLD_API_KEY"] == "ABCD-1234-EFGH-5678"  # the running server uses it now


def test_vworld_domain_is_shown_in_full(client, env_keys):
    client.put("/api/settings/keys/vworld_domain", json={"value": "http://localhost:8765"})
    key = client.get("/api/settings").json()["keys"]["vworld_domain"]
    assert key == {"env": "VWORLD_DOMAIN", "set": True, "value": "http://localhost:8765"}


def test_openrouter_key_is_checked_before_saving(client, env_keys, monkeypatch):
    monkeypatch.setattr(settings, "_check_key", lambda url, key: (False, "unauthorized (401)"))
    r = client.put("/api/settings/keys/openrouter", json={"value": "sk-or-v1-wrongwrongwrong"})
    assert r.status_code == 400 and "unauthorized" in r.json()["detail"]
    assert not settings.ENV_PATH.exists()

    monkeypatch.setattr(settings, "_check_key", lambda url, key: (True, "authorized"))
    r = client.put("/api/settings/keys/openrouter", json={"value": "sk-or-v1-rightrightright"})
    assert r.status_code == 200 and r.json()["verified"] is True
    assert client.get("/api/settings").json()["warnings"]["openrouter_key_missing"] is False


def test_put_key_rejects_unknown_key_and_bad_values(client, env_keys):
    assert client.put("/api/settings/keys/github", json={"value": "x" * 20}).status_code == 404
    assert client.put("/api/settings/keys/law", json={"value": "  "}).status_code == 400
    assert client.put("/api/settings/keys/law", json={"value": "a\nB=c"}).status_code == 400
    assert not settings.ENV_PATH.exists()


def test_write_env_value_replaces_the_line_and_keeps_the_rest(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# comment\nOPENROUTER_API_KEY=old\n# VWORLD_API_KEY=\n", encoding="utf-8")
    settings.write_env_value("OPENROUTER_API_KEY", "new", path=path)
    settings.write_env_value("VWORLD_API_KEY", "vw", path=path)
    settings.write_env_value("LAW_OPEN_API_OC", "oc", path=path)
    assert path.read_text(encoding="utf-8") == (
        "# comment\nOPENROUTER_API_KEY=new\nVWORLD_API_KEY=vw\n\nLAW_OPEN_API_OC=oc\n"
    )
