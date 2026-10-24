"""Output formats the expert prompts ask for (agents/*.md), per the 10/10 meeting."""

from __future__ import annotations

from sida.worker import expected_headers
from tests.conftest import ROOT


def output_sections(file: str) -> list[str]:
    return expected_headers((ROOT / "agents" / file).read_text(encoding="utf-8"))


def test_every_expert_output_ends_with_handoff():
    for path in (ROOT / "agents").glob("[1-6]*_*.md"):
        assert output_sections(path.name)[-1] == "Handoff", path.name


def test_site_reader_keeps_facts_interpretations_and_unconfirmed_apart():
    sections = output_sections("11_site_reader.md")
    assert sections[:2] == ["Facts", "Interpretations"]
    assert sections.index("Unconfirmed") > sections.index("Opportunities")
    assert "Missing Information" not in sections and "Site Conditions" not in sections
    prompt = (ROOT / "agents" / "11_site_reader.md").read_text(encoding="utf-8")
    assert "source: site facts | brief" in prompt
    assert "Only SITE FACTS and the brief can make a fact" in prompt
    assert "rests on: which facts" in prompt


def test_representation_planner_leads_with_diagrams():
    sections = output_sections("61_representation_planner.md")
    assert sections[:2] == ["Essential Diagrams", "Diagram Sequence"]
    assert "Supporting Drawings" in sections
    assert not {"Drawings", "Renders / Visuals", "Model / Prototype"} & set(sections)
    prompt = (ROOT / "agents" / "61_representation_planner.md").read_text(encoding="utf-8")
    assert "Diagrams first" in prompt and "One diagram, one claim" in prompt
