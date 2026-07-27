#!/usr/bin/env python3
"""Conversational Sida CLI — project hub + Conductor sessions."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from harness import (
    agent_by_id,
    call_openrouter,
    fail,
    format_usage,
    get_agents,
    load_config,
    load_env,
    resolve_agent,
    run_worker_agent,
)
from project import list_projects, open_or_create, projects_dir

ACTION_RE = re.compile(r"```action\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def print_help(agents: list[dict]) -> None:
    print(
        """
Commands:
  /help              show this help
  /project           show current project folder
  /rename <name>     rename this project (folder + display name)
  /agents            list modules
  /status            show completed modules
  /setup             (re)configure OpenRouter API key
  /language          change UI language
  /run <agent_id>    run a module now (no conductor call)
  /close             leave project → back to hub
  /quit              exit the app

Or just type normally to talk to the Conductor.
""".strip()
    )
    print("\nModules:")
    for agent in agents:
        print(f"  {agent.get('id'):<24} {agent.get('name')}")


def load_existing_outputs(agents: list[dict], output_dir: Path) -> list[str]:
    blocks: list[str] = []
    for agent in agents:
        path = output_dir / agent["output"]
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                blocks.append(f"### {agent['name']}\n\n{text}")
    return blocks


def completed_ids(agents: list[dict], output_dir: Path) -> list[str]:
    done = []
    for agent in agents:
        if (output_dir / agent["output"]).exists():
            done.append(str(agent.get("id")))
    return done


def parse_action(raw: str) -> tuple[str, dict]:
    match = ACTION_RE.search(raw)
    if not match:
        return raw.strip(), {"type": "none"}
    reply = (raw[: match.start()] + raw[match.end() :]).strip()
    try:
        action = json.loads(match.group(1))
        if not isinstance(action, dict):
            action = {"type": "none"}
    except json.JSONDecodeError:
        action = {"type": "none"}
    action.setdefault("type", "none")
    return reply, action


def build_conductor_messages(
    conductor_prompt: str,
    project_brief: str,
    state_text: str,
    history: list[dict],
    cache_ttl: str,
) -> list[dict]:
    system_content = [
        {
            "type": "text",
            "text": conductor_prompt.strip(),
            "cache_control": {"type": "ephemeral", "ttl": cache_ttl},
        }
    ]
    brief_block = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": f"PROJECT BRIEF:\n\n{project_brief.strip()}",
                "cache_control": {"type": "ephemeral", "ttl": cache_ttl},
            }
        ],
    }
    state_block = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    "KNOWN MODULE OUTPUTS:\n\n"
                    f"{state_text.strip() if state_text.strip() else '(none yet)'}\n\n"
                    "Treat this as the current project state. "
                    "Do not invent missing module outputs."
                ),
            }
        ],
    }
    return [
        {"role": "system", "content": system_content},
        brief_block,
        state_block,
        *history,
    ]


def ask_conductor(
    api_key: str,
    config: dict,
    conductor_prompt: str,
    project_brief: str,
    previous_blocks: list[str],
    history: list[dict],
    session_id: str,
    user_text: str | None = None,
    *,
    project=None,
) -> tuple[str, dict, dict]:
    conductor = config.get("conductor") or {}
    model = conductor.get("model", "anthropic/claude-haiku-4.5")
    temperature = float(conductor.get("temperature", 0.4))
    max_tokens = int(conductor.get("max_tokens", 700))
    cache_ttl = str(conductor.get("cache_ttl", "1h"))

    if user_text is not None:
        history.append({"role": "user", "content": user_text})
        if project is not None:
            project.save_history(history)

    state_text = "\n\n".join(previous_blocks)
    messages = build_conductor_messages(
        conductor_prompt, project_brief, state_text, history, cache_ttl
    )

    raw, usage = call_openrouter(
        api_key,
        model,
        messages,
        temperature,
        max_tokens,
        session_id=session_id,
        use_cache=True,
        cache_ttl=cache_ttl,
    )
    reply, action = parse_action(raw)
    history.append({"role": "assistant", "content": raw})
    if project is not None:
        project.save_history(history)
    return reply, action, usage


def execute_run(
    api_key: str,
    config: dict,
    agents: list[dict],
    agent: dict,
    project_brief: str,
    previous_blocks: list[str],
    output_dir: Path,
) -> None:
    name = agent.get("name", agent.get("id"))
    print(f"\n[module] Running {name}...")
    result = run_worker_agent(
        api_key, config, agent, project_brief, previous_blocks, output_dir
    )
    previous_blocks[:] = load_existing_outputs(agents, output_dir)
    out_path = output_dir / agent["output"]
    print(f"[module] Saved {out_path.as_posix()}")
    preview = result.strip().splitlines()
    preview_text = "\n".join(preview[:12])
    if len(preview) > 12:
        preview_text += "\n..."
    print(f"\n--- {name} preview ---\n{preview_text}\n----------------------\n")


def handle_action(
    action: dict,
    api_key: str,
    config: dict,
    agents: list[dict],
    project_brief: str,
    previous_blocks: list[str],
    output_dir: Path,
    history: list[dict] | None = None,
    project=None,
) -> bool:
    action_type = str(action.get("type", "none")).lower()
    if action_type == "exit":
        return False
    if action_type == "run":
        agent_id = str(action.get("agent", "")).strip()
        agent = resolve_agent(agents, agent_id) or agent_by_id(agents, agent_id)
        if not agent:
            print(f"[conductor] Unknown agent id: {agent_id}")
            return True
        execute_run(
            api_key, config, agents, agent, project_brief, previous_blocks, output_dir
        )
        if history is not None:
            note = (
                f"[module completed] {agent.get('id')} → {agent.get('output')}. "
                "Output is now in project state."
            )
            history.append({"role": "user", "content": note})
            if project is not None:
                project.save_history(history)
                project.append_transcript("System", note)
        return True
    return True


def chat(target: Path, project_name: str | None = None) -> str:
    """
    Run a Conductor session inside one project.
    Returns: "close" (back to hub) or "quit" (exit app).
    """
    from harness import ROOT
    from i18n import t

    api_key = load_env()
    config = load_config()
    agents = get_agents(config)

    conductor_cfg = config.get("conductor") or {}
    prompt_rel = conductor_cfg.get("prompt", "agents/00_conductor.md")
    prompt_path = ROOT / prompt_rel
    if not prompt_path.exists():
        fail(f"Missing conductor prompt: {prompt_path}")
    conductor_prompt = prompt_path.read_text(encoding="utf-8")

    project, created = open_or_create(target, name=project_name, config=config)
    project_brief = project.read_brief()
    output_dir = project.modules_dir

    previous_blocks = load_existing_outputs(agents, output_dir)
    history: list[dict] = project.load_history()

    print(f"Projects root: {projects_dir()}")
    print(f"Project:       {project.path}")
    print(f"Brief:         {project.brief_path}")
    print(f"Modules:       {output_dir}")
    if created:
        print("Created new project folder.")
    else:
        print("Resumed existing project folder.")
        if history:
            turns = sum(1 for m in history if m.get("role") == "user")
            print(f"Loaded conversation: {turns} user turn(s).")
    print(t("session_hint"))
    print()

    if history:
        opening = (
            "Session resumed. The previous conversation is already in context. "
            "Greet briefly in one or two sentences, note completed modules if any, "
            "and wait for the designer's next instruction. Do not rerun modules "
            "unless asked."
        )
    elif created or not previous_blocks:
        opening = (
            "A new session just started. Greet briefly, summarize the core problem "
            "in one or two sentences, and suggest the best first module or question. "
            "Do not run a module yet unless the brief is already very complete and "
            "the first step is obvious."
        )
    else:
        opening = (
            "Session resumed. Greet briefly, note which modules already exist, "
            "and suggest the most useful next step. Do not rerun modules unless asked."
        )

    def _persist() -> None:
        project.save_history(history)
        project.save_session(history_turns=len(history))

    def _leave(kind: str) -> str:
        _persist()
        if kind == "quit":
            print(t("session_saved_quit"))
        else:
            print(t("session_saved_close"))
        return kind

    reply, action, usage = ask_conductor(
        api_key,
        config,
        conductor_prompt,
        project_brief,
        previous_blocks,
        history,
        project.session_id,
        user_text=opening,
        project=project,
    )
    print(f"Conductor: {reply}")
    project.append_transcript("Conductor", reply)
    _persist()
    usage_line = format_usage(usage)
    if usage_line:
        print(f"[{usage_line}]")
    if not handle_action(
        action,
        api_key,
        config,
        agents,
        project_brief,
        previous_blocks,
        output_dir,
        history=history,
        project=project,
    ):
        return _leave("close")

    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return _leave("close")

        if not user_text:
            continue

        lowered = user_text.lower()
        if lowered in {"/quit", "quit", "exit"}:
            return _leave("quit")
        if lowered in {"/close", "/home", "/hub", "/projects"}:
            return _leave("close")
        if lowered in {"/help", "help"}:
            print_help(agents)
            continue
        if lowered == "/project":
            print(f"Project folder: {project.path}")
            print(f"session_id:     {project.session_id}")
            done = completed_ids(agents, output_dir)
            print("Completed:     ", ", ".join(done) if done else "(none)")
            print(f"History turns: {sum(1 for m in history if m.get('role') == 'user')}")
            continue
        if lowered == "/rename" or lowered.startswith("/rename "):
            from i18n import t

            parts = user_text.split(maxsplit=1)
            new_name = parts[1].strip() if len(parts) > 1 else ""
            if not new_name:
                try:
                    new_name = input(t("rename_prompt")).strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    continue
            if not new_name:
                print(t("hub_invalid"))
                continue
            try:
                old = project.name
                project.rename(new_name, config=config)
                output_dir = project.modules_dir
                print(t("rename_ok", old=old, new=project.name, path=str(project.path)))
                project.append_transcript(
                    "System", f"Renamed project: {old} → {project.name}"
                )
            except ValueError as exc:
                print(t("rename_fail", reason=str(exc)))
            continue
        if lowered == "/agents":
            print_help(agents)
            continue
        if lowered == "/status":
            done = completed_ids(agents, output_dir)
            print("Completed:", ", ".join(done) if done else "(none)")
            print(f"Folder:    {project.path}")
            print(f"History:   {project.history_path}")
            continue
        if lowered == "/setup":
            from setup import setup_api_key

            setup_api_key(force=True)
            continue
        if lowered in {"/language", "/lang"}:
            from setup import prompt_language

            prompt_language(force=True)
            continue
        if lowered.startswith("/run"):
            parts = user_text.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /run <agent_id>")
                continue
            agent = resolve_agent(agents, parts[1])
            if not agent:
                print(f"Unknown agent: {parts[1]}")
                continue
            execute_run(
                api_key,
                config,
                agents,
                agent,
                project_brief,
                previous_blocks,
                output_dir,
            )
            note = (
                f"[module completed] {agent.get('id')} → {agent.get('output')}. "
                "Output is now in project state."
            )
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": note})
            project.append_transcript("User", user_text)
            project.append_transcript("System", note)
            _persist()
            continue

        project.append_transcript("You", user_text)
        reply, action, usage = ask_conductor(
            api_key,
            config,
            conductor_prompt,
            project_brief,
            previous_blocks,
            history,
            project.session_id,
            user_text=user_text,
            project=project,
        )
        print(f"\nConductor: {reply}")
        project.append_transcript("Conductor", reply)
        _persist()
        usage_line = format_usage(usage)
        if usage_line:
            print(f"[{usage_line}]")
        if not handle_action(
            action,
            api_key,
            config,
            agents,
            project_brief,
            previous_blocks,
            output_dir,
            history=history,
            project=project,
        ):
            return _leave("close")


def ensure_app_setup() -> None:
    """Language + API key only. No project creation here."""
    from i18n import has_language, t
    from setup import (
        _configure_stdio,
        ensure_api_key,
        prompt_language,
        read_api_key_from_env,
    )

    _configure_stdio()
    if not has_language():
        prompt_language(force=False)
        print()

    print("=" * 40)
    print(f"  {t('welcome_title')}")
    print("=" * 40)
    print(t("welcome_body"))
    print()

    had_key = bool(read_api_key_from_env())
    if not had_key:
        print(t("api_missing"))
        print()
    ensure_api_key(interactive=True)
    if not had_key:
        print()


def _prompt_line(label: str) -> str | None:
    """Return stripped input, or None if cancelled (Ctrl+C). Empty string if skipped."""
    try:
        return input(label).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _build_brief_markdown(fields: dict[str, str]) -> str:
    issues_raw = fields.get("issues", "").strip()
    if issues_raw:
        issues_lines = "\n".join(
            f"- {part.strip()}" for part in issues_raw.split(",") if part.strip()
        )
    else:
        issues_lines = "-"

    def val(key: str) -> str:
        text = fields.get(key, "").strip()
        return text if text else "-"

    return f"""# Project Brief

