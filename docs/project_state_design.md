# project_state.md — design notes (Conductor memory)

## Purpose

`project_state.md` is the **rolling project memory** for the Conductor. It holds synthesis,
not raw sources. Sources stay in their own files:

| File | Role |
|------|------|
| `brief.md` | Original project brief (stable, may grow slowly) |
| `modules/*.md` | Full specialist outputs (long, append-only) |
| `history.json` | Raw chat turns (grows forever) |
| `project_state.md` | **Compressed state** for routing and continuity |

## Token budget

Default commercial target: **7B @ 8K ctx (8GB VRAM)**.  
Optional upgrade: **9B @ 16K (12GB+, recommended)**. See `docs/gpu_tiers.md`.

| Block | `local` (7B / 8K) | `local_plus` (9B / 16K) |
|-------|-------------------|--------------------------|
| System prompt + conductor.md | ~600 | ~600 |
| `brief.md` | 800–1,500 | 800–2,000 |
| `project_state.md` | **800–1,000** | **800–1,200** |
| Module outputs | 0–200 | 0–500 |
| Recent history | ~1,200 (12 msgs) | ~2,000 (16 msgs) |
| User message + headroom | ~500+ | ~500+ |
| **Target total** | **~4–5K** | **~5–8K** |

When `project_state.md` is missing, fall back to full module outputs (current behavior).

## Update triggers

Update `project_state.md` when:

1. A module finishes → refresh **Module Status** + relevant bullets (Decisions, Questions, Tensions)
2. User confirms a design choice → **Confirmed Decisions**
3. Brief edited (`/brief edit`) → mark affected modules **stale**
4. Every ~10 chat turns → roll **Recent Notes**, trim if over cap
5. Phase change (crit, pin-up, final) → **Meta.Phase**

Who updates:

- **v0**: user edits manually, or asks Conductor "state 파일 업데이트해줘"
- **v1** (later): Conductor action `{"type": "update_state", ...}` or post-module hook

## Section design rationale

| Section | Why Conductor needs it |
|---------|------------------------|
| Meta | Routing — phase, weekly focus, freshness |
| Core Problem | Stable anchor so long threads don't drift |
| Current Direction | Evolving stance without re-reading full brief |
| Confirmed Decisions | Don't re-debate settled items |
| Open Questions | Drive `none` vs `run module` choices |
| Tensions | Match constraint_mapper / synthesizer / design_critic framing |
| Module Status | Know what's done/stale without loading full `.md` |
| Missing Information | Trigger site_reader rerun or user homework |
| Recent Notes | Replace old history turns after sliding window |
| Next Focus | Explicit steering; reduces vague Conductor replies |

## Stale modules

Mark **stale** when:

- `brief.md` changed after module was run
- **Current Direction** significantly diverges from module takeaway
- User says direction shifted

Conductor should suggest rerun, not auto-run.

## Config (config.yaml)

```yaml
local_profiles:
  local:       # 8GB default
    model: qwen2.5:7b
    num_ctx: 8192
    history_window: 12
  local_plus:  # 12GB+ recommended
    model: qwen3.5:9b
    num_ctx: 16384
    history_window: 16

conductor:
  provider: openrouter   # or ollama
  local_profile: local
  context:
    state_file: project_state.md
    history_window: 12
    prefer_state_over_modules: true
```

## Local model pairing

| Tier | Model | Ollama |
|------|-------|--------|
| 8GB (`local`) | Qwen2.5-7B Q4 | `ollama pull qwen2.5:7b` |
| 12GB+ (`local_plus`) | Qwen3.5-9B Q4 | `ollama pull qwen3.5:9b` |

Fixed section headers in `project_state.md` help smaller models locate facts
without long-context retrieval degradation.
