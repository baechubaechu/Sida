"""Running one expert: the outputs it reads, its prompt, the local context budget, saving."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

from sida.config import ROOT, agent_inputs, get_agents
from sida.errors import fail
from sida.providers import provider_chat
from sida.runtime import resolve_worker_runtime, worker_provider
from sida.storage import atomic_write_text

MODULE_HISTORY_DIRNAME = "_history"
WORKER_SYSTEM = (
    "You are an architectural reasoning assistant. "
    "Follow the agent role and output format exactly."
)


def strip_md_comments(text: str | None) -> str | None:
    """Drop `<!-- ... -->` guidance comments (written for people) before sending text to a model."""
    if not text:
        return text
    stripped = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def build_worker_prompt(
    agent_prompt: str,
    project_brief: str,
    previous_outputs: str,
    *,
    project_state: str | None = None,
    other_completed: list[str] | None = None,
    knowledge_block: str | None = None,
    facts_block: str | None = None,
) -> str:
    from sida.i18n import get_language

    lang = get_language()
    language_rule = (
        "Write the entire Markdown output in Korean. Keep section headings exactly as specified in the agent output format. In the Handoff section, keep expert ids in English (e.g. → regulation_checker)."
        if lang == "ko"
        else "Write the entire Markdown output in English. Keep section headings exactly as specified in the agent output format."
    )
    state_block = ""
    if project_state and project_state.strip():
        state_block = f"""
PROJECT STATE (designer-curated memory — decisions, open questions, expert status):
{project_state.strip()}
"""
    others_block = ""
    if other_completed:
        others_block = (
            "\nOTHER COMPLETED EXPERTS (not included above; ask via Handoff if needed): "
            + ", ".join(other_completed)
            + "\n"
        )
    knowledge = ""
    if knowledge_block and knowledge_block.strip():
        knowledge = f"""
{knowledge_block.strip()}
"""
    facts = ""
    if facts_block and facts_block.strip():
        facts = f"""
{facts_block.strip()}
"""
    return f"""AGENT PROMPT:
{agent_prompt}

ORIGINAL PROJECT BRIEF:
{project_brief}
{facts}{state_block}
RELEVANT EXPERT OUTPUTS:
{previous_outputs}
{others_block}{knowledge}
LANGUAGE:
{language_rule}

