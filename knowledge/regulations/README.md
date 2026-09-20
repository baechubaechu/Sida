# Regulation knowledge corpus

Markdown files in this folder are retrieved for `regulation_checker` when
`rag.enabled: true` in `config.yaml`.

## Conventions

- One topic per file (or one statute / ordinance chapter).
- Start with `# Title` and use `##` sections — each section becomes a chunk.
- Always include: jurisdiction, statute name, article (if any), and **as-of date**.
- Prefer official wording for numbers; paraphrase only when clarifying design impact.
- Filename: `kr_<topic>.md` (e.g. `kr_building_act_setbacks.md`, `kr_gunpo_zoning.md`).
- Files starting with `_` are ignored by the retriever (drafts, notes).

## Status

This folder ships with **scaffold samples** so the retriever path can be tested.
Replace them with real, dated excerpts before relying on numbers in production.
