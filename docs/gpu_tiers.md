# Local Conductor GPU tiers

**8GB VRAM is the minimum** (default profile). **12GB+ is recommended** — it is where
action-block adherence and Korean quality stop needing workarounds. Modules and state
updates run on OpenRouter by default, so an 8GB machine still gets the full workflow.

## Profiles (`config.yaml` → `local_profiles`)

| Profile | VRAM | Model | num_ctx | history_window |
|---------|------|-------|---------|----------------|
| **`local`** (default) | ~8GB | `qwen2.5:7b` Q4 | 8192 | 12 |
| **`local_plus`** (recommended) | ~12GB+ | `qwen3.5:9b` Q4 | 16384 | 16 |

```yaml
conductor:
  provider: ollama          # openrouter | ollama | mock
  local_profile: local      # local | local_plus
  base_url: http://127.0.0.1:11434   # native /api/chat; num_ctx is passed per request
```

Worker modules stay on OpenRouter (`worker.model`) unless you change them.

## Why `qwen3.5:9b` for 12GB

- Weights ~6.6GB at Q4 → ~4–5GB left for KV cache → 16K context is comfortable
- Strong Korean + tool/JSON adherence (Conductor action blocks)
- Thinking mode off by default on the small series — no `<think>` pollution
- Apache 2.0

14B Q4 (~9GB) leaves little room for context on 12GB; Korean also costs more tokens than English,
so the smaller model with more ctx headroom wins for this app.

## Why 8GB is still the default profile

- RTX 4060 / 3060 8GB / many laptop GPUs sit here
- 9B/12B/14B Q4 do not leave usable context on 8GB
- Conductor only needs short replies + routing + JSON action
- `project_state.md` carries long-project memory so 7B + 8K ctx is enough
- `action_recovery` covers occasional missing action blocks on 7B

## 8GB recipe

1. Install [Ollama](https://ollama.com)
2. `ollama pull qwen2.5:7b`
3. Set in `config.yaml`:

```yaml
conductor:
  provider: ollama
  local_profile: local
```

4. Keep `project_state.md` updated (module runs auto-propose patches; review with Y/n)

## Reliability by size (action block + Korean)

The Conductor must end each reply with a small ```action``` JSON block. What matters
is instruction-following, not knowledge.

| Size | Action block adherence (rough, Q4) | Korean quality | Fits |
|------|------------------------------------|----------------|------|
| 7B (`qwen2.5:7b`) | occasional misses — omit or prose after block | usable, sometimes stiff | 8GB |
| 9B (`qwen3.5:9b`) | good; rare misses | strong | **12GB+ (recommended)** |
| 12B (`gemma3:12b`) | good; rare misses | strong, natural | 12GB+ (~8GB weights) |
| 14B (`qwen2.5:14b`) | good; rare misses | good | 12GB+ (~9GB weights, tight ctx) |

When the block is missing, `conductor.action_recovery` (default `auto` = local providers)
makes one extra JSON-only call (`format: json` on Ollama) that reads the visible reply
and extracts `{"type": ..., "agent": ...}`. Guards: `run`/`read` are accepted only if the
reply text actually names that module; anything unparseable becomes `none`. The recovered
block is written into history so later turns see a correct example. Cost: one short
local call on the turns where the 7B model slipped. Set `always` to enable on cloud,
`off` to disable.

If recovery also fails, the reply is shown, nothing runs, nothing crashes — type
`/run <agent>` or ask again.

Alternatives for `local_plus`:

```yaml
local_profiles:
  local_plus:
    model: gemma3:12b      # prose-first Korean; slightly less ctx headroom
    # model: qwen2.5:14b  # stable fallback; tighter on 12GB
    num_ctx: 16384
```

## 12GB+ recipe (recommended)

```bash
ollama pull qwen3.5:9b
```

```yaml
conductor:
  provider: ollama
  local_profile: local_plus
  ollama_autostart: true      # start server if not running
  ollama_pull_missing: ask    # ask before downloading a missing model
  ollama_warmup: true         # load into VRAM before the first chat turn
```

Ollama still needs to be **installed** once. After that, opening a project is enough —
the app starts the server, offers to pull the model, and warms VRAM.

## Token budget by tier

| Block | `local` (7B / 8K) | `local_plus` (9B / 16K) |
|-------|-------------------|--------------------------|
| System + conductor | ~600 | ~600 |
| brief.md | 800–1,500 | 800–2,000 |
| project_state.md | 800–1,000 | 800–1,200 |
| module snapshot | ~200 | ~200 |
| recent history | ~1,200 (12 msgs) | ~2,000 (16 msgs) |
| **Target total** | **~4–5K** | **~5–8K** |

Always prefer state over full module dumps (`prefer_state_over_modules: true`).