TASK:
Produce the output for this expert in Markdown.
Follow the output format defined in the agent prompt, every header, in order.
Do not invent project facts not included in the brief, site facts, project state, expert outputs, or retrieved knowledge.
When SITE FACTS are present, they come from government land records: use them as given and prefer them over the brief where the two differ (say so).
When RETRIEVED KNOWLEDGE is present, prefer it for numeric limits and cite `source:` paths; still mark uncertain items as verify.
If information is missing, mark it as missing information.
End with the Handoff section: name which experts should look next and what they should check.
"""


def select_input_blocks(
    agents: list[dict], agent: dict, output_dir: Path
) -> tuple[list[str], list[str]] | None:
    """
    Pick which completed outputs this expert receives, per its `inputs` declaration.
    Returns (blocks, other_completed_names) or None for legacy agents (no `inputs` key).
    """
    wanted = agent_inputs(agent)
    if wanted == "legacy":
        return None
    blocks: list[str] = []
    others: list[str] = []
    for other in agents:
        if other.get("id") == agent.get("id"):
            continue
        path = output_dir / str(other.get("output", ""))
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        label = str(other.get("name", other.get("id")))
        if wanted == "all" or other.get("id") in wanted:
            blocks.append(f"### {label} ({other.get('id')})\n\n{text}")
        else:
            others.append(str(other.get("id")))
    return blocks, others


# Rough chars-per-token for Korean-heavy Markdown. Deliberately low (pessimistic) so the
# estimate errs toward trimming rather than overflowing the local context window.
CHARS_PER_TOKEN = 1.5
BUDGET_MARGIN_CHARS = 400
TRIM_MARK = "\n\n[... trimmed to fit the local model context ...]\n\n"


def worker_input_budget(runtime: dict, fixed_chars: int) -> int | None:
    """
    Chars left for expert outputs + retrieved knowledge after the fixed prompt parts.
    None = no limit (cloud providers, or a local provider without a known num_ctx).
    """
    if runtime.get("provider") not in {"ollama", "local"} or not runtime.get("num_ctx"):
        return None
    input_tokens = int(runtime["num_ctx"]) - int(runtime.get("max_tokens") or 0)
    return max(0, int(input_tokens * CHARS_PER_TOKEN) - fixed_chars - BUDGET_MARGIN_CHARS)


def clip_block(text: str, limit: int) -> str:
    """Shorten one expert output to ~`limit` chars: keep its start and its `## Handoff`."""
    if len(text) <= limit:
        return text
    tail = ""
    cut = text.rfind("\n## Handoff")
    if cut != -1:
        tail = text[cut:].strip()[: max(0, limit // 3)]
    head_len = max(0, limit - len(tail) - len(TRIM_MARK))
    return text[:head_len].rstrip() + TRIM_MARK + tail


def fit_worker_inputs(
    blocks: list[str], knowledge: str, budget: int
) -> tuple[list[str], str, int]:
    """
    Trim expert-output blocks and the knowledge block to `budget` chars in total.
    Knowledge gets at most half when blocks exist. Short blocks are kept whole and their
    unused share goes to the longer ones. Returns (blocks, knowledge, pieces trimmed).
    """
    total = sum(len(b) for b in blocks) + len(knowledge)
    if total <= budget:
        return blocks, knowledge, 0

    trimmed = 0
    knowledge_cap = budget // 2 if blocks else budget
    if len(knowledge) > knowledge_cap:
        knowledge = knowledge[: max(0, knowledge_cap - len(TRIM_MARK))].rstrip() + TRIM_MARK.rstrip()
        trimmed += 1

    remaining = max(0, budget - len(knowledge))
    limits = [0] * len(blocks)
    pending = sorted(range(len(blocks)), key=lambda i: len(blocks[i]))
    while pending:
        share = remaining // len(pending)
        i = pending[0]
        if len(blocks[i]) <= share:  # fits whole → give its leftover to the rest
            limits[i] = len(blocks[i])
            remaining -= len(blocks[i])
            pending.pop(0)
            continue
        for j in pending:
            limits[j] = share
        break

    out: list[str] = []
    for block, limit in zip(blocks, limits, strict=True):
        clipped = clip_block(block, limit)
        trimmed += clipped != block
        out.append(clipped)
    return out, knowledge, trimmed


def expected_headers(agent_prompt: str) -> list[str]:
    """`## ...` headers listed under the agent's `## Output Format` section."""
    match = re.search(r"^## Output Format\s*$", agent_prompt, flags=re.MULTILINE)
    if not match:
        return []
    tail = agent_prompt[match.end():]
    return [h.strip() for h in re.findall(r"^## (.+)$", tail, flags=re.MULTILINE)]


def missing_headers(output: str, headers: list[str]) -> list[str]:
    present = {h.strip().lower() for h in re.findall(r"^## (.+)$", output, flags=re.MULTILINE)}
    return [h for h in headers if h.lower() not in present]


