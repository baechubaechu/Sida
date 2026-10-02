"""webapp.py — JSON API and HTML pages, exercised without a browser."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import harness
import webapp
from project import section_body


@pytest.fixture
def client(mock_config):
    return TestClient(webapp.create_app(allowed_hosts={"testserver"}), follow_redirects=False)


# --- JSON API ----------------------------------------------------------------


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True, "app": "sida"}


def test_api_projects_empty_then_created(client, mock_config):
    body = client.get("/api/projects").json()
    assert body["projects"] == [] and body["root"].endswith("projects")

    r = client.post("/api/projects", json={"name": "성수 주택", "fields": {"type": "주택"}})
    assert r.status_code == 201
    assert r.json()["created"] is True and r.json()["project"]["name"] == "성수_주택"

    again = client.post("/api/projects", json={"name": "성수 주택"})
    assert again.status_code == 200 and again.json()["created"] is False

    names = [p["name"] for p in client.get("/api/projects").json()["projects"]]
    assert names == ["성수_주택"]


def test_api_create_rejects_empty_name(client):
    r = client.post("/api/projects", json={"name": "  "})
    assert r.status_code == 400
    assert client.get("/api/projects").json()["projects"] == []


def test_api_sample_and_detail(client, agents):
    r = client.post("/api/projects/sample")
    assert r.status_code == 201 and r.json()["project"]["name"] == "sample_brief"
    assert client.post("/api/projects/sample").status_code == 200

    detail = client.get("/api/projects/sample_brief").json()
    assert detail["brief"].startswith("#")
    assert [e["id"] for e in detail["experts"]] == [a["id"] for a in agents]
    assert not any(e["done"] for e in detail["experts"])


def test_api_unknown_project_is_404(client):
    r = client.get("/api/projects/nope")
    assert r.status_code == 404 and "nope" in r.json()["detail"]
    assert client.get("/api/projects/..%2F..%2Fsecret").status_code == 404


def test_api_runtime_reports_mode_and_missing_key(client, mock_config, monkeypatch):
    monkeypatch.setattr("setup_env.read_api_key_from_env", lambda: "")
    body = client.get("/api/runtime").json()
    assert body["conductor"]["provider"] == "mock"
    assert body["warnings"] == {"openrouter_key_missing": False, "rag_key_missing": False}

    mock_config["conductor"]["provider"] = "openrouter"
    mock_config["worker"]["provider"] = "openrouter"
    mock_config["rag"] = {"enabled": True, "provider": "lawgokr"}
    body = client.get("/api/runtime").json()
    assert body["mode"] == "cloud"
    assert body["warnings"] == {"openrouter_key_missing": True, "rag_key_missing": False}

    monkeypatch.delenv("LAW_OPEN_API_OC")
    warnings = client.get("/api/runtime").json()["warnings"]
    assert warnings == {"openrouter_key_missing": True, "rag_key_missing": True}
    assert "LAW_OPEN_API_OC" in client.get("/").text


def test_core_failure_becomes_http_error_not_server_exit(client, monkeypatch):
    def broken(*_a, **_k):
        harness.fail("config.yaml이 깨졌습니다")

    monkeypatch.setattr(harness, "load_config", broken)
    r = client.get("/api/projects")
    assert r.status_code == 500 and "config.yaml이 깨졌습니다" in r.json()["detail"]


# --- HTML pages --------------------------------------------------------------


def test_hub_page_lists_projects_and_form(client, project):
    html = client.get("/").text
    assert project.name in html
    assert 'action="/projects"' in html and 'name="name"' in html
    assert 'action="/projects/sample"' in html
    assert "프로젝트" in html and '<html lang="ko">' in html


def test_hub_form_creates_project_and_redirects(client, mock_config):
    r = client.post(
        "/projects",
        data={"name": "My House", "type": "주택", "issues": "경사, 소음", "driver": "idea"},
    )
    assert r.status_code == 303 and r.headers["location"] == "/p/my_house"

    page = client.get(r.headers["location"])
    assert page.status_code == 200 and "my_house" in page.text and "주택" in page.text

    brief = client.get("/api/projects/my_house").json()["brief"]
    assert section_body(brief, "Site Issues") == "- 경사\n- 소음"
    assert section_body(brief, "Primary Driver") == "idea"


def test_hub_form_empty_name_shows_error_and_keeps_input(client):
    r = client.post("/projects", data={"name": " ", "type": "도서관"})
    assert r.status_code == 400
    assert "프로젝트 이름을 입력하세요" in r.text
    assert "도서관" in r.text  # what the designer typed is not lost
    assert client.get("/api/projects").json()["projects"] == []


def test_sample_button_redirects_to_project(client):
    r = client.post("/projects/sample")
    assert r.status_code == 303 and r.headers["location"] == "/p/sample_brief"


def test_korean_project_name_round_trips_through_url(client):
    r = client.post("/projects", data={"name": "성수 주택"})
    assert r.status_code == 303
    assert client.get(r.headers["location"]).status_code == 200


def test_project_page_escapes_brief_content(client, project):
    project.brief_path.write_text(
        "# Brief\n\n## Project Type\n<script>alert(1)</script>\n", encoding="utf-8"
    )
    for url in ("/", webapp.project_url(project.name)):
        html = client.get(url).text
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_unknown_project_page_is_404_with_link_home(client):
    r = client.get("/p/nope")
    assert r.status_code == 404 and "nope" in r.text and 'href="/"' in r.text


def test_static_css_served(client):
    r = client.get("/static/app.css")
    assert r.status_code == 200 and "--accent" in r.text


# --- local-only guard --------------------------------------------------------


def test_foreign_host_and_cross_site_writes_are_refused(mock_config):
    local = TestClient(webapp.create_app(), follow_redirects=False)  # default: localhost only

    assert local.get("/api/health").status_code == 403  # Host: testserver
    ok = {"host": "127.0.0.1:8765"}
    assert local.get("/api/health", headers=ok).status_code == 200
    assert local.get("/api/health", headers={"host": "localhost:8765"}).status_code == 200
    assert local.get("/api/health", headers={"host": "evil.example"}).status_code == 403

    # A page on another site posting to the local server
    cross = {**ok, "origin": "https://evil.example"}
    assert local.post("/api/projects/sample", headers=cross).status_code == 403
    assert local.get("/api/projects", headers=ok).json()["projects"] == []

    same = {**ok, "origin": "http://127.0.0.1:8765"}
    assert local.post("/api/projects/sample", headers=same).status_code == 201
