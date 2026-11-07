"""relay/app.py — the Korean server's government API relay, with a fake upstream."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from relay import app as relay
from relay.tokens import KST, TokenStore

KEYS = relay.Keys(vworld="vw-server-key", vworld_domain="https://sida-kr.duckdns.org",
                  datago="dg-server-key", law="law-server-oc")


class FakeUpstream:
    def __init__(self):
        self.calls: list[tuple[str, dict, dict]] = []
        self.reply = relay.Upstream(200, "application/json", b'{"response": {"status": "OK"}}')

    def __call__(self, url, params, headers):
        self.calls.append((url, dict(params), dict(headers)))
        return self.reply


@pytest.fixture
def upstream():
    return FakeUpstream()


@pytest.fixture
def clock():
    return {"now": datetime(2026, 11, 7, 23, 0, tzinfo=KST), "tick": 0.0}


@pytest.fixture
def store(tmp_path, clock):
    return TokenStore(tmp_path / "relay.db", now=lambda: clock["now"])


@pytest.fixture
def token(store):
    return store.issue("지훈")[0]


@pytest.fixture
def client(upstream, store, clock):
    return TestClient(relay.create_app(KEYS, store, fetch=upstream, clock=lambda: clock["tick"]))


def call(client, path, params=None, token=None, **headers):
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.get(path, params=params or {}, headers=headers)


def test_vworld_calls_get_the_server_key_and_the_answer_comes_back_as_is(client, upstream, token):
    upstream.reply = relay.Upstream(201, "application/json;charset=UTF-8", b'{"x": 1}')
    r = call(client, "/relay/vworld/req/data", {"data": "LP_PA_CBND_BUBUN", "key": "client-key", "Domain": "x"}, token)
    assert r.status_code == 201 and r.content == b'{"x": 1}' and r.headers["content-type"].startswith("application/json")
    assert r.headers["cache-control"] == "no-store"
    url, params, _ = upstream.calls[-1]
    assert url == "https://api.vworld.kr/req/data"
    # the client's key and domain are dropped, the server's are used
    assert params == {"data": "LP_PA_CBND_BUBUN", "key": "vw-server-key", "domain": "https://sida-kr.duckdns.org"}

    call(client, "/relay/vworld/req/search", {"query": "무교동 45"}, token)
    assert upstream.calls[-1][0] == "https://api.vworld.kr/req/search"
    assert upstream.calls[-1][1] == {"query": "무교동 45", "key": "vw-server-key"}  # search takes no domain
    call(client, "/relay/vworld/ned/data/getLandUseAttr", {"pnu": "1" * 19}, token)
    assert upstream.calls[-1][0] == "https://api.vworld.kr/ned/data/getLandUseAttr"


def test_only_the_paths_sida_uses_are_relayed(client, upstream, token):
    for path in ("/relay/vworld/req/address", "/relay/vworld/../etc/passwd", "/relay/vworld/req/wmts/1.0.0/Satellite/1/2/3.jpeg",
                 "/relay/datago/OtherService/getX", "/relay/law/DRF/lawSearch.do"):
        assert call(client, path, {"target": "law"}, token).status_code == 404, path
    assert call(client, "/relay/law/DRF/lawSearch.do", {"target": "aiSearch"}, token).status_code == 200
    assert call(client, "/relay/other", token=token).status_code == 404
    assert len(upstream.calls) == 1


def test_datago_and_law_get_their_own_keys(client, upstream, token):
    call(client, "/relay/datago/BldRgstHubService/getBrTitleInfo", {"sigunguCd": "11140", "serviceKey": "x"}, token,
         Accept="application/json")
    url, params, headers = upstream.calls[-1]
    assert url == "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
    assert params == {"serviceKey": "dg-server-key", "sigunguCd": "11140"} and headers == {"Accept": "application/json"}

    call(client, "/relay/law/DRF/lawService.do", {"target": "ordin", "MST": "123", "OC": "mine"}, token)
    url, params, _ = upstream.calls[-1]
    assert url == "https://www.law.go.kr/DRF/lawService.do"
    assert params == {"OC": "law-server-oc", "target": "ordin", "MST": "123"}


def test_calls_need_a_live_access_key(client, upstream, store, token):
    path = "/relay/vworld/req/search"
    assert call(client, path).status_code == 401
    assert call(client, path, token="sida_made-up").status_code == 401
    assert call(client, path, {"sida_token": token}).status_code == 401  # API calls take the header only
    assert upstream.calls == []
    assert call(client, path, token=token).status_code == 200
    store.revoke(store.find(token).id)
    assert call(client, path, token=token).status_code == 403
    assert len(upstream.calls) == 1


def test_a_key_stops_working_after_it_expires(client, store, clock):
    token, _ = store.issue("베타", days=1)
    assert call(client, "/relay/vworld/req/search", token=token).status_code == 200
    clock["now"] = datetime(2026, 11, 9, 0, 1, tzinfo=KST)
    assert call(client, "/relay/vworld/req/search", token=token).status_code == 403


def test_map_images_carry_the_key_as_a_parameter_and_are_not_rewritten(client, upstream, token):
    upstream.reply = relay.Upstream(200, "image/png", b"\x89PNG vw-server-key")
    tile = "/relay/vworld/req/wmts/1.0.0/Base/17/50000/111000.png"
    assert call(client, tile).status_code == 401
    r = call(client, tile, {"sida_token": token})
    assert r.status_code == 200 and r.content == b"\x89PNG vw-server-key"  # images are passed as they are
    assert upstream.calls[-1][:2] == ("https://api.vworld.kr/req/wmts/1.0.0/vw-server-key/Base/17/50000/111000.png", {})
    call(client, "/relay/vworld/req/wms", {"layers": "lp_pa_cbnd_bubun", "sida_token": token})
    params = upstream.calls[-1][1]
    assert params["key"] == "vw-server-key" and "sida_token" not in params


def test_an_answer_that_echoes_a_server_key_has_it_masked(client, upstream, token):
    upstream.reply = relay.Upstream(400, "text/xml", b"<error>bad key dg-server-key</error>")
    r = call(client, "/relay/datago/arLandUseInfoService/DTarLandUseInfo", token=token)
    assert r.status_code == 400 and b"dg-server-key" not in r.content and b"***" in r.content


def test_each_key_has_a_daily_limit_that_starts_again_the_next_korean_day(client, store, clock):
    small, record = store.issue("적게", daily_limit=2)
    path = "/relay/vworld/req/search"
    assert [call(client, path, token=small).status_code for _ in range(3)] == [200, 200, 429]
    other, _ = store.issue("다른 사람")
    assert call(client, path, token=other).status_code == 200  # someone else's key is not affected
    clock["now"] = datetime(2026, 11, 8, 0, 0, tzinfo=KST)  # midnight KST
    assert call(client, path, token=small).status_code == 200


def test_per_minute_limits(client, token, clock, monkeypatch, upstream, store):
    monkeypatch.setattr(relay, "CALLS_PER_MINUTE", 2)
    fast = TestClient(relay.create_app(KEYS, store, fetch=upstream, clock=lambda: clock["tick"]))
    path = "/relay/vworld/req/search"
    assert [call(fast, path, token=token).status_code for _ in range(3)] == [200, 200, 429]
    clock["tick"] = 61.0
    assert call(fast, path, token=token).status_code == 200


def test_usage_is_counted_per_key_and_service_without_queries(client, store, upstream, token):
    call(client, "/relay/vworld/req/search", {"query": "무교동 45"}, token)
    upstream.reply = relay.Upstream(500, "text/plain", b"down")
    call(client, "/relay/law/DRF/lawSearch.do", {"target": "aiSearch", "query": "직통계단"}, token)
    assert store.usage() == [("2026-11-07", "지훈", "law", 1, 1), ("2026-11-07", "지훈", "vworld", 1, 0)]
    dumped = "\n".join(store._db.iterdump())
    assert "무교동" not in dumped and "직통계단" not in dumped and token not in dumped  # only the key's hash


def test_a_service_without_a_server_key_says_so(store, upstream, token):
    bare = TestClient(relay.create_app(relay.Keys(vworld="vw-server-key"), store, fetch=upstream))
    assert bare.get("/relay/health").json() == {"ok": True, "services": {"vworld": True, "datago": False, "law": False}}
    assert call(bare, "/relay/law/DRF/lawSearch.do", {"target": "aiSearch"}, token).status_code == 503
    assert upstream.calls == []


def test_overlong_parameters_are_refused(client, upstream, token):
    r = call(client, "/relay/vworld/req/data", {"geomFilter": "x" * (relay.MAX_PARAM_CHARS + 1)}, token)
    assert r.status_code == 400 and upstream.calls == []


def test_keys_come_from_the_environment():
    keys = relay.Keys.from_env({"VWORLD_API_KEY": " k ", "VWORLD_DOMAIN": "https://d", "LAW_OPEN_API_OC": "oc"})
    assert keys == relay.Keys(vworld="k", vworld_domain="https://d", datago="", law="oc")
