# AGENTS.md

Sida(시다) 저장소에서 작업하는 모든 AI 에이전트(Claude Code, Cursor, Codex, Copilot 등)가 따를 규칙입니다. Claude Code는 `CLAUDE.md`가 이 파일을 불러옵니다. 프로젝트 개요는 `README.md`, 전문가(에이전트) 구성은 `docs/experts.md`, 팀 규칙 전체는 `CONTRIBUTING.md`, 개발 환경 세팅은 `docs/dev-setup.md`, 앞으로의 방향과 순서는 `docs/roadmap.md`를 보세요.

## 프로젝트 요약

건축 설계 추론을 돕는 CLI 기반 LLM 워크플로. Conductor가 12개 전문가(`agents/*.md`)를 조합해 구조화된 Markdown 문서를 만든다. 최종 설계를 대신하지 않는다.

- 진입점: `chat.py`(프로젝트 허브), `run.py`(비대화형 파이프라인), Windows는 `run.bat`
- 핵심 모듈: `harness.py`, `conductor.py`, `engine.py`, `session.py`, `hub.py`, `rag.py`, `i18n.py`(한국어 우선 UI 문자열)
- `engine.py`는 화면과 무관한 세션 코어다. `print`/`input`을 쓰지 않고, 값을 반환하고 진행 상황은 이벤트(`Session.emit`)로 알린다. 터미널 출력과 질문은 `session.py`에 둔다. 새 세션 로직은 `engine.py`에 넣는다.
- 웹 UI(`webapp.py`, `webui/`)는 세 층이다: 코어 함수(`engine.py`, `workspace.py`) → JSON API(`/api/...`) → HTML 화면. 로직은 코어에 두고, 경로와 템플릿에는 넣지 않는다. 기능을 추가하면 JSON API와 그 테스트(`tests/test_webapp.py`)를 같이 만든다. 코어 함수는 경로에서 `core(...)`로 호출한다(`fail()`이 서버를 종료시키지 않게 하기 위해서다).
- 설정: `config.yaml`은 팀 공통 기본값(클라우드, RAG 꺼짐)이다. PC별 설정은 Git이 무시하는 `config.local.yaml`에 두고, `load_config`가 그 값을 덮어쓴다. 허브 설정 메뉴와 첫 실행 질문은 `config.local.yaml`에만 쓴다. 개인 설정을 `config.yaml`에 커밋하지 않는다. 비밀값은 `.env`(키 목록은 `.env.example`)
- 새 모듈을 추가하면 `pyproject.toml`의 `[tool.setuptools] py-modules`에도 등록한다. 빠지면 CI 설치가 깨진다.

## 개발 명령어

```bash
pip install -e ".[dev]"   # 의존성 + pytest, ruff
git config core.hooksPath .githooks   # 머지된 로컬 브랜치 자동 정리 (clone 후 한 번)
ruff check .              # 린트 (--fix로 자동 수정)
pytest                    # 테스트 (tests/)
```

커밋 전에 `ruff check .`와 `pytest`가 모두 통과해야 한다. CI도 같은 검사를 한다.

## 테스트 규칙 (안전장치)

이 팀은 PR 승인 없이 **자동 검사만으로 머지**한다. 테스트가 곧 안전장치다.

- 기능을 추가하거나 동작을 바꾸면 **같은 PR에 테스트도 추가/수정**한다. 테스트 파일은 `tests/test_<모듈명>.py`.
- 버그를 고치면 그 버그를 재현하는 테스트를 먼저 추가하고, 수정 후 통과하는지 확인한다.
- 테스트는 실제 LLM API·네트워크를 호출하지 않는다. `tests/conftest.py`의 기존 패턴처럼 가짜 응답(monkeypatch)을 쓴다.
- 테스트를 지우거나 `skip` 처리해서 CI를 통과시키지 않는다. 불가피하면 PR 설명에 이유를 적는다.
- 사용자에게 작업 결과를 보고할 때 **추가한 테스트가 무엇을 확인하는지** 한 줄로 알려준다.

## Git / GitHub 워크플로

- **main에서 직접 작업하거나 커밋하지 않는다.** 작업마다 최신 main에서 새 브랜치를 만든다.
  - `git switch main && git pull && git switch -c feat/짧은-설명`
  - 브랜치 접두어: `feat/` `fix/` `docs/` `refactor/` `test/` `chore/`
- 커밋 메시지: `타입: 설명` (예: `feat: RAG 검색 결과에 출처 표시`). 한 커밋에 한 가지 변경.
- `git add .` 대신 바꾼 파일만 add하고, 커밋 전 `git status`/`git diff`로 확인한다.
- **커밋과 push는 사용자가 그 턴에 명시적으로 요청했을 때만 한다.** 대화 마지막에 "푸시할까요?"라고 묻지 않는다.
- push 후 PR은 `gh pr create --fill` 등으로 연다. 템플릿은 `.github/pull_request_template.md`.

