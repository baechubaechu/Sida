# 코드 구조

개발하는 팀원을 위한 저장소 지도입니다. 작업 규칙은 [`AGENTS.md`](../AGENTS.md), 세팅은 [`dev-setup.md`](dev-setup.md), 전문가 구성은 [`experts.md`](experts.md)에 있습니다.

## 폴더

| 폴더 | 용도 |
|---|---|
| `sida/` | 앱 코드(파이썬 패키지) |
| `webui/` | 웹 화면(`webui/app/`, [`web-ui.md`](web-ui.md))과 ChatGPT 로그인 결과 페이지 |
| `agents/` | 전문가와 Conductor 프롬프트 |
| `data/` | 앱이 읽는 자료: 법정 건폐율·용적률 표, 프로젝트 메모 틀, 샘플 브리프(`data/briefs/`) |
| `knowledge/` | 법령 검색 `local_files` 방식이 읽는 마크다운 |
| `docs/` | 설계·API 문서 |
| `tests/` | 테스트(녹화한 정부 API 응답은 `tests/fixtures/`) |
| `scripts/` | 테스트용 정부 API 응답 녹화, 관련 테스트 고르기, vendor 파일 다시 만들기 |
| `collector/` | 사용 기록 수집 서버(앱 패키지와 별개, [`telemetry.md`](telemetry.md)) |
| `relay/` | 정부 API 중계 서버(키 없는 PC용, 앱 패키지와 별개) |
| `assets/` | 로고 |

## 프로젝트 폴더

프로젝트 데이터는 저장소가 아니라 사용자 폴더의 `~/Sida/projects/<프로젝트>/`에 저장됩니다(`config.yaml`의 `projects_dir`).

```txt
~/Sida/projects/sample_brief/
├─ brief.md              브리프 (고치면 brief.prev.md에 이전 판)
├─ project_state.md      Conductor가 대화 기록 대신 읽는 설계 상태 (이전 판은 project_state.prev.md)
├─ session.json
├─ history.json          첫 Conductor 대화, 나머지 대화는 talks/
├─ transcript.md         사람이 읽는 기록
├─ board.json            제도판의 종이·매스안·아이디어 보드
├─ site_facts.json       정부 자료로 조회한 대지 사실
└─ modules/
   ├─ 11_site_reader.md  전문가 결과
   ├─ ...
   └─ _history/          다시 실행할 때 옮겨 두는 이전 판
```

`project_state.md`는 짧게 둡니다: 결정, 열린 질문, 전문가 상태, 다음 초점. 전문가 결과는 그 판이 설계 상태에 반영될 때까지 Conductor에게 전문으로 갑니다([`state-editing.md`](state-editing.md)).

## 모듈

공통 코어는 `sida/` 바로 아래, 한 전문가 영역에만 쓰이는 코드는 `sida/experts/<영역>/`에 있습니다(테스트도 `tests/experts/<영역>/`). 영역은 `hooks.py`로 코어에 연결됩니다(`sida/experts/__init__.py`). 저장소 최상위의 `webapp.py`는 `sida/webapp.py`를 실행하기만 합니다.

| 파일 (`sida/` 아래) | 역할 |
|---|---|
| `engine.py` | 화면과 무관한 세션 코어: `Session` 상태, Conductor 턴, 전문가 실행, 상태 반영. 값을 돌려주고 이벤트로 알리며 출력하지 않음 |
| `conductor.py` / `conductor_context.py` | Conductor 메시지 조립·동작 해석·LLM 호출 / Conductor에게 보내는 프롬프트·최근 기록·전문가 결과 |
| `talks.py` | 한 프로젝트 안의 여러 Conductor 대화 |
| `worker.py` | 전문가 하나 실행: 읽을 결과, 프롬프트, 로컬 컨텍스트 예산, 머리말 확인, 저장 |
| `session_api.py` / `session_jobs.py` / `expert_chat.py` | 웹 세션: Conductor 대화, 백그라운드 전문가 실행, 전문가별 채팅([`session-api.md`](session-api.md)) |
| `board.py` / `board_api.py` / `board_export.py` | 제도판: `board.json`의 종이, 고른 종이를 AI에게 보내기, DXF·3dm 내보내기([`board-api.md`](board-api.md)) |
| `model_base/` | 레이저 커팅 대지 모형: 등고선 층, 판 맞춤, DXF·PDF·SVG([`model-base.md`](model-base.md)) |
| `settings.py` / `settings_api.py` | 설정 창: 실행 방식, 모델, API 키 → `config.local.yaml` / `.env`([`settings-api.md`](settings-api.md)) |
| `chatgpt_auth.py` / `chatgpt_api.py` | ChatGPT 로그인([`chatgpt-login.md`](chatgpt-login.md)) |
| `relay.py` / `relay_key.py` | 정부 API를 이 PC의 키로 직접 또는 중계 서버로 부르기 / 설정 창에서 Sida 키 요청 |
| `telemetry.py` / `telemetry_api.py` | 사용 기록(기본 꺼짐)과 전문가 결과 평가([`telemetry.md`](telemetry.md)) |
| `project.py` / `project_documents.py` / `editing.py` / `document_api.py` | 프로젝트 폴더 읽기·쓰기, `project_state.md`, 브리프 절 고치기와 충돌 검사 |
| `state_updater.py` / `state_revisions.py` | 전문가 실행 뒤 `project_state.md` 반영안(JSON → diff → 적용) / 상태에 반영된 결과 판 기록 |
| `workspace.py` | 프로젝트 목록·찾기·만들기 |
| `briefs.py` | 기본 항목으로 `brief.md` 만들기 |
| `migrate.py` | 예전 전문가 파일 이름 바꾸기, 프로젝트를 열 때 Module Status 맞추기 |
| `config.py` | `config.yaml`(팀 기본값) 위에 `config.local.yaml`(이 PC) 덮어 읽기, 전문가 목록 |
| `providers.py` / `runtime.py` | LLM 연결(OpenRouter·OpenAI·ChatGPT·Ollama·mock)과 재시도 / 역할별 모델·컨텍스트 크기 |
| `ollama_boot.py` / `hardware.py` | Ollama 켜기·모델 받기·VRAM 올리기 / GPU 확인과 로컬 프로필 추천([`gpu_tiers.md`](gpu_tiers.md)) |
| `storage.py` / `errors.py` / `console.py` | 파일을 끊김 없이 쓰기 / 공통 오류 / 서버 로그용 UTF-8·색 |
| `i18n.py` | 화면 문자열(한국어 기본, 영어 대체) |
| `webapp.py` | FastAPI 앱: `/api` 아래 JSON API와 `webui/app/` 화면 |
| `experts/site/` | 대지 사실: 정부 토지 API(`landapi.py`, `datago.py`), 필지 → 대지·법정 수치·확인 항목(`site_facts.py` + `data/zoning_limits.yaml`), 주변 3D([`site-context.md`](site-context.md)) |
| `experts/regulation/` | 법령 검색(`rag.py`, `lawapi.py`, `law_search.py`, [`law-search-api.md`](law-search-api.md)), 조례 조문과 건폐율·용적률 읽기(`ordinance.py`, `hwp.py`, [`site-ordinance.md`](site-ordinance.md)) |
| `experts/model/` | 대지 모형 판의 JSON API와 표현 계획자에게 주는 모형 자료 |
| `experts/rhino/` | Rhino 모델링 턴과 MCP 연결(아직 웹에 없음) |
