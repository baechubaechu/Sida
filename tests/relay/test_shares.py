"""relay/shares.py and the share routes of relay/app.py: uploading, limits, the viewer, comments."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relay import app as relay
from relay.shares import MB, Limits, ShareStore, read_snapshot
from relay.tokens import KST, TokenStore

ROOT = Path(__file__).resolve().parents[2]
VIEWER = ROOT / "webui" / "app"


def snapshot_zip(title="무교동 45", by="김시다", photos=None, extra=None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("snapshot.json", json.dumps({"format": 1, "title": title, "by": by, "board": {"papers": []}}))
        for name, body in (photos or {}).items():
            z.writestr(name, body)
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    return out.getvalue()


@pytest.fixture
def clock():
    return {"now": datetime(2026, 11, 18, 10, 0, tzinfo=KST), "tick": 0.0}


@pytest.fixture
def tokens(tmp_path, clock):
    return TokenStore(tmp_path / "relay.db", now=lambda: clock["now"])


@pytest.fixture
def shares(tmp_path, clock):
    return ShareStore(tmp_path / "shares", now=lambda: clock["now"])


@pytest.fixture
def key(tokens):
    return tokens.issue("김시다")[0]


@pytest.fixture
def client(tokens, shares, clock):
    app = relay.create_app(relay.Keys(), tokens, fetch=lambda *a: None, clock=lambda: clock["tick"],
                           shares=shares, viewer_dir=VIEWER)
    return TestClient(app)


def upload(client, key, data=None, share_id=""):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/zip"}
    body = data if data is not None else snapshot_zip()
    if share_id:
        return client.put(f"/relay/shares/{share_id}", content=body, headers=headers)
    return client.post("/relay/shares", content=body, headers=headers)


def test_upload_gives_two_links_and_the_viewer_reads_the_snapshot(client, key):
    made = upload(client, key, snapshot_zip(photos={"photos/p1.jpg": b"\xff\xd8jpeg"}))
    assert made.status_code == 201
    share = made.json()
    assert share["latest"] == 1 and share["comment_link"] != share["view_link"]
    assert share["expires"].startswith("2026-12-18")
    page = client.get(f"/s/{share['comment_link']}")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "noindex" in page.headers["x-robots-tag"] and "frame-ancestors 'none'" in page.headers["content-security-policy"]
    info = client.get(f"/s/{share['view_link']}/info").json()
    assert info["title"] == "무교동 45" and info["by"] == "김시다" and info["can_comment"] is False
    assert "comment_link" not in info and "id" not in info  # a viewer never sees the links or the owner
    assert client.get(f"/s/{share['comment_link']}/info").json()["can_comment"] is True
    snap = client.get(f"/s/{share['view_link']}/v/1/snapshot.json")
    assert snap.json()["title"] == "무교동 45"
    assert client.get(f"/s/{share['view_link']}/v/1/photos/p1.jpg").content == b"\xff\xd8jpeg"
    assert client.get(f"/s/{share['view_link']}/v/1/photos/p2.jpg").status_code == 404
    assert client.get(f"/s/{share['view_link']}/v/9/snapshot.json").status_code == 404


def test_upload_needs_a_known_key(client, tokens):
    assert client.post("/relay/shares", content=snapshot_zip()).status_code == 401
    assert upload(client, "sida_unknown_key_123").status_code == 401
    token, record = tokens.issue("누군가")
    tokens.revoke(record.id)
    assert upload(client, token).status_code == 403


@pytest.mark.parametrize("extra", [{"../evil.txt": b"x"}, {"photos/a.exe": b"x"}, {"terrain.json": b"{}"}],
                         ids=["parent", "exe", "terrain"])
def test_only_the_snapshot_and_photos_are_taken(extra):
    with pytest.raises(ValueError):
        read_snapshot(snapshot_zip(extra=extra), 20 * MB)


def test_a_snapshot_without_its_json_or_not_a_zip_is_refused(client, key):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("photos/a.jpg", b"x")
    assert upload(client, key, out.getvalue()).status_code == 400
    assert upload(client, key, b"not a zip").status_code == 400


def test_a_new_version_keeps_the_links_and_old_versions_go_when_the_share_is_full(tmp_path, clock, tokens, key):
    store = ShareStore(tmp_path / "s", limits=Limits(share_bytes=4 * MB), now=lambda: clock["now"])
    client = TestClient(relay.create_app(relay.Keys(), tokens, shares=store, viewer_dir=VIEWER))
    big = b"x" * (MB + MB // 2)
    first = upload(client, key, snapshot_zip(photos={"photos/a.jpg": big})).json()
    second = upload(client, key, snapshot_zip(title="새 이름", photos={"photos/a.jpg": big}), first["id"]).json()
    assert second["comment_link"] == first["comment_link"] and second["title"] == "새 이름"
    assert [v["number"] for v in second["versions"]] == [1, 2]
    third = upload(client, key, snapshot_zip(photos={"photos/a.jpg": big}), first["id"]).json()
    assert [v["number"] for v in third["versions"]] == [2, 3]  # 1 dropped to make room
    assert client.get(f"/s/{first['view_link']}/v/1/snapshot.json").status_code == 404


def test_limits_on_shares_at_a_time_new_shares_per_period_and_uploads_per_day(tmp_path, clock, tokens, key):
    store = ShareStore(tmp_path / "s", limits=Limits(owner_shares=2, new_shares=3, uploads_per_day=5),
                       now=lambda: clock["now"])
    client = TestClient(relay.create_app(relay.Keys(), tokens, shares=store, viewer_dir=VIEWER))
    a = upload(client, key).json()
    upload(client, key)
    full = upload(client, key)
    assert full.status_code == 429 and full.json()["detail"]["code"] == "owner_shares"
    # deleting does not give the period's new shares back
    client.delete(f"/relay/shares/{a['id']}", headers={"Authorization": f"Bearer {key}"})
    assert upload(client, key).status_code == 201
    clock["now"] += timedelta(hours=1)
    b = client.get("/relay/shares", headers={"Authorization": f"Bearer {key}"}).json()["shares"][0]
    client.delete(f"/relay/shares/{b['id']}", headers={"Authorization": f"Bearer {key}"})
    period = upload(client, key)
    assert period.status_code == 429 and period.json()["detail"]["code"] == "new_shares"
    clock["now"] += timedelta(days=15)
    c = upload(client, key).json()
    for _ in range(4):
        upload(client, key, share_id=c["id"])
    day = upload(client, key, share_id=c["id"])
    assert day.status_code == 429 and day.json()["detail"]["code"] == "uploads_per_day"
    usage = client.get("/relay/shares", headers={"Authorization": f"Bearer {key}"}).json()["usage"]
    assert usage["uploads_today"] == 5 and usage["limits"]["new_shares"] == 3


def test_limits_come_from_the_environment():
    limits = Limits.from_env({"SIDA_SHARE_NEW_SHARES": "4", "SIDA_SHARE_SHARE_BYTES": "30"})
    assert limits.new_shares == 4 and limits.share_bytes == 30 * MB and limits.period_days == 14
    with pytest.raises(ValueError):
        Limits.from_env({"SIDA_SHARE_PERIOD_DAYS": "0"})


def test_another_designer_cannot_touch_a_share(client, key, tokens):
    share = upload(client, key).json()
    other = tokens.issue("다른 사람")[0]
    for method in ("get", "delete"):
        assert getattr(client, method)(f"/relay/shares/{share['id']}",
                                       headers={"Authorization": f"Bearer {other}"}).status_code == 404
    assert upload(client, other, share_id=share["id"]).status_code == 404


def test_comments_from_the_comment_link_with_a_spot_and_replies(client, key):
    share = upload(client, key).json()
    link = share["comment_link"]
    made = client.post(f"/s/{link}/comments", json={
        "name": "이OO 교수", "text": "타워가 높네요", "version": 1, "target": "mass-b#0",
        "at": {"x": 3.5, "y": -2, "z": 45},
    })
    assert made.status_code == 201
    comment = made.json()
    assert comment["at"] == {"x": 3.5, "y": -2.0, "z": 45.0} and comment["target"] == "mass-b#0"
    reply = client.post(f"/relay/shares/{share['id']}/comments", json={"text": "스카이라인 올리겠습니다", "parent": comment["id"]},
                        headers={"Authorization": f"Bearer {key}"}).json()
    assert reply["by_owner"] is True and reply["author"] == "김시다" and reply["parent"] == comment["id"]
    again = client.post(f"/s/{link}/comments", json={"name": "이OO 교수", "text": "좋아요", "parent": reply["id"]}).json()
    assert again["parent"] == comment["id"]  # a reply to a reply hangs under the first comment
    seen = client.get(f"/s/{share['view_link']}/comments").json()["comments"]
    assert [c["text"] for c in seen] == ["타워가 높네요", "스카이라인 올리겠습니다", "좋아요"]
    # the look-only link cannot comment
    assert client.post(f"/s/{share['view_link']}/comments", json={"name": "a", "text": "b"}).status_code == 403


def test_comment_checks(client, key):
    share = upload(client, key).json()
    link = share["comment_link"]
    assert client.post(f"/s/{link}/comments", json={"name": "", "text": "x"}).status_code == 400
    assert client.post(f"/s/{link}/comments", json={"name": "a", "text": " "}).status_code == 400
    assert client.post(f"/s/{link}/comments", json={"name": "a", "text": "x", "version": 7}).status_code == 400
    assert client.post(f"/s/{link}/comments", json={"name": "a", "text": "x", "version": True}).status_code == 400
    assert client.post(f"/s/{link}/comments", json={"name": "a", "text": "x", "at": {"x": "1"}}).status_code == 400
    assert client.post(f"/s/{link}/comments", json={"name": "a", "text": "x", "parent": "c_000000000000"}).status_code == 400


def test_comments_per_minute_are_limited(client, key, clock):
    link = upload(client, key).json()["comment_link"]
    sent = [client.post(f"/s/{link}/comments", json={"name": "a", "text": str(i)}).status_code for i in range(7)]
    assert sent[:6] == [201] * 6 and sent[6] == 429
    clock["tick"] += 61
    assert client.post(f"/s/{link}/comments", json={"name": "a", "text": "again"}).status_code == 201


def test_the_designer_closes_comments_changes_links_resolves_and_deletes(client, key):
    share = upload(client, key).json()
    auth = {"Authorization": f"Bearer {key}"}
    first = client.post(f"/s/{share['comment_link']}/comments", json={"name": "a", "text": "의견"}).json()
    client.post(f"/s/{share['comment_link']}/comments", json={"name": "b", "text": "답", "parent": first["id"]})
    closed = client.patch(f"/relay/shares/{share['id']}", json={"comments_open": False}, headers=auth).json()
    assert closed["comments_open"] is False
    assert client.post(f"/s/{share['comment_link']}/comments", json={"name": "a", "text": "x"}).status_code == 403
    assert client.patch(f"/relay/shares/{share['id']}/comments/{first['id']}", json={"resolved": True},
                        headers=auth).json()["resolved"] is True
    moved = client.patch(f"/relay/shares/{share['id']}", json={"new_links": True}, headers=auth).json()
    assert moved["comment_link"] != share["comment_link"]
    assert client.get(f"/s/{share['comment_link']}/info").status_code == 404  # the old link stops at once
    assert client.get(f"/s/{moved['comment_link']}/info").status_code == 200
    client.delete(f"/relay/shares/{share['id']}/comments/{first['id']}", headers=auth)
    assert client.get(f"/relay/shares/{share['id']}/comments", headers=auth).json()["comments"] == []  # replies too
    assert client.delete(f"/relay/shares/{share['id']}", headers=auth).status_code == 200
    assert client.get(f"/s/{moved['view_link']}").status_code == 404


def test_a_share_is_deleted_a_retention_after_its_last_upload(client, key, clock, shares):
    share = upload(client, key).json()
    clock["now"] += timedelta(days=20)
    upload(client, key, share_id=share["id"])
    clock["now"] += timedelta(days=20)
    assert client.get(f"/s/{share['view_link']}/info").status_code == 200
    clock["now"] += timedelta(days=11)
    assert client.get(f"/s/{share['view_link']}/info").status_code == 404
    assert not (shares.root / "files" / share["id"]).exists()


def test_the_viewer_files_are_served_from_the_list_only(client):
    assert client.get("/s/share-view.js").status_code == 200
    assert client.get("/s/vendor/three.js").status_code == 200
    assert client.get("/s/app.js").status_code == 404  # the app's other screens are not served
    assert client.get("/s/unknownlink_aaaaaaaaaaaaaa").status_code == 404


def test_the_viewer_list_covers_every_module_the_viewer_imports():
    import re

    seen, todo = set(), ["share-view.js"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        text = (VIEWER / name).read_text(encoding="utf-8")
        for found in re.findall(r"""(?:import|from)\s*['"]\./([^'"]+)['"]""", text):
            todo.append(found)
    assert seen <= relay.VIEWER_FILES
    assert (VIEWER / "share.html").is_file()
    for link in re.findall(r"""(?:href|src)="\./([^"]+)\"""", (VIEWER / "share.html").read_text(encoding="utf-8")):
        assert link in relay.VIEWER_FILES


def test_no_sharing_without_a_share_folder(tokens, key):
    client = TestClient(relay.create_app(relay.Keys(), tokens))
    assert client.get("/relay/shares", headers={"Authorization": f"Bearer {key}"}).status_code == 503


def test_the_viewer_gets_the_parcel_boundaries_from_vworld_now_and_nothing_is_kept(tmp_path, tokens, shares, key):
    asked = []

    def vworld(url, params, headers):
        asked.append(params)
        body = {"response": {"status": "OK", "result": {"featureCollection": {"features": [
            {"properties": {"pnu": params["attrFilter"][6:]}, "geometry": {"type": "Polygon", "coordinates": [[[1, 2]]]}},
        ]}}}}
        return relay.Upstream(200, "application/json", json.dumps(body).encode())

    keys = relay.Keys(vworld="vw-server-key", vworld_domain="https://sida-kr.duckdns.org")
    client = TestClient(relay.create_app(keys, tokens, fetch=vworld, shares=shares, viewer_dir=VIEWER))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("snapshot.json", json.dumps({"title": "t", "site": {"plan": {"parcels": [
            {"pnu": "1114010300100450000"}, {"pnu": "not-a-pnu"}]}}}))
    share = upload(client, key, out.getvalue()).json()
    got = client.get(f"/s/{share['view_link']}/parcels").json()
    assert got == {"parcels": [{"pnu": "1114010300100450000", "shape": {"type": "Polygon", "coordinates": [[[1, 2]]]}}]}
    assert len(asked) == 1 and asked[0]["key"] == "vw-server-key" and asked[0]["attrFilter"] == "pnu:=:1114010300100450000"
    assert not any("vw-server-key" in p.read_bytes().decode("latin-1") for p in shares.root.rglob("*") if p.is_file())
