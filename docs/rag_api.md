# Sida ↔ VPS RAG API contract

**API version:** `sida.rag.v1`  
Client: `rag.py` → `HttpApiRetriever`  
Server: your VPS. This doc is what the VPS should implement / log against.

## Enable on the Sida client

```yaml
# config.yaml
rag:
  enabled: true
  provider: http
  base_url: https://YOUR_VPS_HOST   # no trailing slash; or set env SIDA_RAG_URL
  path: /v1/retrieve
  api_key_env: SIDA_RAG_API_KEY
  timeout: 30
  agents:
    regulation_checker: regulation
```

```bash
# .env
SIDA_RAG_URL=https://YOUR_VPS_HOST
SIDA_RAG_API_KEY=secret
```

## Endpoint

```
POST {base_url}{path}          # default path /v1/retrieve
Authorization: Bearer {key}    # omitted if key empty
Content-Type: application/json
Accept: application/json
```

Optional health check (recommended on VPS, not required by client yet):

```
GET {base_url}/health  →  200 {"ok": true, "api_version": "sida.rag.v1"}
```

## Request body (what Sida sends)

Canonical example: [`examples/rag_retrieve_request.json`](../examples/rag_retrieve_request.json)

| Field | Type | Meaning |
|---|---|---|
| `api_version` | string | Always `sida.rag.v1` |
| `collection` | string | Which index — for now always `regulation` |
| `agent_id` | string | Expert that triggered retrieval (`regulation_checker`) |
| `query` | string | Ranked search text: brief + state + prior expert outputs (truncated ~2500 chars) |
| `top_k` | int | Max passages to return |
| `max_chars` | int | Soft budget for total passage text the client will keep |
| `lang` | string | UI language (`ko` / `en`) — prefer Korean passages when `ko` |
| `context.brief` | string | Full-ish project brief (truncated) — **for VPS logging / filters** |
| `context.project_state` | string | Rolling memory (truncated) |
| `context.expert_outputs` | string | Prior experts this agent reads (e.g. site_reader, program_analyst) |

`query` is what you should embed/search.  
`context.*` is so the VPS can **inspect why** this query was built (site type, municipality, rail/stream flags) and apply hard filters (시·군·구, 용도지역) without re-parsing the whole client.

### When it fires

Only when:

1. `rag.enabled: true` and `provider: http`
2. The running expert is listed under `rag.agents` (default: `regulation_checker` → collection `regulation`)
3. A worker run starts for that expert

## Response body (what Sida expects)

```json
{
  "api_version": "sida.rag.v1",
  "passages": [
    {
      "source": "kr/건축법_시행령_86.md#§3",
      "title": "건축법 시행령 제86조 (일조 등)",
      "text": "… official excerpt …",
      "score": 0.82
    }
  ]
}
```

Aliases accepted: `results` or `chunks` instead of `passages`; `content` instead of `text`; `id` / `path` instead of `source`.

| Field | Required | Notes |
|---|---|---|
| `source` | yes | Stable citation id — shown to the model as `source: …` |
| `title` | no | Defaults to `source` |
| `text` | yes | Passage body; keep under a few hundred–1k chars each |
| `score` | no | Higher = better; client sorts only if you already ranked |

Empty hit → `{"passages": []}` (HTTP 200).  
Non-200 or invalid JSON → client injects **nothing** (expert falls back to agenda-only mode). Do not 500 on “no hits”.

## What the expert does with passages

Sida formats passages into a `RETRIEVED KNOWLEDGE (regulation)` block and injects it into the worker prompt. `regulation_checker` must:

- Prefer these numbers over model memory
- Cite `source:` paths
- Fill `## Sources Used`
- Still mark site-specific items as `verify`

## Collections

| collection | Used by | Corpus theme |
|---|---|---|
| `regulation` | `regulation_checker` | KR building / planning / rail / stream ordinances |

Add more later via `rag.agents` + a new index on the VPS — no client code change beyond config.

## Local offline fallback

```yaml
rag:
  enabled: true
  provider: local_files
  knowledge_dir: knowledge
```

Uses `knowledge/regulations/*.md` (scaffold samples in-repo). Same prompt injection path.

## Debugging on the VPS

Log at least:

```txt
agent_id, collection, top_k, len(query), context.brief[:200], passage_count, latency_ms
```

To replay a client call, POST the example JSON:

```bash
curl -sS -X POST "$SIDA_RAG_URL/v1/retrieve" \
  -H "Authorization: Bearer $SIDA_RAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d @examples/rag_retrieve_request.json
```
