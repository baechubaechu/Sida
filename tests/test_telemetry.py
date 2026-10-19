"""telemetry.py — usage records queued on this machine and sent only when turned on."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sida import settings, telemetry, webapp


@pytest.fixture
def on(mock_config):
    mock_config["telemetry"] = {"enabled": True, "endpoint": "https://collector.test/api/v1/events"}
    return mock_config


@pytest.fixture
def server(monkeypatch):
    """A fake collection server: records each request; `server.status` is the reply code."""

    class Server:
        status = 200
        requests: list[dict] = []

    def post(url, payload):
        if isinstance(Server.status, Exception):
            raise Server.status
        Server.requests.append({"url": url, "payload": payload})
        return Server.status

    Server.requests = []
    monkeypatch.setattr(telemetry, "_http_post", post)
    return Server


def test_nothing_is_recorded_by_default(mock_config):
    assert telemetry.record("job", {"ok": True}, config=mock_config) is False
    assert telemetry.queued() == []
    assert not telemetry.TELEMETRY_DIR.exists()


def test_records_wait_in_the_queue_when_on(on):
    assert telemetry.record("job", {"ok": True}, config=on) is True
    [event] = telemetry.queued()
    assert event["kind"] == "job"
    assert event["data"] == {"ok": True}
    assert len(event["id"]) == 32 and event["at"]


def test_record_never_raises(monkeypatch, on):
    def broken(event):
        raise OSError("disk full")

    monkeypatch.setattr(telemetry, "_append", broken)
    assert telemetry.record("job", {}, config=on) is False


def test_install_id_is_random_and_kept():
    first = telemetry.install_id()
    assert len(first) == 32
    assert telemetry.install_id() == first


def test_failed_input_is_sent_only_with_its_own_consent(on):
    telemetry.record_failure("site:search_parcels", "not_found", inputs=("금정동 689",), config=on)
    on["telemetry"]["share_failure_inputs"] = True
    telemetry.record_failure("site:search_parcels", "not_found", inputs=("금정동 689",), config=on)
    first, second = telemetry.queued()
    assert first["data"] == {"stage": "site:search_parcels", "error": "not_found"}
    assert second["data"]["inputs"] == ["금정동 689"]


def test_error_kind_keeps_no_text():
    assert telemetry.error_kind("HTTP 429: Too Many Requests for key sk-or-abc") == "rate_limit"
    assert telemetry.error_kind("Read timed out (30s)") == "timeout"
    assert telemetry.error_kind("서울시 강남구 어딘가 실패") == "other"
    assert telemetry.error_kind(None) is None


def test_job_observer_times_experts_without_text(on):
    now = [100.0]
    observer = telemetry.JobObserver(on, "expert", "site_reader", clock=lambda: now[0])
    observer.event("module_started", {"agent": {"id": "site_reader"}})
    now[0] = 112.34
    observer.event("module_failed", {"agent": {"id": "site_reader"}, "reason": "HTTP 401 bad key sk-123"})
    observer.event("conductor_reply", {"text": "brief text the designer wrote"})
    observer.finished("HTTP 401 bad key sk-123")
    run, job = telemetry.queued()
    assert run["kind"] == "expert_run"
    assert run["data"] == {"agent": "site_reader", "ok": False, "seconds": 12.3, "error": "auth"}
    assert job["data"]["job"] == "expert" and job["data"]["ok"] is False
    assert job["data"]["conductor"] == "mock:" + on["conductor"]["model"]
    sent = json.dumps(telemetry.queued(), ensure_ascii=False)
    assert "sk-123" not in sent and "brief text" not in sent


def test_flush_sends_batches_and_empties_the_queue(on, server, monkeypatch):
    monkeypatch.setattr(telemetry, "BATCH_SIZE", 2)
    for i in range(3):
        telemetry.record("job", {"n": i}, config=on)
    assert telemetry.flush(on) == 3
    assert [len(r["payload"]["events"]) for r in server.requests] == [2, 1]
    payload = server.requests[0]["payload"]
    assert server.requests[0]["url"] == "https://collector.test/api/v1/events"
    assert payload["install_id"] == telemetry.install_id()
    assert payload["app_version"] and payload["os"] is not None
    assert telemetry.queued() == []


@pytest.mark.parametrize("trouble", [503, 429, ConnectionError("offline")])
def test_flush_keeps_records_when_the_server_cannot_take_them(on, server, trouble):
    telemetry.record("job", {}, config=on)
    server.status = trouble
    assert telemetry.flush(on) == 0
    assert len(telemetry.queued()) == 1


def test_flush_drops_a_batch_the_server_rejects(on, server):
    telemetry.record("job", {}, config=on)
    server.status = 400
    assert telemetry.flush(on) == 0
    assert telemetry.queued() == []


def test_flush_sends_nothing_when_off(mock_config, server):
    assert telemetry.flush(mock_config) == 0
    assert server.requests == []


def test_queue_keeps_only_the_newest(on, monkeypatch):
    monkeypatch.setattr(telemetry, "MAX_QUEUED", 3)
    for i in range(5):
        telemetry.record("job", {"n": i}, config=on)
    assert [e["data"]["n"] for e in telemetry.queued()] == [2, 3, 4]


def test_feedback_checks_rating_and_length(on):
    with pytest.raises(ValueError):
        telemetry.record_feedback(on, "site_reader", "meh")
    with pytest.raises(ValueError):
        telemetry.record_feedback(on, "site_reader", "up", "x" * (telemetry.MAX_COMMENT + 1))
    assert telemetry.record_feedback(on, "site_reader", "down", "  수치가 틀림 ") is True
    [event] = telemetry.queued()
    assert event["data"] == {"agent": "site_reader", "rating": "down", "comment": "수치가 틀림"}


# --------------------------------------------------------------------- settings


@pytest.fixture
def settings_client():
    return TestClient(webapp.create_app(allowed_hosts={"testserver"}))


def test_settings_turn_sending_on_and_off(settings_client):
    body = settings_client.get("/api/settings").json()
    assert body["telemetry_enabled"] is False
    assert body["telemetry_share_inputs"] is False

    body = settings_client.put("/api/settings", json={"telemetry_enabled": True}).json()
    assert body["telemetry_enabled"] is True
    assert "telemetry:\n  enabled: true" in settings.local_config_path().read_text(encoding="utf-8")

    telemetry.record("job", {})
    assert len(telemetry.queued()) == 1
    body = settings_client.put("/api/settings", json={"telemetry_enabled": False}).json()
    assert body["telemetry_enabled"] is False
    assert telemetry.queued() == []  # turning it off drops what was waiting


def test_turning_input_sharing_off_strips_queued_inputs(settings_client):
    settings_client.put("/api/settings", json={"telemetry_enabled": True, "telemetry_share_inputs": True})
    telemetry.record_failure("law:search", "no_sources", inputs=("건폐율",))
    assert telemetry.queued()[0]["data"]["inputs"] == ["건폐율"]
    settings_client.put("/api/settings", json={"telemetry_share_inputs": False})
    assert "inputs" not in telemetry.queued()[0]["data"]


def test_settings_reject_non_boolean(settings_client):
    r = settings_client.put("/api/settings", json={"telemetry_enabled": "maybe"})
    assert r.status_code == 422
