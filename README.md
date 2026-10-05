# Sida (시다)

A CLI-based LLM workflow for architectural design reasoning.

**시다**는 한국 건축 현장에서 조수·보조를 부르는 말입니다.  
이 도구도 건물을 대신 설계하지 않고, 설계자의 추론을 옆에서 돕는 조수처럼 동작합니다.

Instead of using one model as a general generator, the workflow divides design reasoning into twelve narrow **experts** — site, program, regulation, precedent, concept, constraints, synthesis, spatial review, systems, critique, representation, presentation — coordinated by a Conductor. Experts are independent lenses: any of them can run alone, in any order, and a `synthesizer` reconciles them. See `docs/experts.md`.

The output is not a final design. It is a set of structured Markdown documents that help clarify site issues, program demands, regulatory agenda, the concept's claims, constraints, unresolved problems, representation needs, and presentation structure.

## Why this project exists

Most AI tools are used as isolated generators — image, text, concept, summary. Architectural design is not a single generation task. It involves reading the site, organizing constraints, testing intentions, receiving critique, and deciding what to represent.

Sida asks a different question:

> How can an LLM support architectural design reasoning without pretending to automatically design a building?

## How the experts combine

Design is not linear. A project may be led by its site, by an idea, by the program, or by
regulation — so there is no fixed pipeline. Instead:

```txt
                 analysis                concept        synthesis
Brief ──┬─ site_reader ─────────┐
        ├─ program_analyst ─────┤                     ┌─ constraint_mapper
        ├─ regulation_checker ──┼─→ concept_framer ──→┤
        └─ precedent_scout ─────┘                     └─ synthesizer ─→ decisions
                                                            │
        development: spatial_reviewer, systems_advisor ←────┤
        critique:    design_critic                     ←────┤
        communication: representation_planner, presentation_editor
```

- Every expert declares `inputs` (which prior outputs it reads) and ends with a **Handoff**
  section naming who should look next. Other completed outputs are listed by name only.
- The Conductor picks the entry expert from the brief's **Primary Driver**
  (`site | idea | program | regulation | competition`) and from what the designer is stuck on.
- `paths` in `config.yaml` are suggested sequences per driver — hints for the Conductor, and
  runnable with `python run.py --path idea_driven brief.md`.

## Installation

### Windows — `run.bat` (권장)

Python 3.10+ 만 설치되어 있으면 됩니다. `run.bat`을 더블클릭하거나:

```bat
run.bat                      :: 채팅 (프로젝트 허브). 첫 실행 시 .venv 생성 + 의존성 설치
run.bat web                  :: 웹 UI (브라우저에서 http://127.0.0.1:8765, 지금은 프로젝트 허브까지)
run.bat setup                :: 언어 / OpenRouter 키 설정
run.bat sample_brief         :: 프로젝트 바로 열기
run.bat pipeline input\brief.md   :: 비대화형 순차 실행
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

가장 쉬운 방법 — 프로그램이 직접 안내합니다:

```bash
python setup_env.py
```

또는 `python chat.py ...` / `python run.py ...` 실행 시 키가 없으면 같은 안내가 자동으로 뜹니다.

안내 내용:
1. https://openrouter.ai/keys 에서 키 발급
2. 터미널에 키 붙여넣기 (입력 중 화면에는 안 보임)
3. `.env`에 저장

채팅 중에도 `/setup`으로 키를 다시 설정할 수 있습니다.

수동으로 하려면:

```bash
cp .env.example .env
# .env 에 OPENROUTER_API_KEY=... 입력
```

Model and agent settings live in `config.yaml` (team defaults: cloud via OpenRouter, RAG off).
Per-machine choices go to the git-ignored `config.local.yaml`, which overrides it.
On first launch the app asks **cloud (OpenRouter) or local (Ollama)** and saves the answer
there; change it later from the hub with `c` (settings) → `9`.

### Local Conductor (optional, Ollama)

In local mode the Conductor and the experts both run on Ollama; cloud mode uses OpenRouter
for both. You can also mix them per role in the settings menu. 8GB VRAM is the minimum (`local`, 7B); 12GB+ is recommended (`local_plus`, `qwen3.5:9b`).
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
Meta lines, and only the bullet sections the module informs — and shows a diff:

```txt
[state] site_reader 결과로 project_state.md 갱신안을 만드는 중 ...
--- project_state.md
+++ proposed
-| site_reader | pending | |
+| site_reader | done | 남북 레벨 차 6m가 동선의 핵심 제약 |
...
이 갱신을 적용할까요? [Y = 적용 / n = 건너뛰기 / e = 적용 후 에디터로 열기]:
```

```yaml
# config.yaml
state_update:
  mode: ask          # ask | auto | off
  provider: worker   # worker (cloud, reliable JSON) | conductor (fully local)
