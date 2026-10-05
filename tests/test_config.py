"""config.yaml + config.local.yaml loading, and the expert registry they define."""

from __future__ import annotations

from sida import config as sida_config
from sida import runtime
from tests.conftest import ROOT


def test_config_agents_cover_all_prompt_files(mock_config):
    agents = sida_config.get_agents(mock_config)
    files = {a["file"].split("/")[-1] for a in agents}
    on_disk = {p.name for p in (ROOT / "agents").glob("[1-6]*_*.md")}
    assert files == on_disk
    ids = [a["id"] for a in agents]
    assert len(ids) == len(set(ids))
    for a in agents:
        assert a.get("phase") and a.get("desc"), a["id"]
        assert a["output"] == a["file"].split("/")[-1]


def test_paths_reference_known_experts(mock_config):
    ids = {a["id"] for a in sida_config.get_agents(mock_config)}
    paths = sida_config.get_paths(mock_config)
    assert {"site_driven", "idea_driven", "program_driven", "regulation_driven", "review_prep"} <= set(paths)
    for name, seq in paths.items():
        assert set(seq) <= ids, name
    # entry expert reflects the driver
    assert paths["site_driven"][0] == "site_reader"
    assert paths["idea_driven"][0] == "concept_framer"
    assert paths["program_driven"][0] == "program_analyst"
    assert paths["regulation_driven"][0] == "regulation_checker"
    assert paths["review_prep"][0] == "synthesizer"


def test_inputs_reference_known_experts(mock_config):
    agents = sida_config.get_agents(mock_config)
    ids = {a["id"] for a in agents}
    for a in agents:
        inputs = sida_config.agent_inputs(a)
        assert inputs != "legacy", a["id"]
        if isinstance(inputs, list):
            assert set(inputs) <= ids and a["id"] not in inputs, a["id"]
    assert sida_config.agent_inputs(sida_config.agent_by_id(agents, "synthesizer")) == "all"
    assert sida_config.agent_inputs({"id": "x"}) == "legacy"


def _write_base(tmp_path):
    base = tmp_path / "config.yaml"
    base.write_text(
        "conductor:\n  provider: openrouter\n  model: m1\n"
        "rag:\n  enabled: false\n  provider: http\n"
        "agents:\n  - id: a\n  - id: b\n",
        encoding="utf-8",
    )
    return base


def test_load_config_without_local_file_is_base_only(tmp_path):
    cfg = sida_config.load_config(_write_base(tmp_path))
    assert cfg["conductor"] == {"provider": "openrouter", "model": "m1"}
    assert cfg["rag"]["enabled"] is False


def test_load_config_overlays_local_file(tmp_path):
    base = _write_base(tmp_path)
    (tmp_path / "config.local.yaml").write_text(
        "conductor:\n  provider: ollama\nrag:\n  enabled: true\n", encoding="utf-8"
    )
    cfg = sida_config.load_config(base)
    assert cfg["conductor"] == {"provider": "ollama", "model": "m1"}  # sibling key kept
    assert cfg["rag"] == {"enabled": True, "provider": "http"}
    assert [a["id"] for a in cfg["agents"]] == ["a", "b"]


def test_load_config_ignores_empty_local_file(tmp_path):
    base = _write_base(tmp_path)
    (tmp_path / "config.local.yaml").write_text("# only a comment\n", encoding="utf-8")
    assert sida_config.load_config(base)["conductor"]["provider"] == "openrouter"


def test_default_load_config_reads_local_config_path():
    # conftest points LOCAL_CONFIG_PATH at a tmp file, never the real one.
    sida_config.LOCAL_CONFIG_PATH.write_text("projects_dir: /tmp/from-local\n", encoding="utf-8")
    assert sida_config.load_config()["projects_dir"] == "/tmp/from-local"


def test_committed_defaults_are_cloud_with_rag_off():
    """config.yaml must stay machine-neutral: personal choices belong in config.local.yaml."""
    cfg = sida_config.load_config(ROOT / "config.yaml")
    assert cfg["conductor"]["provider"] == "openrouter"
    assert cfg["worker"]["provider"] == "openrouter"
    assert cfg["rag"]["enabled"] is False
    assert runtime.needs_openrouter(cfg)
