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
pip install -r requirements.txt
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

Model and agent settings live in `config.yaml`.

### Local Conductor (optional, Ollama)

The Conductor (chat) can run on a local model while modules stay on OpenRouter.
8GB VRAM is the minimum (`local`, 7B); 12GB+ is recommended (`local_plus`, `qwen3.5:9b`).
See `docs/gpu_tiers.md`.

```bash
ollama pull qwen2.5:7b      # 8GB
ollama pull qwen3.5:9b      # 12GB+ recommended
```

`conductor.provider: ollama` 이면 앱이 세션을 열 때 Ollama 서버를 자동으로 띄우고,
모델이 없으면 받을지 물은 뒤 VRAM에 올려 둡니다 (`ollama_autostart` / `ollama_warmup`).
Ollama **설치**만은 한 번 필요합니다 — https://ollama.com

```yaml
# config.yaml
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
pip install -r requirements.txt
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
Modules updated after the state file are shown to the Conductor in full until
you fold them into the state.

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

- Version 0.1 — CLI prototype only
- Does not generate drawings, models, or a finished design
- Quality depends on the brief and the chosen model
- `regulation_checker` and `precedent_scout` produce verification agendas, not facts — numbers and named works must be checked by the designer. Turn on `rag.enabled` once `knowledge/regulations/` has real excerpts (`docs/rag.md`).
- Opening an old project auto-renames `01_*.md` module files to the new `11_` / `31_` / … names and adds missing Module Status rows.
- No web UI, database, or RAG layer

## Next steps

- Add optional dry-run / mock mode for demos without an API key
- Save a run log with model and timestamps
- Attach sample outputs under `examples/sample_output/`
- Refine agent prompts against studio review feedback

## Development

```bash
pip install -e ".[dev]"     # or: pip install pytest ruff
pytest                      # 60+ offline tests (mock provider, no network)
ruff check .
```

Module layout:

| File | Role |
|---|---|
| `chat.py` | entry point: first-run setup → hub → sessions |
| `hub.py` | project picker (create / open / sample) |
| `session.py` | one Conductor session: `Session` state, turns, actions, loop |
| `commands.py` | slash commands (`/brief`, `/state`, `/run`, ...) |
| `conductor.py` | Conductor message assembly, action parsing, one LLM call |
| `briefs.py` | brief.md authoring — guided fields or external editor |
| `console.py` | prompts, `$EDITOR` launch, UTF-8 stdio |
| `state_updater.py` | project_state.md patch proposal (JSON call → diff → apply) |
| `ollama_boot.py` | start Ollama, pull missing model, warm VRAM on session open |
| `migrate.py` | rename legacy module files + sync Module Status on project open |
| `rag.py` | retrieval stub for regulation_checker (`rag.enabled`) |
| `run.bat` | Windows launcher: venv + deps + dispatch |
| `harness.py` | providers (OpenRouter / Ollama / mock), worker runs, context budget |
| `project.py` | project folder I/O, `project_state.md`, brief section patching |
| `i18n.py` | UI strings — Korean default, English fallback |
| `setup_env.py` | language + OpenRouter key setup |
| `run.py` | non-interactive sequential pipeline |

Editor for `/brief edit` and `/state edit`: `SIDA_EDITOR` → `VISUAL` → `EDITOR` → `notepad` (Windows) / `nano`, `vim`, `vi`.

## Tools

Python / OpenRouter / Ollama / Markdown / YAML / LLM prompts
