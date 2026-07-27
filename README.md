# Sida (시다)

A CLI-based LLM workflow for architectural design reasoning.

**시다**는 한국 건축 현장에서 조수·보조를 부르는 말입니다.  
이 도구도 건물을 대신 설계하지 않고, 설계자의 추론을 옆에서 돕는 조수처럼 동작합니다.

Instead of using one model as a general generator, the workflow divides the design process into narrow agents: Site Reader, Constraint Mapper, Design Critic, Representation Planner, and Presentation Editor — coordinated by a Conductor.

The output is not a final design. It is a set of structured Markdown documents that help clarify site issues, constraints, unresolved problems, representation needs, and presentation structure.

## Why this project exists

Most AI tools are used as isolated generators — image, text, concept, summary. Architectural design is not a single generation task. It involves reading the site, organizing constraints, testing intentions, receiving critique, and deciding what to represent.

Sida asks a different question:

> How can an LLM support architectural design reasoning without pretending to automatically design a building?

## Pipeline

```txt
Brief
  → Site Reader
  → Constraint Mapper
  → Design Critic
  → Representation Planner
  → Presentation Editor
  → structured Markdown outputs
```

## Installation

```bash
pip install -r requirements.txt
```

## Environment setup

가장 쉬운 방법 — 프로그램이 직접 안내합니다:

```bash
python setup.py
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

## How to run

### First launch

```bash
pip install -r requirements.txt
python chat.py
```

1. Language (English screen first)
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
├─ session.json
├─ history.json      ← Conductor conversation (restored on resume)
├─ transcript.md     ← human-readable log
└─ modules/
   ├─ 01_site_reader.md
   └─ ...
```

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
  /agents
  /status
  /setup
  /run site_reader
  /quit
```

Conductor model and worker model are set in `config.yaml`.

### Sequential pipeline (all modules, non-interactive)

```bash
python run.py input/sample_brief.md
python run.py input/geumjeong_station_brief.md
```

Outputs go to the same `projects/<name>/modules/` layout.

## Output example

```txt
~/Sida/projects/geumjeong_station_brief/
├─ brief.md
├─ session.json
├─ transcript.md
└─ modules/
   ├─ 01_site_reader.md
   ├─ 02_constraint_mapper.md
   ├─ 03_design_critic.md
   ├─ 04_representation_planner.md
   └─ 05_presentation_editor.md
```

## Agents

| Agent | Role |
|---|---|
| Site Reader | Reads site conditions, conflicts, opportunities, missing info |
| Constraint Mapper | Turns conditions into hard/soft constraints and tensions |
| Design Critic | Critiques direction; names unresolved problems and next actions |
| Representation Planner | Plans diagrams, drawings, and presentation hierarchy |
| Presentation Editor | Structures concise portfolio / review communication |

Each agent has a narrow task, a clear input, a fixed Markdown output format, and constraints on what it should not do.

## Limitations

- Version 0.1 — CLI prototype only
- Does not generate drawings, models, or a finished design
- Quality depends on the brief and the chosen model
- No memory beyond sequential context passed between agents
- No web UI, database, or RAG layer

## Next steps

- Add optional dry-run / mock mode for demos without an API key
- Save a run log with model and timestamps
- Attach sample outputs under `examples/sample_output/`
- Refine agent prompts against studio review feedback

## Tools

Python / OpenRouter / Markdown / YAML / LLM prompts
