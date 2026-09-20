#!/usr/bin/env python3
"""Local LLM + VPS RAG smoke: run regulation_checker with Ollama worker."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from console import configure_stdio
from harness import (
    agent_by_id,
    get_agents,
    load_config,
    resolve_worker_runtime,
    run_worker_agent,
    worker_provider,
)
from ollama_boot import ensure_ollama_ready
import project as prj

# Use whatever chat model is already on this machine (no long pull).
LOCAL_MODEL = "qwen3.5:9b"


def main() -> None:
    configure_stdio()
    cfg = load_config()
    cfg["projects_dir"] = str(ROOT / "_rag_experiment_projects")
    cfg["conductor"]["provider"] = "ollama"
    cfg["conductor"]["local_profile"] = "local_plus"
    cfg["conductor"]["ollama_pull_missing"] = "off"
    cfg["conductor"]["ollama_warmup"] = True
    cfg["worker"]["provider"] = "ollama"
    cfg["worker"]["max_tokens"] = 2500
    cfg["state_update"] = {"mode": "off"}
    cfg["local_profiles"]["local_plus"]["model"] = LOCAL_MODEL
    cfg["rag"]["enabled"] = True
    cfg["rag"]["provider"] = "http"

    prj.load_config = lambda *a, **k: cfg

    print("=== boot Ollama ===")
    ensure_ollama_ready(cfg, prompt_fn=lambda _: "n", print_fn=print)
    rt = resolve_worker_runtime(cfg)
    print(f"worker: {rt['provider']} / {rt['model']} ctx={rt.get('num_ctx')} max={rt['max_tokens']}")

    brief_src = ROOT / "input" / "geumjeong_station_brief.md"
    project = prj.create_project_from_brief(brief_src, config=cfg)
    mods = project.modules_dir
    mods.mkdir(parents=True, exist_ok=True)
    (mods / "11_site_reader.md").write_text(
        "# Site Reader\n\n## Site Conditions\n- 철도 인프라가 금정역 일대를 절단\n"
        "- 하천 수계 단절\n\n## Spatial Conflicts\n- 환승 고속 vs 보행\n\n"
        "## Opportunities\n- 단면 교차\n\n## Missing Information\n- 이격\n\n"
        "## Design Implications\n- 철도·하천 규제 확인\n\n"
        "## Handoff\n- → regulation_checker: 철도 인접·하천구역\n",
        encoding="utf-8",
    )
    (mods / "12_program_analyst.md").write_text(
        "# Program Analyst\n\n## Users and Rhythms\n- 환승객\n\n"
        "## Program Components\n- 체류 candidate\n\n## Adjacency and Separation\n- 환승↔체류\n\n"
        "## Public–Private Gradient\n- 공공\n\n## Area Logic\n- 환승 우세\n\n"
        "## Missing Information\n- 운영\n\n## Handoff\n- → regulation_checker\n",
        encoding="utf-8",
    )

    agents = get_agents(cfg)
    reg = agent_by_id(agents, "regulation_checker")
    provider = worker_provider(cfg, "")

    print("=== run regulation_checker (Ollama + VPS RAG) ===")
    out = run_worker_agent(
        "",
        cfg,
        reg,
        project.read_brief(),
        [],
        mods,
        provider=provider,
        project_state=project.read_state(),
    )
    path = mods / reg["output"]
    print(f"wrote {path} ({len(out)} chars)")
    print("--- output preview ---")
    print(out[:2000])
    print("---")
    lower = out.lower()
    has_sources = "## Sources Used" in out or "## sources used" in lower
    cites = "kr/" in out or "source:" in lower or "건축법" in out
    print(f"has_Sources_Used_header={has_sources} cites_law={cites}")


if __name__ == "__main__":
    main()
