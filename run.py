#!/usr/bin/env python3
"""Sida — sequential agent pipeline into a project folder (non-interactive)."""

from __future__ import annotations

import sys
from pathlib import Path

from console import configure_stdio
from harness import (
    LLMError,
    agent_by_id,
    fail,
    get_agents,
    get_paths,
    load_config,
    load_env,
    run_worker_agent,
    worker_provider,
)
from i18n import get_language, t
from project import open_or_create
from state_updater import propose_state_patch, state_update_settings, write_state


def _auto_update_state(config: dict, api_key: str, project, agent: dict, provider) -> None:
    """Non-interactive: apply the proposed patch unless state_update.mode is off."""
    settings = state_update_settings(config)
    if settings["mode"] == "off":
        return
    try:
        _, proposed = propose_state_patch(
            config, api_key, project, agent, w_provider=provider, lang=get_language()
        )
    except LLMError as exc:
        print(t("state_propose_failed", reason=str(exc)))
        return
    write_state(project, proposed)
    print(t("state_applied", path=str(project.state_path)))


def _select_agents(config: dict, path_name: str | None) -> list[dict]:
    """All experts in config order, or the experts of a named path in that order."""
    agents = get_agents(config)
    if not path_name:
        return agents
    paths = get_paths(config)
    if path_name not in paths:
        fail(
            f"Unknown path '{path_name}'. Available: {', '.join(paths) or 'none'} "
            "(see `paths:` in config.yaml)."
        )
    selected: list[dict] = []
    for agent_id in paths[path_name]:
        agent = agent_by_id(agents, agent_id)
        if agent is None:
            fail(f"Path '{path_name}' references unknown expert '{agent_id}'.")
        selected.append(agent)
    return selected


def run(target: Path, project_name: str | None = None, *, path_name: str | None = None) -> None:
    configure_stdio()
    config = load_config()
    api_key = load_env(config=config)
    agents = _select_agents(config, path_name)

    project, created = open_or_create(target, name=project_name, config=config)
    project_brief = project.read_brief()
    output_dir = project.modules_dir

    previous_blocks: list[str] = []
    total = len(agents)

    print(t("run_project", path=project.path))
    print(t("sess_created") if created else t("sess_resumed"))
    if path_name:
        print(t("run_path", name=path_name, experts=" → ".join(a["id"] for a in agents)))

    try:
        provider = worker_provider(config, api_key)
    except LLMError as exc:
        fail(str(exc))

    for index, agent in enumerate(agents, start=1):
        name = agent.get("name", agent.get("id", f"Agent {index}"))
        print(t("run_step", i=index, n=total, name=name))
        try:
            result = run_worker_agent(
                api_key,
                config,
                agent,
                project_brief,
                previous_blocks,
                output_dir,
                provider=provider,
                project_state=project.read_state(),
            )
        except LLMError as exc:
            fail(t("run_failed", name=name, reason=str(exc)))
        previous_blocks.append(f"### {name}\n\n{result}")
        _auto_update_state(config, api_key, project, agent, provider)

    project.save_session(pipeline=path_name or "sequential")
    print()
    print(t("run_outputs", path=output_dir.as_posix()))


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(t("run_usage_cli"))
        sys.exit(1)

    project_name = None
    path_name = None
    rest = list(args)
    while rest and rest[0].startswith("--"):
        flag = rest.pop(0)
        if flag == "--name" and rest:
            project_name = rest.pop(0)
        elif flag == "--path" and rest:
            path_name = rest.pop(0)
        else:
            fail("Usage: python run.py [--name my_project] [--path site_driven] input/brief.md")
    if not rest:
        fail("Usage: python run.py [--name my_project] [--path site_driven] input/brief.md")
    target = Path(rest[0])

    run(target, project_name=project_name, path_name=path_name)


if __name__ == "__main__":
    main()