## Project Type
{val("type")}

## Site
{val("site")}

## Core Problem
{val("problem")}

## Site Issues
{issues_lines}

## Design Intention
{val("intention")}

## Current Design Direction
{val("direction")}
"""


def collect_basic_brief() -> str | None:
    """Ask for basic brief fields. Returns markdown, or None if cancelled."""
    from i18n import t

    print()
    print("=" * 40)
    print(f"  {t('brief_title')}")
    print("=" * 40)
    print(t("brief_intro"))
    print()

    fields: dict[str, str] = {}
    mapping = [
        ("type", "brief_type"),
        ("site", "brief_site"),
        ("problem", "brief_problem"),
        ("issues", "brief_issues"),
        ("intention", "brief_intention"),
        ("direction", "brief_direction"),
    ]
    for key, label_key in mapping:
        value = _prompt_line(t(label_key))
        if value is None:
            return None
        fields[key] = value

    return _build_brief_markdown(fields)


def _hub_create_new(config: dict) -> Path | None:
    from i18n import t
    from project import (
        create_blank_project,
        ensure_projects_root,
        is_project_dir,
        load_project,
        slugify,
    )

    name = _prompt_line(t("hub_new_name"))
    if name is None:
        return None
    if not name:
        print(t("hub_invalid"))
        return None

    root = ensure_projects_root(config)
    slug = slugify(name)
    existing_path = root / slug

    if is_project_dir(existing_path):
        print(t("hub_exists", name=slug))
        return existing_path

    # 1) Create folder first
    project = create_blank_project(name, config=config)
    print(t("hub_created", path=str(project.path)))

    # 2) Collect basic info into brief.md
    brief_md = collect_basic_brief()
    if brief_md is None:
        print(t("hub_closed"))
        return None

    project.brief_path.write_text(brief_md.strip() + "\n", encoding="utf-8")
    print(t("brief_saved", path=str(project.brief_path)))
    load_project(project.path)  # refresh session stamp
    return project.path


def _hub_create_sample(config: dict) -> Path | None:
    from harness import ROOT
    from i18n import t
    from project import create_project_from_brief

    sample = ROOT / "input" / "sample_brief.md"
    if not sample.exists():
        print(t("hub_not_found", name=str(sample)))
        return None
    project = create_project_from_brief(sample, config=config)
    print(t("hub_created", path=str(project.path)))
    return project.path


def _hub_open_by_name(projects: list[Path]) -> Path | None:
    from i18n import t

    try:
        name = input(t("hub_open_name")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not name:
        return None
    for path in projects:
        if path.name.lower() == name.lower() or path.name.lower() == name.lower().replace(
            " ", "_"
        ):
            return path
    # allow opening even if not in list (path resolve via open_or_create later)
    root = projects_dir()
    candidate = root / name
    if candidate.exists():
        return candidate
    print(t("hub_not_found", name=name))
    return None


def project_hub() -> Path | None:
    """
    Non-conversational project picker.
    Returns project path to open, or None to quit the app.
    """
    from i18n import t

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

        try:
            choice = input(t("hub_prompt")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if not choice or choice in {"q", "quit", "exit"}:
            return None

        if choice in {"n", "new"}:
            path = _hub_create_new(config)
            if path is not None:
                return path
            continue

        if choice in {"s", "sample"}:
            path = _hub_create_sample(config)
            if path is not None:
                return path
            continue

        if choice in {"o", "open"}:
            path = _hub_open_by_name(projects)
            if path is not None:
                print(t("hub_opened", name=path.name))
                return path
            continue

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(projects):
                path = projects[idx - 1]
                print(t("hub_opened", name=path.name))
                return path
            print(t("hub_invalid"))
            continue

        # bare project name
        for path in projects:
            if path.name.lower() == choice:
                print(t("hub_opened", name=path.name))
                return path

        print(t("hub_invalid"))


def main() -> None:
    from i18n import t

    args = sys.argv[1:]

    if args and args[0] in {"-h", "--help"}:
        print("Usage:")
        print("  python chat.py")
        print("  python chat.py sample_brief")
        print("  python chat.py input/project_brief.md")
        print("  python chat.py --list")
        print("  python setup.py")
        raise SystemExit(0)

    if args and args[0] == "--list":
        ensure_app_setup()
        root = projects_dir()
        projects = list_projects()
        print(f"Projects root: {root}")
        if not projects:
            print(t("hub_empty"))
            return
        print("Projects:")
        for path in projects:
            print(f"  {path}")
        return

    ensure_app_setup()

    initial: Path | None = None
    project_name = None
    if args:
        if args[0] == "--name":
            if len(args) < 3:
                fail("Usage: python chat.py --name my_project input/brief.md")
            project_name = args[1]
            initial = Path(args[2])
        else:
            initial = Path(args[0])

    while True:
        if initial is not None:
            target = initial
            name = project_name
            initial = None
            project_name = None
        else:
            target = project_hub()
            name = None
            if target is None:
                print(t("hub_goodbye"))
                break

        outcome = chat(target, project_name=name)
        if outcome == "quit":
            break
        print(t("hub_closed"))


if __name__ == "__main__":
    main()
