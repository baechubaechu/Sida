#!/usr/bin/env python3
"""Project hub: pick, create, or open a project. No model calls."""

from __future__ import annotations

from pathlib import Path

from briefs import collect_basic_brief
from console import prompt_line
from harness import ROOT, load_config
from i18n import t
from project import (
    create_blank_project,
    create_project_from_brief,
    ensure_projects_root,
    is_project_dir,
    list_projects,
    load_project,
    projects_dir,
    slugify,
)

HubChoice = tuple[Path, bool]  # (project path, created just now)


def hub_create_new(config: dict) -> HubChoice | None:
    name = prompt_line(t("hub_new_name"))
    if name is None:
        return None
    if not name:
        print(t("hub_invalid"))
        return None

    root = ensure_projects_root(config)
    existing_path = root / slugify(name)
    if is_project_dir(existing_path):
        print(t("hub_exists", name=existing_path.name))
        return existing_path, False

    project = create_blank_project(name, config=config)
    print(t("hub_created", path=str(project.path)))

    brief_md = collect_basic_brief()
    if brief_md is None:
        print(t("hub_closed"))
        return None

    project.brief_path.write_text(brief_md.strip() + "\n", encoding="utf-8")
    print(t("brief_saved", path=str(project.brief_path)))
    load_project(project.path)  # refresh session stamp
    return project.path, True


def hub_create_sample(config: dict) -> HubChoice | None:
    sample = ROOT / "input" / "sample_brief.md"
    if not sample.exists():
        print(t("hub_not_found", name=str(sample)))
        return None
    existed = is_project_dir(ensure_projects_root(config) / sample.stem)
    project = create_project_from_brief(sample, config=config)
    print(t("hub_exists", name=project.path.name) if existed else t("hub_created", path=str(project.path)))
    return project.path, not existed


def hub_open_by_name(projects: list[Path]) -> Path | None:
    name = prompt_line(t("hub_open_name"))
    if not name:
        return None
    wanted = {name.lower(), name.lower().replace(" ", "_")}
    for path in projects:
        if path.name.lower() in wanted:
            return path
    candidate = projects_dir() / name
    if is_project_dir(candidate):
        return candidate
    print(t("hub_not_found", name=name))
    return None


def project_hub() -> HubChoice | None:
    """Non-conversational project picker. Returns (path, created), or None to quit."""
    config = load_config()

    while True:
        projects = list_projects(config)
        print()
        print("=" * 40)
        print(f"  {t('hub_title')}")
        print("=" * 40)
        print(t("hub_root", path=str(projects_dir())))
        print()
        if projects:
            print(t("existing_projects"))
            for i, path in enumerate(projects, start=1):
                print(f"  {i}) {path.name}")
        else:
            print(t("hub_empty"))
        print()
        print(t("hub_menu"))
        print()

        choice = prompt_line(t("hub_prompt"))
        if choice is None:
            return None
        choice = choice.lower()

        if not choice or choice in {"q", "quit", "exit"}:
            return None

        if choice in {"n", "new"}:
            result = hub_create_new(config)
            if result is not None:
                return result
            continue

        if choice in {"s", "sample"}:
            result = hub_create_sample(config)
            if result is not None:
                return result
            continue

        if choice in {"o", "open"}:
            path = hub_open_by_name(projects)
            if path is not None:
                print(t("hub_opened", name=path.name))
                return path, False
            continue

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(projects):
                path = projects[idx - 1]
                print(t("hub_opened", name=path.name))
                return path, False
            print(t("hub_invalid"))
            continue

        for path in projects:
            if path.name.lower() == choice:
                print(t("hub_opened", name=path.name))
                return path, False

        print(t("hub_invalid"))
