# Sida (시다)

A local web app (LLM workflow) for architectural design reasoning.

**시다**는 한국 건축 현장에서 조수·보조를 부르는 말입니다.  
이 도구도 건물을 대신 설계하지 않고, 설계자의 추론을 옆에서 돕는 조수처럼 동작합니다.

Instead of using one model as a general generator, the workflow divides design reasoning into ten narrow **experts** — site, program, regulation, precedent, concept, spatial review, systems, critique, representation, presentation — coordinated by a Conductor. Experts are independent lenses: any of them can run alone, in any order, and the Conductor lays out the conditions, conflicts, and decisions they add up to. See `docs/experts.md`.

The output is not a final design. It is a set of structured Markdown documents that help clarify site issues, program demands, regulatory agenda, the concept's claims, constraints, unresolved problems, representation needs, and presentation structure.

## Why this project exists

Most AI tools are used as isolated generators — image, text, concept, summary. Architectural design is not a single generation task. It involves reading the site, organizing constraints, testing intentions, receiving critique, and deciding what to represent.

Sida asks a different question:

> How can an LLM support architectural design reasoning without pretending to automatically design a building?

## How the experts combine

Design is not linear. A project may be led by its site, by an idea, by the program, or by
regulation — so there is no fixed pipeline. Instead:

```txt
                 analysis                concept
Brief ──┬─ site_reader ─────────┐
        ├─ program_analyst ─────┤
        ├─ regulation_checker ──┼─→ concept_framer ──┐
        └─ precedent_scout ─────┘                    │
                                                     │
        development: spatial_reviewer, systems_advisor ←─┤
        critique:    design_critic                     ←─┤
        communication: representation_planner, presentation_editor

Conductor: conditions (hard/soft), conflicts between experts, decisions required now
```

- Every expert declares `inputs` (which prior outputs it reads) and ends with a **Handoff**
  section naming who should look next. Other completed outputs are listed by name only.
- The Conductor picks the entry expert from the brief's **Primary Driver**
  (`site | idea | program | regulation | competition`) and from what the designer is stuck on.
- `paths` in `config.yaml` are suggested sequences per driver — hints for the Conductor.

## Installation

### Windows — `run.bat` (권장)

Python 3.10+ 만 설치되어 있으면 됩니다. `run.bat`을 더블클릭하거나:

```bat
run.bat                      :: 웹 UI (브라우저에서 http://127.0.0.1:8765). 첫 실행 시 .venv 생성 + 의존성 설치
run.bat --port 8800          :: 다른 포트 (--no-browser: 브라우저를 열지 않음)
run.bat test                 :: 테스트
run.bat update               :: 의존성 재설치
```

Python이 없으면 python.org 안내 메시지가 뜹니다 (설치 시 "Add python.exe to PATH" 체크).

### Manual (macOS / Linux / 개발용)

Python 3.10 or newer.

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -e .
```

## Environment setup

API 키는 웹 UI의 설정 화면에서 넣습니다(`PUT /api/settings/keys/{key}`, `docs/settings-api.md`).
OpenRouter 키는 https://openrouter.ai/keys 에서 발급하고, 저장 전에 확인한 뒤 `.env`에 씁니다.

설정 화면 없이 하려면:

```bash
cp .env.example .env
# .env 에 OPENROUTER_API_KEY=... 입력
```

Model and agent settings live in `config.yaml` (team defaults: cloud via OpenRouter, RAG off).
Per-machine choices go to the git-ignored `config.local.yaml`, which overrides it.
The settings screen (`GET/PUT /api/settings`) chooses **cloud (OpenRouter) or local (Ollama)**
and writes the answer there.

### Local Conductor (optional, Ollama)

In local mode the Conductor and the experts both run on Ollama; cloud mode uses OpenRouter
for both. You can also mix them per role in the settings. 8GB VRAM is the minimum (`local`, 7B); 12GB+ is recommended (`local_plus`, `qwen3.5:9b`).
See `docs/gpu_tiers.md`.

```bash
ollama pull qwen2.5:7b      # 8GB
ollama pull qwen3.5:9b      # 12GB+ recommended
```

`conductor.provider: ollama` 이면 앱이 세션을 열 때 Ollama 서버를 자동으로 띄우고,
모델이 없으면 받을지 물은 뒤 VRAM에 올려 둡니다 (`ollama_autostart` / `ollama_warmup`).
Ollama **설치**만은 한 번 필요합니다 — https://ollama.com

```yaml
# config.local.yaml (this machine only)
conductor:
  provider: ollama          # openrouter | ollama | mock
  local_profile: local_plus # local (8GB, 7B) | local_plus (12GB+, qwen3.5:9b)
  ollama_autostart: true
  ollama_pull_missing: ask  # ask | auto | off
  ollama_warmup: true
