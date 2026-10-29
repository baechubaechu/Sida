"""webapp.py — JSON API and HTML pages, exercised without a browser."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from sida import config as sida_config
from sida import engine, errors, providers, runtime, webapp
from sida.briefs import BRIEF_FIELD_KEYS
from tests.conftest import land_fixture


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
    # Screens show the Korean name; config.yaml `name` stays English for the models.
    assert detail["experts"][0]["name"] == "대지 분석가"
    tiers = {e["id"]: e["tier"] for e in detail["experts"]}
    assert tiers["site_reader"] == "core" and tiers["concept_framer"] == "held"


def test_api_unknown_project_is_404(client):
    r = client.get("/api/projects/nope")
    assert r.status_code == 404 and "nope" in r.json()["detail"]
    assert client.get("/api/projects/..%2F..%2Fsecret").status_code == 404


def test_api_delete_project_removes_it_from_the_list(client):
    for name in ("지울 프로젝트", "남길 프로젝트"):
        assert client.post("/api/projects", json={"name": name}).status_code == 201
    r = client.delete("/api/projects/지울_프로젝트")
    assert r.status_code == 200 and r.json() == {"deleted": "지울_프로젝트"}
    assert [p["name"] for p in client.get("/api/projects").json()["projects"]] == ["남길_프로젝트"]
    assert client.get("/api/projects/지울_프로젝트").status_code == 404
    assert client.delete("/api/projects/지울_프로젝트").status_code == 404
    assert client.delete("/api/projects/..%2F..%2Fsecret").status_code == 404


def test_api_runtime_reports_mode_and_missing_key(client, mock_config, monkeypatch):
    monkeypatch.setattr("sida.settings.read_key", lambda name: "")
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


@pytest.mark.parametrize(
    ("method", "url"),
    [("get", "/classic"), ("get", "/p/sample_brief"), ("post", "/projects"), ("post", "/projects/sample")],
)
def test_earlier_server_rendered_pages_are_gone(client, method, url):
    client.post("/api/projects/sample")
    assert getattr(client, method)(url).status_code in (404, 405)


def test_no_screen_links_to_the_removed_pages():
    screens = [*webapp.APP_DIR.glob("*.*"), *(webapp.WEB_DIR / "templates").glob("*.html")]
    assert screens
    for path in screens:
        assert "/classic" not in path.read_text(encoding="utf-8"), path.name


def test_static_css_served(client):
    r = client.get("/static/app.css")
    assert r.status_code == 200 and "--accent" in r.text


# --- main screen (webui/app) ---------------------------------------------------


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag, attrs):
        found = dict(attrs)
        if tag == "script" and found.get("src"):
            self.assets.append(found["src"])
        if tag == "link" and found.get("rel") == "stylesheet":
            self.assets.append(found["href"])


def test_main_screen_is_served_at_root_with_its_assets(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"
    assert '<html lang="ko">' in r.text
    parser = AssetParser()
    parser.feed(r.text)
    assert parser.assets == ["/app/vendor/leaflet.css", "/app/styles.css", "/app/app.js"]
    others = ["/app/model.js", "/app/board-model.js", "/app/table.js", "/app/site-map.js", "/app/vendor/three.js", "/app/vendor/leaflet.js"]
    for asset in [*parser.assets, *others]:
        served = client.get(asset)
        assert served.status_code == 200 and served.text.strip()
        assert served.headers["cache-control"] == "no-cache"
    assert "javascript" in client.get("/app/app.js").headers["content-type"]
    assert client.get("/app/nope.js").status_code == 404


def test_main_screen_calls_only_existing_api_paths(client):
    # Every /api/... path the screen fetches must be a route on this server, so a renamed
    # route breaks this test instead of the screen. `${...}` parts are path parameters.
    script = (webapp.APP_DIR / "app.js").read_text(encoding="utf-8")
    segment = r"/(?:[a-z_-]+|\$\{[^}]+\})"
    called = set(re.findall(rf"['`](/api(?:{segment})+)", script))
    called |= {
        "/api/projects/{name}" + rest
        for rest in re.findall(rf"\$\{{projectApi\(name\)\}}((?:{segment})+)", script)
    }

    def shape(path: str) -> str:
        return re.sub(r"\$?\{[^}]+\}", "{}", path)

    def fits(path: str, route: str) -> bool:  # a literal value may fill a route parameter
        ours, theirs = shape(path).split("/"), shape(route).split("/")
        return len(ours) == len(theirs) and all(b in (a, "{}") for a, b in zip(ours, theirs, strict=True))

    routes = list(client.app.openapi()["paths"])
    assert {
        "/api/projects", "/api/settings", "/api/projects/{}/session/messages",
        "/api/site/regions", "/api/site/lots", "/api/projects/{}/site", "/api/projects/{}/site/parcels",
    } <= {shape(path) for path in called}
    for path in called:
        assert any(fits(path, route) for route in routes), path


def test_main_screen_files_hold_no_keys_or_placeholder_urls():
    for path in webapp.APP_DIR.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "figma.com/api/mcp/asset" not in text
        assert "OPENROUTER_API_KEY" not in text
        assert "localStorage" not in text  # project data lives on the server, not the browser


def test_main_screen_new_project_fields_are_brief_fields():
    script = (webapp.APP_DIR / "app.js").read_text(encoding="utf-8")
    fields = re.search(r"for \(const key of \[([^\]]+)\]\)", script).group(1)
    assert {f.strip(" '") for f in fields.split(",")} <= set(BRIEF_FIELD_KEYS)


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
    assert set(proposal) == {"id", "agent", "diff", "changes"}
    status = next(c for c in proposal["changes"] if c["section"] == "Module Status")
    assert status["fields"][0]["name"] == agent["id"]
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


def test_deleted_project_leaves_no_approval_for_a_new_one_of_that_name(state_api, project):
    client, base, agent = state_api
    proposal = client.post(f"{base}/state-proposals", json={"agent": agent["id"]}).json()["proposal"]
    assert client.delete(base).status_code == 200
    assert client.post("/api/projects", json={"name": project.name}).status_code == 201
    assert client.get(f"{base}/session").json()["proposal"] is None
    assert client.post(f"{base}/state-proposals/{proposal['id']}/apply").status_code == 409


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


def test_site_api_searches_looks_up_merged_parcels_and_reads_back(client, project, fake_vworld):
    from sida.experts.site import site_facts

    url = f"/api/projects/{project.name}/site"
    assert client.get(url).json() == {
        "available": False, "query": "", "fetched_at": "", "parcels": [], "summary": None,
        "restrictions": [], "uses": [], "lines": [],
    }

    found = client.post(f"{url}/parcels", json={"query": "  경기도 군포시 금정동 689 "}).json()
    assert found["query"] == "경기도 군포시 금정동 689"
    first, second = found["candidates"][:2]
    assert first == {
        "pnu": "4141010500106890014", "address": "경기도 군포시 금정동 689-14",
        "road_address": first["road_address"], "building": first["building"], "matched_by": "parcel",
    }
    assert site_facts.load_facts(project.path) is None  # searching saves nothing

    r = client.put(url, json={"query": "경기도 군포시 금정동 689", "pnus": [second["pnu"], first["pnu"]]})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] and [p["pnu"] for p in body["parcels"]] == [second["pnu"], first["pnu"]]
    assert body["summary"]["parcel_count"] == 2 and body["summary"]["municipality"] == "경기도 군포시"
    assert body["summary"]["zoning"][0]["zone"] == "일반공업지역" and body["parcels"][0]["area_m2"]
    assert any(line.startswith("조례값(일반공업지역): 건폐율 70% 이하") for line in body["lines"])
    assert client.get(url).json() == body  # saved
    assert client.get(f"{url}/ordinance").json()["name"] == "군포시 도시계획 조례"  # ordinance came with it

    # the designer's choices survive looking the same site up again
    client.put(f"{url}/ordinance/options/제52조", json={"dismissed": True})
    client.put(url, json={"query": "경기도 군포시 금정동 689", "pnus": [first["pnu"]]})
    assert site_facts.load_facts(project.path)["ordinance"]["dismissed"] == ["제52조"]
    assert client.get(url).json()["summary"]["parcel_count"] == 1


def test_site_uses_api_searches_checks_and_forgets_planned_uses(client, project, fake_vworld, fake_datago):
    from sida.experts.site import site_facts

    found = client.get("/api/site/uses", params={"q": " 단독주택 "}).json()
    assert found == {"query": "단독주택", "uses": found["uses"]} and found["uses"][0]["name"] == "단독주택"
    assert client.get("/api/site/uses", params={"q": " "}).status_code == 400

    url = f"/api/projects/{project.name}/site"
    r = client.post(f"{url}/uses", json={"name": "공장"})
    assert r.status_code == 400 and "먼저 대지를 조회" in r.json()["detail"]

    site = client.put(url, json={"query": "경기도 군포시 금정동 689", "pnus": ["4141010500106890014"]}).json()
    assert site["uses"] == [] and site["restrictions"][0]["laws"]
    assert site["parcels"][0]["buildings"][0]["name"] == "(주)혜창"

    body = client.post(f"{url}/uses", json={"name": "공장"}).json()
    assert [u["name"] for u in body["uses"]] == ["공장"]
    assert [z["zone"] for z in body["uses"][0]["zones"]] == ["과밀억제권역", "일반공업지역"]
    assert any(line.startswith("건축 가능 여부(공장, 토지이음 행위제한)") for line in body["lines"])
    assert client.get(url).json() == body  # saved

    r = client.post(f"{url}/uses", json={"name": "우주정거장"})
    assert r.status_code == 400 and "우주정거장" in r.json()["detail"]

    assert client.delete(f"{url}/uses/공장").json()["uses"] == []
    assert client.delete(f"{url}/uses/공장").status_code == 404
    assert site_facts.load_facts(project.path)["uses"] == []

    fake_datago.overrides["DTsearchLunCd"] = "arlanduse_badkey.json"
    r = client.post(f"{url}/uses", json={"name": "공장"})
    assert r.status_code == 503 and r.json()["detail"].startswith("공공데이터포털이 키를 거부했습니다")
    assert client.get("/api/site/uses", params={"q": "공장"}).status_code == 503
    assert client.post("/api/projects/nope/site/uses", json={"name": "공장"}).status_code == 404


def test_site_api_lookup_tells_the_conductor_earlier_site_outputs_are_stale(client, project, fake_vworld):
    from sida.experts.site import site_facts

    project.save_history([{"role": "user", "content": "대지부터 보자"}, {"role": "assistant", "content": "네"}])
    url = f"/api/projects/{project.name}/site"
    assert client.put(url, json={"query": "경기도 군포시 금정동 689", "pnus": ["4141010500106890014"]}).status_code == 200

    history = project.load_history()
    assert history[:2] == [{"role": "user", "content": "대지부터 보자"}, {"role": "assistant", "content": "네"}]
    assert history[2:] == [{"role": "user", "content": site_facts.STALE_NOTE}]  # same note as terminal /site
    assert "Looked up site facts: 경기도 군포시 금정동 689" in project.transcript_path.read_text(encoding="utf-8")
    # The note is for the Conductor: the chat shows it as a hidden system entry, not a user bubble.
    shown = client.get(f"/api/projects/{project.name}/session").json()["messages"]
    assert shown[-1] == {"role": "system", "event": "note", "text": site_facts.STALE_NOTE}


def test_site_api_reports_bad_requests_and_government_api_failures(client, project, fake_vworld, monkeypatch):
    from sida.experts.site import site_facts
    from sida.experts.site.landapi import LandApiError

    url = f"/api/projects/{project.name}/site"
    assert client.post(f"{url}/parcels", json={"query": "   "}).status_code == 400
    assert client.post(f"{url}/parcels", json={}).status_code == 422
    assert client.put(url, json={"query": "금정동 689", "pnus": ["0000000000000000000"]}).status_code == 400
    assert client.put(url, json={"query": "금정동 689", "pnus": []}).status_code == 400
    assert client.post("/api/projects/nope/site/parcels", json={"query": "금정동 689"}).status_code == 404
    assert client.get("/api/projects/nope/site").status_code == 404

    fake_vworld.overrides["search"] = LandApiError("invalid_key", "등록되지 않은 인증키입니다.")
    r = client.post(f"{url}/parcels", json={"query": "금정동 689"})
    assert r.status_code == 503 and "키를 거부" in r.json()["detail"] and "[site]" not in r.json()["detail"]
    fake_vworld.overrides["search"] = LandApiError("over_limit", "")
    assert client.post(f"{url}/parcels", json={"query": "금정동 689"}).status_code == 429
    fake_vworld.overrides["search"] = LandApiError("network", "ConnectTimeout")
    assert client.put(url, json={"query": "금정동 689", "pnus": ["4141010500106890014"]}).status_code == 502
    monkeypatch.delenv("VWORLD_API_KEY")
    del fake_vworld.overrides["search"]
    assert client.post(f"{url}/parcels", json={"query": "금정동 689"}).status_code == 503
    assert site_facts.load_facts(project.path) is None  # nothing was saved by any failed request


def test_address_selection_api_walks_to_a_lot_and_saves_it_by_pnu(client, project, fake_vworld):
    from sida.experts.site import site_facts

    provinces = client.get("/api/site/regions").json()
    assert provinces["parent"] == "" and provinces["level"] == "sido"
    assert "경기도" in [r["name"] for r in provinces["regions"]]
    cities = client.get("/api/site/regions", params={"parent": "41"}).json()
    assert cities["level"] == "sigungu" and "군포시" in [r["name"] for r in cities["regions"]]
    dongs = client.get("/api/site/regions", params={"parent": "41410"}).json()
    dong = next(r for r in dongs["regions"] if r["name"] == "금정동")
    assert dongs["level"] == "emd" and dong["dong_code"] == "4141010500" and dong["has_ri"] is False

    lots = client.get("/api/site/lots", params={"dong_code": dong["dong_code"], "main": 689}).json()
    assert lots["lot"] == "689" and lots["dong_code"] == "4141010500"
    pnus = [c["pnu"] for c in lots["candidates"]]
    assert "4141010500106890014" in pnus and all(c["matched_by"] == "lot" for c in lots["candidates"])
    one = client.get("/api/site/lots", params={"dong_code": "4141010500", "main": 689, "sub": 14}).json()
    assert one["lot"] == "689-14" and [c["pnu"] for c in one["candidates"]] == ["4141010500106890014"]
    mountain = client.get("/api/site/lots", params={"dong_code": "4141010500", "main": 689, "mountain": True})
    assert mountain.json()["lot"] == "산 689" and mountain.json()["candidates"] == []
    assert site_facts.load_facts(project.path) is None  # choosing saves nothing

    # 조회해 저장 by PNU alone: no address search, the parcels are taken as chosen
    url = f"/api/projects/{project.name}/site"
    chosen = ["4141010500106890015", "4141010500106890014"]
    r = client.put(url, json={"pnus": chosen})
    assert r.status_code == 200
    body = r.json()
    assert [p["pnu"] for p in body["parcels"]] == chosen
    assert body["query"] == "경기도 군포시 금정동 689-15, 경기도 군포시 금정동 689-14"
    assert body["summary"]["municipality"] == "경기도 군포시" and body["summary"]["parcel_count"] == 2
    assert body["summary"]["zoning"][0]["zone"] == "일반공업지역"
    assert not [u for u, _ in fake_vworld.calls if u.endswith("/req/search")]
    assert client.get(url).json() == body


def test_map_api_finds_a_clicked_parcel_and_gives_boundary_shapes(client, project, fake_vworld):
    at = client.get("/api/site/parcel-at", params={"lon": 126.945978, "lat": 37.37025}).json()
    assert at["lon"] == 126.945978 and at["lat"] == 37.37025
    [hit] = at["candidates"]
    assert hit["pnu"] == "4141010500106890014" and hit["matched_by"] == "map"
    assert hit["shape"]["type"] == "MultiPolygon"
    sea = client.get("/api/site/parcel-at", params={"lon": 125.0, "lat": 34.0})
    assert sea.status_code == 200 and sea.json()["candidates"] == []

    shapes = client.get("/api/site/shapes", params=[
        ("pnu", "4141010500106890014"), ("pnu", "4141010500106890015"), ("pnu", "4141010500199999999"),
    ]).json()["shapes"]
    assert [s["pnu"] for s in shapes] == ["4141010500106890014", "4141010500106890015", "4141010500199999999"]
    assert shapes[0]["shape"] == hit["shape"] and shapes[1]["shape"]["type"] == "MultiPolygon"
    assert shapes[2]["shape"] is None  # no such parcel

    # the saved site keeps each parcel's boundary, so the map needs no new call when reopened
    url = f"/api/projects/{project.name}/site"
    body = client.put(url, json={"pnus": ["4141010500106890014"]}).json()
    assert body["parcels"][0]["shape"] == hit["shape"]
    fake_vworld.calls.clear()
    assert client.get(url).json()["parcels"][0]["shape"] == hit["shape"] and fake_vworld.calls == []


def test_map_layers_give_the_browser_tile_addresses_without_the_domain(client, fake_vworld, monkeypatch):
    layers = client.get("/api/site/map").json()
    assert layers["base"]["url"] == "https://api.vworld.kr/req/wmts/1.0.0/test-key/Base/{z}/{y}/{x}.png"
    cadastral = layers["cadastral"]
    assert cadastral["url"] == "https://api.vworld.kr/req/wms" and cadastral["params"]["key"] == "test-key"
    assert cadastral["params"]["version"] == "1.3.0" and cadastral["params"]["layers"] == "lp_pa_cbnd_bubun"
    # a browser sends a Referer; VWorld refuses the key when a domain comes with it
    assert "domain" not in {k.lower() for k in cadastral["params"]}
    assert cadastral["min_zoom"] == 18  # the 지적 layer is empty below this
    assert fake_vworld.calls == []  # nothing is fetched by the server

    monkeypatch.delenv("VWORLD_API_KEY")
    assert client.get("/api/site/map").status_code == 503


def test_map_api_reports_bad_requests(client, fake_vworld):
    from sida.experts.site.landapi import LandApiError

    r = client.get("/api/site/parcel-at", params={"lon": 37.37025, "lat": 126.945978})  # swapped
    assert r.status_code == 400 and "한국 밖" in r.json()["detail"]
    assert client.get("/api/site/parcel-at", params={"lon": 126.9}).status_code == 422
    assert client.get("/api/site/shapes").status_code == 400
    r = client.get("/api/site/shapes", params={"pnu": "414101050010689"})
    assert r.status_code == 400 and "19자리" in r.json()["detail"]
    many = [("pnu", f"41410105001{n:08d}") for n in range(51)]
    assert client.get("/api/site/shapes", params=many).status_code == 400
    assert fake_vworld.calls == []

    fake_vworld.overrides["data"] = LandApiError("network", "timeout")
    assert client.get("/api/site/parcel-at", params={"lon": 126.945978, "lat": 37.37025}).status_code == 502


def test_site_lookup_still_saves_when_the_boundary_call_fails(client, project, fake_vworld, monkeypatch):
    from sida.experts.site import landapi, site_facts
    from sida.experts.site.landapi import LandApiError

    def down(pnu, **kwargs):
        raise LandApiError("network", "timeout")

    monkeypatch.setattr(landapi, "parcel_shape", down)
    body = client.put(f"/api/projects/{project.name}/site", json={"pnus": ["4141010500106890014"]}).json()
    assert body["parcels"][0]["shape"] is None and body["parcels"][0]["errors"] == []  # not a missing fact
    assert body["summary"]["missing"] == [] and site_facts.load_facts(project.path)


def test_address_selection_api_reports_bad_requests(client, project, fake_vworld):
    from sida.experts.site import site_facts

    for parent in ("4", "414", "abcde", "4141010500"):
        r = client.get("/api/site/regions", params={"parent": parent})
        assert r.status_code == 400 and "지역 코드" in r.json()["detail"]
    lots = "/api/site/lots"
    assert client.get(lots, params={"dong_code": "41410105", "main": 689}).status_code == 400
    assert client.get(lots, params={"dong_code": "4141010500", "main": 0}).status_code == 400
    assert client.get(lots, params={"dong_code": "4141010500", "main": 1, "sub": 10000}).status_code == 400
    assert client.get(lots, params={"dong_code": "4141010500", "main": "육팔구"}).status_code == 422
    assert client.get(lots, params={"dong_code": "4141010500"}).status_code == 422
    assert fake_vworld.calls == []

    url = f"/api/projects/{project.name}/site"
    assert client.put(url, json={"pnus": []}).status_code == 400
    r = client.put(url, json={"pnus": ["414101050010689"]})
    assert r.status_code == 400 and "19자리" in r.json()["detail"]
    r = client.put(url, json={"query": "  ", "pnus": ["4141010500199999999"]})
    assert r.status_code == 400 and "4141010500199999999" in r.json()["detail"]
    assert client.put("/api/projects/nope/site", json={"pnus": ["4141010500106890014"]}).status_code == 404

    fake_vworld.overrides["data"] = land_fixture("data_bad_key.json")
    r = client.get("/api/site/regions", params={"parent": "41"})
    assert r.status_code == 503 and "키를 거부" in r.json()["detail"]
    assert client.put(url, json={"pnus": ["4141010500106890014"]}).status_code == 503
    assert site_facts.load_facts(project.path) is None  # nothing was saved by any failed request


# --- Session screen API ------------------------------------------------------

RUN_SITE = '대지부터 보겠습니다\n```action\n{"type":"run","agent":"site_reader"}\n```'


@pytest.fixture
def session_api(client, project, monkeypatch, scripted):
    """Jobs run inline (no thread) so each request returns after its job; scripted Conductor."""
    from sida import engine

    monkeypatch.setattr(runtime, "load_env", lambda **_kw: "")
    conductor = scripted([])
    monkeypatch.setattr(engine, "conductor_provider", lambda *_a: conductor)
    client.app.state.session_jobs.runner = lambda work: work()
    return client, f"/api/projects/{project.name}", conductor


def finished_job(client, base, response):
    assert response.status_code == 202
    job = response.json()["job"]
    return client.get(f"{base}/session/jobs/{job['id']}").json()


def test_session_message_waits_for_the_site_before_the_site_reader(session_api, project):
    client, base, conductor = session_api
    run = '대지부터 보겠습니다\n```action\n{"type":"run","agent":"site_reader","address":"군포시 금정동 689"}\n```'
    conductor.replies.append(run)
    job = finished_job(client, base, client.post(f"{base}/session/messages", json={"text": "대지 조사"}))
    assert [e["kind"] for e in job["events"]] == ["conductor_reply", "run_skipped"]
    skipped = job["events"][1]["data"]
    assert skipped["agent"] == {"id": "site_reader", "name": "대지 분석가"}
    assert skipped["reason"] == "no_site" and skipped["address"] == "군포시 금정동 689"
    assert not (project.path / "modules" / "11_site_reader.md").exists()
    messages = client.get(f"{base}/session").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "conductor", "system"]
    assert messages[-1]["event"] == "note"


def test_session_message_runs_expert_and_waits_for_state_approval(session_api, project, monkeypatch):
    client, base, conductor = session_api
    monkeypatch.setattr(engine, "run_needs", lambda *a, **k: None)  # as if the site were saved
    conductor.replies.extend([RUN_SITE, '결과를 검토해 주세요.\n```action\n{"type":"none"}\n```'])
    before = project.state_path.read_bytes()

    job = finished_job(client, base, client.post(f"{base}/session/messages", json={"text": "대지부터"}))
    assert job["status"] == "done" and job["error"] is None
    assert [e["kind"] for e in job["events"]] == [
        "conductor_reply", "module_started", "module_saved", "state_proposing", "state_proposed",
        "conductor_reply",
    ]
    assert [e["seq"] for e in job["events"]] == [1, 2, 3, 4, 5, 6]
    started = job["events"][1]["data"]
    assert started["agent"] == {"id": "site_reader", "name": "대지 분석가"}
    assert job["events"][2]["data"]["path"] == "modules/11_site_reader.md"
    proposal = job["events"][4]["data"]["proposal"]
    assert project.state_path.read_bytes() == before

    # Only events after the given sequence number come back.
    later = client.get(f"{base}/session/jobs/{job['id']}?after=3").json()["events"]
    assert [e["seq"] for e in later] == [4, 5, 6]

    body = client.get(f"{base}/session").json()
    assert body["job"] is None and body["proposal"] == proposal
    assert [(m["role"], m["text"]) for m in body["messages"][:2]] == [
        ("user", "대지부터"), ("conductor", "대지부터 보겠습니다"),
    ]
    assert body["messages"][2] | {"text": ""} == {
        "role": "system", "event": "module_completed", "agent": "site_reader",
        "name": "대지 분석가", "text": "",
    }
    assert body["messages"][3] == {"role": "conductor", "text": "결과를 검토해 주세요."}
    site = next(e for e in body["experts"] if e["id"] == "site_reader")
    assert site["status"] == "review" and site["updated_at"]

    # The approval made by the run goes through the existing state-proposal API.
    assert client.post(f"{base}/state-proposals/{proposal['id']}/apply").status_code == 200
    body = client.get(f"{base}/session").json()
    assert body["proposal"] is None
    assert next(e for e in body["experts"] if e["id"] == "site_reader")["status"] == "done"


def test_session_direct_expert_run_and_result_document(session_api):
    client, base, conductor = session_api
    assert client.get(f"{base}/modules/site_reader").status_code == 404

    job = finished_job(client, base, client.post(f"{base}/session/experts/site_reader/run"))
    assert job["status"] == "done" and conductor.calls == []  # no Conductor call
    doc = client.get(f"{base}/modules/site_reader").json()
    assert doc["name"] == "대지 분석가" and doc["content"].startswith("# Mock Output")
    messages = client.get(f"{base}/session").json()["messages"]
    assert [m.get("event") for m in messages] == ["run_requested", "module_completed"]


def test_session_lists_which_experts_each_expert_reads(session_api, mock_config):
    client, base, _conductor = session_api
    experts = {e["id"]: e for e in client.get(f"{base}/session").json()["experts"]}
    assert experts["site_reader"]["inputs"] == ["program_analyst", "concept_framer"]
    assert experts["site_reader"]["tier"] == "core" and experts["spatial_reviewer"]["tier"] == "held"
    assert experts["design_critic"]["inputs"] == [i for i in experts if i != "design_critic"]  # inputs: all

    agents = mock_config["agents"]
    del agents[1]["inputs"]  # no key: every expert before it
    agents[2]["inputs"] = ["site_reader", "nobody"]  # unknown ids are dropped
    experts = client.get(f"{base}/session").json()["experts"]
    assert experts[1]["inputs"] == [agents[0]["id"]]
    assert experts[2]["inputs"] == ["site_reader"]


def test_module_versions_api_lists_and_reads_earlier_results(session_api, project):
    client, base, _conductor = session_api
    assert client.get(f"{base}/modules/site_reader/versions").json() == {"agent": "site_reader", "versions": []}

    for _ in range(3):
        finished_job(client, base, client.post(f"{base}/session/experts/site_reader/run"))
    versions = client.get(f"{base}/modules/site_reader/versions").json()["versions"]
    assert len(versions) == 2  # the current result is not an earlier version
    doc = client.get(f"{base}/modules/site_reader/versions/{versions[0]['id']}").json()
    assert doc["agent"] == "site_reader" and doc["content"].startswith("# Mock Output")
    assert doc["saved_at"] == versions[0]["saved_at"]

    # Newest first, same-second saves by their counter; other experts' and stray files stay out.
    history = project.path / "modules" / "_history"
    for file in history.iterdir():
        file.unlink()
    for stem in ("11_site_reader.20260920-235440", "11_site_reader.20261001-090000",
                 "11_site_reader.20261001-090000-1", "12_program_analyst.20261002-000000",
                 "11_site_reader.backup", "11_site_reader_old.20261003-000000", "11_site_reader.20261399-999999"):
        (history / f"{stem}.md").write_text(stem, encoding="utf-8")
    versions = client.get(f"{base}/modules/site_reader/versions").json()["versions"]
    assert versions == [
        {"id": "20261001-090000-1", "saved_at": "2026-10-01T09:00:00"},
        {"id": "20261001-090000", "saved_at": "2026-10-01T09:00:00"},
        {"id": "20260920-235440", "saved_at": "2026-09-20T23:54:40"},
    ]
    assert client.get(f"{base}/modules/site_reader/versions/20260920-235440").json()["content"] == (
        "11_site_reader.20260920-235440"
    )
    for bad in ("backup", "20261002-000000", "..%2F11_site_reader.20260920-235440"):
        assert client.get(f"{base}/modules/site_reader/versions/{bad}").status_code == 404
    assert client.get(f"{base}/modules/nope/versions").status_code == 404
    assert client.get("/api/projects/nope/modules/site_reader/versions").status_code == 404


def test_session_opening_is_not_stored_as_a_user_message(session_api, project):
    client, base, conductor = session_api
    conductor.replies.append('안녕하세요\n```action\n{"type":"none"}\n```')
    job = finished_job(client, base, client.post(f"{base}/session/opening"))
    assert job["status"] == "done"
    messages = client.get(f"{base}/session").json()["messages"]
    assert messages == [{"role": "conductor", "text": "안녕하세요"}]


def test_session_model_error_fails_the_job_and_saves_nothing(session_api, project):
    client, base, conductor = session_api
    conductor.replies.append(providers.LLMError("model down"))
    job = finished_job(client, base, client.post(f"{base}/session/messages", json={"text": "안녕"}))
    assert job["status"] == "failed" and job["error"] == "model down"
    assert [e["kind"] for e in job["events"]] == ["conductor_error"]
    assert client.get(f"{base}/session").json()["messages"] == []


def test_session_allows_one_job_per_project(session_api):
    client, base, conductor = session_api
    held = []
    client.app.state.session_jobs.runner = held.append  # start, but do not run yet
    first = client.post(f"{base}/session/messages", json={"text": "하나"})
    assert first.status_code == 202 and first.json()["job"]["status"] == "running"
    assert client.get(f"{base}/session").json()["job"]["id"] == first.json()["job"]["id"]
    second = client.post(f"{base}/session/experts/site_reader/run")
    assert second.status_code == 409

    conductor.replies.append('네\n```action\n{"type":"none"}\n```')
    held.pop()()
    assert client.get(f"{base}/session").json()["job"] is None
    assert client.post(f"{base}/session/messages", json={"text": "둘"}).status_code == 202


def test_delete_waits_for_a_running_job(session_api, project):
    client, base, conductor = session_api
    held = []
    client.app.state.session_jobs.runner = held.append  # start, but do not run yet
    assert client.post(f"{base}/session/messages", json={"text": "하나"}).status_code == 202
    refused = client.delete(base)
    assert refused.status_code == 409 and "실행 중" in refused.json()["detail"]
    assert project.path.exists()

    conductor.replies.append('네\n```action\n{"type":"none"}\n```')
    held.pop()()
    assert client.delete(base).status_code == 200
    assert not project.path.exists()
    assert client.get(f"{base}/session").status_code == 404


def test_session_runs_jobs_on_a_background_thread(session_api):
    from sida.session_jobs import start_thread

    client, base, conductor = session_api
    client.app.state.session_jobs.runner = start_thread
    conductor.replies.append('네\n```action\n{"type":"none"}\n```')
    job_id = client.post(f"{base}/session/messages", json={"text": "안녕"}).json()["job"]["id"]
    assert client.app.state.session_jobs._jobs[job_id].wait(5)
    assert client.get(f"{base}/session/jobs/{job_id}").json()["status"] == "done"


def test_session_rejects_bad_requests(session_api, mock_config):
    from sida.project import create_blank_project

    client, base, _conductor = session_api
    assert client.post(f"{base}/session/messages", json={"text": "  "}).status_code == 400
    assert client.post(f"{base}/session/experts/nope/run").status_code == 400
    assert client.get(f"{base}/session/jobs/nope").status_code == 404
    assert client.get(f"{base}/modules/nope").status_code == 404
    assert client.get("/api/projects/nope/session").status_code == 404
    # A job id is only readable through the project it belongs to.
    other = create_blank_project("other", config=mock_config)
    job = client.post(f"{base}/session/experts/site_reader/run").json()["job"]
    assert client.get(f"/api/projects/{other.name}/session/jobs/{job['id']}").status_code == 404


def test_expert_chat_api_answers_and_revises(session_api, monkeypatch):
    from sida import engine
    from tests.test_expert_chat import REVISE, ChatProvider

    client, base, _conductor = session_api
    provider = ChatProvider([REVISE])
    monkeypatch.setattr(engine, "worker_provider", lambda *_a: provider)
    url = f"{base}/experts/program_analyst/chat"

    empty = client.get(url).json()
    assert empty["chat"] is True and empty["messages"] == [] and empty["name"]

    job = finished_job(client, base, client.post(url, json={"text": "더 자세히"}))
    assert job["status"] == "done" and job["kind"] == "expert_chat"
    kinds = [e["kind"] for e in job["events"]]
    assert kinds[:3] == ["expert_reply", "module_started", "module_saved"]
    assert kinds[-1] == "state_proposed"
    assert [m["role"] for m in client.get(url).json()["messages"]] == ["user", "expert", "system"]
    # The main chat shows the revision run as a completed expert.
    main = client.get(f"{base}/session").json()["messages"]
    assert main[-1]["event"] == "module_completed" and main[-1]["agent"] == "program_analyst"


def test_expert_chat_api_rejects_experts_without_chat(session_api):
    client, base, _conductor = session_api
    site = client.get(f"{base}/experts/site_reader/chat").json()
    assert site["chat"] is False
    assert client.post(f"{base}/experts/site_reader/chat", json={"text": "안녕"}).status_code == 400
    assert client.post(f"{base}/experts/program_analyst/chat", json={"text": " "}).status_code == 400
    assert client.get(f"{base}/experts/nope/chat").status_code == 404
    experts = {e["id"]: e["chat"] for e in client.get(f"{base}/session").json()["experts"]}
    assert experts["site_reader"] is False and experts["program_analyst"] is True


def test_expert_chats_api_lists_creates_and_keeps_chats_apart(session_api, monkeypatch):
    from sida import engine
    from tests.test_expert_chat import ANSWER, ChatProvider

    client, base, _conductor = session_api
    provider = ChatProvider([ANSWER, ANSWER])
    monkeypatch.setattr(engine, "worker_provider", lambda *_a: provider)
    chats = f"{base}/experts/program_analyst/chats"

    listing = client.get(chats).json()
    assert listing["chat"] is True and [c["id"] for c in listing["chats"]] == ["01"]
    assert listing["chats"][0]["messages"] == 0

    job = finished_job(client, base, client.post(f"{chats}/01/messages", json={"text": "첫 질문"}))
    assert job["status"] == "done" and job["chat"] == "01"
    created = client.post(chats)
    assert created.status_code == 201 and created.json()["chat"]["id"] == "02"
    job = finished_job(client, base, client.post(f"{chats}/02/messages", json={"text": "다른 질문"}))
    assert job["chat"] == "02"

    one = client.get(f"{chats}/01").json()
    two = client.get(f"{chats}/02").json()
    assert one["chat_id"] == "01" and one["messages"][0]["text"] == "첫 질문"
    assert two["chat_id"] == "02" and two["messages"][0]["text"] == "다른 질문"
    assert [(c["id"], c["preview"]) for c in client.get(chats).json()["chats"]] == [
        ("01", "첫 질문"), ("02", "다른 질문"),
    ]
    # The earlier single-chat path is the first chat.
    assert client.get(f"{base}/experts/program_analyst/chat").json()["messages"] == one["messages"]
    # The side panel gets each expert's chat list with the session.
    experts = {e["id"]: e for e in client.get(f"{base}/session").json()["experts"]}
    assert [c["id"] for c in experts["program_analyst"]["chats"]] == ["01", "02"]
    assert experts["site_reader"]["chats"] == []


def test_expert_chats_api_rejects_missing_chats_and_experts_without_chat(session_api):
    client, base, _conductor = session_api
    chats = f"{base}/experts/program_analyst/chats"
    assert client.get(f"{chats}/02").status_code == 404
    assert client.get(f"{chats}/abc").status_code == 404
    assert client.post(f"{chats}/02/messages", json={"text": "안녕"}).status_code == 404
    site = client.get(f"{base}/experts/site_reader/chats").json()
    assert site["chat"] is False and site["chats"] == []
    assert client.post(f"{base}/experts/site_reader/chats").status_code == 400
    assert client.post(f"{base}/experts/nope/chats").status_code == 404


def test_session_expert_run_with_revision_request(session_api, monkeypatch):
    from sida import engine
    from tests.test_expert_chat import ChatProvider

    client, base, _conductor = session_api
    provider = ChatProvider([])
    monkeypatch.setattr(engine, "worker_provider", lambda *_a: provider)
    finished_job(client, base, client.post(f"{base}/session/experts/site_reader/run"))
    job = finished_job(client, base, client.post(
        f"{base}/session/experts/site_reader/run", json={"revision": "북측 도로를 더 자세히"},
    ))
    assert job["status"] == "done"
    worker_calls = [c for c in provider.calls if c["role"] == "worker"]
    assert "북측 도로를 더 자세히" in worker_calls[-1]["messages"][-1]["content"]
    messages = client.get(f"{base}/session").json()["messages"]
    assert messages[-2] | {"text": ""} == {
        "role": "system", "event": "run_requested", "agent": "site_reader",
        "name": "대지 분석가", "text": "",
    }


# --- Usage records (telemetry) ----------------------------------------------


def test_feedback_api_records_a_rating_only_when_sending_is_on(client, project, mock_config):
    from sida import telemetry

    url = f"/api/projects/{project.name}/experts/site_reader/feedback"
    r = client.post(url, json={"rating": "up"})
    assert r.status_code == 200 and r.json() == {"recorded": False}
    assert telemetry.queued() == []

    mock_config["telemetry"] = {"enabled": True}
    r = client.post(url, json={"rating": "down", "comment": "면적이 틀렸어요"})
    assert r.json() == {"recorded": True}
    [event] = telemetry.queued()
    assert event["kind"] == "feedback"
    assert event["data"] == {"agent": "site_reader", "rating": "down", "comment": "면적이 틀렸어요"}

    assert client.post(url, json={"rating": "meh"}).status_code == 400
    assert client.post(url, json={}).status_code == 422
    assert client.post(f"/api/projects/{project.name}/experts/nobody/feedback", json={"rating": "up"}).status_code == 404
    assert client.post("/api/projects/nope/experts/site_reader/feedback", json={"rating": "up"}).status_code == 404


def test_session_jobs_leave_usage_records_without_project_text(session_api, project, mock_config):
    import json

    from sida import telemetry

    client, base, _conductor = session_api
    mock_config["telemetry"] = {"enabled": True}
    finished_job(client, base, client.post(f"{base}/session/experts/site_reader/run"))
    records = telemetry.queued()
    assert [r["kind"] for r in records][:1] == ["expert_run"] and records[-1]["kind"] == "job"
    assert records[0]["data"]["agent"] == "site_reader" and records[0]["data"]["ok"] is True
    assert records[-1]["data"] | {"seconds": 0} == {
        "job": "expert", "agent": "site_reader", "ok": True, "seconds": 0, "error": None,
        "conductor": "mock:" + mock_config["conductor"]["model"],
        "worker": "mock:" + mock_config["model"],
    }
    sent = json.dumps(records, ensure_ascii=False)
    assert project.name not in sent and "Mock Output" not in sent


def test_failed_site_lookup_is_recorded_with_the_address_only_when_shared(client, project, fake_vworld, mock_config):
    from sida import telemetry
    from sida.experts.site.landapi import LandApiError

    url = f"/api/projects/{project.name}/site/parcels"
    mock_config["telemetry"] = {"enabled": True}
    fake_vworld.overrides["search"] = LandApiError("invalid_key", "")
    assert client.post(url, json={"query": "금정동 689"}).status_code == 503
    mock_config["telemetry"]["share_failure_inputs"] = True
    assert client.post(url, json={"query": "금정동 689"}).status_code == 503
    first, second = telemetry.queued()
    assert first["data"] == {"stage": "site:search_parcels", "error": "invalid_key"}
    assert second["data"]["inputs"] == ["금정동 689"]


# --- Drawing table API -------------------------------------------------------


def test_board_api_lays_moves_and_removes_papers(client, project):
    base = f"/api/projects/{project.name}/board"
    assert client.get(base).json()["papers"][0]["kind"] == "site"

    mass = {"kind": "mass", "id": "mass-a", "title": "안 A", "blocks": [{"w": 30, "d": 20, "floors": 4}]}
    r = client.post(f"{base}/papers", json=mass)
    assert r.status_code == 201 and r.json()["paper"]["blocks"][0]["floors"] == 4
    r = client.patch(f"{base}/papers/mass-a", json={"x": 12.5})
    assert r.status_code == 200 and r.json()["paper"]["x"] == 12.5 and r.json()["rev"] == 2
    assert [p["id"] for p in client.get(base).json()["papers"]] == ["site", "mass-a"]
    assert client.delete(f"{base}/papers/mass-a").json() == {"rev": 3}

    assert client.post(f"{base}/papers", json={"kind": "site"}).status_code == 400
    assert client.post(f"{base}/papers", json={**mass, "blocks": []}).status_code == 400
    assert client.patch(f"{base}/papers/site", json={"text": "x"}).status_code == 400
    assert client.patch(f"{base}/papers/site", json={"folded": True}).json()["paper"]["folded"] is True
    assert "folded" not in client.patch(f"{base}/papers/site", json={"folded": False}).json()["paper"]
    assert client.patch(f"{base}/papers/site", json={"folded": "yes"}).status_code == 400
    assert client.delete(f"{base}/papers/site").status_code == 400
    assert client.patch(f"{base}/papers/gone", json={"x": 1}).status_code == 404
    assert client.get("/api/projects/nope/board").status_code == 404


def test_board_api_places_and_discards_ai_papers(client, project):
    from sida import board

    base = f"/api/projects/{project.name}/board"
    client.post(f"{base}/papers", json={"kind": "mass", "id": "mass-a", "blocks": [{"w": 30, "d": 20, "floors": 4}]})
    copy = board.propose_paper(
        project.path, {"kind": "mass", "based_on": "mass-a", "blocks": [{"w": 30, "d": 20, "floors": 6}], "reason": "층수 +2"}
    )
    note = board.propose_paper(project.path, {"kind": "note", "text": "북측 사선 확인", "reason": "검토"})

    got = client.get(base).json()
    assert [p["id"] for p in got["papers"]] == ["site", "mass-a"]
    assert [p["id"] for p in got["tray"]] == [copy["id"], note["id"]]
    assert got["tray"][0]["based_on"] == "mass-a" and got["tray"][0]["origin"] == "conductor"

    r = client.post(f"{base}/tray/{copy['id']}/place", json={"x": 40, "y": 5})
    assert r.status_code == 200 and r.json()["paper"]["x"] == 40.0
    got = client.get(base).json()
    assert [p["id"] for p in got["papers"]] == ["site", "mass-a", copy["id"]]
    assert got["papers"][2]["blocks"][0]["floors"] == 6
    assert client.patch(f"{base}/papers/{copy['id']}", json={"title": "안 B"}).json()["paper"]["based_on"] == "mass-a"

    assert client.delete(f"{base}/tray/{note['id']}").status_code == 200
    assert client.get(base).json()["tray"] == []
    assert client.post(f"{base}/tray/{note['id']}/place").status_code == 404
    assert client.delete(f"{base}/tray/mass-a").status_code == 404
    assert client.post(f"{base}/tray/x/place", json={"x": "far"}).status_code == 404


def test_board_context_computes_ratios_from_the_saved_site_facts(client, project, fake_vworld, mock_config):
    from sida.experts.site import site_facts

    client.put(f"/api/projects/{project.name}/site", json={
        "query": "경기도 군포시 금정동 689", "pnus": ["4141010500106890014", "4141010500106890015"],
    })
    area = site_facts.load_facts(project.path)["summary"]["total_area_m2"]
    base = f"/api/projects/{project.name}/board"
    client.post(f"{base}/papers", json={"kind": "mass", "id": "mass-a", "blocks": [{"w": 30, "d": 20, "floors": 4}]})

    drawn = client.get(base).json()  # what the screen draws: parcels in metres and the figures
    plan = drawn["site"]["plan"]
    assert [p["pnu"] for p in plan["parcels"]] == ["4141010500106890014", "4141010500106890015"]
    assert plan["bounds"]["max_x"] - plan["bounds"]["min_x"] > 20 and "angle" in plan["frame"]
    assert drawn["figures"]["mass-a"]["coverage_pct"] == round(600 / area * 100, 1)
    assert drawn["site"]["area_m2"] == area

    mock_config["conductor"]["board_context"] = "full"
    body = client.get(f"{base}/context", params={"ids": "mass-a,site"}).json()
    assert body["mode"] == "full"
    assert body["papers"] == [{"id": "mass-a", "name": "매스안"}, {"id": "site", "name": "대지"}]
    assert f"building coverage {600 / area * 100:.1f}%" in body["expert"]
    assert "용도지역: 일반공업지역" in body["expert"]  # the site paper carries the zoning lines
    assert body["conductor"].startswith("DRAWING TABLE")

    mock_config["conductor"]["board_context"] = "names"
    body = client.get(f"{base}/context", params={"ids": "mass-a"}).json()
    assert body["mode"] == "names" and body["conductor"] == "" and "FAR" in body["expert"]
    assert client.get(f"{base}/context", params={"ids": "gone"}).status_code == 400


def test_session_message_carries_the_selected_papers_and_shows_them_as_chips(session_api, project):
    client, base, conductor = session_api
    client.post(f"{base}/board/papers", json={"kind": "note", "id": "n1", "text": "북측 일조"})
    conductor.replies.append('확인하겠습니다.\n```action\n{"type":"none"}\n```')

    job = finished_job(client, base, client.post(
        f"{base}/session/messages", json={"text": "이 메모 봐 줘", "context": ["n1"]}
    ))
    assert job["status"] == "done"
    first = client.get(f"{base}/session").json()["messages"][0]
    assert first == {"role": "user", "text": "이 메모 봐 줘", "context": [{"id": "n1", "name": "메모: 북측 일조"}]}

    r = client.post(f"{base}/session/messages", json={"text": "x", "context": ["gone"]})
    assert r.status_code == 400 and "gone" in r.json()["detail"]
    r = client.post(f"{base}/session/experts/site_reader/run", json={"context": ["gone"]})
    assert r.status_code == 400
    r = client.post(f"{base}/experts/design_critic/chats/01/messages", json={"text": "x", "context": ["gone"]})
    assert r.status_code == 400


def test_expert_run_and_chat_get_the_selected_papers(session_api, project, monkeypatch, scripted, mock_config):
    from sida import engine

    client, base, _conductor = session_api
    mock_config["state_update"]["mode"] = "off"
    # the run (and its retry for missing headers), then the chat reply
    worker = scripted(["## 결과\n- 메모 확인함"] * 2 + ["메모를 봤습니다.\n```action\n{\"type\":\"none\"}\n```"])
    monkeypatch.setattr(engine, "worker_provider", lambda *_a: worker)
    client.post(f"{base}/board/papers", json={"kind": "note", "id": "n1", "text": "북측 일조"})

    job = finished_job(client, base, client.post(
        f"{base}/session/experts/design_critic/run", json={"context": ["n1"]}
    ))
    assert job["status"] == "done"
    assert "DRAWING TABLE" in worker.calls[0]["messages"][-1]["content"]
    assert "북측 일조" in worker.calls[0]["messages"][-1]["content"]

    job = finished_job(client, base, client.post(
        f"{base}/experts/design_critic/chats/01/messages", json={"text": "이거 봐", "context": ["n1"]}
    ))
    assert job["status"] == "done", job["error"]
    assert "DRAWING TABLE" in worker.calls[-1]["messages"][1]["content"]
    chat = client.get(f"{base}/experts/design_critic/chats/01").json()["messages"]
    assert chat[0] == {"role": "user", "text": "이거 봐", "context": [{"id": "n1", "name": "메모: 북측 일조"}]}
