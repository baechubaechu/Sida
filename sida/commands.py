#!/usr/bin/env python3
"""Slash commands inside a session. `dispatch()` returns None for plain chat."""

from __future__ import annotations

from collections.abc import Callable

from sida.briefs import collect_brief_updates, edit_file_in_editor
from sida.harness import resolve_agent
from sida.i18n import t
from sida.session import Session, run_module_command

Outcome = str  # "continue" | "close" | "quit"

SITE_FACTS_NOTE = (
    "[system] Site facts were looked up from the address and saved as site_facts.json "
    "(parcel, zoning, statutory coverage/FAR limits). site_reader and regulation_checker now "
    "receive them; outputs of those experts produced before this are stale."
)

BRIEF_CHANGED_NOTE = (
    "[system] The project brief was updated. "
    "Use the latest PROJECT BRIEF block going forward. "
    "Mark affected modules stale in project_state.md if direction changed."
)


def print_help(agents: list[dict]) -> None:
    print(t("help_commands"))
    print()
    print(t("help_modules"))
    for agent in agents:
        print(f"  {agent.get('id'):<24} {agent.get('name')}")


def _print_file(title: str, body: str) -> None:
    print(f"\n--- {title} ---\n")
    print(body.rstrip() if body.strip() else t("empty"))
    print("\n----------------------")


# ---------------------------------------------------------------------------
# Handlers — each receives (session, argument string)
# ---------------------------------------------------------------------------


def cmd_help(session: Session, _arg: str) -> Outcome:
    print_help(session.agents)
    return "continue"


def cmd_project(session: Session, _arg: str) -> Outcome:
    done = session.completed_ids()
    print(t("project_folder", path=session.project.path))
    print(t("project_session", id=session.project.session_id))
    print(t("project_completed", list=", ".join(done) if done else t("none")))
    print(t("project_history_turns", n=session.user_turns()))
    print(t("project_state_file", path=session.project.state_path))
    return "continue"


def cmd_status(session: Session, _arg: str) -> Outcome:
    done = session.completed_ids()
    print(t("status_completed", list=", ".join(done) if done else t("none")))
    print(t("status_folder", path=session.project.path))
    print(t("status_history", path=session.project.history_path))
    print(t("status_state", path=session.project.state_path))
    return "continue"


def _after_brief_change(session: Session) -> None:
    session.reload_brief()
    session.project.append_transcript("System", "Updated brief.md")
    session.history.append({"role": "user", "content": BRIEF_CHANGED_NOTE})
    session.persist()


def cmd_brief(session: Session, arg: str) -> Outcome:
    sub = arg.strip().lower()
    project = session.project

    if sub in {"", "show", "view"}:
        _print_file(project.brief_path.name, project.read_brief())
        return "continue"

    if sub in {"edit", "open"}:
        changed = edit_file_in_editor(project.brief_path, backup=project.path / "brief.prev.md")
        if changed:
            _after_brief_change(session)
        return "continue"

    if sub in {"fields", "form"}:
        updates = collect_brief_updates(project.read_brief())
        if updates is None:
            return "continue"
        if not any(v.strip() for v in updates.values()):
            print(t("brief_no_changes"))
            return "continue"
        project.update_brief_sections(updates)
        print(t("brief_saved", path=str(project.brief_path)))
        print(t("brief_backup", path=str(project.path / "brief.prev.md")))
        _after_brief_change(session)
        return "continue"

    print(t("brief_usage"))
    return "continue"


def cmd_state(session: Session, arg: str) -> Outcome:
    sub = arg.strip().lower()
    project = session.project
    if not project.state_path.exists():
        project.init_state()

    if sub in {"", "show", "view"}:
        _print_file(project.state_path.name, project.read_state() or "")
        return "continue"

    if sub in {"edit", "open"}:
        edit_file_in_editor(project.state_path)
        return "continue"

    if sub.startswith("update"):
        from sida.session import update_state_after_module

        _, _, target = sub.partition(" ")
        agent = _pick_module_for_state(session, target.strip())
        if agent is None:
            print(t("state_update_no_module"))
            return "continue"
        # Manual request: always show the diff and ask, even if mode is auto/off.
        update_state_after_module(session, agent, mode="ask")
        return "continue"

    print(t("state_usage"))
    return "continue"


def _pick_module_for_state(session: Session, query: str) -> dict | None:
    """Explicit agent, or the most recently written module file."""
    if query:
        return resolve_agent(session.agents, query)
    done = [(session.output_dir / a["output"], a) for a in session.agents if (session.output_dir / a["output"]).exists()]
    if not done:
        return None
    return max(done, key=lambda pair: pair[0].stat().st_mtime)[1]