```

`provider: mock` runs the whole app without any model (UI / flow testing).

### Project memory updates (`state_update`)

After every module run the app proposes a `project_state.md` patch — Module Status row,
Meta lines, and only the bullet sections the module informs — as a diff the designer applies
or skips (`docs/session-api.md`, `docs/state-editing.md`).

```yaml
# config.yaml
state_update:
  mode: ask          # ask | auto | off
  provider: worker   # worker (cloud, reliable JSON) | conductor (fully local)
```

The previous version is kept in `project_state.prev.md`.

## How to run

```bash
pip install -e .
python webapp.py            # http://127.0.0.1:8765 (--port, --no-browser)
```

The browser opens the project list (create / open / sample). Inside a project you talk with the
Conductor, and experts run when needed. The screens call the JSON API under `/api`; see
`docs/session-api.md`, `docs/settings-api.md`, `docs/chatgpt-login.md`, `docs/site-ordinance.md`, `docs/law-search-api.md`
and `docs/state-editing.md`.

Projects are saved under the user home folder (easy to open in File Explorer):

```txt
~/Sida/projects/sample_brief/
├─ brief.md
├─ brief.prev.md       ← backup written when the brief is edited
├─ project_state.md    ← rolling project memory for the Conductor (auto-proposed after module runs)
├─ project_state.prev.md ← backup written before each state update
├─ session.json
├─ history.json        ← Conductor conversation (restored on resume)
├─ transcript.md       ← human-readable log
└─ modules/
   ├─ 11_site_reader.md
   ├─ 21_concept_framer.md
   ├─ ...
   └─ _history/        ← previous versions, archived on rerun
```

`project_state.md` is what the Conductor reads instead of the full chat log.
Keep it short: decisions, open questions, module status, next focus.
Expert outputs are shown to the Conductor in full until their exact content version
is accepted into the state. Updating one expert's state does not hide other unreflected
outputs. Existing projects without version records retain full outputs until accepted.

Path is set in `config.yaml` → `projects_dir`.

The Conductor can also ask to read a completed module file
(`{"type": "read", "module": "site_reader"}`) when the state file lacks detail.

Conductor model and worker model are set in `config.yaml`.

## Experts

File numbers are grouped by phase (1x analysis, 2x concept, 4x development, 5x critique,
6x communication). They are not an execution order. There is no 3x: putting the lenses
together is the Conductor's job.

| Expert | Phase | What it does | Reads |
|---|---|---|---|
| `site_reader` | analysis | site systems, conflicts, opportunities, missing site info | program, concept |
| `program_analyst` | analysis | users and rhythms, components, adjacency, public–private gradient | site, concept |
| `regulation_checker` | analysis | governing frameworks (KR default), what to verify, binding constraints, incentives | site, program |
| `precedent_scout` | analysis | precedents/typologies matched to the problem — lesson and caution | concept, site |
| `concept_framer` | concept | sharpen the designer's idea into a testable concept and operative strategy | site, program, precedent |
| `spatial_reviewer` | development | test the described organization: circulation, section, thresholds, program fit | concept, site, program, regulation |
| `systems_advisor` | development | structure / envelope / services / egress questions and trade-offs — no sizing | spatial, regulation, site, program |
| `design_critic` | critique | jury-style critique against the core problem | all |
| `representation_planner` | communication | diagrams, drawings, models that prove the concept and test weak points | concept, spatial, critic, site |
| `presentation_editor` | communication | review / portfolio story, structure, anticipated questions | concept, critic, representation |

Each expert has a narrow lens, declared inputs, a fixed Markdown output format ending in
`## Handoff`, and constraints on what it must not do (none of them designs the building).
Adding an expert = one prompt file + one `agents:` entry in `config.yaml`; the Conductor's
expert list and the `project_state.md` Module Status table are generated from config.

