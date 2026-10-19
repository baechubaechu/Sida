"""collector/app.py — the team server's write-only endpoint, with an in-memory store."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from collector import app as collector

INSTALL = "a" * 32


class MemoryStore:
    def __init__(self):
        self.rows: dict[str, tuple] = {}

    def add(self, batch):
        new = 0
        for e in batch.events:
            if e.id not in self.rows:
                self.rows[e.id] = (batch.install_id, batch.app_version, batch.os, e.kind, e.at, e.data)
                new += 1
        return new


def event(kind="job", **data):
    return {"id": uuid.uuid4().hex, "kind": kind, "at": "2026-10-20T01:00:00+00:00", "data": data}


def batch(*events, install=INSTALL):
    return {"install_id": install, "app_version": "0.2.0", "os": "Windows", "events": list(events)}


@pytest.fixture
def server():
    store = MemoryStore()
    now = [1000.0]
    client = TestClient(collector.create_app(store, clock=lambda: now[0]))
    return client, store, now


def test_records_are_stored_and_a_resend_is_not_duplicated(server):
    client, store, _ = server
    body = batch(event("expert_run", agent="site_reader", ok=True), event("feedback", rating="up"))
    r = client.post("/api/v1/events", json=body)
    assert r.status_code == 202 and r.json() == {"accepted": 2, "stored": 2}
    assert client.post("/api/v1/events", json=body).json() == {"accepted": 2, "stored": 0}
    assert len(store.rows) == 2
    assert {row[3] for row in store.rows.values()} == {"expert_run", "feedback"}


def test_nothing_can_be_read_back(server):
    client, _, _ = server
    assert client.get("/api/v1/events").status_code == 405
    assert client.get("/docs").status_code == 404
    assert client.get("/api/v1/health").json() == {"ok": True}


@pytest.mark.parametrize(
    "body",
    [
        batch(),  # no records
        batch(event(), install="not-an-id"),
        batch(event("DROP TABLE")),
        batch({**event(), "extra": 1}),
        batch(event(blob="x" * (collector.MAX_DATA + 1))),
        batch(*[event() for _ in range(collector.MAX_EVENTS + 1)]),
        {"events": [event()]},
    ],
)
def test_malformed_batches_are_refused(server, body):
    client, store, _ = server
    assert client.post("/api/v1/events", json=body).status_code == 422
    assert store.rows == {}


def test_oversized_request_is_refused(server):
    client, _, _ = server
    huge = b"{" + b" " * (collector.MAX_BODY + 1) + b"}"
    r = client.post("/api/v1/events", content=huge, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_each_installation_and_address_has_an_hourly_limit(server, monkeypatch):
    monkeypatch.setattr(collector, "INSTALL_LIMIT", 3)
    client, store, now = server
    client = TestClient(collector.create_app(store, clock=lambda: now[0]))
    assert client.post("/api/v1/events", json=batch(event(), event())).status_code == 202
    assert client.post("/api/v1/events", json=batch(event(), event())).status_code == 429
    # Another installation is not held back by the first one.
    assert client.post("/api/v1/events", json=batch(event(), install="b" * 32)).status_code == 202
    now[0] += collector.WINDOW + 1
    assert client.post("/api/v1/events", json=batch(event(), event())).status_code == 202


def test_address_limit_uses_the_forwarded_sender(monkeypatch):
    monkeypatch.setattr(collector, "ADDRESS_LIMIT", 1)
    client = TestClient(collector.create_app(MemoryStore()))
    office = {"x-forwarded-for": "203.0.113.7, 172.18.0.2"}
    assert client.post("/api/v1/events", json=batch(event()), headers=office).status_code == 202
    assert client.post("/api/v1/events", json=batch(event(), install="b" * 32), headers=office).status_code == 429
    other = {"x-forwarded-for": "198.51.100.1"}
    assert client.post("/api/v1/events", json=batch(event()), headers=other).status_code == 202


def test_dsn_reads_the_password_from_its_secret_file(tmp_path):
    secret = tmp_path / "db_password"
    secret.write_text("p@ss/word\n", encoding="utf-8")
    dsn = collector.dsn_from_env({"SIDA_DB_PASSWORD_FILE": str(secret)})
    assert dsn == "postgresql://sida:p%40ss%2Fword@db:5432/sida"


def test_the_app_and_the_collector_agree_on_the_batch_shape(mock_config, monkeypatch):
    """What sida/telemetry.py sends is exactly what the collector accepts."""
    from sida import telemetry

    mock_config["telemetry"] = {"enabled": True}
    telemetry.record("expert_run", {"agent": "site_reader", "ok": True, "seconds": 3.2}, config=mock_config)
    telemetry.record_feedback(mock_config, "site_reader", "down", "면적이 틀림")
    client = TestClient(collector.create_app(MemoryStore()))
    sent = []

    def post(url, payload):
        r = client.post("/api/v1/events", json=payload)
        sent.append(r.status_code)
        return r.status_code

    monkeypatch.setattr(telemetry, "_http_post", post)
    assert telemetry.flush(mock_config) == 2
    assert sent == [202]
