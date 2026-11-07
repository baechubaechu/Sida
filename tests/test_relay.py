"""relay.py — where the Sida relay is, and the access key the app sends it."""

from __future__ import annotations

import pytest

from sida import relay

TOKEN = "sida_test-access-key-0001"


@pytest.fixture
def relayed(monkeypatch):
    monkeypatch.setenv(relay.ENV_NAME, "https://sida-kr.duckdns.org")
    monkeypatch.setenv(relay.TOKEN_ENV, TOKEN)


def test_only_https_addresses_or_this_pc_are_taken():
    assert relay.valid_url("https://sida-kr.duckdns.org")
    assert relay.valid_url("http://localhost:8000") and relay.valid_url("http://127.0.0.1:8000")
    for bad in ("", "sida-kr.duckdns.org", "http://sida-kr.duckdns.org", "ftp://x.kr",
                "https://u:p@x.kr", "https://x.kr/?key=1", "https://"):
        assert not relay.valid_url(bad), bad


def test_access_keys_look_like_the_ones_the_relay_makes():
    assert relay.valid_token(TOKEN)
    for bad in ("", "sida_", "abc_1234567890", "sida_has space", "sida_" + "x" * 100, "sida_한글키입니다아"):
        assert not relay.valid_token(bad), bad


def test_the_relay_is_used_only_with_both_an_address_and_a_key(monkeypatch):
    assert relay.base_url() == ""  # tests start with no relay
    monkeypatch.setenv(relay.ENV_NAME, " https://sida-kr.duckdns.org/ ")
    assert relay.base_url() == ""  # no access key yet
    monkeypatch.setenv(relay.TOKEN_ENV, TOKEN)
    assert relay.base_url() == "https://sida-kr.duckdns.org"
    monkeypatch.setenv(relay.ENV_NAME, "http://sida-kr.duckdns.org")  # plain http only for this PC
    assert relay.base_url() == ""


def test_the_access_key_goes_only_to_the_relay(relayed):
    assert relay.headers("https://sida-kr.duckdns.org/relay/vworld/req/search") == {"Authorization": f"Bearer {TOKEN}"}
    assert relay.headers("https://api.vworld.kr/req/search") == {}
    assert relay.headers("https://sida-kr.duckdns.org.evil.kr/relay/x") == {}