### main 보호 규칙 (GitHub Ruleset "main 보호")

- main 직접 push 불가. 반드시 PR을 거친다. 관리자도 우회 불가. force push와 main 삭제도 금지.
- 필수 검사: `test (3.10)`, `test (3.12)` (`.github/workflows/ci.yml`의 ruff + pytest)
- **최신 main 기준 검사**: PR 브랜치가 main보다 뒤처지면 머지되지 않는다. PR에 "Update branch"가 뜨면 누르거나 `git merge main` 후 push한다. 업데이트하면 CI가 다시 돌고 통과하면 자동 머지된다.
- 필요 승인 수: 0명. 팀원이 있어도 승인 없이 **자동 검사(CI) + 테스트**를 안전장치로 쓰기로 했다. 그래서 PR 설명에 무엇을 왜 바꿨는지 팀원이 알 수 있게 쓴다.
- **자동 머지**: PR이 열리면 `.github/workflows/auto-merge.yml`이 squash 자동 머지를 예약하고, 검사를 통과하면 머지된다. 머지된 원격 브랜치는 `.github/workflows/delete-merged-branch.yml`이 1시간마다 삭제한다(GITHUB_TOKEN 머지는 다른 워크플로를 실행시키지 않아 주기 실행으로 정리). 머지 후 새 커밋이 올라온 브랜치는 지우지 않는다.
- 아직 머지하면 안 되는 작업은 **Draft PR**로 연다. Draft PR은 자동 머지에서 제외된다.
- 머지 후에는 `git switch main && git pull`로 동기화하고, 다음 작업은 새 브랜치에서 시작한다. `core.hooksPath`를 `.githooks`로 설정해 두면 이때 원격이 삭제됐고 변경이 모두 main에 들어간 로컬 브랜치를 `.githooks/post-merge`가 지운다.
- **머지된 브랜치에서 이어서 작업하지 않는다.** squash 머지라 같은 브랜치로 다음 PR을 열면 이미 들어간 커밋이 다시 섞인다. 커밋 전에 `gh pr view --json state -q .state`로 현재 브랜치의 PR을 확인하고, `MERGED`면 `git stash` → 최신 main에서 새 브랜치 → `git stash pop` 후 커밋한다.

## 주의사항

- GitHub Push protection이 켜져 있어 API 키가 담긴 커밋은 push가 거부된다. 거부되면 해당 커밋에서 키를 제거하고 키를 재발급한다.
- `.env`, API 키, `projects/`, `output/`의 개인 데이터는 절대 커밋하지 않는다(`.gitignore`에 등록됨).
- 줄바꿈은 LF로 통일한다(`.gitattributes`). Windows에서 CRLF 차이로 전체 파일이 변경된 것처럼 보이면 내용 변경이 아니다.
- `harness.py`, `i18n.py`, `conductor.py` 같은 큰 파일은 다른 사람(또는 다른 에이전트)과 동시에 크게 수정하지 않는다.
- 이 저장소는 여러 에이전트를 함께 쓴다. 한 작업 폴더를 두 에이전트가 동시에 쓰면 브랜치 전환과 커밋 안 된 변경이 서로 섞인다. 작업 전에 `git status`와 현재 브랜치를 확인하고, 내가 만들지 않은 커밋 안 된 변경은 커밋하거나 되돌리지 말고 사용자에게 알린다.
- 대지 사실(`site_facts.py`, `landapi.py`)은 정부 API에서 가져온 값만 담는다. 수치를 추정하거나 지어내지 않고, 가져오지 못한 항목은 "미확인"으로 둔다. 법정 수치 표(`data/zoning_limits.yaml`)를 고칠 때는 조문 원문과 대조하고 `verified` 날짜를 갱신한다.
- 테스트는 외부 API를 호출하지 않는다. `tests/conftest.py`가 `landapi._http_get`을 막아 두었고, 녹화한 응답(`tests/fixtures/landapi/`)을 `fake_vworld`로 쓴다.
- 규칙 파일: 공통 규칙은 이 파일(`AGENTS.md`), Claude Code는 `CLAUDE.md`(이 파일을 import), Cursor 전용 보충 규칙은 `.cursor/rules/`. 공통 규칙은 이 파일만 고친다.

## 답변 스타일

- 한국어로 답한다.
- 이미 보고한 내용을 반복해서 요약하지 않는다. 지금 받은 질문에만 답한다.
- 실수는 한 번 정정하고 넘어간다. 사과를 반복하지 않는다.
