# RAG for specialist experts

## Goal

`regulation_checker` should cite **retrieved, dated ordinance text** instead of inventing
numbers from model memory. Production retrieval runs on a **VPS over HTTP**; local markdown
is an offline fallback.

## Status

| Piece | State |
|---|---|
| Config (`rag:` in `config.yaml`) | ready — `enabled: false` by default |
| Worker hook (`retrieve_for_agent`) | ready |
| **HTTP client → VPS** (`provider: http`) | ready — see **[docs/rag_api.md](rag_api.md)** |
| Local markdown retriever | ready — `provider: local_files` |
| Corpus `knowledge/regulations/` | scaffold samples for offline / contract demos |
| Example request/response JSON | `examples/rag_retrieve_request.json` |

## Production (VPS)

```yaml
rag:
  enabled: true
  provider: http
  # base_url: https://YOUR_VPS   # or SIDA_RAG_URL
  path: /v1/retrieve
  api_key_env: SIDA_RAG_API_KEY
```

What the VPS receives / must return is fully specified in **[rag_api.md](rag_api.md)**.
Replay a call:

```bash
curl -sS -X POST "$SIDA_RAG_URL/v1/retrieve" \
  -H "Authorization: Bearer $SIDA_RAG_API_KEY" \
  -H "Content-Type: application/json" \
  -d @examples/rag_retrieve_request.json
```

## Offline fallback

```yaml
rag:
  enabled: true
  provider: local_files
  knowledge_dir: knowledge
```

## Call path

```
run_worker_agent(regulation_checker)
  → build_retrieval_query(brief + state + input experts)
  → retrieve_for_agent(...)
       → HttpApiRetriever  POST /v1/retrieve  { api_version, collection, query, context… }
       → or LocalFileRetriever over knowledge/regulations/
  → build_worker_prompt(..., knowledge_block=formatted passages)
  → model sees RETRIEVED KNOWLEDGE with source: paths
```

## Tests

`tests/test_rag.py` — settings, local ranking, HTTP request body, response parse, worker hook.