## Limitations

- Version 0.2 — local web prototype; the screens are still being built
- Does not generate drawings, models, or a finished design
- Quality depends on the brief and the chosen model
- `regulation_checker` and `precedent_scout` produce verification agendas, not facts — numbers and named works must be checked by the designer. Statute retrieval is off by default; turned on, it searches 법제처 (law.go.kr) directly and needs only `LAW_OPEN_API_OC` in `.env` (`docs/rag.md`).
- In local mode, long inputs are trimmed to fit the model's context window (a notice is shown); `design_critic` reads every output and is affected most.
- Opening an old project auto-renames `01_*.md` module files to the new `11_` / `31_` / … names and adds missing Module Status rows.
- No database: projects are folders of Markdown and JSON files

## Next steps

See the [roadmap in the team's Notion](https://app.notion.com/p/3ecf5f66cbb7811596e0e3c69b7a229b) (moved out of the repo on 2026-10-25). In short: build the web screens on the JSON API.
The terminal CLI was removed (2026-10-16); every feature goes through the web.

## Development

처음 개발 환경을 세팅한다면 [`docs/dev-setup.md`](docs/dev-setup.md), 팀 규칙은 [`CONTRIBUTING.md`](CONTRIBUTING.md), AI 에이전트 규칙은 [`AGENTS.md`](AGENTS.md)를 보세요.

```bash
pip install -e ".[dev]"     # or: pip install pytest ruff
pytest                      # offline tests (mock provider, no network)
ruff check .
```

저장소 폴더:

| 폴더 | 용도 |
|---|---|
| `sida/` | 앱 코드(파이썬 패키지) |
| `webui/` | 웹 화면(`webui/app/`)과 ChatGPT 로그인 결과 페이지 |
| `agents/` | 전문가와 Conductor 프롬프트 |
| `data/` | 앱이 읽는 자료: 법정 건폐율·용적률 표, 프로젝트 메모 틀, 샘플 브리프(`data/briefs/`) |
| `knowledge/` | 법령 검색 `local_files` 방식이 읽는 마크다운 |
| `docs/` | 설계·API 문서 |
| `tests/` | 테스트(녹화한 정부 API 응답은 `tests/fixtures/`) |
| `scripts/` | 테스트용 정부 API 응답을 다시 녹화하는 스크립트 |
| `collector/` | 팀 VPS의 사용 기록 수집 서버(앱 패키지와 별개) |
| `assets/` | 로고 |

프로젝트 데이터는 저장소가 아니라 `~/Sida/projects`에 저장됩니다.

Module layout. The code is the `sida/` package: the shared core sits directly in `sida/`, and code that belongs to one expert domain sits in `sida/experts/<domain>/` (tests mirror this under `tests/experts/<domain>/`). `webapp.py` in the repo root only starts `sida/webapp.py`.

| File (under `sida/`) | Role |
|---|---|
| `engine.py` | UI-agnostic session core: `Session` state, Conductor turns, expert runs, state updates — returns values and emits events, never prints |
| `conductor.py` | Conductor message assembly, action parsing, one LLM call |
| `briefs.py` | brief.md from the seven basic fields |
| `console.py` | UTF-8 stdio, terminal colors for server logs |
| `state_updater.py` | project_state.md patch proposal (JSON call → diff → apply) |
| `ollama_boot.py` | start Ollama, pull missing model, warm VRAM on session open |
| `migrate.py` | rename legacy module files + sync Module Status on project open |
| `experts/__init__.py` | how a domain plugs into the core: each `experts/<domain>/hooks.py` is discovered automatically and may provide `prompt_blocks(run)` (text for an expert's prompt) and `api_router(...)` (JSON routes for the web UI) |
| `experts/regulation/rag.py` | statute retrieval for regulation_checker / law search — 법제처 search (default) or local markdown |
| `experts/regulation/lawapi.py` | client for the 법제처 OPEN API (law.go.kr): intelligent statute search |
| `experts/regulation/law_search.py` | statute Q&A without a project (retrieved articles + Conductor model), `POST /api/law/search` |
| `experts/rhino/rhino_modeler.py` | Rhino modeling turn (OpenAI model plans, MCP tools execute); not on the web yet, a later special feature |
| `experts/rhino/rhino_mcp.py` / `mcp_stdio.py` | Rhino MCP router bridge, allowed-tool list, stdio JSON-RPC client |
| `hardware.py` | GPU detection (NVIDIA) and local-profile recommendation |
| `workspace.py` | UI-agnostic project hub operations: list, look up, create |
| `session_api.py` / `session_jobs.py` / `expert_chat.py` | web session: Conductor chat, expert runs in the background, per-expert chat (`docs/session-api.md`) |
| `settings.py` / `settings_api.py` | settings screen: run mode, models, API keys → `config.local.yaml` / `.env` (`docs/settings-api.md`) |
| `chatgpt_auth.py` / `chatgpt_api.py` | Sign in with ChatGPT: the Conductor on the user's own ChatGPT plan (`docs/chatgpt-login.md`) |
| `experts/regulation/ordinance.py` | finds the municipality's 도시·군계획 조례 on law.go.kr and quotes its 건폐율 / 용적률 articles as written, and reads the figure for the site's zone by fixed rules, shown next to the quoted line; follows "별표 N과 같다" into the annex file (`hwp.py` reads HWP) (stored in `site_facts.json` by the site lookup, given to `regulation_checker`) |
| `experts/site/landapi.py` | clients for the government land APIs (VWorld): parcel search, zoning, land characteristics |
| `experts/site/site_facts.py` + `data/zoning_limits.yaml` (repo root) | site facts: parcels → one site, statutory coverage / FAR limits, items to verify; saved as `site_facts.json` and given to `site_reader` / `regulation_checker` |
| `webapp.py` + `webui/` (repo root) | local web UI (FastAPI): JSON API under `/api`; the main screen at `/` is `webui/app/` (plain HTML/CSS/JS calling the API, see `docs/web-ui.md`); `webui/templates` and `webui/static` only render the ChatGPT sign-in result page |
| `run.bat` (repo root) | Windows launcher: venv + deps, then the web UI |
| `config.py` | `config.yaml` (team defaults) overlaid with `config.local.yaml` (this machine); the expert list and lookups |
| `providers.py` | LLM providers (OpenRouter / OpenAI / Ollama / mock) behind one `chat()` call, with retries |
| `runtime.py` | which provider, model and context size the Conductor and the workers run with (local profiles applied) |
| `worker.py` | running one expert: the outputs it reads, its prompt, the local context budget, header check, saving |
| `conductor_context.py` | what the Conductor is sent: prompt with the expert list, recent history, expert outputs |
| `project.py` | project folder I/O, `project_state.md`, brief section patching |
| `i18n.py` | UI strings — Korean default, English fallback |

## Tools

Python / OpenRouter / Ollama / Markdown / YAML / LLM prompts
