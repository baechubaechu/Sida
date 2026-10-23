"""chatgpt_auth.py / chatgpt_api.py — signing in with ChatGPT so the Conductor uses the user's plan."""

from __future__ import annotations

import json
import os
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from sida import chatgpt_auth, runtime, settings, webapp
from sida.providers import ChatGPTProvider, LLMError

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), "kid": "k1", "alg": "RS256"}
ISSUED = "oaiapp_test"
PLAN_SCOPES = "chatgpt.tokens.use.direct email offline_access openid profile resource.invoke"


class FakeOpenAI:
    """auth.openai.com and the model list: answers by URL, records every call."""

    def __init__(self):
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, str | None]] = []
        self.scope = PLAN_SCOPES
        self.token_status = 200
        self.refresh_reply: tuple[int, dict] | None = None
        self.nonce = ""  # set from the authorize URL
        self.client_id = ISSUED
        self.revoke_status = 200

    def id_token(self, **extra) -> str:
        now = int(time.time())
        claims = {
            "iss": chatgpt_auth.ISSUER, "aud": self.client_id, "sub": "user-1",
            "email": "jh@example.com", "iat": now, "exp": now + 3600, "nonce": self.nonce,
            **extra,
        }
        return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})

    def post(self, url, data):
        self.posts.append((url, dict(data)))
        if url == chatgpt_auth.TOKEN_URL and data["grant_type"] == "authorization_code":
            return self.token_status, {
                "access_token": "at-1", "refresh_token": "rt-1", "id_token": self.id_token(),
                "token_type": "Bearer", "expires_in": 3600, "scope": self.scope,
            }
        if url == chatgpt_auth.TOKEN_URL and data["grant_type"] == "refresh_token":
            return self.refresh_reply or (200, {
                "access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600,
            })
        if url == "https://auth.openai.com/oauth/revoke":
            return self.revoke_status, {}
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url, token=None):
        self.gets.append((url, token))
        if url == chatgpt_auth.DISCOVERY_URL:
            return 200, {
                "jwks_uri": "https://auth.openai.com/.well-known/jwks.json",
                "revocation_endpoint": "https://auth.openai.com/oauth/revoke",
            }
        if url.endswith("/jwks.json"):
            return 200, {"keys": [JWK]}
        if url == chatgpt_auth.MODELS_URL:
            return 200, {"models": [
                {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol", "visibility": "list"},
                {"slug": "internal", "visibility": "hide"},
                {"slug": "gpt-6.1-mini", "visibility": "list"},
            ]}
        raise AssertionError(f"unexpected GET {url}")


@pytest.fixture
def openai(monkeypatch):
    fake = FakeOpenAI()
    monkeypatch.setattr(chatgpt_auth, "_http_post_form", fake.post)
    monkeypatch.setattr(chatgpt_auth, "_http_get_json", fake.get)
    return fake


@pytest.fixture
def client():
    return TestClient(webapp.create_app(allowed_hosts={"testserver"}))


def authorize_params(url: str) -> dict[str, str]:
    assert url.startswith(chatgpt_auth.AUTHORIZE_URL + "?")
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def sign_in(openai: FakeOpenAI, **callback) -> dict:
    params = authorize_params(chatgpt_auth.start_login(8765)["authorize_url"])
    openai.nonce = params["nonce"]
    return chatgpt_auth.finish_login(
        {"code": "c1", "state": params["state"], "client_id": ISSUED, **callback}
    )


def test_tests_never_touch_this_machines_login():
    assert chatgpt_auth.CREDENTIALS_PATH != chatgpt_auth.Path.home() / "Sida" / "chatgpt_login.json"


def test_first_sign_in_registers_this_pc(openai):
    params = authorize_params(chatgpt_auth.start_login(8765)["authorize_url"])
    assert params["client_id"] == "dynamic_agent_client"
    assert params["agent_name_hint"] == "Sida"
    assert params["ext_agent_host_id"].startswith("urn:uuid:")
    assert params["redirect_uri"] == "http://127.0.0.1:8765/auth/callback"  # never localhost
    assert params["resource"] == "https://api.openai.com/v1"
    assert params["code_challenge_method"] == "S256" and "=" not in params["code_challenge"]
    assert set(params["scope"].split()) == set(PLAN_SCOPES.split())


def test_callback_exchanges_the_code_and_keeps_tokens_private(openai):
    result = sign_in(openai)
    assert result == {"signed_in": True, "email": "jh@example.com", "plan_usage": True, "registered": True}
    url, form = openai.posts[0]
    assert url == chatgpt_auth.TOKEN_URL
    assert form["client_id"] == ISSUED  # the issued id, not dynamic_agent_client
    assert form["redirect_uri"] == "http://127.0.0.1:8765/auth/callback"
    assert "client_secret" not in form and form["code_verifier"]
    saved = json.loads(chatgpt_auth.CREDENTIALS_PATH.read_text(encoding="utf-8"))
    assert saved["client_id"] == ISSUED and saved["session"]["refresh_token"] == "rt-1"
    if os.name == "posix":
        assert chatgpt_auth.CREDENTIALS_PATH.stat().st_mode & 0o777 == 0o600


def test_later_sign_in_reuses_the_issued_client_and_host(openai):
    sign_in(openai)
    host = json.loads(chatgpt_auth.CREDENTIALS_PATH.read_text())["ext_agent_host_id"]
    params = authorize_params(chatgpt_auth.start_login(9000)["authorize_url"])
    assert params["client_id"] == ISSUED and "agent_name_hint" not in params
    assert params["ext_agent_host_id"] == host
    assert params["login_hint"] == "jh@example.com" and params["id_token_hint"]
    assert params["redirect_uri"] == "http://127.0.0.1:9000/auth/callback"  # only the port moves


def test_callback_rejects_a_bad_state_a_denial_and_a_wrong_nonce(openai):
    with pytest.raises(chatgpt_auth.LoginError):
        chatgpt_auth.finish_login({"code": "c", "state": "forged"})
    params = authorize_params(chatgpt_auth.start_login(8765)["authorize_url"])
    with pytest.raises(chatgpt_auth.LoginError, match="access_denied"):
        chatgpt_auth.finish_login({"state": params["state"], "error": "access_denied"})
    assert openai.posts == []  # a denied sign-in is never exchanged
    params = authorize_params(chatgpt_auth.start_login(8765)["authorize_url"])
    openai.nonce = "someone-else"
    with pytest.raises(chatgpt_auth.LoginError, match="nonce"):
        chatgpt_auth.finish_login({"code": "c", "state": params["state"], "client_id": ISSUED})
    assert chatgpt_auth.status()["signed_in"] is False


def test_id_token_signed_by_another_key_is_rejected(openai, monkeypatch):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    real = openai.id_token
    monkeypatch.setattr(
        openai, "id_token",
        lambda: jwt.encode(jwt.decode(real(), options={"verify_signature": False}), other,
                           algorithm="RS256", headers={"kid": "k1"}),
    )
    with pytest.raises(chatgpt_auth.LoginError, match="invalid ID token"):
        sign_in(openai)


def test_sign_in_without_plan_scope_cannot_run_the_conductor(openai):
    openai.scope = "openid profile email"
    assert sign_in(openai)["plan_usage"] is False
    with pytest.raises(LLMError, match="plan"):
        chatgpt_auth.access_token()


def test_access_token_refreshes_near_expiry_and_keeps_the_new_refresh_token(openai):
    sign_in(openai)
    assert chatgpt_auth.access_token() == "at-1"
    data = json.loads(chatgpt_auth.CREDENTIALS_PATH.read_text())
    data["session"]["expires_at"] = time.time() + 30
    chatgpt_auth._save(data)
    assert chatgpt_auth.access_token() == "at-2"
    url, form = openai.posts[-1]
    assert form == {
        "grant_type": "refresh_token", "client_id": ISSUED, "refresh_token": "rt-1",
        "resource": "https://api.openai.com/v1",
    }
    session = json.loads(chatgpt_auth.CREDENTIALS_PATH.read_text())["session"]
    assert session["refresh_token"] == "rt-2"
    assert "chatgpt.tokens.use.direct" in session["scopes"]  # kept across the refresh


def test_dead_refresh_token_signs_out_but_keeps_the_client(openai):
    sign_in(openai)
    data = json.loads(chatgpt_auth.CREDENTIALS_PATH.read_text())
    data["session"]["expires_at"] = 0
    chatgpt_auth._save(data)
    openai.refresh_reply = (400, {"error": "refresh_token_reused"})
    with pytest.raises(LLMError, match="Sign in again"):
        chatgpt_auth.access_token()
    assert chatgpt_auth.status() == {
        "signed_in": False, "email": "", "plan_usage": False, "registered": True,
    }


def test_refresh_server_error_keeps_the_session(openai):
    sign_in(openai)
    data = json.loads(chatgpt_auth.CREDENTIALS_PATH.read_text())
    data["session"]["expires_at"] = 0
    chatgpt_auth._save(data)
    openai.refresh_reply = (503, {"detail": "busy"})
    with pytest.raises(LLMError) as err:
        chatgpt_auth.access_token()
    assert getattr(err.value, "retryable", False) is True
    assert chatgpt_auth.status()["signed_in"] is True


def test_sign_out_revokes_the_refresh_token(openai):
    sign_in(openai)
    assert chatgpt_auth.sign_out() == {"revoked": True}
    assert openai.posts[-1] == (
        "https://auth.openai.com/oauth/revoke",
        {"token": "rt-1", "token_type_hint": "refresh_token", "client_id": ISSUED},
    )
    assert chatgpt_auth.status()["signed_in"] is False


def test_sign_out_reports_when_revocation_is_not_confirmed(openai):
    sign_in(openai)
    openai.revoke_status = 500
    assert chatgpt_auth.sign_out() == {"revoked": False}
    assert chatgpt_auth.status()["signed_in"] is False  # local tokens are gone either way


def test_models_keep_the_listed_ones_in_order(openai):
    sign_in(openai)
    assert chatgpt_auth.list_models() == [
        {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol"},
        {"slug": "gpt-6.1-mini", "display_name": "gpt-6.1-mini"},
    ]
    assert openai.gets[-1] == (chatgpt_auth.MODELS_URL, "at-1")


# ---------------------------------------------------------------------------
# JSON API and the callback page
# ---------------------------------------------------------------------------


def test_api_sign_in_flow(client, openai):
    assert client.get("/api/settings/chatgpt").json()["signed_in"] is False
    r = client.post("/api/settings/chatgpt/login", json={})
    assert r.status_code == 200
    params = authorize_params(r.json()["authorize_url"])
    assert params["redirect_uri"].startswith("http://127.0.0.1:")
    openai.nonce = params["nonce"]
    page = client.get(
        "/auth/callback", params={"code": "c1", "state": params["state"], "client_id": ISSUED}
    )
    assert page.status_code == 200 and "jh@example.com" in page.text
    body = client.get("/api/settings/chatgpt").json()
    assert body["signed_in"] is True and "access_token" not in json.dumps(body)
    models = client.get("/api/settings/chatgpt/models").json()["models"]
    assert [m["slug"] for m in models] == ["gpt-6.1-sol", "gpt-6.1-mini"]
    assert client.delete("/api/settings/chatgpt").json() == {"revoked": True}


def test_callback_page_shows_a_failed_sign_in(client):
    page = client.get("/auth/callback", params={"code": "c1", "state": "nope"})
    assert page.status_code == 400
    assert "ChatGPT 로그인 실패" in page.text


def test_models_need_a_sign_in(client):
    r = client.get("/api/settings/chatgpt/models")
    assert r.status_code == 502 and "not signed in" in r.json()["detail"]


def test_settings_let_the_conductor_use_chatgpt(client, openai):
    body = client.get("/api/settings").json()
    assert body["options"]["conductor_providers"] == ["openrouter", "ollama", "chatgpt"]
    assert body["chatgpt"]["signed_in"] is False and body["chatgpt"]["model"] == "gpt-6.1-sol"
    r = client.put(
        "/api/settings", json={"conductor_provider": "chatgpt", "chatgpt_model": "gpt-6.1-mini"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["conductor"] == {"provider": "chatgpt", "model": "gpt-6.1-mini"}
    assert body["worker"]["provider"] == "openrouter" and body["mode"] == "custom"
    assert body["warnings"]["chatgpt_signed_out"] is True
    sign_in(openai)
    assert client.get("/api/settings").json()["warnings"]["chatgpt_signed_out"] is False


def test_experts_can_run_on_chatgpt_with_their_own_model(client, openai):
    body = client.get("/api/settings").json()
    assert body["options"]["worker_providers"] == ["openrouter", "ollama", "chatgpt"]
    assert body["chatgpt"]["worker_model"] == "gpt-6.1-sol"
    r = client.put(
        "/api/settings", json={"worker_provider": "chatgpt", "worker_chatgpt_model": "gpt-6-luna"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["worker"] == {"provider": "chatgpt", "model": "gpt-6-luna"}
    assert body["conductor"]["provider"] == "openrouter"  # the Conductor keeps its own choice
    assert body["chatgpt"]["model"] == "gpt-6.1-sol" and body["warnings"]["chatgpt_signed_out"] is True
    for field in ("chatgpt_model", "worker_chatgpt_model"):
        assert client.put("/api/settings", json={field: "two words"}).status_code == 400

    cfg = {"conductor": {"provider": "mock"}, "worker": {"provider": "chatgpt", "chatgpt_model": "gpt-6-luna"}}
    assert runtime.resolve_worker_runtime(cfg)["model"] == "gpt-6-luna"
    assert isinstance(runtime.worker_provider(cfg, ""), ChatGPTProvider)
    assert runtime.needs_openrouter(cfg) is False


def test_conductor_runtime_uses_the_chatgpt_model(mock_config, openai):
    mock_config["conductor"]["provider"] = "chatgpt"
    mock_config["conductor"]["chatgpt_model"] = "gpt-6.1-mini"
    rt = runtime.resolve_conductor_runtime(mock_config)
    assert rt["provider"] == "chatgpt" and rt["model"] == "gpt-6.1-mini"
    assert runtime.needs_openrouter({**mock_config, "worker": {"provider": "mock"}}) is False
    provider = runtime.conductor_provider(mock_config, "")
    assert isinstance(provider, ChatGPTProvider)
    sign_in(openai)
    assert provider.token() == "at-1"
    assert settings.settings_view(mock_config)["conductor"]["provider"] == "chatgpt"
