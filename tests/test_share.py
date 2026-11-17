"""sida/share.py and its JSON API, against the real relay server (relay/app.py) in memory."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from relay import app as relay_app
from relay.shares import ShareStore
from relay.tokens import KST, TokenStore
from sida import board, relay, share, webapp

SERVER = "http://127.0.0.1:9"
SITE = {
    "area_m2": 1000.0,
    "lines": ["대지: 필지 1개, 1,000㎡", "용도지역: 일반상업지역"],
    "rules": [{"label": "정북일조", "text": "적용 안 됨"}],
    "parcels": [{"pnu": "1114010300100450000", "address": "서울 중구 무교동 45", "area_m2": 1000.0,
                 "shape": {"type": "Polygon", "coordinates": [[[126.98, 37.568], [126.9803, 37.568],
                                                                [126.9803, 37.5683], [126.98, 37.5683], [126.98, 37.568]]]}}],
}


def picture(size=(3000, 1500), mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, (200, 100, 50, 255) if mode == "RGBA" else (200, 100, 50)).save(
        out, "PNG" if mode == "RGBA" else "JPEG")
    return out.getvalue()


@pytest.fixture
def server(tmp_path, monkeypatch):
    """The relay with sharing on, reached through share._http; a designer key in the settings."""
    now = {"at": datetime(2026, 11, 18, 10, 0, tzinfo=KST)}
    tokens = TokenStore(tmp_path / "relay.db", now=lambda: now["at"])
    key = tokens.issue("김시다")[0]
    store = ShareStore(tmp_path / "shares", now=lambda: now["at"])
    client = TestClient(relay_app.create_app(relay_app.Keys(), tokens, shares=store))
    calls = []

    def http(method, url, *, headers, data=None, json_body=None):
        assert url.startswith(SERVER)
        calls.append((method, url[len(SERVER):]))
        r = client.request(method, url[len(SERVER):], headers=headers, content=data, json=json_body)
        return r.status_code, r.json()

    monkeypatch.setattr(share, "_http", http)
    monkeypatch.setenv(relay.ENV_NAME, SERVER)
    monkeypatch.setenv(relay.TOKEN_ENV, key)
    return {"client": client, "calls": calls, "store": store, "key": key}


@pytest.fixture
def table(project, monkeypatch):
    """A project with a site, two schemes (one on a hidden layer), a note, a tracing and a photo."""
    monkeypatch.setattr(board, "site_summary", lambda path, hooks=None: SITE)
    path = project.path
    board.add_paper(path, {"id": "mass-a", "kind": "mass", "title": "A안", "blocks": [{"u": 0, "v": 0, "w": 20, "d": 15, "floors": 5}]})
    board.add_paper(path, {"id": "mass-b", "kind": "mass", "title": "B안", "layer": "secret",
                           "blocks": [{"u": 0, "v": 0, "w": 10, "d": 10, "floors": 15}]})
    board.add_paper(path, {"id": "note-1", "kind": "note", "text": "북쪽 일조 다시"})
    board.add_paper(path, {"id": "trace-1", "kind": "tracing", "strokes": [[[0, 0], [10, 10]]]})
    board.add_photo(path, picture(), {"title": "현장"})
    layers = board.load_board(path)["layers"] + [{"id": "secret", "name": "비공개", "parent": "", "visible": False}]
    board.set_layers(path, layers)
    return path


def test_the_snapshot_holds_shown_papers_the_site_card_and_small_photos_but_no_boundaries(table):
    data, made = share.build(table, by="김시다")
    archive = zipfile.ZipFile(io.BytesIO(data))
    snap = json.loads(archive.read("snapshot.json"))
    kinds = sorted(p["kind"] for p in snap["board"]["papers"])
    assert kinds == ["mass", "note", "photo", "site", "tracing"]  # B안 is on a hidden layer
    assert set(snap["board"]["figures"]) == {"mass-a"}
    assert snap["by"] == "김시다" and snap["address"] == "서울 중구 무교동 45"
    assert snap["site"]["lines"][1] == "용도지역: 일반상업지역"
    parcel = snap["site"]["plan"]["parcels"][0]
    assert parcel == {"pnu": "1114010300100450000", "address": "서울 중구 무교동 45", "area_m2": 1000.0}
    assert "rings" not in json.dumps(snap) and "shape" not in json.dumps(snap)  # VWorld's terms
    assert snap["site"]["plan"]["origin"]["lon"] == pytest.approx(126.98015)
    photo = next(p for p in snap["board"]["papers"] if p["kind"] == "photo")
    assert "file" not in photo and photo["photo"].startswith("photos/")
    shrunk = Image.open(io.BytesIO(archive.read(photo["photo"])))
    assert max(shrunk.size) == share.SHARE_PHOTO_EDGE
    assert made["papers"]["mass"] == 1 and made["photos"] == 1
    assert "talks" not in archive.namelist() and all(n == "snapshot.json" or n.startswith("photos/") for n in archive.namelist())


def test_photos_can_stay_home_and_left_out_kinds_are_counted(table):
    board.add_paper(table, {"id": "sec-1", "kind": "section", "line": [[0, -20], [0, 20]]})
    data, made = share.build(table, photos=False)
    snap = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("snapshot.json"))
    assert all(p["kind"] != "photo" for p in snap["board"]["papers"])
    assert made["left_out"] == {"photo": 1, "section": 1} and made["photos"] == 0


def test_a_transparent_picture_stays_png():
    data, ext = share.shrink_photo(picture((400, 300), "RGBA"))
    assert ext == "png" and Image.open(io.BytesIO(data)).size == (400, 300)
    with pytest.raises(ValueError):
        share.shrink_photo(b"not a picture")


def test_publish_then_a_new_version_behind_the_same_links(table, server):
    first = share.publish(table, by="김시다")["share"]
    assert first["on"] and first["version"] == 1
    assert first["comment_url"].startswith(f"{SERVER}/s/") and first["view_url"] != first["comment_url"]
    again = share.publish(table)["share"]
    assert again["version"] == 2 and again["comment_url"] == first["comment_url"]
    assert [m for m, _ in server["calls"]] == ["POST", "PUT"]
    assert share.plan(table)["share"]["version"] == 2


def test_no_key_no_share(table):
    with pytest.raises(share.ShareError) as caught:
        share.publish(table)
    assert caught.value.code == "no_key" and "Sida 키" in caught.value.message
    assert share.plan(table)["has_key"] is False


def test_comments_come_back_and_stay_after_the_share_is_turned_off(table, server):
    made = share.publish(table, by="김시다")["share"]
    link = made["comment_url"].rsplit("/", 1)[1]
    client = server["client"]
    posted = client.post(f"/s/{link}/comments", json={"name": "이 교수", "text": "타워가 높네요", "version": 1,
                                                       "target": "mass-a#0", "at": {"x": 1, "y": 2, "z": 20}}).json()
    got = share.refresh_comments(table)
    assert [c["text"] for c in got["comments"]] == ["타워가 높네요"] and got["unread"] == 1
    assert share.plan(table)["share"]["unread"] == 1
    replied = share.reply(table, posted["id"], "스카이라인 같이 올리겠습니다")
    assert replied["comments"][1]["by_owner"] is True and replied["comments"][1]["author"] == "김시다"
    assert share.mark_seen(table, [posted["id"]])["unread"] == 0
    assert share.resolve(table, posted["id"], True)["comments"][0]["resolved"] is True
    off = share.stop(table)["share"]
    assert off["on"] is False
    assert client.get(f"/s/{link}/info").status_code == 404  # the server's copy is gone
    kept = share.cached_comments(table)
    assert len(kept["comments"]) == 2 and kept["on"] is False
    with pytest.raises(share.ShareError):
        share.reply(table, posted["id"], "더")
    assert share.delete_comment(table, posted["id"])["comments"] == []  # here only


def test_limits_come_back_in_the_designers_words(table, server, monkeypatch):
    monkeypatch.setattr(server["store"], "limits", server["store"].limits.__class__(uploads_per_day=1))
    share.publish(table)
    with pytest.raises(share.ShareError) as caught:
        share.publish(table)
    assert caught.value.status == 429 and "하루 1번" in caught.value.message


def test_a_share_gone_from_the_server_starts_again_on_publish(table, server):
    made = share.publish(table)
    state = share.load_state(table)
    server["store"].delete(state["id"])
    again = share.publish(table)["share"]
    assert again["version"] == 1 and again["comment_url"] != made["share"]["comment_url"]


def test_new_links_and_closing_comments(table, server):
    first = share.publish(table)["share"]
    moved = share.change(table, new_links=True)["share"]
    assert moved["comment_url"] != first["comment_url"]
    assert share.change(table, comments_open=False)["share"]["comments_open"] is False


# --- JSON API ----------------------------------------------------------------


@pytest.fixture
def client(mock_config):
    return TestClient(webapp.create_app(allowed_hosts={"testserver"}), follow_redirects=False)


def test_share_api(client, table, server, project):
    url = f"/api/projects/{project.name}/share"
    plan = client.get(url).json()
    assert plan["papers"] == {"site": 1, "mass": 1, "note": 1, "tracing": 1, "photo": 1}
    assert plan["share"]["on"] is False and plan["has_key"] is True
    made = client.post(url, json={"photos": False, "by": "김시다"}).json()
    assert made["share"]["on"] and made["made"]["photos"] == 0
    assert client.patch(url, json={"comments_open": False}).json()["share"]["comments_open"] is False
    comments = client.get(f"{url}/comments").json()
    assert comments == {"comments": [], "unread": 0, "seen": [], "on": True}
    assert client.post(f"{url}/comments", json={"parent": "c_000000000000", "text": "x"}).status_code == 400
    assert client.delete(url).json()["share"]["on"] is False


def test_share_api_without_a_key_says_so(client, table, project):
    response = client.post(f"/api/projects/{project.name}/share", json={})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "no_key"


def test_comments_api_falls_back_to_the_kept_ones_when_the_server_is_out_of_reach(client, table, server, project, monkeypatch):
    client.post(f"/api/projects/{project.name}/share", json={})

    def down(*a, **k):
        raise share.ShareError("Sida 자료 서버에 닿지 못했습니다.", 502)

    monkeypatch.setattr(share, "_http", down)
    got = client.get(f"/api/projects/{project.name}/share/comments").json()
    assert got["comments"] == [] and "닿지 못했습니다" in got["stale"]
