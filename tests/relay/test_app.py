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
    assert bare.get("/relay/health").json() == {"ok": True, "services": {"vworld": True, "datago": False, "law": False,
                                                                         "vworld3d": True}}  # the VWorld key serves 3D too
    assert call(bare, "/relay/law/DRF/lawSearch.do", {"target": "aiSearch"}, token).status_code == 503
    assert upstream.calls == []


def test_overlong_parameters_are_refused(client, upstream, token):
    r = call(client, "/relay/vworld/req/data", {"geomFilter": "x" * (relay.MAX_PARAM_CHARS + 1)}, token)
    assert r.status_code == 400 and upstream.calls == []


def test_keys_come_from_the_environment():
    keys = relay.Keys.from_env({"VWORLD_API_KEY": " k ", "VWORLD_DOMAIN": "https://d", "LAW_OPEN_API_OC": "oc"})
    assert keys == relay.Keys(vworld="k", vworld_domain="https://d", datago="", law="oc")
    assert keys.webgl3d == "k"  # without a key of its own, the 3D map uses the server's VWorld key
    keys = relay.Keys.from_env({"VWORLD_API_KEY": "kkkkkk", "VWORLD_3D_API_KEY": " k3d-key "})
    assert (keys.vworld, keys.webgl3d) == ("kkkkkk", "k3d-key")
    assert "k3d-key" not in keys.secrets()  # the 3D key is in viewers' browsers anyway


STATIC_COPIES = ("vworld3d.html", "vworld3d-frame.js")


@pytest.mark.parametrize("name", STATIC_COPIES)
def test_the_relay_serves_the_same_3d_page_as_the_app(name):
    # the relay's image is built from relay/ only, so it keeps copies of the app's 3D page
    app_file = relay.STATIC.parents[1] / "webui" / "app" / name
    assert (relay.STATIC / name).read_bytes() == app_file.read_bytes(), f"copy webui/app/{name} to relay/static/"


def test_the_3d_page_needs_an_access_key_and_carries_the_3d_key(client, store, upstream, token):
    assert client.get("/relay/vworld3d").status_code == 401
    assert client.get("/relay/vworld3d", params={"sida_token": "sida_made-up"}).status_code == 401
    r = client.get("/relay/vworld3d", params={"sida_token": token})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    script = "https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=vw-server-key"
    assert f'window.SIDA_VWORLD_SCRIPT = "{script}";' in page
    # the address is set before the page's own script loads VWorld's, and the rest is the app's page
    assert page.index("SIDA_VWORLD_SCRIPT =") < page.index("window.SIDA_VWORLD_SCRIPT ||")
    assert '<script src="./vworld3d-frame.js"></script>' in page and token not in page
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "origin"  # VWorld never sees the access key in the address
    assert r.headers["content-security-policy"] == "frame-ancestors 'self' http://localhost:* http://127.0.0.1:*"
    assert upstream.calls == [] and store.usage() == []  # not an API call: VWorld's viewer loads the map
    store.revoke(store.find(token).id)
    assert client.get("/relay/vworld3d", params={"sida_token": token}).status_code == 403


def test_the_3d_page_uses_the_3d_key_and_needs_one(store, upstream, token):
    own = TestClient(relay.create_app(relay.Keys(vworld="vw-server-key", vworld3d="vw-3d-key"), store, fetch=upstream))
    page = own.get("/relay/vworld3d", params={"sida_token": token}).text
    assert "apiKey=vw-3d-key" in page and "vw-server-key" not in page
    bare = TestClient(relay.create_app(relay.Keys(datago="dg"), store, fetch=upstream))
    assert bare.get("/relay/vworld3d", params={"sida_token": token}).status_code == 503


def test_the_3d_key_is_written_into_the_page_safely():
    page = relay.webgl3d_page('k"</script><script>alert(1)//')
    assert "</script><script>alert" not in page and "\\u003c/script>" in page


def test_the_3d_page_script_needs_no_key(client):
    r = client.get("/relay/vworld3d-frame.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert r.content == (relay.STATIC / "vworld3d-frame.js").read_bytes()


def test_a_key_request_is_collected_by_the_app_once_after_approval(client, store, upstream):
    r = client.post("/relay/requests", json={"name": "  김 철수 ", "contact": "kim@example.com"})
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    sent = r.json()
    assert sent["state"] == "pending" and sent["claim"].startswith("sidareq_")
    assert store.get_request(sent["id"]).name == "김 철수"
    claim = {"claim": sent["claim"]}
    assert client.post("/relay/requests/claim", json=claim).json() == {"id": sent["id"], "state": "pending"}

    assert store.approve(sent["id"], daily_limit=500, days=30)
    got = client.post("/relay/requests/claim", json=claim).json()
    assert got["state"] == "delivered" and got["key"].startswith("sida_")
    record = store.find(got["key"])
    assert (record.name, record.daily_limit, record.expires) == ("김 철수", 500, "2026-12-07")
    assert call(client, "/relay/vworld/req/search", token=got["key"]).status_code == 200
    # the key is given only once; the claim code and the key are kept only as hashes
    assert client.post("/relay/requests/claim", json=claim).json() == {"id": sent["id"], "state": "delivered"}
    dumped = "\n".join(store._db.iterdump())
    assert sent["claim"] not in dumped and got["key"] not in dumped


def test_a_refused_or_unknown_request_gets_no_key(client, store):
    sent = client.post("/relay/requests", json={"name": "모르는 사람"}).json()
    assert store.refuse(sent["id"]) and not store.approve(sent["id"])
    assert client.post("/relay/requests/claim", json={"claim": sent["claim"]}).json() == {"id": sent["id"], "state": "refused"}
    assert client.post("/relay/requests/claim", json={"claim": "sidareq_made-up"}).status_code == 404
    assert client.post("/relay/requests/claim", json={"claim": "sida_not-a-claim"}).status_code == 404
    assert store.all() == []


def test_key_requests_are_limited_per_address_and_checked(client, store, clock):
    assert client.post("/relay/requests", json={"name": " "}).status_code == 400
    assert client.post("/relay/requests", json={"name": "x", "contact": "c" * 121}).status_code == 422
    assert client.post("/relay/requests", json={"name": "x", "extra": 1}).status_code == 422
    codes = [client.post("/relay/requests", json={"name": f"사람 {i}"}).status_code for i in range(5)]
    assert codes == [201, 201, 201, 201, 429]  # 5 an hour; the blank name above counted too
    other = client.post("/relay/requests", json={"name": "다른 곳"}, headers={"X-Forwarded-For": "10.0.0.9"})
    assert other.status_code == 201
    clock["tick"] = 3601.0
    assert client.post("/relay/requests", json={"name": "한 시간 뒤"}).status_code == 201


def test_too_many_waiting_requests_are_refused(client, store, monkeypatch):
    monkeypatch.setattr("relay.tokens.MAX_PENDING_REQUESTS", 1)
    assert client.post("/relay/requests", json={"name": "첫째"}).status_code == 201
    r = client.post("/relay/requests", json={"name": "둘째"}, headers={"X-Forwarded-For": "10.0.0.9"})
    assert r.status_code == 429
