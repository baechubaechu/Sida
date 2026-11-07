"""relay_key.py and /api/settings/relay-key — asking the Sida relay for a key, then collecting it."""

from __future__ import annotations

import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from relay import app as relay_server
from relay.tokens import KST, TokenStore
from sida import relay, relay_key, settings, webapp


class FakeRelay:
    """The real relay server (relay/app.py) in memory, reached through relay_key._http_post."""

    def __init__(self, tmp_path):
        self.store = TokenStore(tmp_path / "relay.db", now=lambda: datetime(2026, 11, 7, 23, 0, tzinfo=KST))
        self.client = TestClient(relay_server.create_app(relay_server.Keys(vworld="vw"), self.store))
        self.urls: list[str] = []
        self.down = False

    def __call__(self, url, body):
        self.urls.append(url)
        if self.down:
            raise relay_key.RelayUnreachable("Sida relay unreachable: ConnectionError")
        assert url.startswith(relay.DEFAULT_URL + "/")
        r = self.client.post(url[len(relay.DEFAULT_URL):], json=body)
        return r.status_code, r.json()


@pytest.fixture
def server(tmp_path, monkeypatch):
    fake = FakeRelay(tmp_path)
    monkeypatch.setattr(relay_key, "_http_post", fake)
    for spec in settings.KEYS.values():
        monkeypatch.setenv(spec["env"], "")
    return fake


@pytest.fixture
def client():
    return TestClient(webapp.create_app(allowed_hosts={"testserver"}))


def test_a_request_is_approved_and_the_key_lands_in_settings(client, server):
    assert client.get("/api/settings").json()["relay"] == {"url": relay.DEFAULT_URL, "default_url": relay.DEFAULT_URL}
    assert client.get("/api/settings/relay-key").json() == {"state": "none"}
    sent = client.post("/api/settings/relay-key", json={"name": "김철수 (OO대)", "contact": "kim@example.com"})
    assert sent.status_code == 200 and sent.json()["state"] == "pending" and sent.json()["name"] == "김철수 (OO대)"
    assert "sidareq_" not in sent.text  # the claim code stays in the file
    assert oct(relay_key.REQUEST_PATH.stat().st_mode & 0o777) == "0o600" or os.name == "nt"
    assert server.urls == [f"{relay.DEFAULT_URL}/relay/requests"]

    assert client.get("/api/settings/relay-key").json()["state"] == "pending"  # not answered yet
    waiting = server.store.requests("pending")
    assert [(r.name, r.contact) for r in waiting] == [("김철수 (OO대)", "kim@example.com")]
    server.store.approve(waiting[0].id, daily_limit=500)

    got = client.get("/api/settings/relay-key")
    assert got.json()["state"] == "approved" and got.json()["key"]["set"] is True
    key = os.environ[relay.TOKEN_ENV]
    assert key.startswith("sida_") and key not in got.text and key not in client.get("/api/settings").text
    assert settings.read_key(relay.TOKEN_ENV) == key  # saved to .env too
    assert relay.base_url() == relay.DEFAULT_URL  # government calls now go through the relay
    assert server.store.find(key).daily_limit == 500
    assert not relay_key.REQUEST_PATH.exists()
    assert client.get("/api/settings/relay-key").json() == {"state": "none"}


def test_a_refused_request_is_forgotten(client, server):
    client.post("/api/settings/relay-key", json={"name": "모르는 사람"})
    server.store.refuse(server.store.requests("pending")[0].id)
    assert client.get("/api/settings/relay-key").json()["state"] == "refused"
    assert client.get("/api/settings/relay-key").json() == {"state": "none"}
    assert not os.environ.get(relay.TOKEN_ENV)


def test_the_relay_being_down_keeps_the_request(client, server):
    client.post("/api/settings/relay-key", json={"name": "김철수"})
    server.down = True
    assert client.get("/api/settings/relay-key").json() == {
        "state": "pending", "name": "김철수", "requested": relay_key.status()["requested"], "unreachable": True}
    assert client.post("/api/settings/relay-key", json={"name": "김철수"}).status_code == 502
    server.down = False
    assert client.delete("/api/settings/relay-key").json() == {"state": "none"}
    assert client.get("/api/settings/relay-key").json() == {"state": "none"}


def test_requests_are_checked_and_limited(client, server):
    assert client.post("/api/settings/relay-key", json={"name": "  "}).status_code == 400
    assert client.post("/api/settings/relay-key", json={"name": "x", "contact": "c" * 121}).status_code == 400
    codes = [client.post("/api/settings/relay-key", json={"name": f"사람 {i}"}).status_code for i in range(6)]
    assert codes == [200] * 5 + [429]  # the relay takes 5 an hour from one address


def test_a_request_goes_to_the_address_set_in_settings(client, server, monkeypatch):
    monkeypatch.setenv(relay.ENV_NAME, "http://sida-kr.duckdns.org")  # not valid: nothing is sent
    assert client.post("/api/settings/relay-key", json={"name": "김철수"}).status_code == 400
    assert server.urls == []
