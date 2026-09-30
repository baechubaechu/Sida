# CLAUDE.md

Sida(시다) 저장소에서 작업할 때 따를 규칙입니다. 프로젝트 개요는 `README.md`, 전문가(에이전트) 구성은 `docs/experts.md`, 팀 규칙 전체는 `CONTRIBUTING.md`를 보세요.

## 프로젝트 요약

건축 설계 추론을 돕는 CLI 기반 LLM 워크플로. Conductor가 12개 전문가(`agents/*.md`)를 조합해 구조화된 Markdown 문서를 만든다. 최종 설계를 대신하지 않는다.

- 진입점: `chat.py`(프로젝트 허브), `run.py`(비대화형 파이프라인), Windows는 `run.bat`
- 핵심 모듈: `harness.py`, `conductor.py`, `session.py`, `hub.py`, `rag.py`, `i18n.py`(한국어 우선 UI 문자열)
- 설정: `config.yaml`, 비밀값은 `.env`(키 목록은 `.env.example`)
- 새 모듈을 추가하면 `pyproject.toml`의 `[tool.setuptools] py-modules`에도 등록한다. 빠지면 CI 설치가 깨진다.

## 개발 명령어

```bash
pip install -e ".[dev]"   # 의존성 + pytest, ruff
ruff check .              # 린트 (--fix로 자동 수정)
pytest                    # 테스트 (tests/)
```

커밋 전에 `ruff check .`와 `pytest`가 모두 통과해야 한다. CI도 같은 검사를 한다.

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
- 필요 승인 수: 현재 0명(1인 개발). 팀원이 합류하면 1명으로 올린다. PR 작성자는 자기 PR을 승인할 수 없다.
- **자동 머지**: PR이 열리면 `.github/workflows/auto-merge.yml`이 squash 자동 머지를 예약하고, 검사를 통과하면 머지된다. 머지된 원격 브랜치는 자동 삭제된다.
- 아직 머지하면 안 되는 작업은 **Draft PR**로 연다. Draft PR은 자동 머지에서 제외된다.
- 머지 후에는 `git switch main && git pull`로 동기화하고, 다음 작업은 새 브랜치에서 시작한다.

## 주의사항

- `.env`, API 키, `projects/`, `output/`의 개인 데이터는 절대 커밋하지 않는다(`.gitignore`에 등록됨).
- 줄바꿈은 LF로 통일한다(`.gitattributes`). Windows에서 CRLF 차이로 전체 파일이 변경된 것처럼 보이면 내용 변경이 아니다.
- `harness.py`, `i18n.py`, `conductor.py` 같은 큰 파일은 다른 사람(또는 Cursor 에이전트)과 동시에 크게 수정하지 않는다.
- 이 저장소는 Cursor와 Claude Code를 함께 쓴다. Cursor 규칙은 `.cursor/rules/`에 있다.

## 답변 스타일

- 한국어로 답한다.
- 이미 보고한 내용을 반복해서 요약하지 않는다. 지금 받은 질문에만 답한다.
- 실수는 한 번 정정하고 넘어간다. 사과를 반복하지 않는다.
