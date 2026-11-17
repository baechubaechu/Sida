"""settings.py / settings_api.py — the web settings screen's JSON API."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from sida import config as sida_config
from sida import settings, webapp

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


def test_the_sida_relay_address_must_be_https_and_is_shown_in_full(client, env_keys):
    assert client.put("/api/settings/keys/relay_url", json={"value": "http://sida-kr.duckdns.org"}).status_code == 400
    assert client.put("/api/settings/keys/relay_url", json={"value": "https://sida-kr.duckdns.org/"}).status_code == 200
    key = client.get("/api/settings").json()["keys"]["relay_url"]
    assert key == {"env": "SIDA_RELAY_URL", "set": True, "value": "https://sida-kr.duckdns.org"}
    assert os.environ["SIDA_RELAY_URL"] == "https://sida-kr.duckdns.org"  # used at once, no restart


def test_the_sida_access_key_is_a_hidden_sida_key(client, env_keys):
    assert client.put("/api/settings/keys/relay_token", json={"value": "not-a-sida-key"}).status_code == 400
    assert client.put("/api/settings/keys/relay_token", json={"value": "sida_abcdefghij1234"}).status_code == 200
    key = client.get("/api/settings").json()["keys"]["relay_token"]
    assert key == {"env": "SIDA_RELAY_TOKEN", "set": True, "hint": "…1234"}
    assert "sida_abcdefghij1234" not in client.get("/api/settings").text


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


def test_anthropic_key_is_checked_and_the_role_runs_on_claude(client, env_keys, monkeypatch):
    monkeypatch.setattr(settings, "_check_anthropic_key", lambda key: (False, "unauthorized (401)"))
    r = client.put("/api/settings/keys/anthropic", json={"value": "sk-ant-wrongwrongwrong"})
    assert r.status_code == 400 and "unauthorized" in r.json()["detail"]

    body = client.put("/api/settings", json={"conductor_provider": "anthropic"}).json()
    assert body["mode"] == "custom"
    assert body["conductor"] == {"provider": "anthropic", "model": "claude-opus-5-5"}
    assert body["anthropic"]["models"][0] == "claude-opus-5-5"
    assert body["warnings"]["anthropic_key_missing"] is True

    monkeypatch.setattr(settings, "_check_anthropic_key", lambda key: (True, "authorized"))
    assert client.put("/api/settings/keys/anthropic", json={"value": "sk-ant-rightrightright"}).json()["verified"] is True
    body = client.put("/api/settings", json={"worker_provider": "anthropic", "worker_anthropic_model": "claude-sonnet-5-5"}).json()
    assert body["worker"] == {"provider": "anthropic", "model": "claude-sonnet-5-5"}
    assert body["warnings"]["anthropic_key_missing"] is False
    assert body["keys"]["anthropic"] == {"env": "ANTHROPIC_API_KEY", "set": True, "hint": "…ight"}


@pytest.mark.parametrize("model", ["anthropic/claude-opus-5-5", "claude opus", ""])
def test_anthropic_model_must_be_a_claude_api_id(client, model):
    assert client.put("/api/settings", json={"anthropic_model": model}).status_code == 400


def test_an_anthropic_role_gets_the_anthropic_key_not_openrouters(env_keys, monkeypatch):
    from sida import runtime

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-for-claude")
    cfg = {"conductor": {"provider": "anthropic"}, "worker": {"provider": "openrouter"}}
    assert runtime.conductor_provider(cfg, "sk-or-openrouter")._client.api_key == "sk-ant-for-claude"
    assert runtime.worker_provider(cfg, "sk-or-openrouter").api_key == "sk-or-openrouter"


def test_gemini_key_and_model_are_saved_per_role(client, env_keys, monkeypatch):
    monkeypatch.setattr(settings, "_check_google_key", lambda key: (True, "authorized"))
    assert client.put("/api/settings/keys/google", json={"value": "AIza-rightrightright"}).json()["verified"] is True
    body = client.put("/api/settings", json={"conductor_provider": "google", "google_model": "gemini-3.8-flash"}).json()
    assert body["conductor"] == {"provider": "google", "model": "gemini-3.8-flash"}
    assert body["google"]["worker_model"] == "gemini-4-hydrogen"
    assert body["warnings"]["google_key_missing"] is False
    assert "google" in body["options"]["worker_providers"]


def test_model_list_is_read_from_the_service(client, env_keys, monkeypatch):
    assert client.get("/api/settings/models/google").status_code == 502  # no key yet
    assert client.get("/api/settings/models/openrouter").status_code == 404
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-x")

    class Reply:
        status_code = 200

        @staticmethod
        def json():
            return {"models": [
                {"name": "models/gemini-9-preview", "displayName": "Gemini 9 Preview", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-5-pro", "displayName": "Gemini 5 Pro", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-embedding-2", "supportedGenerationMethods": ["embedContent"]},
                {"name": "models/gemini-5-flash-tts", "supportedGenerationMethods": ["generateContent"]},
            ]}

    monkeypatch.setattr(settings.requests, "get", lambda *a, **kw: Reply())
    body = client.get("/api/settings/models/google").json()
    # A model released after this build shows up; speech and embedding models do not; previews last.
    assert [m["id"] for m in body["models"]] == ["gemini-5-pro", "gemini-9-preview"]


def test_anthropic_model_list_keeps_claude_models(env_keys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")

    class Models:
        @staticmethod
        def list(limit):
            return [type("M", (), {"id": "claude-opus-6", "display_name": "Claude Opus 6"})()]

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: type("C", (), {"models": Models})())
    assert settings.model_list("anthropic")["models"] == [{"id": "claude-opus-6", "name": "Claude Opus 6"}]