```

`/state update [agent_id]` re-proposes from any completed module. Previous version is kept
in `project_state.prev.md`.

## How to run

### First launch

```bash
pip install -e .
python chat.py
```

1. Language (Korean default, English available)
2. API key + verification
3. **Project hub** — create / open / switch projects (no chat)
4. Inside a project — Conductor session

In a session:
- `/close` → save conversation, back to hub
- `/quit` → save and exit app
- Ctrl+C → same as `/close`

Projects are saved under the user home folder (easy to open in File Explorer):

```txt
~/Sida/projects/sample_brief/
├─ brief.md
├─ brief.prev.md       ← backup written by /brief edit
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

Resume later:

```bash
python chat.py sample_brief
python chat.py --list
```
Talk in the terminal. Modules run only when needed.

```txt
Commands:
  /help
  /project
  /brief            show brief
  /brief edit       open brief.md in your editor (backup → brief.prev.md)
  /brief fields     update the seven basic fields only (other sections kept; includes Primary Driver)
  /state            show project_state.md
  /state edit       open project_state.md in your editor
  /state update     propose a state patch from the latest module (diff + confirm)
  /site             show site facts (parcel, zoning, statutory coverage / FAR limits)
  /site <address>   look up a lot-number address; pick one parcel or several to merge
  /site ordinance   list every coverage / FAR article of the municipality's ordinance, in three groups
  /site ordinance <article>   full text of one article
  /site hide <article>        leave it out of what the experts receive (/site show to undo)
  /agents
  /status
  /setup
  /run site_reader
  /quit
```

The Conductor can also ask to read a completed module file
(`{"type": "read", "module": "site_reader"}`) when the state file lacks detail.

Conductor model and worker model are set in `config.yaml`.

### Non-interactive runs

```bash
python run.py input/sample_brief.md                         # every expert, config order
python run.py --path site_driven input/geumjeong_station_brief.md
python run.py --path review_prep projects/geumjeong_station_brief
```

Outputs go to the same `projects/<name>/modules/` layout.

## Experts

File numbers are grouped by phase (1x analysis, 2x concept, 3x synthesis, 4x development,
5x critique, 6x communication). They are not an execution order.

| Expert | Phase | What it does | Reads |
|---|---|---|---|
| `site_reader` | analysis | site systems, conflicts, opportunities, missing site info | program, concept |
| `program_analyst` | analysis | users and rhythms, components, adjacency, public–private gradient | site, concept |
| `regulation_checker` | analysis | governing frameworks (KR default), what to verify, binding constraints, incentives | site, program |
| `precedent_scout` | analysis | precedents/typologies matched to the problem — lesson and caution | concept, site |
| `concept_framer` | concept | sharpen the designer's idea into a testable concept and operative strategy | site, program, precedent |
| `constraint_mapper` | synthesis | hard/soft constraints, priorities, tensions | site, program, regulation |
| `synthesizer` | synthesis | convergences, conflicts between experts, decisions required now, stale views | all |
| `spatial_reviewer` | development | test the described organization: circulation, section, thresholds, program fit | concept, constraints, site, program |
| `systems_advisor` | development | structure / envelope / services / egress questions and trade-offs — no sizing | spatial, constraints, regulation, site |
| `design_critic` | critique | jury-style critique against the core problem | all |
| `representation_planner` | communication | diagrams, drawings, models that prove the concept and test weak points | concept, spatial, critic, site |
| `presentation_editor` | communication | review / portfolio story, structure, anticipated questions | concept, synthesis, critic, representation |

Each expert has a narrow lens, declared inputs, a fixed Markdown output format ending in
`## Handoff`, and constraints on what it must not do (none of them designs the building).
Adding an expert = one prompt file + one `agents:` entry in `config.yaml`; the Conductor's
expert list and the `project_state.md` Module Status table are generated from config.

## Limitations

- Version 0.2 — CLI prototype only
- Does not generate drawings, models, or a finished design
- Quality depends on the brief and the chosen model
- `regulation_checker` and `precedent_scout` produce verification agendas, not facts — numbers and named works must be checked by the designer. Statute retrieval is off by default; turned on, it searches 법제처 (law.go.kr) directly and needs only `LAW_OPEN_API_OC` in `.env` (`docs/rag.md`).
- In local mode, long inputs are trimmed to fit the model's context window (a notice is printed); `synthesizer` and `design_critic` read every output and are affected most.
- Opening an old project auto-renames `01_*.md` module files to the new `11_` / `31_` / … names and adds missing Module Status rows.
- No web UI or database

## Next steps

See [`docs/roadmap.md`](docs/roadmap.md). In short: separate the core from the terminal I/O,
then add a local web UI on top of it (the CLI stays for automation and tests).

## Development

처음 개발 환경을 세팅한다면 [`docs/dev-setup.md`](docs/dev-setup.md), 팀 규칙은 [`CONTRIBUTING.md`](CONTRIBUTING.md), AI 에이전트 규칙은 [`AGENTS.md`](AGENTS.md)를 보세요.

