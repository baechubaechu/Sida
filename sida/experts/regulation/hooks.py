"""How the regulation domain plugs into the core (see sida/experts/__init__.py)."""

from __future__ import annotations

from sida.experts import KNOWLEDGE, ExpertRun, PromptBlock
from sida.experts.regulation import rag
from sida.experts.site import site_facts
from sida.i18n import t


def prompt_blocks(run: ExpertRun) -> list[PromptBlock]:
    """Statute articles for the experts mapped to a collection in `rag.agents`."""
    try:
        query = rag.build_retrieval_query(
            run.project_brief,
            project_state=run.project_state,
            expert_outputs=run.previous_outputs,
        )
        text = rag.retrieve_for_agent(
            run.config,
            run.agent,
            query,
            project_brief=run.project_brief,
            site_facts=site_facts.load_facts(run.project_dir),
        )
        note = rag.last_retrieval_warning()
    except Exception as exc:  # retrieval must never block the expert run
        text = ""
        note = t("rag_warn_error", reason=str(exc) or type(exc).__name__)
    if note:
        run.warn(note)
    return [PromptBlock(text, KNOWLEDGE)] if text else []