def archive_module_output(output_path: Path) -> Path | None:
    """Copy the old output to _history, leaving it available until the new save succeeds."""
    if not output_path.exists():
        return None
    hist = output_path.parent / MODULE_HISTORY_DIRNAME
    hist.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(output_path.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
    target = hist / f"{output_path.stem}.{stamp}{output_path.suffix}"
    counter = 1
    while target.exists():
        target = hist / f"{output_path.stem}.{stamp}-{counter}{output_path.suffix}"
        counter += 1
    atomic_write_text(target, output_path.read_text(encoding="utf-8"))
    return target


def run_worker_agent(
    api_key: str,
    config: dict,
    agent: dict,
    project_brief: str,
    previous_blocks: list[str],
    output_dir: Path,
    *,
    provider=None,
    project_state: str | None = None,
    notify=None,
) -> str:
    """Run one expert. Raises LLMError on provider failure.

    Experts with an `inputs` declaration receive only the listed completed outputs
    (read from output_dir); other completed experts are named but not included.
    Legacy agents (no `inputs`) receive `previous_blocks` unchanged.

    Warnings (RAG unavailable, inputs trimmed, missing headers, archived file) go to
    `notify(message)` when given; otherwise they are printed as before.
    """

    def say(message: str, *, err: bool = True) -> None:
        if notify is not None:
            notify(message)
        else:
            print(message, file=sys.stderr if err else sys.stdout)

    rt = resolve_worker_runtime(config)
    provider = provider or worker_provider(config, api_key)
    # project_state.md carries long editing notes in HTML comments; they only cost context.
    project_state = strip_md_comments(project_state)

    prompt_rel = agent.get("file")
    output_name = agent.get("output")
    name = agent.get("name", agent.get("id", "agent"))
    if not prompt_rel or not output_name:
        fail(f"Agent '{name}' is missing 'file' or 'output' in config.yaml")

    prompt_path = ROOT / prompt_rel
    if not prompt_path.exists():
        fail(f"Missing agent prompt file: {prompt_path}")

    agent_prompt = prompt_path.read_text(encoding="utf-8")

    selected = select_input_blocks(get_agents(config), agent, output_dir)
    other_completed: list[str] | None = None
    if selected is None:
        blocks = previous_blocks
    else:
        blocks, other_completed = selected
    previous_outputs = "\n\n".join(blocks) if blocks else "(none yet)"
    from sida.experts import FACTS, KNOWLEDGE, ExpertRun, collect_prompt_blocks
    from sida.i18n import t

    # What each expert domain adds to this prompt (site facts, retrieved statutes, ...) comes
    # from its sida/experts/<domain>/hooks.py — nothing domain-specific is written here.
    extra = collect_prompt_blocks(
        ExpertRun(
            config=config,
            agent=agent,
            project_dir=output_dir.parent,
            project_brief=project_brief,
            project_state=project_state,
            previous_outputs=previous_outputs,
            warn=say,
        )
    )
    facts_block = extra[FACTS]
    knowledge_block = extra[KNOWLEDGE]

    # Local models silently drop the start of an over-long prompt (the agent role itself),
    # so trim expert outputs and retrieved knowledge to what the context window can hold.
    fixed_prompt = build_worker_prompt(
        agent_prompt,
        project_brief,
        "",
        project_state=project_state,
        other_completed=other_completed,
        facts_block=facts_block or None,
    )
    budget = worker_input_budget(rt, len(WORKER_SYSTEM) + len(fixed_prompt))
    if budget is not None:
        blocks, knowledge_block, trimmed = fit_worker_inputs(blocks, knowledge_block, budget)
        if trimmed:
            previous_outputs = "\n\n".join(blocks) if blocks else "(none yet)"
            say(t("worker_input_trimmed", name=name, n=trimmed, ctx=rt["num_ctx"]))
    full_prompt = build_worker_prompt(
        agent_prompt,
        project_brief,
        previous_outputs,
        project_state=project_state,
        other_completed=other_completed,
        knowledge_block=knowledge_block or None,
        facts_block=facts_block or None,
    )

    messages = [
        {"role": "system", "content": WORKER_SYSTEM},
        {"role": "user", "content": full_prompt},
    ]
    from sida.console import agent_look
    from sida.i18n import t

    tag, accent = agent_look(agent.get("id"))
    labeled = f"[{tag}] {name}"
    result, _usage = provider_chat(
        provider,
        rt["model"],
        messages,
        rt["temperature"],
        rt["max_tokens"],
        role="worker",
        status=t("busy_worker", name=labeled),
        color=accent,
    )

    headers = expected_headers(agent_prompt)
    missing = missing_headers(result, headers)
    if missing:
        fix = (
            "Your previous output was missing these required section headers: "
            + ", ".join(f"'## {h}'" for h in missing)
            + ". Rewrite the full output with every header from the Output Format, in order."
        )
        retry_messages = messages + [
            {"role": "assistant", "content": result},
            {"role": "user", "content": fix},
        ]
        retried, _ = provider_chat(
            provider,
            rt["model"],
            retry_messages,
            rt["temperature"],
            rt["max_tokens"],
            role="worker",
            status=t("busy_worker_retry", name=labeled),
            color=accent,
        )
        if len(missing_headers(retried, headers)) < len(missing):
            result = retried
        still = missing_headers(result, headers)
        if still:
            say(t("module_missing_headers", name=name, headers=", ".join(still)))

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name
    archived = archive_module_output(output_path)
    if archived:
        say(t("module_archived", path=archived.relative_to(output_dir).as_posix()), err=False)
    atomic_write_text(output_path, result + "\n")
    return result
