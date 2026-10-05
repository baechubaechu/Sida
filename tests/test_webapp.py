"""webapp.py — JSON API and HTML pages, exercised without a browser."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sida import config as sida_config
from sida import errors, providers, runtime, webapp
from sida.project import section_body


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
    monkeypatch.setattr("sida.setup_env.read_api_key_from_env", lambda: "")
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


def test_core_failure_becomes_http_error_not_server_exit(client, monkeypatch, capsys):
    def broken(*_a, **_k):
        errors.fail("config.yaml이 깨졌습니다")

    monkeypatch.setattr(sida_config, "load_config", broken)
    r = client.get("/api/projects")
    assert r.status_code == 500 and "config.yaml이 깨졌습니다" in r.json()["detail"]
    assert client.get("/api/health").status_code == 200
    assert capsys.readouterr() == ("", "")


def test_save_failure_returns_http_error_and_server_stays_available(client, monkeypatch, capsys):
    def locked(*_args):
        raise PermissionError("simulated locked file")

    monkeypatch.setattr("os.replace", locked)
    response = client.post("/api/projects", json={"name": "locked-project"})
    assert response.status_code == 500
    assert "simulated locked file" in response.json()["detail"]
    assert client.get("/api/health").json()["ok"] is True
    assert capsys.readouterr() == ("", "")


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


@pytest.mark.parametrize("kind", ["brief", "state"])
def test_document_api_edits_and_rejects_stale_save(client, project, kind):
    url = f"/api/projects/{project.name}/documents/{kind}"
    before_session = project.session_path.read_bytes()
    original = client.get(url).json()
    assert set(original) == {"kind", "content", "revision"}
    assert project.session_path.read_bytes() == before_session  # GET never opens/touches the session
    body = {
        "content": original["content"] + "\n## 사용자 작성 항목\n- 보존할 내용\n",
        "expected_revision": original["revision"],
    }
    saved = client.put(url, json=body)
    assert saved.status_code == 200
    assert "보존할 내용" in saved.json()["content"]
    assert client.put(url, json=body).status_code == 409
    assert client.get(url).json() == saved.json()


def test_document_api_rejects_bad_kind_and_missing_project(client, project):
    assert client.get(f"/api/projects/{project.name}/documents/history").status_code == 400
    assert client.get("/api/projects/missing/documents/state").status_code == 404
    project.state_path.unlink()
    assert client.get(f"/api/projects/{project.name}/documents/state").status_code == 404


@pytest.fixture
def state_api(client, project, agents, monkeypatch):
    # This feature never needs a real API key or provider in tests.
    monkeypatch.setattr(runtime, "load_env", lambda **_kw: "")
    (project.modules_dir / agents[0]["output"]).write_text("analysis", encoding="utf-8")
    return client, f"/api/projects/{project.name}", agents[0]


@pytest.mark.parametrize("decision", ["apply", "skip"])
def test_state_api_requires_explicit_decision_and_blocks_replay(state_api, project, decision):
    from sida.state_revisions import module_revisions

    client, base, agent = state_api
    before = project.state_path.read_bytes()
    response = client.post(f"{base}/state-proposals", json={"agent": agent["id"]})
    assert response.status_code == 200
    proposal = response.json()["proposal"]
    assert set(proposal) == {"id", "agent", "diff"}
    assert "sida-module-revisions" not in proposal["diff"]
    assert project.state_path.read_bytes() == before
    url = f"{base}/state-proposals/{proposal['id']}/{decision}"
    result = client.post(url)
    assert result.status_code == 200
    if decision == "apply":
        assert result.json()["applied"] is True
        assert "sida-module-revisions" not in result.json()["document"]["content"]
        assert agent["id"] in module_revisions(project.read_state())
        assert (project.path / "project_state.prev.md").read_bytes() == before
    else:
        assert result.json() == {"skipped": True}
        assert project.state_path.read_bytes() == before
        assert module_revisions(project.read_state()) == {}
    assert client.post(url).status_code == 409


@pytest.mark.parametrize("source", ["state", "brief", "module"])
def test_state_api_rejects_approval_after_source_changes(state_api, project, source):
    client, base, agent = state_api
    proposal = client.post(f"{base}/state-proposals", json={"agent": agent["id"]}).json()["proposal"]
    if source == "module":
        (project.modules_dir / agent["output"]).write_text("new analysis", encoding="utf-8")
    else:
        url = f"{base}/documents/{source}"
        original = client.get(url).json()
        assert client.put(url, json={
            "content": original["content"] + "\nchanged\n",
            "expected_revision": original["revision"],
        }).status_code == 200
    before = project.state_path.read_bytes()
    response = client.post(f"{base}/state-proposals/{proposal['id']}/apply")
    assert response.status_code == 409
    assert project.state_path.read_bytes() == before


def test_state_api_replacement_invalidates_previous_approval(state_api):
    client, base, agent = state_api
    old = client.post(f"{base}/state-proposals", json={"agent": agent["id"]}).json()["proposal"]
    new = client.post(f"{base}/state-proposals", json={"agent": agent["id"]}).json()["proposal"]
    assert old["id"] != new["id"]
    assert client.post(f"{base}/state-proposals/{old['id']}/apply").status_code == 409
    assert client.post(f"{base}/state-proposals/{new['id']}/apply").status_code == 200


def test_state_api_approval_cannot_cross_project(state_api, mock_config):
    from sida.project import create_blank_project

    client, base, agent = state_api
    other = create_blank_project("other", config=mock_config)
    proposal = client.post(f"{base}/state-proposals", json={"agent": agent["id"]}).json()["proposal"]
    response = client.post(f"/api/projects/{other.name}/state-proposals/{proposal['id']}/apply")
    assert response.status_code == 409
    assert client.post(f"{base}/state-proposals/{proposal['id']}/apply").status_code == 200


@pytest.mark.parametrize("agent_id", ["nope", "program_analyst"])
def test_state_api_rejects_unknown_or_unrun_expert(state_api, agent_id):
    client, base, _agent = state_api
    assert client.post(f"{base}/state-proposals", json={"agent": agent_id}).status_code == 400


def test_state_api_reports_provider_error_without_writing_state(state_api, project, monkeypatch):
    from sida import engine

    client, base, agent = state_api
    before = project.state_path.read_bytes()

    def broken(*_args):
        raise providers.LLMError("provider unavailable")

    monkeypatch.setattr(engine, "propose_state", broken)
    response = client.post(f"{base}/state-proposals", json={"agent": agent["id"]})
    assert response.status_code == 502
    assert "provider unavailable" in response.json()["detail"]
    assert project.state_path.read_bytes() == before
    assert client.get("/api/health").status_code == 200


def test_state_api_no_change_returns_no_pending_approval(state_api, monkeypatch):
    from sida import engine

    client, base, agent = state_api
    monkeypatch.setattr(engine, "propose_state", lambda *_args: None)
    assert client.post(f"{base}/state-proposals", json={"agent": agent["id"]}).json() == {"proposal": None}


def test_document_api_writes_keep_cross_site_guard(client, project):
    url = f"/api/projects/{project.name}/documents/brief"
    original = client.get(url).json()
    headers = {"origin": "https://evil.example"}
    assert client.put(url, headers=headers, json={
        "content": "x", "expected_revision": original["revision"],
    }).status_code == 403
    assert client.post(
        f"/api/projects/{project.name}/state-proposals", headers=headers,
        json={"agent": "site_reader"},
    ).status_code == 403


# --- site domain API (sida/experts/site/api.py, registered through hooks.api_router) -----


def test_site_ordinance_api_lists_groups_and_saves_dismissals(client, project, fake_vworld):
    from sida.experts.site import landapi, site_facts

    url = f"/api/projects/{project.name}/site/ordinance"
    empty = client.get(url).json()
    assert empty["available"] is False and empty["groups"] == []

    parcel = landapi.search_parcels("경기도 군포시 금정동 689")[:1]
    facts = site_facts.attach_ordinance(site_facts.build_facts("금정동 689-14", parcel))
    site_facts.save_facts(project.path, facts)

    body = client.get(url).json()
    assert body["available"] and body["name"] == "군포시 도시계획 조례"
    assert body["base"][0]["far"]["value"] == 350 and "100분의 350" in body["base"][0]["far"]["quote"]
    assert [g["id"] for g in body["groups"]] == ["site", "design", "admin"]
    design = {i["id"]: i for i in body["groups"][1]["items"]}
    assert design["제52조"]["dismissed"] is False and "제52조(건폐율의 완화)" in design["제52조"]["text"]

    r = client.put(f"{url}/options/제52조", json={"dismissed": True})
    assert r.status_code == 200
    assert {i["id"]: i for i in r.json()["groups"][1]["items"]}["제52조"]["dismissed"] is True
    assert {i["id"]: i for i in client.get(url).json()["groups"][1]["items"]}["제52조"]["dismissed"] is True
    assert client.put(f"{url}/options/제52조", json={"dismissed": False}).status_code == 200

    picked = client.put(f"{url}/options/제52조", json={"detailed": True}).json()
    item = {i["id"]: i for i in picked["groups"][1]["items"]}["제52조"]
    assert item["detailed"] is True and item["dismissed"] is False
    assert "source: 군포시 도시계획 조례 제52조" in site_facts.ordinance_block(site_facts.load_facts(project.path))

    assert client.put(f"{url}/options/제999조", json={"dismissed": True}).status_code == 404
    assert client.put(f"{url}/options/제52조", json={}).status_code == 422
    assert client.get("/api/projects/nope/site/ordinance").status_code == 404
