"""Terminal slash commands of the site domain. Registered through hooks.COMMANDS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sida.experts.site import landapi, site_facts
from sida.i18n import t

if TYPE_CHECKING:
    from sida.session import Session


def _print_site_facts(facts: dict) -> None:
    print(t("site_title", when=facts.get("fetched_at", "")[:10], query=facts.get("query", "")))
    print(site_facts.describe(facts))


def cmd_site(session: Session, arg: str) -> str:
    """
    `/site` shows saved facts, `/site 조례` the ordinance articles, `/site 용도 <use>` checks a
    planned use, `/site <address>` looks up.
    """
    from sida.console import prompt_line

    project = session.project
    query = arg.strip()
    if not query:
        facts = site_facts.load_facts(project.path)
        if facts:
            _print_site_facts(facts)
        else:
            print(t("site_none"))
        return "continue"
    head, _, rest = query.partition(" ")
    if head.lower() in {"조례", "ordinance"}:
        facts = site_facts.load_facts(project.path) or {}
        view = site_facts.ordinance_options(facts)
        if not view["available"]:
            print(t("site_ordinance_none"))
        elif not rest.strip():
            print(site_facts.describe_options(facts))
            print(t("site_ordinance_hint"))
        else:
            wanted = rest.strip()
            found = [a for a in view["articles"] if a["label"] == wanted]
            found += [i for g in view["groups"] for i in g["items"] if i["label"] == wanted]
            for article in found:
                print(f"{article['label']} {article['title']}\n{article['text']}")
            if not found:
                print(t("site_ordinance_unknown", label=wanted))
        return "continue"
    if head.lower() in {"용도", "use"}:
        print(t("site_use_checking", name=rest.strip()))
        try:
            facts = site_facts.check_use(project.path, rest)
        except ValueError as exc:
            print(f"[site] {exc}")
            return "continue"
        except landapi.LandApiError as exc:
            print(t(exc.MESSAGE_PREFIX + exc.kind, detail=exc.detail))
            return "continue"
        print("\n".join(site_facts.use_lines(facts)))
        return "continue"
    if head.lower() in {"용도삭제", "unuse"}:
        try:
            site_facts.remove_use(project.path, rest.strip())
        except ValueError as exc:
            print(f"[site] {exc}")
            return "continue"
        print(t("site_use_removed", name=rest.strip()))
        return "continue"
    choices = {
        "숨김": ("dismissed", True, "site_ordinance_hidden"), "hide": ("dismissed", True, "site_ordinance_hidden"),
        "표시": ("dismissed", False, "site_ordinance_shown"), "show": ("dismissed", False, "site_ordinance_shown"),
        "원문": ("detailed", True, "site_ordinance_detailed"), "detail": ("detailed", True, "site_ordinance_detailed"),
        "제목만": ("detailed", False, "site_ordinance_brief"), "brief": ("detailed", False, "site_ordinance_brief"),
    }
    if head.lower() in choices:
        key, value, message = choices[head.lower()]
        try:
            site_facts.set_option(project.path, rest.strip(), **{key: value})
        except ValueError:
            print(t("site_ordinance_unknown", label=rest.strip()))
            return "continue"
        print(t(message, label=rest.strip()))
        return "continue"

    print(t("site_searching", query=query))
    try:
        candidates = landapi.search_parcels(query)
    except landapi.LandApiError as exc:
        print(t(exc.MESSAGE_PREFIX + exc.kind, detail=exc.detail))
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
    facts = site_facts.refresh(
        project.path,
        query,
        [candidates[i] for i in picks],
        progress=lambda body: print(t("site_ordinance_fetching", body=body)),
    )
    path = site_facts.facts_path(project.path)
    print()
    _print_site_facts(facts)
    print()
    print(t("site_saved", path=str(path)))
    if facts["summary"]["missing"]:
        print(t("site_partial"))
    site_facts.note_lookup(project, query, session.history)
    session.persist()
    return "continue"
