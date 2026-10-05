# 팀 협업 가이드

Sida를 여러 명이 함께 개발할 때의 Git/GitHub 규칙입니다.

## 시작하기

프로그램 설치, GitHub 로그인, 에이전트별 설정까지 자세한 순서는 [`docs/dev-setup.md`](docs/dev-setup.md)를 보세요. 요약하면:

```bash
git clone https://github.com/baechubaechu/Sida.git
cd Sida
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -e ".[dev]"
git config core.hooksPath .githooks   # 머지된 로컬 브랜치 자동 정리
copy .env.example .env          # Mac/Linux: cp .env.example .env  → 본인 API 키 입력
pytest                          # 전부 통과하는지 확인
```

`.env`는 절대 커밋하지 않습니다 (`.gitignore`에 등록됨). 새 환경변수가 생기면 `.env.example`에만 이름을 추가하세요.

## 기본 규칙

1. **`main`에 직접 push하지 않습니다.** 모든 변경은 브랜치 → Pull Request → 리뷰 → 머지 순서로 합니다.
2. 작업 하나 = 브랜치 하나 = PR 하나. PR은 작게(리뷰 30분 이내) 유지합니다.
3. PR 승인은 필수가 아닙니다(승인 0명). 대신 자동 검사와 테스트가 안전장치이고, 서로의 PR은 설명을 읽고 무엇이 바뀌었는지 공유합니다.
4. CI(ruff, pytest)가 실패한 PR은 머지되지 않습니다.
5. **기능을 추가하거나 바꾸면 테스트도 같이 추가합니다.** 승인 대신 테스트가 안전장치입니다. AI에게 작업을 맡길 때도 "테스트도 같이"라고 요청하세요.
6. PR 브랜치가 main보다 뒤처지면 머지되지 않습니다. PR에 "Update branch" 버튼이 보이면 누르세요.
7. API 키가 담긴 커밋은 GitHub이 push를 거부합니다(Push protection). 거부되면 키를 지우고 재발급하세요.

## 작업 흐름

```bash
git switch main
git pull
git switch -c feat/짧은-설명

# 코드 수정 후
ruff check . && pytest
git add <바꾼 파일>              # git add . 는 지양, 커밋 전 git status/diff 확인
git commit -m "feat: 무엇을 했는지"
git push -u origin feat/짧은-설명
```

이후 GitHub에서 Pull Request를 엽니다.

- **자동 머지**: PR을 열면 CI(ruff, pytest)가 돌고, 필요한 승인까지 모두 채워지면 자동으로 main에 머지됩니다. 검사가 실패하면 머지되지 않으니 고쳐서 다시 push하세요.
- **아직 머지하면 안 되는 작업**은 PR을 **Draft**로 여세요. 준비되면 "Ready for review"를 누르면 자동 머지가 예약됩니다.
- 머지된 원격 브랜치는 1시간마다 자동 삭제됩니다. 로컬에서는 `git switch main && git pull`하면 머지된 로컬 브랜치도 지워집니다(`core.hooksPath` 설정 시). 머지 후 새로 커밋한 내용이 있는 브랜치는 원격·로컬 모두 지우지 않습니다.
- 머지된 브랜치에서 이어서 작업하지 말고, 다음 작업은 최신 main에서 새 브랜치로 시작하세요.

## 브랜치 이름

`feat/…` 기능 · `fix/…` 버그 · `docs/…` 문서 · `refactor/…` 구조 개선 · `chore/…` 설정·잡일

## 커밋 메시지

`타입: 설명` 형식. 타입은 `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.
예) `feat: RAG 검색 결과에 출처 표시`, `fix: 한글 경로에서 프로젝트 로드 실패 수정`

## 충돌이 났을 때

```bash
git switch main && git pull
git switch feat/내-브랜치
git merge main
# 충돌 파일을 열어 <<<<<<< ======= >>>>>>> 부분을 정리 → git add → git commit → git push
```

여러 작업이 거쳐 가는 파일(`i18n.py`, `worker.py`, `providers.py` 등)을 크게 고칠 때는 미리 팀에 알려 같은 파일을 동시에 수정하지 않도록 합니다.

## 작업 관리

- 할 일은 GitHub Issues로 등록하고 담당자(Assignee)를 지정합니다.
- PR 설명에 `closes #이슈번호`를 적으면 머지 시 이슈가 자동으로 닫힙니다.

## 주의

- API 키, 개인 프로젝트 데이터(`projects/`, `output/`)는 커밋하지 않습니다.
- 실수로 키를 올렸다면 삭제 커밋만으론 부족합니다. 즉시 키를 재발급하고 팀에 알리세요.
