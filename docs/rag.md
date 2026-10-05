# Statute retrieval for experts and the law search

## Goal

`regulation_checker` and the hub law search (`l`) should cite **retrieved, dated statute
text** instead of numbers from model memory. Retrieval never raises: when it yields nothing
the run continues and a one-line `[rag]` warning says why.

Parcel facts (zoning, statutory coverage / FAR limits) are a separate feature — see
`sida/experts/site/site_facts.py` and `/site`. The municipality's planning ordinance (건폐율 / 용적률
articles) is also fetched by `/site`, through `sida/experts/regulation/ordinance.py`, and does not
depend on `rag.enabled`. This document is only about finding statute articles.

## Providers (`rag.provider` in `config.yaml`)

| Provider | What it is | Needs |
|---|---|---|
| `lawgokr` (default) | 법제처 국가법령정보 **지능형 법령검색**, called directly from Sida (`sida/experts/regulation/lawapi.py`) | `LAW_OPEN_API_OC` in `.env`, with "지능형 법령검색 시스템 검색 API" checked in the OPEN API application |
| `local_files` | Markdown under `knowledge/regulations/` (offline, keyword match) | nothing |

Retrieval is off in the team defaults. Turn it on per machine: hub → `c` (settings) → `4`,
or in `config.local.yaml`:

```yaml
rag:
  enabled: true
  # provider: lawgokr   # default; local_files uses the offline corpus instead
```

## Why 법제처 search is the default

법제처 search covers every statute, is always current, and needs no server of our own.
On eight topical questions (2026-10) it found the expected article in six and a related
one in the other two. An unknown `rag.provider` value gets a warning that names it.

What to know about it (`lawapi.py` has the details):

- **It wants short questions.** "직통계단 설치 기준" works; a whole project brief returns
  nothing or noise. So for `regulation_checker`, Sida does not send the brief. It builds up
  to five short questions (`rag.focus_queries`) from **site facts** — the zoning
  ("일반공업지역에서 건축할 수 있는 건축물", "일반공업지역 건폐율 용적률") and districts
  that need checking — and then from short Korean lines in the brief (Project Type, Core
  Problem). With no site facts and an English brief there is nothing to ask, and the
  warning tells the designer to run `/site <주소>` first.
- **Rank only, no score.** Nonsense still returns results, and the tail of each list is
  noisy. Sida keeps the top 3 per question (6 for a single question in the law search).
- **Articles come with full text**; long ones are cut to 1,800 characters.
- **Annexes (별표) come as titles only** and the annex search is unreliable, so they are not
  injected. Ordinances are not covered; they are planned through the ordinance API.
- **Be gentle with the service.** Identical questions are answered from memory within a
  run, and one expert run sends at most five requests.

## Call path

```
run_worker_agent(regulation_checker)
  → site_facts.load_facts(project)                       # zoning etc., if /site was run
  → rag.retrieve_for_agent(..., site_facts=facts)
       lawgokr:      focus_queries(brief, facts) → lawapi.ai_search per question → merge
       local_files:  keyword match over knowledge/regulations/
  → build_worker_prompt(..., knowledge_block=formatted passages)
  → model sees RETRIEVED KNOWLEDGE with `source: law.go.kr/<법령명> <조>` lines

hub → l (law_search.py)
  → the designer's question (plus a synonym variant) → rag.retrieve_passages → model answer
```

## Tests

- `tests/experts/regulation/test_lawapi.py` — the 법제처 client and provider against recorded responses
  (`tests/fixtures/lawapi/`): parsing, caching, rejected or missing key, focused questions,
  what `regulation_checker` receives.
- `tests/experts/regulation/test_rag.py` — settings, local ranking, worker prompt injection, warnings.

Tests never call law.go.kr: `tests/conftest.py` blocks `lawapi._http_get` and sets a fake OC.
