"""config.yaml (team defaults) overlaid with config.local.yaml (this machine), and the expert list."""

from __future__ import annotations

from pathlib import Path

import yaml

from sida.errors import fail

ROOT = Path(__file__).resolve().parents[1]  # repo root (config.yaml, agents/, projects/)
CONFIG_PATH = ROOT / "config.yaml"
LOCAL_CONFIG_NAME = "config.local.yaml"
LOCAL_CONFIG_PATH = ROOT / LOCAL_CONFIG_NAME


def local_config_path(path: Path = CONFIG_PATH) -> Path:
    """Per-machine overrides file that sits next to `path` (git-ignored)."""
    if path == CONFIG_PATH:
        return LOCAL_CONFIG_PATH
    return path.with_name(LOCAL_CONFIG_NAME)


def merge_config(base: dict, override: dict) -> dict:
    """Deep-merge dicts: override wins; lists and scalars are replaced whole."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_config(out[key], value)
        else:
            out[key] = value
    return out


def _read_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        fail(f"Invalid YAML in {path}: {exc}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(f"Invalid config format in {path}")
    return data


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Team defaults (config.yaml) overlaid with this machine's config.local.yaml."""
    if not path.exists():
        fail(f"Missing config file: {path}")
    config = _read_yaml(path)
    if not config:
        fail(f"Invalid config format in {path}")
    local = local_config_path(path)
    if local.exists():
        config = merge_config(config, _read_yaml(local))
    return config


def get_agents(config: dict) -> list[dict]:
    agents = config.get("agents")
    if not isinstance(agents, list) or not agents:
        fail("No agents defined in config.yaml")
    return agents


def get_paths(config: dict) -> dict[str, list[str]]:
    """Named suggested expert sequences (hints for the Conductor / run.py --path)."""
    raw = config.get("paths") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for name, ids in raw.items():
        if isinstance(ids, list) and ids:
            out[str(name)] = [str(i) for i in ids]
    return out


def agent_inputs(agent: dict) -> list[str] | str:
    """
    Which prior outputs this expert reads: a list of ids, "all", or "legacy"
    (key absent → caller passes every prior block, as before).
    """
    raw = agent.get("inputs")
    if raw is None:
        return "legacy"
    if isinstance(raw, str):
        return "all" if raw.strip().lower() == "all" else [raw]
    if isinstance(raw, list):
        return [str(i) for i in raw]
    return "legacy"


def agent_by_id(agents: list[dict], agent_id: str) -> dict | None:
    for agent in agents:
        if agent.get("id") == agent_id:
            return agent
    return None


def resolve_agent(agents: list[dict], query: str) -> dict | None:
    """Resolve by id, output stem, or case-insensitive name substring."""
    q = query.strip().lower().replace(" ", "_").replace("-", "_")
    if not q:
        return None

    exact = agent_by_id(agents, q)
    if exact:
        return exact

    for agent in agents:
        aid = str(agent.get("id", "")).lower()
        name = str(agent.get("name", "")).lower().replace(" ", "_")
        output = str(agent.get("output", "")).lower().replace(".md", "")
        if q in {aid, name, output}:
            return agent
        if q in aid or q in name or q in output:
            return agent
    return None
