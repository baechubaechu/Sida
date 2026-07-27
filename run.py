#!/usr/bin/env python3
"""Sida — sequential agent pipeline into a project folder."""

from __future__ import annotations

import sys
from pathlib import Path

from harness import fail, get_agents, load_config, load_env, run_worker_agent
from project import open_or_create


def run(target: Path, project_name: str | None = None) -> None:
    api_key = load_env()
    config = load_config()
    agents = get_agents(config)

    project, created = open_or_create(target, name=project_name, config=config)
    project_brief = project.read_brief()
    output_dir = project.modules_dir

    previous_blocks: list[str] = []
    total = len(agents)

    print(f"Project: {project.path}")
    if created:
        print("Created new project folder.")
    else:
        print("Using existing project folder.")

    for index, agent in enumerate(agents, start=1):
        name = agent.get("name", agent.get("id", f"Agent {index}"))
        print(f"[{index}/{total}] Running {name}...")
        result = run_worker_agent(
            api_key, config, agent, project_brief, previous_blocks, output_dir
        )
        previous_blocks.append(f"### {name}\n\n{result}")

    project.save_session(pipeline="sequential")
    print(f"\nOutputs saved to {output_dir.as_posix()}/")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: python run.py input/project_brief.md")
        print("       python run.py projects/project_name")
        print("       python chat.py input/project_brief.md   # conversational")
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