```bash
pip install -e ".[dev]"     # or: pip install pytest ruff
pytest                      # offline tests (mock provider, no network)
ruff check .
```

Module layout. The code is the `sida/` package: the shared core sits directly in `sida/`, and code that belongs to one expert domain sits in `sida/experts/<domain>/` (tests mirror this under `tests/experts/<domain>/`). `chat.py`, `run.py`, `setup_env.py` and `webapp.py` in the repo root only start the module of the same name.

| File (under `sida/`) | Role |
|---|---|
| `chat.py` | entry point: first-run setup → hub → sessions |
| `hub.py` | project picker (create / open / sample) |
| `engine.py` | UI-agnostic session core: `Session` state, Conductor turns, expert runs, state updates — returns values and emits events, never prints |
| `session.py` | terminal front end for a session: renders engine events, asks the inline questions, input loop |
| `commands.py` | slash commands (`/brief`, `/state`, `/run`, ...) |
| `conductor.py` | Conductor message assembly, action parsing, one LLM call |
| `briefs.py` | brief.md authoring — guided fields or external editor |
| `console.py` | prompts, `$EDITOR` launch, UTF-8 stdio |
| `state_updater.py` | project_state.md patch proposal (JSON call → diff → apply) |
| `ollama_boot.py` | start Ollama, pull missing model, warm VRAM on session open |
| `migrate.py` | rename legacy module files + sync Module Status on project open |
| `experts/__init__.py` | how a domain plugs into the core: each `experts/<domain>/hooks.py` is discovered automatically and may provide `prompt_blocks(run)` (text for an expert's prompt), `COMMANDS` (session slash commands) and `api_router(...)` (JSON routes for the web UI) |
| `experts/regulation/rag.py` | statute retrieval for regulation_checker / law search — 법제처 search (default) or local markdown |
| `experts/regulation/lawapi.py` | client for the 법제처 OPEN API (law.go.kr): intelligent statute search |
| `experts/regulation/law_search.py` | hub `l`: regulation Q&A without a project (retrieved articles + Conductor model) |
| `experts/rhino/rhino_modeler.py` | hub `m`: Rhino modeling loop (OpenAI model plans, MCP tools execute) |
| `experts/rhino/rhino_mcp.py` / `mcp_stdio.py` | Rhino MCP router bridge, allowed-tool list, stdio JSON-RPC client |
| `hub_settings.py` | hub `c`: settings menu and run mode → `config.local.yaml` |
| `hub_about.py` | hub `h`: about page listing the experts |
| `hardware.py` | GPU detection (NVIDIA) and local-profile recommendation |
| `workspace.py` | UI-agnostic project hub operations: list, look up, create |
| `experts/regulation/ordinance.py` | finds the municipality's 도시·군계획 조례 on law.go.kr and quotes its 건폐율 / 용적률 articles as written, and reads the figure for the site's zone by fixed rules, shown next to the quoted line; follows "별표 N과 같다" into the annex file (`hwp.py` reads HWP) (stored in `site_facts.json` by `/site`, given to `regulation_checker`) |
| `experts/site/landapi.py` | clients for the government land APIs (VWorld): parcel search, zoning, land characteristics |
| `experts/site/site_facts.py` + `data/zoning_limits.yaml` (repo root) | site facts: parcels → one site, statutory coverage / FAR limits, items to verify; saved as `site_facts.json` and given to `site_reader` / `regulation_checker` |
| `webapp.py` + `webui/` (repo root) | local web UI (FastAPI): JSON API under `/api`, HTML pages from `webui/templates`, styles in `webui/static` |
| `run.bat` (repo root) | Windows launcher: venv + deps + dispatch |
| `config.py` | `config.yaml` (team defaults) overlaid with `config.local.yaml` (this machine); the expert list and lookups |
| `providers.py` | LLM providers (OpenRouter / OpenAI / Ollama / mock) behind one `chat()` call, with retries |
| `runtime.py` | which provider, model and context size the Conductor and the workers run with (local profiles applied) |
| `worker.py` | running one expert: the outputs it reads, its prompt, the local context budget, header check, saving |
| `conductor_context.py` | what the Conductor is sent: prompt with the expert list, recent history, expert outputs |
| `project.py` | project folder I/O, `project_state.md`, brief section patching |
| `i18n.py` | UI strings — Korean default, English fallback |
| `setup_env.py` | language + OpenRouter key setup |
| `run.py` | non-interactive sequential pipeline |

Editor for `/brief edit` and `/state edit`: `SIDA_EDITOR` → `VISUAL` → `EDITOR` → `notepad` (Windows) / `nano`, `vim`, `vi`.

## Tools

Python / OpenRouter / Ollama / Markdown / YAML / LLM prompts