def _print_site_facts(facts: dict) -> None:
    from sida.experts.site import site_facts

    print(t("site_title", when=facts.get("fetched_at", "")[:10], query=facts.get("query", "")))
    print(site_facts.describe(facts))


def cmd_site(session: Session, arg: str) -> Outcome:
    """`/site` shows saved site facts; `/site <address>` looks a parcel (or several) up."""
    from sida.console import prompt_line
    from sida.experts.site import landapi, site_facts

    project = session.project
    query = arg.strip()
    if not query:
        facts = site_facts.load_facts(project.path)
        if facts:
            _print_site_facts(facts)
        else:
            print(t("site_none"))
        return "continue"

    print(t("site_searching", query=query))
    try:
        candidates = landapi.search_parcels(query)
    except landapi.LandApiError as exc:
        print(t(f"site_err_{exc.kind}", detail=exc.detail))
        return "continue"
    if not candidates:
        print(t("site_no_match"))
        return "continue"

    print(t("site_candidates"))
    for i, c in enumerate(candidates, start=1):
        extra = " · ".join(x for x in (c["road_address"], c["building"]) if x)
        print(f"  {i}) {c['address']}" + (f"  ({extra})" if extra else ""))
    answer = prompt_line(t("site_pick"))
    if answer is None or answer.strip() == "0":
        print(t("site_cancelled"))
        return "continue"
    picks = site_facts.parse_selection(answer or "1", len(candidates))
    if picks is None:
        print(t("site_pick_invalid"))
        return "continue"

    print(t("site_fetching", n=len(picks)))
    facts = site_facts.build_facts(query, [candidates[i] for i in picks])
    path = site_facts.save_facts(project.path, facts)
    print()
    _print_site_facts(facts)
    print()
    print(t("site_saved", path=str(path)))
    if facts["summary"]["missing"]:
        print(t("site_partial"))
    project.append_transcript("System", f"Looked up site facts: {query}")
    session.history.append({"role": "user", "content": SITE_FACTS_NOTE})
    session.persist()
    return "continue"


def cmd_rename(session: Session, arg: str) -> Outcome:
    from sida.console import prompt_line

    new_name = arg.strip()
    if not new_name:
        new_name = prompt_line(t("rename_prompt")) or ""
    if not new_name:
        print(t("hub_invalid"))
        return "continue"
    try:
        old = session.project.name
        session.project.rename(new_name, config=session.config)
        print(t("rename_ok", old=old, new=session.project.name, path=str(session.project.path)))
        session.project.append_transcript("System", f"Renamed project: {old} → {session.project.name}")
    except ValueError as exc:
        print(t("rename_fail", reason=str(exc)))
    return "continue"


def cmd_setup(_session: Session, _arg: str) -> Outcome:
    from sida.setup_env import setup_api_key

    setup_api_key(force=True)
    return "continue"


def cmd_language(_session: Session, _arg: str) -> Outcome:
    from sida.setup_env import prompt_language

    prompt_language(force=True)
    return "continue"


def cmd_run(session: Session, arg: str) -> Outcome:
    query = arg.strip()
    if not query:
        print(t("run_usage"))
        return "continue"
    agent = resolve_agent(session.agents, query)
    if not agent:
        print(t("unknown_agent", agent=query))
        return "continue"
    run_module_command(session, agent, f"/run {query}")
    return "continue"


def cmd_close(_session: Session, _arg: str) -> Outcome:
    return "close"


def cmd_quit(_session: Session, _arg: str) -> Outcome:
    return "quit"


COMMANDS: dict[str, Callable[[Session, str], Outcome]] = {
    "/help": cmd_help,
    "help": cmd_help,
    "/project": cmd_project,
    "/status": cmd_status,
    "/brief": cmd_brief,
    "/state": cmd_state,
    "/site": cmd_site,
    "/rename": cmd_rename,
    "/agents": cmd_help,
    "/setup": cmd_setup,
    "/language": cmd_language,
    "/lang": cmd_language,
    "/run": cmd_run,
    "/close": cmd_close,
    "/home": cmd_close,
    "/hub": cmd_close,
    "/projects": cmd_close,
    "/quit": cmd_quit,
    "quit": cmd_quit,
    "exit": cmd_quit,
}


def dispatch(session: Session, user_text: str) -> Outcome | None:
    """Run a slash command. Returns None when `user_text` is ordinary chat."""
    text = user_text.strip()
    if not text:
        return "continue"
    head, _, rest = text.partition(" ")
    handler = COMMANDS.get(head.lower())
    if handler is None:
        return None
    return handler(session, rest)
