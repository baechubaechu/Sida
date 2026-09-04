#!/usr/bin/env python3
"""Sida — sequential agent pipeline into a project folder (non-interactive)."""

from __future__ import annotations

import sys
from pathlib import Path

from console import configure_stdio
from harness import (
    LLMError,
    fail,
    get_agents,
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


def run(target: Path, project_name: str | None = None) -> None:
    configure_stdio()
    api_key = load_env()
    config = load_config()
    agents = get_agents(config)

    project, created = open_or_create(target, name=project_name, config=config)
    project_brief = project.read_brief()
    output_dir = project.modules_dir

    previous_blocks: list[str] = []
    total = len(agents)

    print(t("run_project", path=project.path))
    print(t("sess_created") if created else t("sess_resumed"))

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
            )
        except LLMError as exc:
            fail(t("run_failed", name=name, reason=str(exc)))
        previous_blocks.append(f"### {name}\n\n{result}")
        _auto_update_state(config, api_key, project, agent, provider)

    project.save_session(pipeline="sequential")
    print()
    print(t("run_outputs", path=output_dir.as_posix()))


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(t("run_usage_cli"))
        sys.exit(1)

    project_name = None
    if args[0] == "--name":
        if len(args) < 3:
            fail("Usage: python run.py --name my_project input/brief.md")
        project_name = args[1]
        target = Path(args[2])
    else:
        target = Path(args[0])

    run(target, project_name=project_name)


if __name__ == "__main__":
    main()
