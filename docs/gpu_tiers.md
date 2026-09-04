# Local Conductor GPU tiers

Commercial default is **8GB VRAM**. 12GB+ is an optional upgrade, not a requirement.

## Profiles (`config.yaml` → `local_profiles`)

| Profile | VRAM | Model | num_ctx | history_window |
|---------|------|-------|---------|----------------|
| **`local`** (default) | ~8GB | `qwen2.5:7b` Q4 | 8192 | 12 |
| **`local_plus`** | ~12GB+ | `qwen2.5:14b` Q4 | 16384 | 16 |

```yaml
conductor:
  provider: ollama          # openrouter | ollama | mock
  local_profile: local      # local | local_plus
  base_url: http://127.0.0.1:11434   # native /api/chat; num_ctx is passed per request
```

Worker modules stay on OpenRouter (`worker.model`) unless you change them.

## Why 8GB is the default

- RTX 4060 / 3060 8GB / many laptop GPUs sit here
- 14B Q4 needs ~9–10GB weights alone — does not fit 8GB with usable context
- Conductor only needs short replies + routing + JSON action
- `project_state.md` carries long-project memory so 7B + 8K ctx is enough

## 8GB recipe

1. Install [Ollama](https://ollama.com)
2. `ollama pull qwen2.5:7b`
3. Set in `config.yaml`:

```yaml
conductor:
  provider: ollama
  local_profile: local
```

4. Keep `project_state.md` updated (module runs, decisions, phase changes)

## Reliability by size (action block + Korean)

The Conductor must end each reply with a small ```action``` JSON block. What matters
is instruction-following, not knowledge.

| Size | Action block adherence (rough, Q4) | Korean quality | Fits |
|------|------------------------------------|----------------|------|
| 7B (`qwen2.5:7b`) | occasional misses — omits the block or writes prose after it | usable, sometimes stiff | 8GB |
| 12B (`gemma3:12b`) | good; rare misses | strong, natural | 12GB+ (weights ~8GB alone) |
| 14B (`qwen2.5:14b`) | good; rare misses | good | 12GB+ |

When the block is missing, `conductor.action_recovery` (default `auto` = local providers)
makes one extra JSON-only call (`format: json` on Ollama) that reads the visible reply
and extracts `{"type": ..., "agent": ...}`. Guards: `run`/`read` are accepted only if the
reply text actually names that module; anything unparseable becomes `none`. The recovered
block is written into history so later turns see a correct example. Cost: one short
local call on the turns where the 7B model slipped. Set `always` to enable on cloud,
`off` to disable.

If recovery also fails, the reply is shown, nothing runs, nothing crashes — type
`/run <agent>` or ask again.

`gemma3:12b` is a valid `local_plus` alternative. Q4_K_M weights are ~8.1GB, so it is
a 12GB-tier model, not an 8GB one, despite the smaller parameter count.

```yaml
local_profiles:
  local_plus:
    model: gemma3:12b      # instead of qwen2.5:14b; stronger Korean
    num_ctx: 16384
```

## 12GB+ recipe

```bash
ollama pull qwen2.5:14b
```

```yaml
conductor:
  provider: ollama
  local_profile: local_plus
```

## Token budget by tier

| Block | `local` (7B / 8K) | `local_plus` (14B / 16K) |
|-------|-------------------|--------------------------|
| System + conductor | ~600 | ~600 |
| brief.md | 800–1,500 | 800–2,000 |
| project_state.md | 800–1,000 | 800–1,200 |
| module snapshot | ~200 | ~200 |
| recent history | ~1,200 (12 msgs) | ~2,000 (16 msgs) |
| **Target total** | **~4–5K** | **~5–8K** |

Always prefer state over full module dumps (`prefer_state_over_modules: true`).
