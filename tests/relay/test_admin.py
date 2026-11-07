"""relay/admin.py and relay/tokens.py — making, listing and revoking access keys."""

from __future__ import annotations

import io
from datetime import datetime

import pytest

from relay import admin
from relay.tokens import KST, TokenStore


@pytest.fixture
def store(tmp_path):
    return TokenStore(tmp_path / "relay.db", now=lambda: datetime(2026, 11, 7, 12, 0, tzinfo=KST))


def run(store, *argv):
    out = io.StringIO()
    code = admin.main(list(argv), store=store, out=out)
    return code, out.getvalue()


def test_issue_shows_the_key_once_and_keeps_only_its_hash(store):
    code, text = run(store, "issue", "홍길동 (OO대)", "--limit", "500", "--days", "30")
    assert code == 0
    key = text.split("키(지금 한 번만 보입니다): ")[1].strip()
    assert key.startswith("sida_") and len(key) > 30
    record = store.find(key)
    assert (record.name, record.daily_limit, record.expires) == ("홍길동 (OO대)", 500, "2026-12-07")
    assert key not in "\n".join(store._db.iterdump())
    _code, listed = run(store, "list")
    assert "홍길동 (OO대)" in listed and "사용 중" in listed and key not in listed


def test_revoke_and_limit(store):
    _key, record = store.issue("베타")
    assert run(store, "limit", record.id, "100") == (0, f"{record.id}: 하루 100회\n")
    assert run(store, "revoke", record.id)[0] == 0
    assert run(store, "revoke", record.id)[0] == 1  # already revoked
    assert "폐기" in run(store, "list")[1] and store.get(record.id).daily_limit == 100
    assert run(store, "limit", "nope", "5")[0] == 1


def test_names_and_limits_are_checked(store):
    with pytest.raises(ValueError):
        store.issue("  ")
    with pytest.raises(ValueError):
        store.issue("x", daily_limit=0)


def test_key_requests_are_listed_approved_and_refused(store):
    _claim, first = store.request("김철수 (OO대)", "kim@example.com")
    _claim, second = store.request("모르는 사람")
    code, text = run(store, "requests")
    assert code == 0 and "김철수 (OO대)" in text and "kim@example.com" in text and "모르는 사람" in text
    assert "기다리는 키 요청 2건" in run(store, "list")[1]
    assert run(store, "approve", first.id, "--limit", "500", "--days", "30")[0] == 0
    assert run(store, "approve", first.id)[0] == 1  # already answered
    assert run(store, "refuse", second.id)[0] == 0
    assert run(store, "refuse", "nope")[0] == 1
    assert run(store, "requests")[1] == "기다리는 요청이 없습니다.\n"
    everything = run(store, "requests", "--all")[1]
    assert "승인(아직 안 받아 감)" in everything and "거절" in everything
    assert (store.get_request(first.id).daily_limit, store.get_request(first.id).days) == (500, 30)
