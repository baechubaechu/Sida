"""sida.experts — how a domain folder plugs into the core without the core naming it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sida import commands, experts, harness
from sida.experts import FACTS, KNOWLEDGE, ExpertRun, PromptBlock
from tests.conftest import ROOT


def make_run(warnings: list[str]) -> ExpertRun:
    return ExpertRun(
        config={},
        agent={"id": "site_reader"},
        project_dir=Path("."),
        project_brief="brief",
        project_state=None,
        previous_outputs="",
        warn=warnings.append,
    )


def hook(**attrs):
    return SimpleNamespace(**attrs)


def test_domains_are_discovered_alphabetically_and_hooks_are_optional():
    found = [domain for domain, _module in experts.domain_hooks()]
    assert found == sorted(found)
    assert {"regulation", "site"} <= set(found)
    assert "rhino" not in found  # a domain folder without hooks.py is fine


def test_blocks_are_joined_per_slot_in_domain_order_and_blanks_dropped():
    hooks = [
        ("a", hook(prompt_blocks=lambda run: [PromptBlock("facts A"), PromptBlock("  ", FACTS)])),
        ("b", hook(COMMANDS={})),  # no prompt_blocks at all
        ("c", hook(prompt_blocks=lambda run: [PromptBlock("law C", KNOWLEDGE), PromptBlock("facts C")])),
    ]
    warnings: list[str] = []
    assert experts.collect_prompt_blocks(make_run(warnings), hooks) == {
        FACTS: "facts A\n\nfacts C",
        KNOWLEDGE: "law C",
    }
    assert warnings == []


def test_failing_hook_warns_and_the_other_domains_still_contribute():
    def boom(run):
        raise RuntimeError("no network")

    hooks = [
        ("broken", hook(prompt_blocks=boom)),
        ("typo", hook(prompt_blocks=lambda run: [PromptBlock("x", "sidebar")])),
        ("ok", hook(prompt_blocks=lambda run: [PromptBlock("kept")])),
    ]
    warnings: list[str] = []
    assert experts.collect_prompt_blocks(make_run(warnings), hooks)[FACTS] == "kept"
    assert len(warnings) == 2
    assert "[broken]" in warnings[0] and "no network" in warnings[0]
    assert "[typo]" in warnings[1] and "sidebar" in warnings[1]


def test_expert_commands_do_not_shadow_core_commands_or_each_other():
    contributed = experts.expert_commands()
    assert "/site" in contributed
    assert not set(contributed) & set(commands.COMMANDS)
    names = [
        name.lower()
        for _domain, module in experts.domain_hooks()
        for name in getattr(module, "COMMANDS", {})
    ]
    assert len(names) == len(set(names))


def test_unknown_slash_command_is_still_plain_chat(make_session):
    assert commands.dispatch(make_session(), "/nope 1") is None


@pytest.mark.parametrize("module", ["harness", "engine", "conductor", "session", "commands", "run"])
def test_core_does_not_import_a_domain_by_name(module):
    source = (ROOT / "sida" / f"{module}.py").read_text(encoding="utf-8")
    domains = [p.name for p in (ROOT / "sida" / "experts").iterdir() if (p / "__init__.py").exists()]
    assert domains
    for domain in domains:
        assert f"sida.experts.{domain}" not in source, f"{module}.py names the {domain} domain"


def test_worker_prompt_places_facts_before_state_and_knowledge_after_outputs():
    prompt = harness.build_worker_prompt(
        "AGENT",
        "BRIEF",
        "OUTPUTS",
        project_state="STATE",
        facts_block="FACTS-BLOCK",
        knowledge_block="KNOWLEDGE-BLOCK",
    )
    order = [prompt.index(x) for x in ("BRIEF", "FACTS-BLOCK", "STATE", "OUTPUTS", "KNOWLEDGE-BLOCK")]
    assert order == sorted(order)
