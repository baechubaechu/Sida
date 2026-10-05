"""Terminal slash commands of the site domain. Registered through hooks.COMMANDS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sida.experts.site import landapi, site_facts
from sida.i18n import t

if TYPE_CHECKING:
    from sida.session import Session

SITE_FACTS_NOTE = (
    "[system] Site facts were looked up from the address and saved as site_facts.json "
    "(parcel, zoning, statutory coverage/FAR limits, the municipality's ordinance articles on "
    "coverage/FAR). site_reader and regulation_checker now "
    "receive them; outputs of those experts produced before this are stale."
)


def _print_site_facts(facts: dict) -> None:
    print(t("site_title", when=facts.get("fetched_at", "")[:10], query=facts.get("query", "")))
    print(site_facts.describe(facts))


def cmd_site(session: Session, arg: str) -> str:
    """`/site` shows saved facts, `/site 조례` the ordinance articles, `/site <address>` looks up."""
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
    if query.lower() in {"조례", "ordinance"}:
        text = site_facts.ordinance_text(site_facts.load_facts(project.path) or {})
        print(text or t("site_ordinance_none"))
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
    if facts["summary"]["zoning"]:
        print(t("site_ordinance_fetching", body=facts["summary"]["municipality"]))
        site_facts.attach_ordinance(facts)
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
